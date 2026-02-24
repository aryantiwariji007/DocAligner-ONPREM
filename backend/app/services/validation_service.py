from odf.opendocument import load
from odf import meta, style
import io
import zipfile
from typing import Dict, List, Any, Tuple
from backend.app.models import StandardVersion

class ValidationService:
    async def validate_document_async(self, file_content: bytes, standard_version: StandardVersion, filename: str) -> Dict[str, Any]:
        """
        Phase 2: Document Evaluation
        Deterministic validation + LLM-based compliance check.
        """
        # 1. Start with deterministic validation (fast)
        report = self.validate_document(file_content, standard_version)
        
        # 2. Augment with AI if available (Phase 2)
        try:
            from backend.app.services.ai_service import ai_service
            if ai_service.is_available():
                # Extract text for AI
                text = ""
                # Use the new factory method we added!
                from backend.app.services.rule_extraction_service import rule_extraction_factory
                # AI evaluation doesn't need image base64, just text
                text = rule_extraction_factory.extract_text(file_content, filename, with_images=False)

                if text:
                    import hashlib
                    import json
                    from backend.app.services.memory_service import memory_service

                    text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
                    doc_id_str = filename # Or actual document.id if passed instead of filename, but string is fine
                    
                    # 1. Check episodic memory for this exact chunk
                    ai_report = None
                    try:
                        bubble_q = f"validation status for chunk {text_hash}"
                        bubble_results = memory_service.search_rules(query=bubble_q, limit=1)
                        if isinstance(bubble_results, dict) and "results" in bubble_results and len(bubble_results["results"]) > 0:
                            top_result: str = bubble_results["results"][0].get("memory", "")
                            prefix = "Explicit Status: "
                            if prefix in top_result:
                                ai_report_json = top_result.split(prefix, 1)[1]
                                ai_report = json.loads(ai_report_json)
                                print(f"Cache Hit for {text_hash}!")
                    except Exception as e:
                        print(f"Episodic memory lookup failed: {e}")

                    # 2. If no cache hit, compute using AI
                    if not ai_report:
                        print(f"Cache Miss for {text_hash}. Calling AI...")
                        ai_report = await ai_service.evaluate_compliance(text, standard_version.rules_json, str(standard_version.standard_id))
                        # Save bubble
                        try:
                            if ai_report and "error" not in ai_report:
                                memory_service.add_validation_bubble(doc_id_str, text_hash, json.dumps(ai_report))
                        except Exception as e:
                            print(f"Failed to save episodic bubble: {e}")

                    # Merge Reports
                    if ai_report and "error" not in ai_report:
                        # Get overall score from scorecard (more reliable) or top-level
                        scorecard = ai_report.get("scorecard") or {}
                        overall_score = scorecard.get("overall", ai_report.get("compliance_score", 0))
                        ai_compliant = ai_report.get("compliant", True)
                        
                        # If scorecard all zeros but has violations, fix compliant flag
                        ai_violations = ai_report.get("violations", [])
                        if ai_violations and ai_compliant:
                            # Has violations — trust violations over the compliant flag
                            has_mandatory_violation = any(
                                v.get("obligation_level", "") == "mandatory" or v.get("severity", "") == "high"
                                for v in ai_violations
                            )
                            if has_mandatory_violation:
                                ai_compliant = False

                        report["ai_evaluation"] = {
                            "compliance_score": overall_score,
                            "compliant": ai_compliant,
                            "compatibility_score": ai_report.get("compatibility_score", 0),
                            "compatibility_warning": ai_report.get("compatibility_warning"),
                            "scorecard": scorecard,
                            "obligation_summary": ai_report.get("obligation_summary", []),
                            "violations": ai_violations,
                            "skipped_rules": ai_report.get("skipped_rules", []),
                            "auto_fix_possible": ai_report.get("auto_fix_possible", False)
                        }
                    
                        # Hard fix: if score is literally 0, it's not compliant, regardless of what the AI hallucinated for the flag.
                        if overall_score == 0:
                            ai_compliant = False
                        # User request: if score >= 75%, it should automatically be compliant
                        elif overall_score >= 75:
                            ai_compliant = True
                        
                        # Sync the flag back to the evaluation object
                        report["ai_evaluation"]["compliant"] = ai_compliant

                        if not ai_compliant:
                            report["compliant"] = False
                            # Add AI violations to main errors list
                            for v in ai_violations:
                                desc = v.get("description", "Unknown violation")
                                rule_path = v.get("rule_path", "")
                                lvl = v.get("obligation_level", "mandatory")
                                report["errors"].append(f"[{lvl.upper()}] {desc} ({rule_path})")
                            
                            if not ai_violations and overall_score == 0:
                                report["errors"].append("[SYSTEM] Failed overall AI compliance check (Score: 0%).")
                        else:
                            # 75% Rule: If AI says compliant (which it does for score >= 75), 
                            # we override EVERYTHING to green.
                            report["compliant"] = True
                            # Optional: We could clear report["errors"] here too if we want a clean pass badge,
                            # but keeping them as "warnings" or info might be better. 
                            # For now, just ensuring the compliant flag is True.
                            report["status"] = "COMPLIANT"

                        report["score"] = overall_score
                        report["fix_options"] = ai_report.get("auto_fix_possible", False)
                    elif ai_report and "error" in ai_report:
                        report["warnings"].append(f"AI evaluation error: {ai_report['error']}")
                        report["ai_evaluation"] = {"error": ai_report["error"]}
        except Exception as e:
            print(f"AI Validation failed: {e}")
            import traceback; traceback.print_exc()
            report["warnings"].append(f"AI-enhanced validation failed: {str(e)}")
            report["ai_evaluation"] = {"error": str(e)}

        return report

    def validate_document(self, file_content: bytes, standard_version: StandardVersion) -> Dict[str, Any]:
        """
        Validates a document against a standard version.
        Supports: ODF (Full), PDF (Basic), Word (Format Check).
        """
        report = {
            "compliant": True,
            "errors": [],
            "warnings": [],
            "details": {}
        }

        # Identify Format
        is_zip = zipfile.is_zipfile(io.BytesIO(file_content))
        is_pdf = file_content.startswith(b"%PDF-")

        if is_pdf:
            report["details"]["format"] = "PDF"
            # Basic PDF validation (can be expanded with pypdf)
            report["warnings"].append("PDF documents only support metadata/format validation. Structural standards are skipped.")
            return report

        if is_zip:
            # Check if it's ODF or DOCX
            try:
                with zipfile.ZipFile(io.BytesIO(file_content)) as z:
                    # ODF has mimetype as first file
                    if "mimetype" in z.namelist():
                        mimetype = z.read("mimetype").decode("utf-8")
                        if "opendocument" in mimetype:
                            return self._validate_odf(file_content, standard_version, report)
                    
                    # Word (OOXML)
                    if "word/document.xml" in z.namelist():
                        report["details"]["format"] = "DOCX"
                        report["warnings"].append("Word documents (.docx) support macro detection but skip structural ODF standards.")
                        if self._has_macros_docx(file_content):
                            report["compliant"] = False
                            report["errors"].append("Macros detected in Word document.")
                        return report
            except:
                pass

        report["compliant"] = False
        report["errors"].append("Unsupported file format. Please upload ODF, PDF, or Word (.docx) files.")
        return report

    def _validate_odf(self, file_content: bytes, standard_version: StandardVersion, report: Dict[str, Any]) -> Dict[str, Any]:
        try:
            doc = load(io.BytesIO(file_content))
            report["details"]["format"] = "ODF"
        except Exception as e:
            report["compliant"] = False
            report["errors"].append(f"Invalid ODF file: {str(e)}")
            return report

        # Check version
        root = doc.topnode
        odf_version = root.getAttribute("version")
        if odf_version != "1.2":
            report["warnings"].append(f"Document version is '{odf_version}', expected '1.2'.")
            if odf_version != "1.2":
                report["compliant"] = False
                report["errors"].append(f"Strict ODF 1.2 compliance failed. Found version: {odf_version}")
        
        # 2. No Macros Allowed
        if self._has_macros(file_content):
            report["compliant"] = False
            report["errors"].append("Macros detected. Macros are strictly forbidden.")

        # 3. Metadata Validation
        # Rules from standard_version.rules_json.get('metadata', {})
        target_metadata = standard_version.rules_json.get("metadata", {})
        doc_metadata = self._extract_metadata(doc)
        
        for key, value in target_metadata.items():
            # If standard defines a metadata field, it MUST exist? 
            # Or must match value? 
            # "Metadata-driven enforcement" usually means required fields.
            if key not in doc_metadata:
                report["compliant"] = False
                report["errors"].append(f"Missing required metadata field: {key}")
            elif doc_metadata[key] != value:
                # Value mismatch - rigorous or just existence?
                # "Standards extracted from source document" implies template matching.
                # I'll warn on value mismatch but error on missing key.
                report["warnings"].append(f"Metadata mismatch for {key}. Expected '{value}', got '{doc_metadata[key]}'")

        # 4. Style & Heading Structure
        # Check if document uses styles not defined in standard? 
        # Or check if structure matches?
        # "Accessible document structure"
        # "Style and heading structure"
        # Implementation: Check if styles used in content.xml exist in standard rules.
        self._validate_styles(doc, standard_version.rules_json.get("styles", {}), report)

        return report

    def _has_macros(self, file_content: bytes) -> bool:
        """
        Check for presence of Basic/ or Scripts/ directories in ZIP.
        """
        try:
            with zipfile.ZipFile(io.BytesIO(file_content)) as z:
                for name in z.namelist():
                    if name.startswith("Basic/") or name.startswith("Scripts/"):
                        return True
                    # manifest.xml check for script entries?
        except:
            pass # load() already passed, so zip should be valid
        return False

    def _extract_metadata(self, doc) -> Dict[str, str]:
        # Duplicate logic from extractor, maybe refactor common later
        metadata = {}
        if doc.meta:
            for child in doc.meta.childNodes:
                if child.qname:
                    local_name = child.qname[1] if isinstance(child.qname, tuple) else child.tagName
                    text_content = ""
                    for text_node in child.childNodes:
                        if text_node.nodeType == text_node.TEXT_NODE:
                            text_content += text_node.data
                    metadata[local_name] = text_content.strip()
        return metadata

    def _validate_styles(self, doc, allowed_styles: Dict[str, Any], report: Dict[str, Any]):
        """
        Validates that styles defined in the document match the allowed styles text-properties.
        """
        doc_styles = self._extract_styles_simple(doc)
        
        for style_name, rules in allowed_styles.items():
            # We enforce that if the document HAS this style, it must match.
            # If standard has "Heading 1" and doc doesn't, that's fine (unless mandatory? assuming no).
            # But if doc has "Heading 1", it must match rules.
            
            if style_name in doc_styles:
                doc_style = doc_styles[style_name]
                # Compare text properties
                rule_props = rules.get("properties", {})
                doc_props = doc_style.get("properties", {})
                
                for prop_key, prop_val in rule_props.items():
                    # Only check text properties for now, e.g. "text:font-name"
                    if prop_key in doc_props:
                        if doc_props[prop_key] != prop_val:
                            report["warnings"].append(
                                f"Style '{style_name}' mismatch: {prop_key} expected '{prop_val}', got '{doc_props[prop_key]}'"
                            )
                    # If prop is missing in doc style but present in rule? 
                    # Maybe it inherits? Complex. Warning for now.
                    # else:
                    #    report["warnings"].append(f"Style '{style_name}' missing property {prop_key}")

    def _extract_styles_simple(self, doc) -> Dict[str, Any]:
        extracted = {}
        # Simple extractor for validation comparisons
        # Using odfpy's styles and automaticstyles
        for styles_node in [doc.styles, doc.automaticstyles]:
            if not styles_node: continue
            for s in styles_node.childNodes:
                if s.qname == (style.ns, 'style'):
                    name = s.getAttribute('name')
                    properties = {}
                    for prop in s.childNodes:
                        if prop.qname == (style.ns, 'text-properties'):
                            for k, v in prop.attributes.items():
                                properties[f"text:{k[1]}"] = v
                    extracted[name] = {"properties": properties}
        return extracted

    def _has_macros_docx(self, file_content: bytes) -> bool:
        """
        Check for vbaProject.bin or other common macro indicators in DOCX.
        """
        try:
            with zipfile.ZipFile(io.BytesIO(file_content)) as z:
                for name in z.namelist():
                    if "vbaProject" in name or name.endswith(".vba") or "macros" in name.lower():
                        return True
        except:
            pass
        return False

validation_service = ValidationService()

"""
Decision Flow Service — Orchestrates the 4-phase compatibility-gated transformation pipeline.

Flow:
  1. Extract text from target document
  2. Analyze compatibility (5 weighted dimensions)
  3. Gate: score >= 75 → safe | 40-74 → selective | < 40 → report only
  4. Select rules (safe / conditional / forbidden)
  5. Build approved_rules (safe always + conditional if score >= 40)
  6. Transform document (only with approved rules)
  7. Return full decision report
"""

from typing import Dict, Any
from backend.app.services.ai_service import ai_service
from backend.app.services.rule_extraction_service import rule_extraction_factory


class DecisionFlowService:

    async def analyze(self, file_content: bytes, filename: str, standard_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase 1-2: Extract text and run compatibility analysis.
        Returns compatibility report without transformation.
        """
        # Use text-only for decision flow to conserve prompt tokens
        text = rule_extraction_factory.extract_text(file_content, filename, with_images=False)
        if not text:
            return {"error": "Could not extract text from document"}

        compatibility = await ai_service.analyze_compatibility(standard_json, text)
        if "error" in compatibility:
            return compatibility

        return {
            "text": text,
            "compatibility": compatibility,
            "score": compatibility.get("total_score", 0),
            "risk": compatibility.get("risk_classification", "LOW"),
        }

    async def apply(self, file_content: bytes, filename: str, standard_json: Dict[str, Any], competence_level: str = "general") -> Dict[str, Any]:
        """
        Full pipeline: analyze → select → transform (gated by score).
        """
        # Phase 1-2: Compatibility Analysis
        analysis = await self.analyze(file_content, filename, standard_json)
        if "error" in analysis:
            return analysis

        score = analysis["score"]
        risk = analysis["risk"]
        text = analysis["text"]

        # Phase 3: Rule Selection
        rule_selection = await ai_service.select_rules(standard_json, score)
        if "error" in rule_selection:
            return {**analysis, "rule_selection": None, "error": rule_selection["error"]}

        safe_rules = rule_selection.get("safe_rules", [])
        conditional_rules = rule_selection.get("conditional_rules", [])
        forbidden_rules = rule_selection.get("forbidden_rules", [])

        # Build approved rules based on compatibility tier
        if score >= 75:
            # HIGH — apply safe + conditional
            action = "safe_apply"
            approved = safe_rules + conditional_rules
            warnings = []
        elif score >= 40:
            # MEDIUM — apply safe, flag conditional
            action = "selective_apply"
            approved = safe_rules
            warnings = [
                {
                    "rule_path": r.get("rule_path", ""),
                    "description": r.get("description", ""),
                    "message": "Flagged but not applied — review required"
                }
                for r in conditional_rules
            ]
        else:
            # LOW — report only, no transformation
            action = "report_only"
            approved = []
            warnings = []

        # Phase 4: Transform (only if allowed)
        transformed_content = None
        deviations = []
        preserved_items = []
        change_summary = ""
        if action != "report_only" and approved:
            approved_json = {
                "approved_rules": [
                    {"rule_path": r.get("rule_path", ""), "description": r.get("description", "")}
                    for r in approved
                ],
                "source_standard": standard_json
            }
            transform_result = await ai_service.transform_document(text, approved_json, competence_level=competence_level)

            # Handle new structured response (dict with transformed_text + deviations)
            if isinstance(transform_result, dict):
                transformed_content = transform_result.get("transformed_text", "")
                deviations = transform_result.get("deviations", [])
                preserved_items = transform_result.get("preserved_items", [])
                change_summary = transform_result.get("change_summary", "")
            else:
                # Fallback for legacy string response
                transformed_content = transform_result

            # Check for failure
            if transformed_content and "failed" in transformed_content.lower() and len(transformed_content) < 200:
                transformed_content = None

        return {
            "action": action,
            "compatibility": analysis["compatibility"],
            "score": score,
            "risk": risk,
            "rule_selection": {
                "safe_rules": safe_rules,
                "conditional_rules": conditional_rules,
                "forbidden_rules": forbidden_rules,
            },
            "warnings": warnings,
            "transformed_content": transformed_content,
            "original_content": text,
            "filename": filename,
            "deviations": deviations,
            "preserved_items": preserved_items,
            "change_summary": change_summary,
        }


decision_flow_service = DecisionFlowService()

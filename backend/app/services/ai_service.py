from typing import Dict, Any, List, Optional
import json
import httpx
from backend.app.core.config import settings
from backend.app.services.memory_service import memory_service


class AIService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_MODEL
        self.timeout = 300  # 5 min — local LLMs can be slow

    def is_available(self) -> bool:
        """Always returns True — Ollama is assumed to be running on-premise.
        Actual connectivity errors will be caught in _chat()."""
        return True

    async def async_is_available(self) -> bool:
        """Non-blocking async check if Ollama is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    async def _chat(self, prompt: str, schema_hint: str = "") -> Dict[str, Any]:
        """
        Send a chat request to Ollama and parse the JSON response.
        Returns a dict. On failure returns {"error": "..."}.
        """
        import time
        start_time = time.time()
        
        system_msg = (
            "You are a precise document analysis engine. "
            "You MUST reply with ONLY valid JSON — no markdown fences, no explanation text. "
            "Do not wrap your response in ```json. Return raw JSON only."
        )
        if schema_hint:
            system_msg += f"\n\nRequired JSON shape:\n{schema_hint}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096,      # Reduced to 4k for faster local processing/lower memory
                "num_predict": 1024,  # Cap output tokens to prevent infinite loops
            },
        }

        print(f"[AI] Calling Ollama ({self.model}) with prompt length {len(prompt)}...")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                
                duration = time.time() - start_time
                load_duration = data.get("load_duration", 0) / 1e9 # ns to s
                total_duration = data.get("total_duration", 0) / 1e9
                
                print(f"[AI] Request complete in {duration:.2f}s (Ollama total: {total_duration:.2f}s, Load time: {load_duration:.2f}s)")
                
                content = data.get("message", {}).get("content", "")
                # Strip any accidental code fences
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("```", 2)[-1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.rsplit("```", 1)[0].strip()
                return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[AI] JSON Parse Error: {e}")
            return {"error": f"Failed to parse JSON from LLM: {e}. Response was: {content[:500]}"}
        except Exception as e:
            print(f"[AI] HTTP/Connection Error: {e}")
            return {"error": str(e)}

    async def extract_standard(self, text: str, filename: str) -> Dict[str, Any]:
        """
        Phase 1: Implicit Standard Extraction
        Reverse-engineers the behavioral rules a document demonstrates using strict system prompts.
        """
        schema_hint = json.dumps({
            "standard_id": "string",
            "version": "string",
            "document_type_and_purpose": "string",
            "structural_rules": ["string"],
            "language_rules": ["string"],
            "compliance_and_authority_model": "string",
            "versioning_and_governance_rules": ["string"]
        }, indent=2)

        prompt = f"""
SYSTEM

You are a document standard extraction engine.
Your task is to infer rules, not content.

USER

Analyze the following document as a reference standard.

Extract:
- Document type and purpose
- Structural rules
- Language rules
- Compliance and authority model
- Versioning and governance rules

Do NOT rewrite content.
Do NOT summarize.
Return structured JSON only.

REFERENCE DOCUMENT:
{text[:10000]}
"""

        result = await self._chat(prompt, schema_hint)
        if "error" not in result and "standard_id" not in result:
            result["standard_id"] = filename
        if "error" not in result and "version" not in result:
            result["version"] = "1.0"
        return result

    async def evaluate_compliance(self, doc_text: str, standard_json: Dict[str, Any], standard_id: str = "unknown") -> Dict[str, Any]:
        """
        Phase 2: Domain-Aware Selective Compliance Evaluation.
        Returns a compliance scorecard.
        """
        # Retrieve context-relevant rules from Memory rather than sending the full standard
        doc_sample = doc_text[:1000] # Use the first part of doc_text as semantic query
        try:
             memory_results = memory_service.search_rules(query=f"Rules relevant to: {doc_sample}", topic_id=standard_id, limit=3)
             # Extract string rules or fallback
             if isinstance(memory_results, dict) and "results" in memory_results:
                 memory_rules = [r.get("memory", "") for r in memory_results["results"]]
                 relevant_standard_text = "\n".join(memory_rules)
             else:
                 relevant_standard_text = str(memory_results)
                 
             if not relevant_standard_text.strip():
                 relevant_standard_text = str(standard_json)[:4000] # Fallback to original
        except Exception as e:
             print(f"Memory lookup failed: {e}")
             relevant_standard_text = str(standard_json)[:4000] # Fallback

        schema_hint = json.dumps({
            "compliance_score": 0,
            "compliant": True,
            "compatibility_score": 0,
            "compatibility_warning": "string or empty",
            "scorecard": {
                "authority_compliance": 0,
                "obligation_compliance": 0,
                "structural_compliance": 0,
                "metadata_compliance": 0,
                "terminology_compliance": 0,
                "overall": 0
            },
            "obligation_summary": [{"level": "mandatory|recommended|optional", "total_rules": 0, "passed": 0, "failed": 0}],
            "violations": [{"rule_path": "string", "description": "string", "severity": "low|medium|high", "obligation_level": "mandatory|recommended|optional"}],
            "skipped_rules": [{"rule_path": "string", "reason": "string"}],
            "auto_fix_possible": True
        }, indent=2)

        prompt = f"""
You are a policy-aware compliance evaluation engine enforcing SELECTIVE APPLICATION.

The provided standard is a LENS, not a hammer. You must apply it dynamically based on the target document's scope and domain.
- If the target document MATCHES the standard's domain (e.g., Policy applied to Policy), enforce ALL rules including domain-specific ones (like audit terminology or training assurance).
- If the target document is from a DIFFERENT domain (e.g., Defence Policy applied to an Engineering Manual), it has Low Compatibility. You MUST warn about this AND ONLY apply UNIVERSAL rules (Versioning discipline, Document control rules, Formatting rules, Authority presence). DO NOT penalize the document for missing rigid domain-specific sections.

OBLIGATION ENFORCEMENT:
- MUST / SHALL violations = HARD FAILURES (document is non-compliant)
- SHOULD / SHOULD NOT violations = SOFT FAILURES (flag, but don't break compliance)
- MAY / COULD = informational only

MULTI-DIMENSION SCORING (0-100 each):
- authority_compliance: ownership, approval blocks, sponsor references?
- obligation_compliance: MUST/SHOULD rules correctly used?
- structural_compliance: section hierarchy matches, mandatory sections present (SKIP domain-specific sections if mismatch)?
- metadata_compliance: versioning, document codes, traceability?
- terminology_compliance: controlled vocabulary adhered to?

overall = (authority*0.25) + (obligation*0.30) + (structural*0.20) + (metadata*0.15) + (terminology*0.10)

SELECTIVE APPLICATION LOGIC:
- Determine target domain vs standard domain to get `compatibility_score`.
- If different (score < 50), provide a `compatibility_warning` (e.g., "Low compatibility: applying Policy standard to Engineering Manual. Skipping domain-specific rules.").
- In `skipped_rules`, LIST explicitly the standard rules you ignored because they didn't make sense for this document's domain.

Relevant Standard Rules (Retrieved from Memory):
{relevant_standard_text}

Document Content:
{doc_text[:10000]}
"""

        return await self._chat(prompt, schema_hint)

    async def analyze_compatibility(self, standard_json: Dict[str, Any], target_text: str) -> Dict[str, Any]:
        """
        Phase 2: Compatibility Analysis.
        Scores how reasonable it is to apply a standard to a target document.
        """
        schema_hint = json.dumps({
            "total_score": 0,
            "per_dimension_scores": {
                "document_type": 0,
                "structure": 0,
                "language": 0,
                "compliance_philosophy": 0,
                "terminology": 0
            },
            "risk_classification": "HIGH|MEDIUM|LOW"
        }, indent=2)

        prompt = f"""
SYSTEM

You are a document compatibility assessor.
You must be conservative and risk-aware.

USER

Compare the reference standard with the target document.

Score compatibility (0-100) across:
- Document type
- Structure
- Language
- Compliance philosophy
- Terminology

Return:
- Total score
- Per-dimension scores
- Risk classification (HIGH / MEDIUM / LOW)

REFERENCE STANDARD:
{str(standard_json)[:3000]}

TARGET DOCUMENT:
{target_text[:5000]}
"""

        return await self._chat(prompt, schema_hint)

    async def select_rules(self, standard_json: Dict[str, Any], compatibility_score: float) -> Dict[str, Any]:
        """
        Phase 3: Rule Selection.
        Categorizes rules into safe, conditional, and forbidden.
        """
        schema_hint = json.dumps({
            "safe_rules": [{"rule_path": "string", "description": "string"}],
            "conditional_rules": [{"rule_path": "string", "description": "string"}],
            "forbidden_rules": [{"rule_path": "string", "description": "string"}],
            "justification": "string"
        }, indent=2)

        prompt = f"""
SYSTEM

You are a compliance-safe rule selector.
Never apply rules that could change meaning.

USER

Given:
- A standard specification
- A compatibility score of {compatibility_score}/100

Decide:
- Which rules are SAFE to apply
- Which rules require warnings
- Which rules must NOT be applied

Return JSON with:
- safe_rules
- conditional_rules
- forbidden_rules
- justification

STANDARD SPECIFICATION:
{str(standard_json)[:4000]}
"""

        return await self._chat(prompt, schema_hint)

    async def transform_document(self, doc_text: str, approved_rules: Dict[str, Any], competence_level: str = "general") -> Dict[str, Any]:
        """
        Phase 4: Gated Transformation with Deviation Accountability.
        Only applies pre-approved rules. Preserves meaning at all costs.
        """
        schema_hint = json.dumps({
            "transformed_text": "The full transformed document in Markdown",
            "deviations": [{
                "location": "string",
                "original_text": "string",
                "changed_to": "string",
                "reason": "string",
                "rule_reference": "string",
                "severity": "cosmetic|structural|semantic"
            }],
            "preserved_items": ["string"],
            "change_summary": "string"
        }, indent=2)

        prompt = f"""
SYSTEM

You are a document transformation engine.
Preserve meaning at all costs.

USER

Apply ONLY the approved rules to the target document.

Constraints:
- Do not introduce new obligations
- Do not invent content
- Insert placeholders where required
- Preserve original intent

APPROVED RULES:
{str(approved_rules)[:3000]}

TARGET DOCUMENT:
{doc_text[:12000]}
"""

        result = await self._chat(prompt, schema_hint)

        # Normalize response for legacy callers
        if isinstance(result, dict) and "transformed_text" not in result and "error" not in result:
            result["transformed_text"] = ""
        return result


ai_service = AIService()

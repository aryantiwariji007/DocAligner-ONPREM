from typing import Dict, Any, List, Optional
import httpx
import json
from backend.app.core.config import settings

class AIService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip('/')
        self.model_name = settings.OLLAMA_MODEL

    async def is_available(self) -> bool:
        """Check if the Ollama endpoint is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    async def _chat(self, prompt: str, schema_dict: Dict[str, Any], images: List[str] = None, temperature: float = 0.0) -> Dict[str, Any]:
        """Helper to call Ollama chat with a JSON schema constraint and optional images."""
        print(f"DEBUG: [AIService] Calling LLM model {self.model_name} with {len(images) if images else 0} images...")
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system", 
                    "content": "You are a document structure extraction engine.\n\nYour task is to extract ONLY structural information:\n- section titles\n- hierarchy levels\n- order\n- content type (narrative, list, table, mixed)\n\nSTRICT PROHIBITIONS:\n- Do NOT extract rules\n- Do NOT infer policies\n- Do NOT describe compliance requirements\n- Do NOT interpret legal meaning\n- Do NOT generalize standards\n\nIf content appears rule-like, IGNORE its meaning.\nReturn ONLY document structure.\n\nOutput must strictly follow the provided JSON schema.\nIf uncertain, return null."
                },
                {"role": "user", "content": prompt}
            ],
            "format": schema_dict,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "top_p": 0.9,
                "num_ctx": 16000,
            }
        }
        
        if images:
            payload["messages"][1]["images"] = images
        
        async with httpx.AsyncClient(timeout=1200.0) as client:
            try:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
                content = data.get("message", {}).get("content", "")
                return json.loads(content)
            except httpx.ReadTimeout as e:
                 print(f"[AIService] ReadTimeout: The AI model took too long to respond ({self.model_name})")
                 return {"error": "AI response timed out. Try with a smaller document or higher performance hardware."}
            except httpx.HTTPStatusError as e:
                print(f"[AIService] HTTP Error: {e.response.status_code} - {e.response.text}")
                raise e
            except json.JSONDecodeError as e:
                print(f"[AIService] JSON Parse Error. Content was: {content}")
                return {"error": "Invalid AI response structure", "p_content": content[:200]}
            except Exception as e:
                print(f"[AIService] Chat error ({type(e).__name__}): {e}")
                return {"error": f"AI process failed: {str(e)}"}

    async def extract_standard(self, text: str, filename: str, images: List[str] = None) -> Dict[str, Any]:
        """
        Extracts ONLY the document structure, hierarchy, and formatting patterns.
        Can process with vision (images) if provided.
        """
        if not await self.is_available():
            return {"error": "AI Service not configured"}

        prompt = f"""
        Analyze the document and extract the structural template. 
        {"Review the provided images to better understand layout, tables, and headers." if images else ""}
        
        Tasks:
        1. Identify Section titles and numbering logic
        2. Determine Nesting (H1 -> H2 -> H3)
        3. Establish Expected order
        4. Identify Presence requirements (mandatory / optional)
        5. Identify Content type per section (narrative | list | table | mixed)

        Do NOT extract or infer rules, policies, constraints, or compliance logic.

        Document Filename: {filename}
        Document Content:
        {text[:50000]}
        """
        
        # We define a flat list of sections rather than deeply recursive to ensure stable JSON output from Ollama,
        # but we capture the 'level' and 'parent_id' or 'id' to re-construct hierarchy if needed.
        schema = {
            "type": "object",
            "properties": {
                "template_id": {"type": "string"},
                "document_type": {"type": "string"},
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "level": {"type": "integer"},
                            "mandatory": {"type": "boolean"},
                            "order_index": {"type": "integer"},
                            "content_type": {"type": "string", "enum": ["narrative", "list", "table", "mixed"]}
                        },
                        "required": ["id", "title", "level", "mandatory", "order_index", "content_type"]
                    }
                }
            },
            "required": ["template_id", "document_type", "sections"]
        }

        try:
            return await self._chat(prompt, schema, images=images)
        except Exception as e:
            return {"error": f"AI extraction failed: {str(e)}"}

    async def extract_target_structure(self, text: str, filename: str, images: List[str] = None) -> Dict[str, Any]:
        """
        Node 1: Structure Extractor.
        Parses the Target Document to identify its current structure.
        """
        # We reuse the exact same schema and prompt logic as extraction, applied to target
        return await self.extract_standard(text, filename, images=images)

    async def normalize_structure(self, target_structure: Dict[str, Any], template: Dict[str, Any]) -> Dict[str, Any]:
        """
        Node 2: Structure Normalizer.
        Canonicalize section names, remove domain wording, collapse synonyms to match template IDs where possible.
        """
        if not await self.is_available():
             return target_structure

        prompt = f"""
        Given the following list of raw document headings:

        {json.dumps(target_structure.get("sections", []), indent=2)}

        Normalize the section titles and hierarchy ONLY against the canonical Template provided below.

        Template Sections (Canonical):
        {json.dumps(template.get("sections", []), indent=2)}

        Tasks:
        1. Remove numbering and formatting noise
        2. Normalize synonymous titles (e.g. "Applicability" → "Scope")
        3. Preserve original order
        4. Assign hierarchy levels
        5. Identify content type (narrative | list | table | mixed)

        Do NOT extract or infer:
        - rules
        - requirements
        - constraints
        - compliance logic
        """

        schema = {
            "type": "object",
            "properties": {
                "normalized_sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "original_title": {"type": "string"},
                            "canonical_id": {"type": "string", "description": "The matching ID from the Template, or null if no match"},
                            "level": {"type": "integer"},
                            "order_index": {"type": "integer"}
                        }
                    }
                }
            },
            "required": ["normalized_sections"]
        }
        
        try:
            return await self._chat(prompt, schema)
        except Exception as e:
            return {"error": f"AI normalization failed: {str(e)}"}

    async def transform_document(self, doc_text: str, target_structure: Dict[str, Any], missing_sections: List[str], misplaced_sections: List[Dict[str, Any]], images: List[str] = None) -> Dict[str, Any]:
        """
        Node 5/Auto-Fix: Transforms document to match the exact template structure.
        """
        if not await self.is_available():
            return {"transformed_text": "", "error": "AI Service not configured"}

        prompt = f"""
        You are a Document-Structure Auto-Fix Engine.
        Your job is to rewrite the target document ONLY to correct structural alignment errors.
        {"Review the provided images of the original document as a layout reference to ensure correct reconstruction." if images else ""}
        
        Fix Instructions:
        - Add missing mandatory sections: {missing_sections} (Insert "[TO BE ADDED]" as placeholder text if content is unknown)
        - Move misplaced sections to their correct order: {json.dumps(misplaced_sections)}
        - Target Structure Reference: {json.dumps(target_structure)}
        
        CRITICAL CONSTRAINTS:
        - Do NOT infer rules or change the meaning of the content.
        - Do NOT alter the wording beyond moving sections or adding placeholders.
        - Only shift structure to match the required standard.
        - Return the full document content reconstructed structurally.
        
        TARGET DOC CONTENT:
        {doc_text[:60000]}
        """
        
        schema = {
            "type": "object",
            "properties": {
                "transformed_text": {"type": "string"},
                "change_summary": {"type": "string"},
                "structural_json": {
                    "type": "object",
                    "properties": {
                        "TITLE": {"type": "string"},
                        "ABSTRACT": {"type": "string"},
                        "CONTEXT": {"type": "string"},
                        "CONTENT": {"type": "string"}
                    },
                    "required": ["TITLE", "ABSTRACT", "CONTEXT", "CONTENT"]
                }
            },
            "required": ["transformed_text", "change_summary", "structural_json"]
        }

        try:
            return await self._chat(prompt, schema, images=images)
        except Exception as e:
            return {"error": f"AI transformation failed: {str(e)}"}

ai_service = AIService()

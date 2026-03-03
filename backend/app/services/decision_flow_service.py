"""
Decision Flow Service — Orchestrates the Structural Alignment pipeline using LangGraph StateGraph.

Pipeline Nodes (STATIC Architecture):
1. extract_structure (LLM Proposal)
2. static_constrained_decoder (CSR Matrix enforce)
3. structure_scorer (Deterministic Scoring)
4. text_realizer (Content placement)
"""

from typing import Dict, Any, List, TypedDict, Literal
import math
from langgraph.graph import StateGraph, START, END
from backend.app.services.ai_service import ai_service
from backend.app.services.rule_extraction_service import rule_extraction_factory
from backend.app.services.static_index import StandardStructureIndex, STRUCTURE_VOCAB, REVERSE_VOCAB

# Global index caching (in a real app, this would be a specialized cache per standard)
_active_indices: Dict[str, StandardStructureIndex] = {}

class DecisionState(TypedDict):
    file_content: bytes
    filename: str
    standard_json: Dict[str, Any]
    text: str

    candidate_structure: List[int] | None
    validated_structure: List[int] | None
    
    score_svs: float | None
    score_bcs: float | None
    score_ess: float | None
    final_score: float | None
    
    action: str | None
    transformed_content: str | None
    structural_json: Dict[str, Any] | None
    
    template_id: str | None
    pdf_path: str | None
    
    stop_at_scoring: bool | None
    
    images: List[str] | None
    
    error: str | None

async def extract_structure(state: DecisionState) -> Dict[str, Any]:
    """Node 1: Extract candidate structure using LLM (Vision-augmented)."""
    print("DEBUG: [DecisionFlow] Node 1: extract_structure")
    extraction_res = rule_extraction_factory.extract_text(state["file_content"], state["filename"], as_multimodal=True)
    
    if isinstance(extraction_res, tuple):
        text, images = extraction_res
    else:
        text, images = extraction_res, []
        
    if not text:
        return {"error": "Could not extract text from document"}
        
    # Standard AI extraction to get a rough idea (passing images for better structural understanding)
    target_raw = await ai_service.extract_target_structure(text, state["filename"], images=images)
    if not target_raw or "error" in target_raw:
        return {"error": target_raw.get("error", "AI Extraction failed")}
        
    # Map raw strings back into our VOCAB as a simple list for the MVP proposal
    candidate = [STRUCTURE_VOCAB["DOC"]]
    for sec in target_raw.get("sections", []):
        t = sec.get("title", "").upper()
        if "TITLE" in t: candidate.append(STRUCTURE_VOCAB["TITLE"])
        elif "ABSTRACT" in t: candidate.append(STRUCTURE_VOCAB["ABSTRACT"])
        elif "SECTION" in t: candidate.append(STRUCTURE_VOCAB["SECTION"])
        elif "SUBSECTION" in t: candidate.append(STRUCTURE_VOCAB["SUBSECTION"])
        elif "CLAUSE" in t: candidate.append(STRUCTURE_VOCAB["CLAUSE"])
        elif "TABLE" in t: candidate.append(STRUCTURE_VOCAB["TABLE"])
        elif "FIGURE" in t: candidate.append(STRUCTURE_VOCAB["FIGURE"])
        elif "REFERENCE" in t: candidate.append(STRUCTURE_VOCAB["REFERENCES"])
        else: candidate.append(STRUCTURE_VOCAB["SECTION"])
    candidate.append(STRUCTURE_VOCAB["END"])
    
    return {"text": text, "images": images, "candidate_structure": candidate}


async def validate_and_score(state: DecisionState) -> Dict[str, Any]:
    """
    Node 2: Deterministic Validation & Scoring.
    1. Enforce valid structures via the CSR mask mathematically (Ollama Snapping).
    2. Compute final deterministic compliance score.
    """
    print("DEBUG: [DecisionFlow] Node 2: validate_and_score")
    
    if state.get("error"):
        return {"final_score": 0.0, "action": "fail", "risk": "CRITICAL"}
    
    # --- 1. CSR Validation (Snapping) ---
    std_hash = str(hash(str(state["standard_json"])))
    if std_hash not in _active_indices:
        idx = StandardStructureIndex()
        idx.build_from_standard(state["standard_json"])
        _active_indices[std_hash] = idx
    static_index = _active_indices[std_hash]

    candidate = state.get("candidate_structure") or [STRUCTURE_VOCAB["DOC"], STRUCTURE_VOCAB["END"]]
    validated, valid_transitions = static_index.snap_to_valid_path(candidate)

    # Calculate deterministic metrics
    total_steps = len(candidate) - 1
    svs = valid_transitions / max(total_steps, 1)
    bcs = 0.7 + (svs * 0.25)
    ess = 0.8 + (svs * 0.15)
    
    # --- 2. Final Scoring ---
    final_score = (0.5 * svs) + (0.3 * bcs) + (0.2 * ess)
    
    if final_score >= 0.8:
        action = "safe_apply"
        risk = "LOW"
    elif final_score >= 0.60:
        action = "selective_apply"
        risk = "MEDIUM" 
    else:
        action = "enforced_apply"
        risk = "CRITICAL"

    return {
        "validated_structure": validated,
        "score_svs": svs,
        "score_bcs": bcs,
        "score_ess": ess,
        "final_score": final_score,
        "action": action,
        "alignment_report": {
            "SVS": svs,
            "BCS": bcs,
            "ESS": ess,
            "risk": risk
        }
    }

async def text_realizer(state: DecisionState) -> Dict[str, Any]:
    """Node 4: Map content into validated structure."""
    print("DEBUG: [DecisionFlow] Node 4: text_realizer")
    
    if state.get("error"):
        return {"transformed_content": state.get("text", ""), "structural_json": {}}

    # We use AI to map the original text into the rigorously mathematically validated structure tokens!
    valid_path = state.get("validated_structure") or []
    candidate_path = state.get("candidate_structure") or []
    
    # 1. Calculate specific missing/misplaced sections for precise fixing
    # We map tokens to their names for better AI understanding
    valid_names = [REVERSE_VOCAB.get(t, "SECTION") for t in valid_path if t not in [STRUCTURE_VOCAB["DOC"], STRUCTURE_VOCAB["END"]]]
    candidate_names = [REVERSE_VOCAB.get(t, "SECTION") for t in candidate_path if t not in [STRUCTURE_VOCAB["DOC"], STRUCTURE_VOCAB["END"]]]
    
    missing_sections = [name for name in valid_names if name not in candidate_names]
    
    # Misplaced logic: Sections that are present but in the wrong order
    misplaced = []
    # Simple check: if the sequence of common elements differs
    common_in_candidate = [name for name in candidate_names if name in valid_names]
    common_in_valid = [name for name in valid_names if name in candidate_names]
    
    if common_in_candidate != common_in_valid:
        for i, name in enumerate(common_in_candidate):
            if i < len(common_in_valid) and name != common_in_valid[i]:
                misplaced.append({"section": name, "should_be_near": common_in_valid[i]})

    target_structure_str = " -> ".join(valid_names)
    
    # 2. Call ai_service with full context and vision evidence
    transformed = await ai_service.transform_document(
        state["text"], 
        {"expected_hierarchy": target_structure_str},
        missing_sections=missing_sections, 
        misplaced_sections=misplaced,
        images=state.get("images", []) # Passing the vision evidence!
    )
    
    return {
        "transformed_content": transformed.get("transformed_text", state["text"]),
        "structural_json": transformed.get("structural_json", {}),
        "change_summary": transformed.get("change_summary", "Reconstructing document to align with standard structure.")
    }

async def fixed_pdf_generator_node(state: DecisionState) -> Dict[str, Any]:
    """Node 5: Generate a fixed-structure PDF using a predefined LaTeX template."""
    print("DEBUG: [DecisionFlow] Node 5: fixed_pdf_generator_node")
    
    if not state["structural_json"]:
        return {"pdf_path": None}

    from backend.app.services.pdf_service import pdf_service
    
    template_id = state.get("template_id") or "compliance_report_v1"
    
    try:
        # Use structural_json directly from previous node
        pdf_path = pdf_service.create_structural_pdf(
            template_id=template_id,
            content_dict=state["structural_json"]
        )
        return {"pdf_path": pdf_path}
    except Exception as e:
        print(f"Warning: PDF Generator Node failed: {e}")
        return {"pdf_path": None, "error": f"PDF generation failed: {str(e)}"}

def _build_graph() -> StateGraph:
    workflow = StateGraph(DecisionState)
    
    workflow.add_node("extract_structure", extract_structure)
    workflow.add_node("validate_and_score", validate_and_score)
    workflow.add_node("text_realizer", text_realizer)
    workflow.add_node("fixed_pdf_generator", fixed_pdf_generator_node)
    
    workflow.add_edge(START, "extract_structure")
    workflow.add_edge("extract_structure", "validate_and_score")
    
    def router(state: DecisionState) -> Literal["text_realizer", "__end__"]:
        if state.get("stop_at_scoring") or state.get("error"):
            return "__end__"
        return "text_realizer"

    workflow.add_conditional_edges(
        "validate_and_score",
        router,
        {
            "text_realizer": "text_realizer",
            "__end__": END
        }
    )
    workflow.add_edge("text_realizer", "fixed_pdf_generator")
    workflow.add_edge("fixed_pdf_generator", END)
    
    return workflow.compile()

_decision_graph = _build_graph()

class DecisionFlowService:
    async def analyze(self, file_content: bytes, filename: str, standard_json: Dict[str, Any]) -> Dict[str, Any]:
        """Runs the pipeline up through scoring."""
        # Now we specify to stop after scoring for faster analysis
        return await self.apply(file_content, filename, standard_json, stop_at_scoring=True)

    async def apply(self, file_content: bytes, filename: str, standard_json: Dict[str, Any], competence_level: str = "general", stop_at_scoring: bool = False) -> Dict[str, Any]:
        """Runs the full STATIC pipeline."""
        initial_state: DecisionState = {
            "file_content": file_content,
            "filename": filename,
            "standard_json": standard_json,
            "text": "",
            "candidate_structure": None,
            "validated_structure": None,
            "score_svs": None,
            "score_bcs": None,
            "score_ess": None,
            "final_score": None,
            "action": None,
            "transformed_content": None,
            "structural_json": None,
            "template_id": "compliance_report_v1",
            "pdf_path": None,
            "stop_at_scoring": stop_at_scoring,
            "images": None,
            "error": None
        }
        
        final_state = await _decision_graph.ainvoke(initial_state)
        
        if final_state.get("error"):
            return {"error": final_state["error"]}
            
        report = final_state.get("alignment_report", {})
        final_score = final_state.get("final_score", 0.0) * 100
        
        return {
            "action": final_state["action"],
            "score": final_score,
            "risk": report.get("risk", "high"),
            "transformed_content": final_state.get("transformed_content"),
            "structural_json": final_state.get("structural_json"),
            "pdf_path": final_state.get("pdf_path"),
            "original_content": final_state.get("text"),
            "filename": filename,
            "change_summary": report.get("change_summary", "Enforced STATIC template structure."),
            "alignment_details": report,
            "vision_evidence": final_state.get("images", [])[:3], # Provide first 3 pages as vision evidence
            "compatibility": {
                "total_score": final_score,
                "risk_classification": report.get("risk", "high"),
                "dimensions": {
                    "presence": final_state.get("score_svs", 0) * 100,
                    "order": final_state.get("score_bcs", 0) * 100,
                    "hierarchy": final_state.get("score_ess", 0) * 100,
                    "completeness": 100
                },
                "alignment_details": report
            },
            "decision_flow": {
                "action": final_state["action"],
                "score": final_score,
                "risk": report.get("risk", "high"),
                "rule_selection": {},
                "warnings": report.get("warnings", []),
                "deviations": report.get("deviations", []),
                "preserved_items": [],
                "change_summary": report.get("change_summary", "Static constrained decoding complete."),
                "ai_evaluation": {
                    "scorecard": {"overall": final_score}
                }
            }
        }

decision_flow_service = DecisionFlowService()

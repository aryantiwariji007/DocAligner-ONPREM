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
    
    error: str | None

async def extract_structure(state: DecisionState) -> Dict[str, Any]:
    """Node 1: Extract candidate structure using LLM."""
    print("DEBUG: [DecisionFlow] Node 1: extract_structure")
    text = rule_extraction_factory.extract_text(state["file_content"], state["filename"])
    if not text:
        return {"error": "Could not extract text from document"}
        
    # Standard AI extraction to get a rough idea (ignoring constraints just for the proposal)
    target_raw = await ai_service.extract_target_structure(text, state["filename"])
    if "error" in target_raw:
        return {"error": target_raw["error"]}
        
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
    
    return {"text": text, "candidate_structure": candidate}


async def static_constrained_decoder(state: DecisionState) -> Dict[str, Any]:
    """
    Node 2: Enforce valid structures via the CSR mask mathematically.
    Temporary Ollama Fallback: Snaps the candidate structure to the nearest valid CSR path.
    """
    print("DEBUG: [DecisionFlow] Node 2: static_constrained_decoder (Ollama Snapping)")
    
    # 1. Prepare Standard Index
    std_hash = str(hash(str(state["standard_json"])))
    if std_hash not in _active_indices:
        idx = StandardStructureIndex()
        idx.build_from_standard(state["standard_json"])
        _active_indices[std_hash] = idx
    static_index = _active_indices[std_hash]

    # 2. Algorithmic Snapping (Deterministic Path Alignment)
    # Since we aren't masking logits with llama-cpp right now, we post-process the candidate.
    # We walk the candidate and force every transition to be valid according to the CSR.
    
    candidate = state.get("candidate_structure") or [STRUCTURE_VOCAB["DOC"], STRUCTURE_VOCAB["END"]]
    validated, valid_transitions = static_index.snap_to_valid_path(candidate)

    # Calculate deterministic metrics
    # SVS: Percentage of transitions that were valid WITHOUT snapping
    total_steps = len(candidate) - 1
    svs = valid_transitions / max(total_steps, 1)
    
    # BCS/ESS: Estimated since we don't have raw logits from Ollama
    # High SVS implies high confidence in the candidate layout.
    bcs = 0.7 + (svs * 0.25)
    ess = 0.8 + (svs * 0.15)
    
    return {
        "validated_structure": validated,
        "score_svs": svs,
        "score_bcs": bcs,
        "score_ess": ess
    }

async def structure_scorer(state: DecisionState) -> Dict[str, Any]:
    """Node 3: Compute final deterministic compliance score."""
    print("DEBUG: [DecisionFlow] Node 3: structure_scorer")
    
    svs = state.get("score_svs", 0.0)
    bcs = state.get("score_bcs", 0.0)
    ess = state.get("score_ess", 0.0)
    
    # FinalComplianceScore = 0.5 * SVS + 0.3 * BCS + 0.2 * ESS
    final_score = (0.5 * svs) + (0.3 * bcs) + (0.2 * ess)
    
    # Threshold Routing
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
    
    # We use AI to map the original text into the rigorously mathematically validated structure tokens!
    # [BYPASS] Irrespective of score, we allow regeneration as requested.

    # Format the strict validated structure path as text to feed the realizer prompt
    valid_path_names = [REVERSE_VOCAB[t] for t in state["validated_structure"]]
    target_structure_str = " -> ".join(valid_path_names)
    
    # Simple realizer via ai_service
    transformed = await ai_service.transform_document(
        state["text"], 
        {"validated_path": target_structure_str},
        missing_sections=[], 
        misplaced_sections=[]
    )
    
    return {
        "transformed_content": transformed.get("transformed_text", state["text"]),
        "structural_json": transformed.get("structural_json", {})
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
    workflow.add_node("static_constrained_decoder", static_constrained_decoder)
    workflow.add_node("structure_scorer", structure_scorer)
    workflow.add_node("text_realizer", text_realizer)
    workflow.add_node("fixed_pdf_generator", fixed_pdf_generator_node)
    
    workflow.add_edge(START, "extract_structure")
    workflow.add_edge("extract_structure", "static_constrained_decoder")
    workflow.add_edge("static_constrained_decoder", "structure_scorer")
    def router(state: DecisionState) -> Literal["text_realizer", "__end__"]:
        if state.get("stop_at_scoring"):
            return "__end__"
        return "text_realizer"

    workflow.add_conditional_edges(
        "structure_scorer",
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

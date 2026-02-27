"""
langgraph_service.py
====================
LangGraph-controlled DSAT-Centric Policy Compliance Engine for DocAligner.

DAG:
  START
    → classify_scope_node           (functional role classification, rules-only)
    → retrieve_standards_node       (Qdrant search, cached)
    → resolve_alignment_type_node   (applies structural rules R1-R4)
    → extract_evidence_node         (Qwen2.5-7b, evidence extraction only)
    → deterministic_scorer_node     (weighted math scorer, rules-only)
    → finalize_node                 (formats report)
    → END
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from backend.app.core.config import settings

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class VolumeRole(str, Enum):
    TRAINING_EXECUTION = "Training Definition & Execution" # Vol 2, 3
    SAFEGUARDS = "Human & Welfare Safeguards"              # Vol 4, 7
    ASSURANCE = "Independent Assurance Layer"             # Vol 5
    SYSTEM_ENABLER = "System / Technology Enabler"        # Vol 6
    UNKNOWN = "Unknown"

class AlignmentType(str, Enum):
    DIRECT = "DIRECT"             # Explicitly implements the requirement (Weight: 1.00)
    ENABLING = "ENABLING"         # Provides systems/processes that support it (Weight: 0.75)
    GOVERNING = "GOVERNING"       # Oversees or assures it (Weight: 0.85)
    SPECIALISED = "SPECIALISED"   # Applies it to specific population/context (Weight: 0.80)
    REFERENCED = "REFERENCED"     # Explicitly defers to another JSP volume (Weight: 0.65)
    OUT_OF_SCOPE = "OUT_OF_SCOPE" # Intentionally not applicable (Excluded from scoring)
    NO = "NO"                     # Failed to comply


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class DocAlignState(TypedDict):
    """Shared mutable state threaded through every graph node."""
    doc_id: str
    doc_title: str
    chunks: List[str]                # document text chunks
    standards: List[Dict[str, Any]]  # retrieved from Qdrant with cosine scores
    
    # New Pipeline State
    volume_role: str
    alignment_types: Dict[str, str]               # Clause ID -> AlignmentType string
    extracted_evidence: Dict[str, Dict[str, Any]] # Clause ID -> {evidence: [], strength: str, justification: str}
    final_score: float                            # 0.0 to 1.0
    
    final_result: Dict[str, Any]     # backward-compatible compliance report
    langgraph_run_id: str


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

ALIGNMENT_WEIGHTS = {
    AlignmentType.DIRECT.value: 1.00,
    AlignmentType.GOVERNING.value: 0.85,
    AlignmentType.SPECIALISED.value: 0.80,
    AlignmentType.ENABLING.value: 0.75,
    AlignmentType.REFERENCED.value: 0.65,
    AlignmentType.OUT_OF_SCOPE.value: 0.0,
}

EVIDENCE_MULTIPLIERS = {
    "Explicit": 1.0,
    "Clear": 0.9,
    "Implicit": 0.7,
    "None": 0.0
}


def _chunk_text(text: str, max_chunk_length: int = 2500) -> List[str]:
    """Simple paragraph-aware chunker."""
    try:
        from backend.app.services.rule_extraction_service import rule_extraction_factory
        return rule_extraction_factory.split_by_headings(text, max_chunk_length=max_chunk_length)
    except Exception:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks, current = [], ""
        for p in paragraphs:
            if len(current) + len(p) + 2 > max_chunk_length and current:
                chunks.append(current)
                current = p
            else:
                current = (current + "\n\n" + p).strip() if current else p
        if current:
            chunks.append(current)
        return chunks or [text[:max_chunk_length]]


# ---------------------------------------------------------------------------
# Node 1: classify_scope_node
# ---------------------------------------------------------------------------

async def classify_scope_node(state: DocAlignState) -> DocAlignState:
    """Classifies document role based on name/metadata. (Rules only)"""
    title = state.get("doc_title", "").lower()
    
    # Improved regex to handle underscores, dashes, etc.
    vol_pattern = r'vol(?:ume)?[\s_\-]*([2-7])'
    match = re.search(vol_pattern, title)
    
    role = VolumeRole.UNKNOWN.value
    if match:
        vol_num = match.group(1)
        if vol_num in ('2', '3'):
            role = VolumeRole.TRAINING_EXECUTION.value
        elif vol_num in ('4', '7'):
            role = VolumeRole.SAFEGUARDS.value
        elif vol_num == '5':
            role = VolumeRole.ASSURANCE.value
        elif vol_num == '6':
            role = VolumeRole.SYSTEM_ENABLER.value

    print(f"[LangGraph] classify_scope_node: '{title}' matched Vol {match.group(1) if match else 'None'} -> {role}")
    return {**state, "volume_role": role}


# ---------------------------------------------------------------------------
# Node 1.5: retrieve_standards_node (Existing Qdrant search)
# ---------------------------------------------------------------------------

async def retrieve_standards_node(state: DocAlignState) -> DocAlignState:
    """Searches Qdrant for relevant standards."""
    from backend.app.services.cache_service import cache_service
    from backend.app.services.memory_service import memory_service

    doc_id = state["doc_id"]
    chunks = state["chunks"]

    all_standards: List[Dict[str, Any]] = []
    seen_clause_ids: set = set()

    for chunk in chunks:
        chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
        cache_key = f"qdrant:{chunk_hash}"

        cached = await cache_service.get_cached_result(cache_key)
        if cached:
            for item in cached:
                if item.get("clause_id") not in seen_clause_ids:
                    all_standards.append(item)
                    seen_clause_ids.add(item.get("clause_id"))
            continue

        try:
            # Broaden search for accuracy (limit 15, lower threshold 0.60)
            results = memory_service.search_rules(query=chunk, topic_id=doc_id, limit=15)
            hits = results.get("results", []) if isinstance(results, dict) else []
            filtered = [h for h in hits if h.get("score", 0) >= 0.60]

            await cache_service.set_cached_result(cache_key, filtered, ttl=60 * 60 * 6)

            for item in filtered:
                if item.get("clause_id") not in seen_clause_ids:
                    all_standards.append(item)
                    seen_clause_ids.add(item.get("clause_id"))
        except Exception as e:
            print(f"[LangGraph] retrieve_standards_node: Qdrant error — {e}")

    return {**state, "standards": all_standards}


# ---------------------------------------------------------------------------
# Node 2: resolve_alignment_type_node
# ---------------------------------------------------------------------------

def _get_dsat_element(text: str) -> str:
    text = text.lower()
    if "analysis" in text: return "Analysis"
    if "design" in text: return "Design"
    if "deliver" in text: return "Delivery"
    if "assur" in text: return "Assurance"
    return "Unknown"

async def resolve_alignment_type_node(state: DocAlignState) -> DocAlignState:
    """Applies rules R1-R4 to classify clause alignment type before extraction."""
    role = state.get("volume_role", VolumeRole.UNKNOWN.value)
    standards = state.get("standards", [])
    chunks = state.get("chunks", [])
    
    doc_text_lower = "\n".join(chunks).lower()
    
    # R4: Explicit Reference detection globally
    has_explicit_reference = any(phrase in doc_text_lower for phrase in [
        "in accordance with jsp 822",
        "dsat must be applied",
        "governed under defence policy"
    ])
    
    if has_explicit_reference:
        print("[LangGraph] resolve_alignment_type_node: Detected Explicit Reference (R4)")

    alignment_types = {}

    for s in standards:
        cid = s.get("clause_id", "")
        mem = s.get("memory", "")
        elem = _get_dsat_element(mem)
        
        atype = AlignmentType.DIRECT.value
        
        # Apply DSAT-centric functional mapping
        if elem != "Unknown":
            if role == VolumeRole.SAFEGUARDS.value:
                if elem in ("Analysis", "Design"):
                    atype = AlignmentType.REFERENCED.value
                else:
                    atype = AlignmentType.SPECIALISED.value
                    
            elif role == VolumeRole.ASSURANCE.value:
                if elem == "Assurance":
                    atype = AlignmentType.DIRECT.value
                else:
                    atype = AlignmentType.GOVERNING.value
                    
            elif role == VolumeRole.SYSTEM_ENABLER.value:
                atype = AlignmentType.ENABLING.value
        
        # R4: Explicit Reference Upgrade (If absent artefacts → OUT_OF_SCOPE or Unknown, but we have global reference)
        if has_explicit_reference and atype == AlignmentType.OUT_OF_SCOPE.value:
            atype = AlignmentType.REFERENCED.value
            
        alignment_types[cid] = atype

    print(f"[LangGraph] resolve_alignment_type_node: resolved {len(alignment_types)} alignment types")
    return {**state, "alignment_types": alignment_types}


# ---------------------------------------------------------------------------
# Node 3: extract_evidence_node
# ---------------------------------------------------------------------------

async def extract_evidence_node(state: DocAlignState) -> DocAlignState:
    """Uses LLM solely to extract evidence quotes matching the Alignment Type."""
    from backend.app.services.ai_service import ai_service
    from backend.app.services.cache_service import cache_service

    doc_id = state["doc_id"]
    chunks = state["chunks"]
    standards = state["standards"]
    alignment_types = state.get("alignment_types", {})

    # Use cache to avoid LLM spam
    cache_key = f"evidence:{doc_id}"
    cached_evidence = await cache_service.get_cached_result(cache_key)
    if cached_evidence:
        print(f"[LangGraph] extract_evidence_node: Cache hit for {doc_id}")
        return {**state, "extracted_evidence": cached_evidence}

    print(f"[LangGraph] extract_evidence_node: extracting evidence for {len(standards_to_extract)} standards across {len(chunks)} chunks.")
    
    # We increase max_tokens for better accuracy and detailed evidence
    max_tokens = 4096 
    
    chunks_text = "\n\n---\n\n".join(chunks[:20]) # Increased chunk limit for more context
    
    standards_payload = [
        {
            "standard_id": s.get("clause_id"),
            "text": s.get("memory"),
            "expected_alignment_type": alignment_types.get(s.get("clause_id"))
        }
        for s in standards_to_extract[:25] # Increased standard limit
    ]

    system_prompt = (
        "You are an expert policy auditor and evidence extraction engine.\n"
        "Your task is to identify EXACT evidence (direct quotes or specific section references) from the provided document chunks that support the given alignment type.\n"
        "ALIGNMENT TYPES GUIDE:\n"
        "- DIRECT: The document specifically fulfills this rule.\n"
        "- ENABLING: The document provides the infrastructure or processes that allow others to fulfill this rule.\n"
        "- GOVERNING: The document sets the strategy or oversight for this rule.\n"
        "- REFERENCED: The document explicitly mentions following the JSP 822 volume or external policy covering this rule.\n"
        "Strictly cite evidence only from the provided text. Be thorough."
    )

    user_prompt = f"""DOCUMENT CHUNKS:
{chunks_text}

TARGET STANDARDS & EXPECTED ALIGNMENT:
{json.dumps(standards_payload, indent=2)}

TASK:
For each standard:
1. Search the chunks for evidence matching the 'expected_alignment_type'.
2. Provide verbatim quotes.
3. Rate strength as:
   - 'Explicit': Verbatim confirmation.
   - 'Clear': Strong structural/procedural support.
   - 'Implicit': Logical necessity based on the role/references.
   - 'None': No support found.

OUTPUT (JSON ONLY):
{{
  "extracted_evidence": [
    {{
      "standard_id": "...",
      "evidence": ["quote 1", "quote 2"],
      "strength": "Explicit | Clear | Implicit | None",
      "justification": "Detailed reasoning for this strength rating."
    }}
  ]
}}"""

    schema_hint = json.dumps({
        "extracted_evidence": [
            {
                "standard_id": "string",
                "evidence": ["string"],
                "strength": "Explicit | Clear | Implicit | None",
                "justification": "string"
            }
        ]
    })

    combined = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}"
    try:
        # Pass higher max_tokens
        result = await ai_service._chat(combined, schema_hint, temperature=0.0, max_tokens=max_tokens)
    except Exception as e:
        print(f"[LangGraph] extract_evidence_node: LLM error — {e}")
        result = {"extracted_evidence": []}

    evidence_dict = {}
    for ev in result.get("extracted_evidence", []):
        sid = ev.get("standard_id", "")
        # Normalize strength string safely
        raw_strength = ev.get("strength", "None")
        if isinstance(raw_strength, str):
            strength = next((k for k in EVIDENCE_MULTIPLIERS.keys() if k.lower() in raw_strength.lower()), "None")
        else:
            strength = "None"
            
        evidence_dict[sid] = {
            "evidence": ev.get("evidence", []),
            "strength": strength,
            "justification": ev.get("justification", "")
        }

    # Fill missing
    for s in standards:
        cid = s["clause_id"]
        if alignment_types.get(cid) == AlignmentType.OUT_OF_SCOPE.value:
            evidence_dict[cid] = {"evidence": [], "strength": "None", "justification": "Out of scope"}
            continue
        if cid not in evidence_dict:
            evidence_dict[cid] = {"evidence": [], "strength": "None", "justification": "Missed by extraction"}

    print(f"[LangGraph] extract_evidence_node: extracted evidence for {len(evidence_dict)} standards")
    await cache_service.set_cached_result(cache_key, evidence_dict, ttl=60 * 30)

    return {**state, "extracted_evidence": evidence_dict}


# ---------------------------------------------------------------------------
# Node 4: deterministic_scorer_node
# ---------------------------------------------------------------------------

async def deterministic_scorer_node(state: DocAlignState) -> DocAlignState:
    """Computes systemic math score avoiding duplication penalties."""
    alignment_types = state.get("alignment_types", {})
    extracted_evidence = state.get("extracted_evidence", {})

    total_score = 0.0
    total_weight = 0.0
    
    # R4 Fallback: Explicit reference gives baseline minimum
    doc_text_lower = "\n".join(state.get("chunks", [])).lower()
    has_explicit_reference = any(phrase in doc_text_lower for phrase in [
        "in accordance with jsp 822",
        "dsat must be applied",
        "governed under defence policy"
    ])

    for cid, atype in alignment_types.items():
        if atype == AlignmentType.OUT_OF_SCOPE.value:
            continue
            
        weight = ALIGNMENT_WEIGHTS.get(atype, 1.0)
        ev = extracted_evidence.get(cid, {})
        strength = ev.get("strength", "None")

        # R4 Logic: Explicit Reference = Partial Credit (never 0)
        if has_explicit_reference and atype == AlignmentType.REFERENCED.value and EVIDENCE_MULTIPLIERS.get(strength, 0.0) == 0.0:
            strength = "Implicit"
            ev["strength"] = "Implicit"
            ev["justification"] = "Implicit support via Explicit Document Reference (R4)"

        mult = EVIDENCE_MULTIPLIERS.get(strength, 0.0)
        clause_score = weight * mult
        
        total_score += clause_score
        total_weight += weight

    final_score = total_score / total_weight if total_weight > 0 else 0.0
    
    print(f"[LangGraph] deterministic_scorer_node: final_score {final_score:.2f} (from denominator weight {total_weight})")
    return {**state, "final_score": final_score, "extracted_evidence": extracted_evidence} # return updated missing evidence if R4 patched it


# ---------------------------------------------------------------------------
# Node 5: finalize_node
# ---------------------------------------------------------------------------

async def finalize_node(state: DocAlignState) -> DocAlignState:
    """Assembles backward-compatible compliance report."""
    final_score = state.get("final_score", 0.0)
    standards = state.get("standards", [])
    alignment_types = state.get("alignment_types", {})
    extracted_evidence = state.get("extracted_evidence", {})

    violations: List[Dict[str, Any]] = []
    active_alignments: List[Dict[str, Any]] = []

    for s in standards:
        cid = s.get("clause_id", "")
        atype = alignment_types.get(cid, AlignmentType.OUT_OF_SCOPE.value)
        ev = extracted_evidence.get(cid, {})
        strength = ev.get("strength", "None")
        
        status = "YES" if strength in ("Explicit", "Clear") else "PARTIAL" if strength == "Implicit" else "NO"
        if atype == AlignmentType.OUT_OF_SCOPE.value:
            status = "OUT_OF_SCOPE"
            strength_mult = 0.0
        else:
            strength_mult = EVIDENCE_MULTIPLIERS.get(strength, 0.0)
            
        conf = ALIGNMENT_WEIGHTS.get(atype, 1.0) * strength_mult

        align_obj = {
            "standard_id": cid,
            "status": status,
            "alignment_type": atype,
            "evidence": ev.get("evidence", []),
            "justification": ev.get("justification", ""),
            "confidence": conf
        }
        active_alignments.append(align_obj)

        if status in ("NO", "PARTIAL") and atype != AlignmentType.OUT_OF_SCOPE.value:
            violations.append({
                "status": "FAIL" if status == "NO" else "PARTIAL",
                "observation": f"Standard {cid} ({atype}) — {status}",
                "expert_reasoning": ev.get("justification", ""),
                "severity": "high" if status == "NO" else "medium",
                "obligation_level": s.get("obligation", "mandatory"),
                "rule_path": cid,
                "standard_excerpt": s.get("memory", ""),
                "suggested_fix": "Add explicit phrasing supporting this clause.",
            })

    compliance_score = round(final_score * 100)
    mandatory_fails = [v for v in violations if v.get("obligation_level") == "mandatory" and v.get("status") == "FAIL"]
    is_compliant = len(mandatory_fails) == 0

    scorecard = {
        "authority_compliance": compliance_score,
        "obligation_compliance": compliance_score,
        "structural_compliance": compliance_score,
        "metadata_compliance": compliance_score,
        "terminology_compliance": compliance_score,
        "overall": compliance_score,
    }

    must_failed = len(mandatory_fails)
    should_failed = len([v for v in violations if v.get("status") == "PARTIAL"])
    obligation_summary = [
        {"level": "mandatory", "total_rules": max(must_failed, 1), "passed": 0 if must_failed > 0 else 1, "failed": must_failed},
        {"level": "recommended", "total_rules": max(should_failed, 1), "passed": 0 if should_failed > 0 else 1, "failed": should_failed},
    ]

    final_result: Dict[str, Any] = {
        "standard_id": state.get("doc_id", "unknown"),
        "compliance_score": compliance_score,
        "compliant": is_compliant,
        "scorecard": scorecard,
        "obligation_summary": obligation_summary,
        "confidence": "high",
        "confidence_score": final_score,
        "risk_areas": [v.get("observation", "") for v in violations[:5]],
        "reviewer_notes": f"Role: {state.get('volume_role')}. Evaluated {len(active_alignments)} rules systemically.",
        "violations": violations,
        "skipped_rules": [],
        "auto_fix_possible": len(violations) > 0,
        "compatibility_score": 0,
        "compatibility_warning": "",
        "langgraph_run_id": state.get("langgraph_run_id", ""),
        "aligned_standards": active_alignments,
    }

    return {**state, "final_result": final_result}


# ---------------------------------------------------------------------------
# Node 6: audit_alignment_node (High Accuracy / Accuracy over Latency)
# ---------------------------------------------------------------------------

async def audit_alignment_node(state: DocAlignState) -> DocAlignState:
    """Extra deep-dive pass for low-scoring documents to ensure no evidence was missed."""
    from backend.app.services.ai_service import ai_service
    
    current_score = state.get("final_score", 0.0)
    print(f"[LangGraph] audit_alignment_node: Auditing low score {current_score:.2f}...")

    # We take even MORE context for the audit (top 40 chunks / almost whole doc)
    chunks = state["chunks"]
    chunks_text = "\n\n".join(chunks[:40])
    
    alignment_types = state.get("alignment_types", {})
    extracted_evidence = state.get("extracted_evidence", {})
    
    # Identify failed standards
    failed_standards = [
        s for s in state["standards"]
        if extracted_evidence.get(s["clause_id"], {}).get("strength") == "None"
        and alignment_types.get(s["clause_id"]) != AlignmentType.OUT_OF_SCOPE.value
    ]

    if not failed_standards:
        return state

    print(f"[LangGraph] audit_alignment_node: Re-evaluating {len(failed_standards)} 'None' matches...")

    payload = [
        {"id": s["clause_id"], "text": s["memory"], "atype": alignment_types.get(s["clause_id"])}
        for s in failed_standards[:10] # Audit in chunks of 10
    ]

    prompt = f"""
SYSTEM: You are a Lead Policy Auditor. Your goal is to find subtle or implicit evidence that might have been missed.
USER: We found NO evidence for these standards. Please re-scan the document thoroughly. 
If you find ANY support—even implicit or procedural—upgrade them from 'None'.

DOCUMENT:
{chunks_text}

TARGETS:
{json.dumps(payload, indent=2)}

OUTPUT (JSON ONLY):
{{ "audit_results": [ {{ "id": "...", "found": true|false, "quote": "...", "strength": "Clear|Implicit", "reason": "..." }} ] }}
"""

    schema_hint = json.dumps({"audit_results": [{"id": "string", "found": True, "quote": "string", "strength": "Implicit", "reason": "string"}]})
    
    try:
        res = await ai_service._chat(prompt, schema_hint, temperature=0.0, max_tokens=2048)
        
        # Merge results
        for item in res.get("audit_results", []):
            if item.get("found"):
                sid = item.get("id")
                extracted_evidence[sid] = {
                    "evidence": [item.get("quote")],
                    "strength": item.get("strength", "Implicit"),
                    "justification": f"AUDIT PASS: {item.get('reason')}"
                }
                print(f"[LangGraph] Audit SUCCESS: Upgraded {sid} to {item.get('strength')}")
    except Exception as e:
        print(f"[LangGraph] audit_alignment_node: Error — {e}")

    # Re-trigger scoring math
    return await deterministic_scorer_node({**state, "extracted_evidence": extracted_evidence})


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

def audit_gate(state: DocAlignState) -> str:
    """Route to audit if score is low and accuracy is prioritized."""
    score = state.get("final_score", 0.0)
    # If score < 70%, try one more time to find missing evidence (Audit)
    # To prevent loops, we track if we already audited
    if score < 0.70 and "audited" not in state.get("langgraph_run_id", ""):
        # We append 'audited' to run_id to flag it
        return "audit"
    return "finalize"


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    """Compile the LangGraph state machine once at module load time."""
    builder = StateGraph(DocAlignState)

    builder.add_node("classify_scope", classify_scope_node)
    builder.add_node("retrieve_standards", retrieve_standards_node)
    builder.add_node("resolve_alignment", resolve_alignment_type_node)
    builder.add_node("extract_evidence", extract_evidence_node)
    builder.add_node("deterministic_scorer", deterministic_scorer_node)
    builder.add_node("audit_alignment", audit_alignment_node)
    builder.add_node("finalize", finalize_node)

    # 4-node + retrieval pipeline
    builder.add_edge(START, "classify_scope")
    builder.add_edge("classify_scope", "retrieve_standards")
    builder.add_edge("retrieve_standards", "resolve_alignment")
    builder.add_edge("resolve_alignment", "extract_evidence")
    builder.add_edge("extract_evidence", "deterministic_scorer")
    
    # Accuracy Gate
    builder.add_conditional_edges(
        "deterministic_scorer",
        audit_gate,
        {
            "audit": "audit_alignment",
            "finalize": "finalize"
        }
    )
    
    builder.add_edge("audit_alignment", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()

_graph = _build_graph()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_alignment_graph(
    doc_id: str,
    doc_text: str,
    standard_id: str,
    standard_json: Optional[Dict[str, Any]] = None,
    doc_title: str = "Unknown",
) -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    print(f"[LangGraph] run_alignment_graph: doc_id={doc_id} doc_title='{doc_title}' run_id={run_id}")
    
    if not doc_text:
        print("[LangGraph] ERROR: Received EMPTY doc_text")
    else:
        print(f"[LangGraph] doc_text prefix: {doc_text[:150]}...")

    chunks = _chunk_text(doc_text)

    initial_state: DocAlignState = {
        "doc_id": standard_id,
        "doc_title": doc_title,
        "chunks": chunks,
        "standards": [],
        "volume_role": "",
        "alignment_types": {},
        "extracted_evidence": {},
        "final_score": 0.0,
        "final_result": {},
        "langgraph_run_id": run_id,
    }

    try:
        final_state = await _graph.ainvoke(initial_state)
        result = final_state.get("final_result", {})
        result["langgraph_run_id"] = run_id
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[LangGraph] run_alignment_graph: FATAL error — {e}")
        return {
            "error": str(e),
            "compliance_score": 0,
            "compliant": False,
            "violations": [],
            "scorecard": {},
            "obligation_summary": [],
            "auto_fix_possible": False,
            "langgraph_run_id": run_id,
        }

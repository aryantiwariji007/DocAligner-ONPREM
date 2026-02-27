from typing import Dict, Any, List

class AlignmentEngine:
    """
    Pure Python deterministic Alignment Engine.
    Takes a structural template and normalized target sections, and calculates fidelity.
    No LLM hallucinations.
    """

    def build_structure_tree(self, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Node 3: Convert flat list -> tree (deterministic)."""
        tree = {}
        last_at_level = {}
        
        for sec in sections:
            lvl = sec.get("level", 1)
            sec_id = str(sec.get("id"))
            node = {
                "title": sec.get("title"),
                "children": {}
            }
            
            if lvl == 1:
                tree[sec_id] = node
            else:
                parent_lvl = lvl - 1
                if parent_lvl in last_at_level:
                    parent_node = last_at_level[parent_lvl]
                    parent_node["children"][sec_id] = node
            
            last_at_level[lvl] = node
            
        return tree

    def align_target(self, template: Dict[str, Any], normalized_target: Dict[str, Any]) -> Dict[str, Any]:
        """Node 4, 5, 6 logic."""
        template_sections = template.get("sections", [])
        target_sections = normalized_target.get("normalized_sections", [])

        # Build lookup tables
        template_map = {str(s.get("id")): s for s in template_sections if s.get("id")}
        mandatory_ids = {str(s.get("id")) for s in template_sections if s.get("mandatory")}
        
        matched_results = []
        extra_sections = []
        
        matched_ids_in_order = []
        
        # 1. Match structures
        for t_sec in target_sections:
            c_id = str(t_sec.get("canonical_id")) if t_sec.get("canonical_id") else None
            if c_id and c_id in template_map:
                matched_ids_in_order.append(c_id)
                matched_results.append({
                    "standard_id": c_id,
                    "standard_title": template_map[c_id].get("title"),
                    "target_title": t_sec.get("original_title"),
                    "status": "matched",
                    "level": t_sec.get("level"),
                    "order_index": t_sec.get("order_index")
                })
            else:
                extra_sections.append(t_sec.get("original_title", "Unknown Section"))

        matched_set = set(matched_ids_in_order)
        missing_sections = [
            template_map[m_id].get("title", m_id) 
            for m_id in mandatory_ids 
            if m_id not in matched_set
        ]

        # 2. Compute Alignment Score (Deterministic)
        
        # 3.1 Presence Score (40%)
        presence_score = 1.0
        if mandatory_ids:
            presence_score = (len(mandatory_ids) - len(missing_sections)) / len(mandatory_ids)

        # 3.2 Order Score (25%) - Normalized Distance
        order_score = 1.0
        if matched_ids_in_order:
            # Expected order of THESE matched ids
            expected_order = sorted(matched_ids_in_order, key=lambda x: template_map[x].get("order_index", 0))
            
            # Sum of absolute differences in relative positions
            distance_sum = 0
            for i, c_id in enumerate(matched_ids_in_order):
                expected_i = expected_order.index(c_id)
                distance_sum += abs(i - expected_i)
            
            # Max possible distance is roughly n^2 / 2
            n = len(matched_ids_in_order)
            max_possible_distance = (n * n) // 2 if n > 1 else 1
            order_score = 1.0 - (distance_sum / max_possible_distance)
            order_score = max(0.0, order_score)

        # 3.3 Hierarchy Score (25%)
        hierarchy_score = 1.0
        if matched_ids_in_order:
            correct_levels = 0
            # Need to match the target_sections accurately to their matched results
            target_matched = [s for s in target_sections if str(s.get("canonical_id")) in template_map]
            for t_sec in target_matched:
                c_id = str(t_sec["canonical_id"])
                if t_sec.get("level") == template_map[c_id].get("level"):
                    correct_levels += 1
            hierarchy_score = correct_levels / len(target_matched) if target_matched else 1.0

        # 3.4 Completeness Score (10%)
        completeness_score = 1.0
        if target_sections:
            completeness_score = 1.0 - (len(extra_sections) / len(target_sections))
            completeness_score = max(0.0, completeness_score)

        final_score = (
            0.40 * presence_score +
            0.25 * order_score +
            0.25 * hierarchy_score +
            0.10 * completeness_score
        )

        # Determine structural confidence label
        if final_score >= 0.9:
            confidence = "high"
        elif final_score >= 0.75:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "final_score": round(final_score, 2),
            "breakdown": {
                "presence": round(presence_score, 2),
                "order": round(order_score, 2),
                "hierarchy": round(hierarchy_score, 2),
                "completeness": round(completeness_score, 2)
            },
            "missing_sections": missing_sections,
            "misplaced_sections": [m["standard_title"] for m in matched_results if matched_ids_in_order.index(m["standard_id"]) != sorted(matched_ids_in_order, key=lambda x: template_map[x].get("order_index", 0)).index(m["standard_id"])],
            "extra_sections": extra_sections,
            "confidence": confidence,
            "alignment_map": matched_results
        }

alignment_engine = AlignmentEngine()

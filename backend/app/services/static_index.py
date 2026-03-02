from typing import Dict, List, Any, Set, Tuple
import json

# Standard structural tokens mapping
# We decouple structure from text. These tokens represent semantics, not content.
STRUCTURE_VOCAB = {
    "DOC": 0,
    "TITLE": 1,
    "ABSTRACT": 2,
    "SECTION": 3,
    "SUBSECTION": 4,
    "CLAUSE": 5,
    "TABLE": 6,
    "FIGURE": 7,
    "REFERENCES": 8,
    "END": 9
}

REVERSE_VOCAB = {v: k for k, v in STRUCTURE_VOCAB.items()}

class TrieNode:
    def __init__(self, token_id: int, depth: int):
        self.token_id = token_id
        self.depth = depth
        self.children: Dict[int, 'TrieNode'] = {}
        # Used during flattening
        self.node_id: int = -1

class StandardStructureIndex:
    """
    Offline indexing step for STATIC constraints.
    Builds a Trie of all VALID document structure paths from a reference dictionary,
    then flattens it into a CSR-style sparse matrix for O(1) vectorized lookups on GPU/CPU.
    """
    def __init__(self):
        self.root = TrieNode(STRUCTURE_VOCAB["DOC"], depth=0)
        
        # CSR Representation Arrays
        self.row_ptr: List[int] = []
        self.col_idx: List[int] = []
        self.node_depth: List[int] = []
        self.node_token: List[int] = []
        self.is_built = False

    def _normalize_token(self, section_name: str) -> int:
        """Heuristic to map arbitrary JSON keys to our strict VOCAB."""
        name = section_name.upper()
        if "TITLE" in name or "INTRO" in name: return STRUCTURE_VOCAB["TITLE"]
        if "ABSTRACT" in name or "SUMMARY" in name: return STRUCTURE_VOCAB["ABSTRACT"]
        if "SUBSECTION" in name: return STRUCTURE_VOCAB["SUBSECTION"]
        if "SECTION" in name or "RESPONSIBILITIES" in name: return STRUCTURE_VOCAB["SECTION"]
        if "CLAUSE" in name or "RULE" in name: return STRUCTURE_VOCAB["CLAUSE"]
        if "TABLE" in name: return STRUCTURE_VOCAB["TABLE"]
        if "FIGURE" in name or "IMAGE" in name: return STRUCTURE_VOCAB["FIGURE"]
        if "REFERENCES" in name or "BIBLIOGRAPHY" in name: return STRUCTURE_VOCAB["REFERENCES"]
        
        # Default fallback to section if unknown structure, to maintain a safe tree
        return STRUCTURE_VOCAB["SECTION"]

    def _extract_paths(self, rules_json: Dict[str, Any]) -> List[List[int]]:
        """
        Parses the nested document standard JSON to extract all valid sequential paths.
        Simplified MVP: Assuming rules_json defines 'structure' as a nested dict/list.
        """
        paths = []
        
        # Example logic for standard_v2 'structure_rules'
        structure_rules = rules_json.get("structure", {}).get("required_sections", [])
        
        if not structure_rules:
            # Fallback for completely empty standards: [DOC, SECTION, END]
            return [[STRUCTURE_VOCAB["DOC"], STRUCTURE_VOCAB["SECTION"], STRUCTURE_VOCAB["END"]]]

        # We will build exactly one main valid path based on required order for MVP.
        # In a full complex standard, we'd add branching for optional sections.
        current_path = [STRUCTURE_VOCAB["DOC"]]
        for section in structure_rules:
            if isinstance(section, dict):
                title = section.get("title", "SECTION")
            else:
                title = str(section)
            current_path.append(self._normalize_token(title))
        
        current_path.append(STRUCTURE_VOCAB["END"])
        return [current_path]

    def build_from_standard(self, rules_json: Dict[str, Any]):
        """Build the Trie and flatten to CSR."""
        valid_paths = self._extract_paths(rules_json)
        
        # 1. Build Trie
        for path in valid_paths:
            current = self.root
            for depth, token_id in enumerate(path[1:], start=1):
                if token_id not in current.children:
                    current.children[token_id] = TrieNode(token_id, depth)
                current = current.children[token_id]
                
        # 2. Flatten to CSR
        self._flatten_to_csr()
        self.is_built = True

    def _flatten_to_csr(self):
        """
        Walks the Trie (BFS/DFS) and builds the CSR arrays.
        row_ptr[i] to row_ptr[i+1] dictates the valid transitions (col_idx) for node i.
        """
        nodes = []
        
        # Assign Node IDs in BFS order
        queue = [self.root]
        node_counter = 0
        while queue:
            current = queue.pop(0)
            current.node_id = node_counter
            nodes.append(current)
            node_counter += 1
            for child in current.children.values():
                queue.append(child)
                
        # Initialize CSR Arrays
        self.row_ptr = [0] * (len(nodes) + 1)
        self.col_idx = []
        self.node_depth = [0] * len(nodes)
        self.node_token = [0] * len(nodes)
        
        current_col_idx = 0
        for i, node in enumerate(nodes):
            self.node_depth[i] = node.depth
            self.node_token[i] = node.token_id
            
            # Record children transitions
            for child_token, child_node in node.children.items():
                # We store the *node_id* of the child so we can traverse the graph, 
                # AND we need to know what token it takes to get there.
                # In standard CSR, col_idx usually stores the destination node. 
                # However, for Logit Masking, we need the *valid tokens*.
                # We will store a tuple or parallel array if we need both.
                # For pure masking: we just need the valid tokens!
                self.col_idx.append(child_token)
                
                # To actually TRANSITION state in decoder, we also need child.node_id.
                # Let's add an aux array for state transitions
                if not hasattr(self, 'transition_dest'):
                    self.transition_dest = []
                self.transition_dest.append(child_node.node_id)
                current_col_idx += 1
                
            self.row_ptr[i + 1] = current_col_idx

    def get_valid_next_tokens(self, current_node_id: int) -> List[int]:
        """O(1) lookup for valid tokens."""
        if not self.is_built or current_node_id >= len(self.row_ptr) - 1:
            return []
        start = self.row_ptr[current_node_id]
        end = self.row_ptr[current_node_id + 1]
        return self.col_idx[start:end]

    def get_next_node(self, current_node_id: int, token_id: int) -> int:
        """Find the next state node given a valid token choice."""
        if not self.is_built:
            return -1
        start = self.row_ptr[current_node_id]
        end = self.row_ptr[current_node_id + 1]
        
        for i in range(start, end):
            if self.col_idx[i] == token_id:
                return self.transition_dest[i]
        return -1

    def snap_to_valid_path(self, candidate_tokens: List[int]) -> List[int]:
        """
        Deterministic Snapping: Force-aligns a candidate sequence to the nearest valid CSR path.
        Returns a (snapped_sequence, valid_transition_count) tuple.
        """
        if not self.is_built:
            return candidate_tokens, 0
            
        current_node = 0
        snapped = [STRUCTURE_VOCAB["DOC"]]
        valid_transitions = 0
        
        # We handle DOC explicitly, then process the rest
        # Filter out start/end markers from input to process body
        input_body = [t for t in candidate_tokens if t not in [STRUCTURE_VOCAB["DOC"], STRUCTURE_VOCAB["END"]]]
        
        for token in input_body:
            allowed = self.get_valid_next_tokens(current_node)
            if not allowed:
                break # Nowhere left to go
                
            if token in allowed:
                snapped.append(token)
                valid_transitions += 1
                current_node = self.get_next_node(current_node, token)
            else:
                # Snap to first allowed transition to maintain a valid path
                snapped_token = allowed[0]
                snapped.append(snapped_token)
                current_node = self.get_next_node(current_node, snapped_token)
                
        # Terminate: Continue until we hit END
        MAX_RECOVERY_STEPS = 20
        steps = 0
        while snapped[-1] != STRUCTURE_VOCAB["END"] and steps < MAX_RECOVERY_STEPS:
            allowed = self.get_valid_next_tokens(current_node)
            if not allowed:
                # If we're stuck, force add END and break
                if snapped[-1] != STRUCTURE_VOCAB["END"]:
                    snapped.append(STRUCTURE_VOCAB["END"])
                break
                
            if STRUCTURE_VOCAB["END"] in allowed:
                snapped.append(STRUCTURE_VOCAB["END"])
                break
            else:
                # Move forward on any valid path
                snapped_token = allowed[0]
                snapped.append(snapped_token)
                current_node = self.get_next_node(current_node, snapped_token)
                steps += 1

        return snapped, valid_transitions

    def to_gbnf_grammar(self) -> str:
        """
        Generates a GBNF grammar from the CSR index trie.
        Forces the LLM to only output sequences that exist in the valid structure index.
        """
        if not self.is_built:
            return ""
        
        # We walk the trie and build grammar rules for each node.
        # Rule name: Node_{id} ::= "TOKEN" (Node_{child1} | Node_{child2} ...)
        rules = []
        for i in range(len(self.row_ptr) - 1):
            start = self.row_ptr[i]
            end = self.row_ptr[i + 1]
            
            # Semantic token for this node (e.g. 'SECTION')
            token_name = REVERSE_VOCAB[self.node_token[i]]
            
            # Transitions
            children = []
            for j in range(start, end):
                child_token = REVERSE_VOCAB[self.col_idx[j]]
                child_node_id = self.transition_dest[j]
                # Each child is a rule like Node_123
                children.append(f"node_{child_node_id}")
            
            if not children:
                # Leaf node: current rule is just its name (though usually it outputs its token then ends)
                rules.append(f'node_{i} ::= "{token_name}"')
            else:
                choice = " | ".join(children)
                rules.append(f'node_{i} ::= "{token_name}" " " ({choice})')

        # Entry point: start from the root (Node 0)
        rules.append('root ::= node_0')
        return "\n".join(rules[::-1]) # Reverse so root is often at top-ish or it doesn't matter much in GBNF

from typing import List, Optional, Tuple, Any
try:
    from llama_cpp import LogitsProcessor
    import numpy as np
except ImportError:
    # Not installed in all environments
    LogitsProcessor = object
    np = None

from backend.app.services.static_index import StandardStructureIndex, STRUCTURE_VOCAB, REVERSE_VOCAB

class StaticLogitsProcessor(LogitsProcessor):
    """
    Applies mathematical certainty to Qwen2.5 structure generation using the STATIC CSR index.
    Masks out any tokens that violate the document standard template.
    """
    def __init__(self, tokenizer: Any, static_index: StandardStructureIndex):
        self.tokenizer = tokenizer
        self.static_index = static_index
        
        # We need to map our semantic vocab (STRUCTURE_VOCAB) to the model's actual token IDs.
        # This requires tokenizing the string literals of our structure markers.
        self.vocab_to_tokens = {}
        self.tokens_to_vocab = {}
        self._init_token_mapping()
        
        # State tracking: where are we in the document structure Trie?
        self.current_node_id = 0 # Starts at root (DOC)

    def _init_token_mapping(self):
        """Map Qwen tokens to our semantic STRUCTURE_VOCAB IDs."""
        for name, vocab_id in STRUCTURE_VOCAB.items():
            # Example: tokenize "SECTION"
            # Depending on Qwen's tokenizer, it might add a space prefix ' SECTION' or just 'SECTION'.
            # We must map all subwords that constitute this token, or assume a strict template.
            # Simplified MVP mapping:
            # We assume the model outputs structured tokens like [SECTION] or just SECTION
            token_ids = self.tokenizer.encode(name, add_bos=False)
            
            # If the token maps to multiple BPE tokens, we'd need a multi-step Trie.
            # For this MVP, we map the first/primary token that strongly indicates the structure.
            if token_ids:
                primary_token = token_ids[0]
                self.vocab_to_tokens[vocab_id] = primary_token
                self.tokens_to_vocab[primary_token] = vocab_id

    def __call__(self, input_ids: List[int], scores: 'np.ndarray') -> 'np.ndarray':
        """
        Called by llama_cpp at EVERY generation step.
        Modify `scores` in-place or return a new array.
        """
        if np is None or not self.static_index.is_built:
            return scores
            
        # 1. Update our state based on the LAST generated token (from input_ids)
        if input_ids:
            last_token = input_ids[-1]
            if last_token in self.tokens_to_vocab:
                semantic_id = self.tokens_to_vocab[last_token]
                next_node = self.static_index.get_next_node(self.current_node_id, semantic_id)
                if next_node != -1:
                    self.current_node_id = next_node
                    
        # 2. Lookup valid tokens for CURRENT state
        valid_vocab_ids = self.static_index.get_valid_next_tokens(self.current_node_id)
        
        # 3. Apply the constraint mask
        if valid_vocab_ids:
            # Get the exact LLM token IDs that are permitted
            allowed_llm_tokens = [
                self.vocab_to_tokens[vid] for vid in valid_vocab_ids if vid in self.vocab_to_tokens
            ]
            
            # Mask everything to -inf
            mask = np.full_like(scores, -np.inf)
            
            # Unmask only explicitly allowed tokens
            # We also typically allow whitespace/newline tokens if needed, but for strict 
            # structure output, we force ONLY the structure tokens.
            for t_id in allowed_llm_tokens:
                mask[t_id] = scores[t_id]
                
            return mask
            
        return scores
        
    def reset(self):
        self.current_node_id = 0

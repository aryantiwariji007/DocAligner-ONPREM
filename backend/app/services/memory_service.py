import os
import json
import httpx
import uuid
import hashlib
from typing import List, Dict, Any
from backend.app.core.config import settings
from qdrant_client import QdrantClient
from qdrant_client.http import models

class MemoryService:
    def __init__(self):
        # Initialize Qdrant client
        # Use QDRANT_URL if available, else fallback to a local host or memory instance
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        try:
            self.client = QdrantClient(url=qdrant_url)
        except Exception as e:
            print(f"Warning: Failed to connect to Qdrant at {qdrant_url}: {e}")
            # Fallback to pure memory if docker container isn't reachable during dev setup
            self.client = QdrantClient(":memory:")
            
        self.collection_name = "standard_rules"
        self.embedding_model = "nomic-embed-text"
        self.embedding_dim = 768  # nomic-embed-text dimension
        
        # Determine Ollama URL
        self.ollama_base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        
        # Ensure collection exists
        self._ensure_collection()
        
    def _ensure_collection(self):
        """Creates the Qdrant collection if it doesn't already exist."""
        try:
            if not self.client.collection_exists(collection_name=self.collection_name):
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.embedding_dim,
                        distance=models.Distance.COSINE
                    )
                )
                print(f"[Qdrant] Created collection: {self.collection_name}")
        except Exception as e:
            print(f"[Qdrant] Error creating collection: {e}")

    def _get_embedding(self, text: str) -> List[float]:
        """
        Calls Ollama's embedding API synchronously to get vectors for nomic-embed-text.
        """
        if not text or not text.strip():
            # Return zero vector if empty
            return [0.0] * self.embedding_dim
            
        try:
            response = httpx.post(
                f"{self.ollama_base_url}/api/embeddings",
                json={
                    "model": self.embedding_model,
                    "prompt": text
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding", [])
            if not embedding:
                print(f"[Qdrant] Warning: Ollama returned empty embedding for text!")
                return [0.0] * self.embedding_dim
            return embedding
        except Exception as e:
            print(f"[Qdrant] Failed to get embedding from Ollama: {e}")
            return [0.0] * self.embedding_dim

    def add_standard_rules(self, standard_id: str, rules_json: dict) -> dict:
        """
        Extracts complex rules JSON into granular text chunks, 
        embeds them, and stores them in Qdrant with `standard_id` metadata.
        """
        try:
            # Flatten rules into meaningful chunks
            chunks = self._flatten_rules(rules_json, standard_id)
            if not chunks:
                return {"status": "error", "message": "No valid rule chunks generated"}
            
            points = []
            for i, chunk in enumerate(chunks):
                # We prefix the chunk with context so the embedding captures it's a rule
                embed_text = f"Standard Section: {chunk['standard_section']} - Obligation: {chunk['obligation']} - Rule: {chunk['text']}"
                vector = self._get_embedding(embed_text)
                
                # Create a deterministic ID based on standard and chunk index
                point_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{standard_id}_{i}_{hash(chunk['text'])}"))
                
                points.append(models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "standard_id": str(standard_id),
                        "clause_id": chunk['clause_id'],
                        "standard_section": chunk['standard_section'],
                        "obligation": chunk['obligation'],
                        "memory": chunk['text']  # Keep "memory" key to match previous interface
                    }
                ))
            
            # Upsert into Qdrant
            if points:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points
                )
                print(f"[Qdrant] Inserted {len(points)} rules for standard {standard_id}")
                
            return {"status": "success", "inserted": len(points)}
            
        except Exception as e:
            print(f"[Qdrant] Error adding standard rules: {e}")
            return {"status": "error", "message": str(e)}

    def search_rules(self, query: str, topic_id: str, limit: int = 5) -> dict:
        """
        Embeds the incoming section query and searches Qdrant for relevant rules,
        filtering strictly by `topic_id` (standard_id).
        """
        try:
            vector = self._get_embedding(query)
            
            # Search Qdrant, filtering by the exact standard_id
            search_result = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="standard_id",
                            match=models.MatchValue(value=str(topic_id))
                        )
                    ]
                ),
                limit=limit
            ).points
            
            # Format results exactly like contextmemory did so ai_service doesn't break
            # but now include clause_id and standard_section
            results = []
            for hit in search_result:
                results.append({
                    "clause_id": hit.payload.get("clause_id", ""),
                    "standard_section": hit.payload.get("standard_section", "General"),
                    "obligation": hit.payload.get("obligation", "mandatory"),
                    "memory": hit.payload.get("memory", ""),
                    "score": hit.score
                })
                
            return {"status": "success", "results": results}
            
        except Exception as e:
            print(f"[Qdrant] Error searching standard rules: {e}")
            return {"status": "error", "results": []}

    def add_validation_bubble(self, doc_id: str, text_hash: str, ai_report: str):
        """
        Stub to preserve compatibility with validation_service.
        Future: Store evaluation history in Qdrant for temporal RAG.
        """
        pass

    def _flatten_rules(self, rules_json: dict, standard_id: str) -> List[Dict[str, str]]:
        """
        Takes a highly structured rules JSON and flattens it into an array of readable
        clause dictionaries suitable for embedding and semantic retrieval with metadata attached.
        """
        chunks = []
        
        # Safely extract dict elements
        doc_type = rules_json.get("document_type", "Document")
        
        authority_model = rules_json.get("authority_model", {})
        if isinstance(authority_model, dict):
            if authority_model.get("model_type"):
                chunks.append({
                    "clause_id": f"{standard_id}-auth-1",
                    "standard_section": "Authority Model",
                    "obligation": "mandatory",
                    "text": f"The document follows a {authority_model.get('model_type')} authority model."
                })
            
            chain = authority_model.get("authority_chain", [])
            if isinstance(chain, list) and chain:
                chunks.append({
                    "clause_id": f"{standard_id}-auth-chain",
                    "standard_section": "Authority Model",
                    "obligation": "mandatory",
                    "text": f"Authority chain roles: {', '.join(chain)}"
                })
        
        hierarchy = rules_json.get("hierarchy_map", {})
        if isinstance(hierarchy, dict):
            levels = hierarchy.get("levels", [])
            pattern = hierarchy.get("mandatory_pattern", "")
            if levels:
                chunks.append({
                    "clause_id": f"{standard_id}-hierarchy-levels",
                    "standard_section": "Hierarchy Map",
                    "obligation": "mandatory",
                    "text": f"The document hierarchy is structured as: {' -> '.join(levels)}."
                })
            if pattern:
                chunks.append({
                    "clause_id": f"{standard_id}-hierarchy-pattern",
                    "standard_section": "Hierarchy Map",
                    "obligation": "mandatory",
                    "text": f"The structural pattern is: {pattern}."
                })
                
        obligation = rules_json.get("obligation_semantics", {})
        if isinstance(obligation, dict):
            for level, words in obligation.items():
                if isinstance(words, list) and words:
                    chunks.append({
                        "clause_id": f"{standard_id}-semantics-{level}",
                        "standard_section": "Obligation Semantics",
                        "obligation": "mandatory",
                        "text": f"Words indicating '{level}' level of obligation: {', '.join(words)}"
                    })
        
        rules = rules_json.get("rules", [])
        if isinstance(rules, list):
            for idx, rule in enumerate(rules):
                if isinstance(rule, dict):
                    category = rule.get("category", "General")
                    description = rule.get("description", "")
                    enforcement = rule.get("enforcement_level", "mandatory")
                    if description:
                        chunks.append({
                            "clause_id": f"{standard_id}-rule-{idx+1}-{category.lower()[:5]}",
                            "standard_section": category,
                            "obligation": enforcement,
                            "text": f"[{category.upper()}] ({enforcement}) {description}"
                        })
                        
        # Fallback: if rules are just string values or generic objects
        if not chunks:
            # Attempt to stringify
            import json
            chunks.append({
                "clause_id": f"{standard_id}-fallback",
                "standard_section": "General",
                "obligation": "mandatory",
                "text": json.dumps(rules_json)
            })
            
        return chunks

memory_service = MemoryService()

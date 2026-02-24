import os
from contextmemory import configure, create_table, Memory, SessionLocal
from backend.app.core.config import settings

# Wait to configure until explicitly called or instantiated, but we can configure it right away
# We will use the 'openai' provider as a passthrough to Ollama by overriding the API base via env vars,
# or if contextmemory supports base_url we will pass it. 
# Currently contextmemory uses openai package underneath.

class MemoryService:
    def __init__(self):
        # Configure contextmemory.
        # We must set OPENAI_BASE_URL for the underlying OpenAI client to hit Ollama.
        os.environ["OPENAI_BASE_URL"] = f"{settings.OLLAMA_BASE_URL}/v1"
        os.environ["OPENAI_API_KEY"] = "ollama" # Dummy key
        
        # Determine database URL: Use the app's database URL or fallback to sqlite
        db_url = str(settings.DATABASE_URL) if settings.DATABASE_URL else "sqlite:///./contextmemory.db"
        # Contextmemory might expect a specific format, we will just pass it through
        # contextmemory requires async-free engines or specific engines, we'll see if it works with async PG
        # Actually contextmemory uses synchronous psycopg2 / sqlite under the hood usually.
        # It's safer to use sqlite for the memory graph if the main DB is asyncpg and contextmemory expects sync.
        # For this prototype, let's use a local sqlite db for the memory graph to avoid async/sync conflicts.
        memory_db_url = "sqlite:///./memory.db"

        # Monkeypatch FAISSVectorStore to default to 768 dimensions for nomic-embed-text
        from contextmemory.memory.vector_store import FAISSVectorStore
        original_init = FAISSVectorStore.__init__
        def new_init(self, dimension=768):
            original_init(self, dimension)
        FAISSVectorStore.__init__ = new_init

        # Configure the library
        configure(
            openai_api_key="ollama", # Dummy key for Ollama
            llm_provider="openai",
            llm_model=settings.OLLAMA_MODEL, # e.g. qwen2.5:14b-instruct
            embedding_model="nomic-embed-text", # Standard ollama embedding model
            database_url=memory_db_url
        )

        # Create tables (Idempotent)
        create_table()
        
        # Initialize memory instance
        self.db = SessionLocal()
        self.memory = Memory(self.db)
        
    def add_standard_rules(self, standard_id: str, rules_json: dict) -> dict:
        """
        Extract and store rules into semantic memory.
        """
        # Convert rules to a format suitable for conversation history
        import json
        rules_text = json.dumps(rules_json, indent=2)
        
        messages = [
            {"role": "user", "content": f"Please memorize the following official rules for standard {standard_id}: {rules_text}"},
            {"role": "assistant", "content": f"I have memorized the rules for standard {standard_id}. Semantic Fact: The rules for {standard_id} are {rules_text}"}
        ]
        
        # Use standard_id as the conversation_id or a hashed integer
        conv_id = abs(hash(standard_id)) % (10 ** 8)
        
        result = self.memory.add(messages=messages, conversation_id=conv_id)
        return result

    def search_rules(self, query: str, topic_id: str, limit: int = 5) -> dict:
        """
        Search for relevant rules across a specific topic (standard_id or document_id).
        """
        conv_id = abs(hash(topic_id)) % (10 ** 8)
        try:
             # Force rebuild index if first time or count is 0
             results = self.memory.search(query=query, conversation_id=conv_id, limit=limit)
        except Exception as e:
             print(f"Memory search error: {e}")
             results = {"query": query, "results": []}
             
        return results
        
    def add_validation_bubble(self, document_id: str, hash_chunk: str, status: str):
        """
        Add an episodic bubble for a specific document chunk.
        """
        messages = [
            {"role": "user", "content": f"Context: Validating document {document_id}, chunk hash {hash_chunk}."},
            {"role": "assistant", "content": f"Result: Validated chunk {hash_chunk}. Explicit Status: {status}"}
        ]
        conv_id = abs(hash(document_id)) % (10 ** 8)
        return self.memory.add(messages=messages, conversation_id=conv_id)

memory_service = MemoryService()

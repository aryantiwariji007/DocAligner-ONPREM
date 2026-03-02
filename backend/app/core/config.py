from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional
import os

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "DocAligner"
    
    # DATABASE
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docstandards")
    
    # KEYCLOAK
    KEYCLOAK_URL: str = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
    KEYCLOAK_REALM: str = os.getenv("KEYCLOAK_REALM", "docstandards")
    KEYCLOAK_CLIENT_ID: str = os.getenv("KEYCLOAK_CLIENT_ID", "backend")
    # For dev mostly, in prod we verify signature via JWKS
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "secret") 
    JWT_ALGORITHM: str = "HS256" # Default to HS256 for dev simplicity if RS256 not setup
    
    # MINIO
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "minio")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "minio123")
    MINIO_BUCKET_DOCUMENTS: str = "documents"
    MINIO_SECURE: bool = False
    
    # REDIS
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # AI (Ollama - on-premise)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:14b-instruct")
    
    # AI (Local llama.cpp)
    LLAMA_CPP_MODEL_PATH: str = os.getenv("LLAMA_CPP_MODEL_PATH", "/app/models/qwen2.5-7b-instruct.gguf")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True
    )

settings = Settings()
print(f"DEBUG: Loaded DATABASE_URL: {settings.DATABASE_URL}")

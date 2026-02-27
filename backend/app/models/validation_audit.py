from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, Dict
from datetime import datetime
import uuid
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from enum import Enum
from .base import IDMixin, TimestampMixin

class ValidationStatus(str, Enum):
    INGESTED = "INGESTED"
    CLASSIFIED = "CLASSIFIED"
    INCOMPATIBLE_STANDARD = "INCOMPATIBLE_STANDARD"
    STRUCTURE_MISMATCH = "STRUCTURE_MISMATCH"
    EVALUATED = "EVALUATED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    PENDING = "PENDING"
    WARN = "WARN" # Leaving WARN for legacy compat if needed
    PASS = "PASS" # Restored for legacy compat
    FAIL = "FAIL" # Restored for legacy compat

class ValidationResult(IDMixin, TimestampMixin, table=True):
    __tablename__ = "validationresult"
    document_id: uuid.UUID = Field(foreign_key="document.id", ondelete="CASCADE")
    standard_version_id: uuid.UUID = Field(foreign_key="standardversion.id")
    status: ValidationStatus = Field(index=True)
    report_json: Dict = Field(default={}, sa_column=Column(JSONB))
    
    document: "Document" = Relationship(back_populates="validation_results")
    standard_version: "StandardVersion" = Relationship()

class AuditLog(IDMixin, table=True):
    __tablename__ = "auditlog"
    actor_id: str = Field(index=True)
    action: str = Field(index=True)
    target_id: uuid.UUID = Field(index=True)
    details: Dict = Field(default={}, sa_column=Column(JSONB))
    timestamp: datetime = Field(default_factory=datetime.utcnow)

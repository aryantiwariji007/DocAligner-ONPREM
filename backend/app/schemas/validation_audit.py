from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime
import uuid
from enum import Enum

class ValidationStatus(str, Enum):
    INGESTED = "INGESTED"
    CLASSIFIED = "CLASSIFIED"
    INCOMPATIBLE_STANDARD = "INCOMPATIBLE_STANDARD"
    STRUCTURE_MISMATCH = "STRUCTURE_MISMATCH"
    EVALUATED = "EVALUATED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    PENDING = "PENDING"
    WARN = "WARN"
    PASS = "PASS"
    FAIL = "FAIL"

class ValidationResultBase(BaseModel):
    document_id: uuid.UUID
    standard_version_id: uuid.UUID
    status: ValidationStatus
    report_json: Dict

class ValidationResult(ValidationResultBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
import uuid
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from enum import Enum
from .base import IDMixin, TimestampMixin

class TargetType(str, Enum):
    FOLDER = "FOLDER"
    DOCUMENT = "DOCUMENT"

class Standard(IDMixin, TimestampMixin, table=True):
    __tablename__ = "standard"
    name: str = Field(index=True)
    description: Optional[str] = None
    versions: List["StandardVersion"] = Relationship(
        back_populates="standard",
        sa_relationship_kwargs={"lazy": "selectin", "cascade": "all, delete-orphan"}
    )

class StandardVersion(IDMixin, TimestampMixin, table=True):
    __tablename__ = "standardversion"
    standard_id: uuid.UUID = Field(foreign_key="standard.id")
    version_number: int
    rules_json: Dict = Field(default={}, sa_column=Column(JSONB))
    is_active: bool = Field(default=True)
    
    standard: Standard = Relationship(
        back_populates="versions",
        sa_relationship_kwargs={"lazy": "selectin"}
    )
    assignments: List["StandardAssignment"] = Relationship(
        back_populates="standard_version",
        sa_relationship_kwargs={"lazy": "selectin", "cascade": "all, delete-orphan"}
    )

class StandardAssignment(IDMixin, TimestampMixin, table=True):
    __tablename__ = "standardassignment"
    target_id: uuid.UUID = Field(index=True) # Polymorphic ID for Folder or Document
    target_type: TargetType = Field(index=True)
    standard_version_id: uuid.UUID = Field(foreign_key="standardversion.id")
    
    standard_version: StandardVersion = Relationship(back_populates="assignments")

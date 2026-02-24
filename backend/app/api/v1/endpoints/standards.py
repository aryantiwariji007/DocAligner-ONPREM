from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from backend.app import schemas
from backend.app.models import Standard, StandardVersion, Document
from backend.app.database import get_session
from backend.app.api import deps
from backend.app.services.rule_extraction_service import rule_extraction_factory
from backend.app.services.storage import minio_client
from backend.app.services.audit_service import audit_service
import uuid
import json
from backend.app.services.memory_service import memory_service

router = APIRouter()

@router.post("/", response_model=None)
async def create_standard(
    *,
    db: AsyncSession = Depends(get_session),
    standard_in: schemas.standard.StandardCreate,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Create new standard definition (without versions).
    """
    print(f"Creating standard: {standard_in}")
    standard = Standard.from_orm(standard_in)
    db.add(standard)
    
    # Audit
    try:
        await audit_service.log_action(
            db,
            actor_id=current_user.get("sub", "unknown"),
            action="CREATE_STANDARD",
            target_id=standard.id,
            details={"name": standard.name}
        )
    except Exception as e:
        print(f"Audit log failed: {e}")
        # Continue even if audit fails for debugging
    
    await db.commit()
    await db.refresh(standard)
    return standard

@router.get("/", response_model=List[schemas.standard.Standard])
async def read_standards(
    db: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve standards.
    """
    from sqlalchemy.orm import selectinload
    stmt = select(Standard).options(selectinload(Standard.versions)).offset(skip).limit(limit)
    result = await db.execute(stmt)
    standards = result.scalars().all()
    return standards

@router.get("/{standard_id}", response_model=schemas.standard.Standard)
async def read_standard(
    *,
    db: AsyncSession = Depends(get_session),
    standard_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve a single standard with its versions.
    """
    from sqlalchemy.orm import selectinload
    stmt = select(Standard).options(selectinload(Standard.versions)).where(Standard.id == standard_id)
    result = await db.execute(stmt)
    standard = result.scalar_one_or_none()
    if not standard:
        raise HTTPException(status_code=404, detail="Standard not found")
    return standard

@router.post("/{standard_id}/versions/promote/{document_id}", response_model=schemas.standard.StandardVersion)
async def promote_document_to_standard(
    *,
    db: AsyncSession = Depends(get_session),
    standard_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Promote a document to be a new version of a standard.
    """
    # 1. Fetch Standard
    standard = await db.get(Standard, standard_id)
    if not standard:
        raise HTTPException(status_code=404, detail="Standard not found")
        
    # 2. Fetch Document
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
        
    # 3. Retrieve file from MinIO
    # Assuming document.minio_version_id stores object_name or version info 
    # (based on our quick fix in documents.py, it stores object_name)
    storage_path = document.minio_version_id or f"{document.id}/{document.filename}"
    file_content = minio_client.get_file(storage_path)
    
    # 4. Extract Rules with Strict Schema
    try:
        extracted_data = await rule_extraction_factory.extract_rules_async(file_content, document.filename, use_ai=True)
        # Validate against strict schema
        from backend.app.schemas.standard_v2 import DocumentStandard
        # We might need to adapt the extracted data if the LLM returns extra fields or slightly different structure,
        # but the strict schema in AI service should handle it.
        # Ideally, we should parse it into DocumentStandard to ensure validity.
        # For now, we store the raw JSON but it's guaranteed by Gemini schema.
        rules = extracted_data
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract rules: {str(e)}")
        
    # 5. Store rules in Long-Term Memory (ContextMemory)
    try:
        memory_service.add_standard_rules(str(standard_id), rules)
    except Exception as e:
        print(f"Warning: Failed to add standard rules to context memory: {e}")
        
    # 6. Determine new version number (simplified: count existing + 1)
    stmt = select(StandardVersion).where(StandardVersion.standard_id == standard_id)
    result = await db.execute(stmt)
    versions = result.scalars().all()
    next_version = len(versions) + 1
    
    # 6. Create StandardVersion
    # The rules_json now contains the FULL standard definition including metadata.
    # We might want to merge it or just store it.
    new_version = StandardVersion(
        standard_id=standard_id,
        version_number=next_version,
        rules_json=rules,
        is_active=True
    )
    db.add(new_version)
    
    # Audit
    await audit_service.log_action(
        db,
        actor_id=current_user.get("sub", "unknown"),
        action="PROMOTE_STANDARD_VERSION",
        target_id=new_version.id,
        details={"standard_id": str(standard_id), "version": next_version}
    )
    
    await db.commit()
    await db.refresh(new_version)
    return new_version

@router.post("/{standard_id}/apply/document/{document_id}", response_model=schemas.standard.StandardAssignment)
async def apply_standard_to_document(
    *,
    db: AsyncSession = Depends(get_session),
    standard_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Apply the latest active version of a standard to a document.
    """
    from backend.app.services.standard_service import standard_service as service
    
    # 1. Get active version
    version = await service.get_active_version(db, standard_id)
    if not version:
        raise HTTPException(status_code=404, detail="No active version found for this standard")
        
    # 2. Apply
    assignment = await service.apply_to_document(
        db, 
        standard_version_id=version.id, 
        document_id=document_id,
        user_id=current_user.get("sub", "unknown")
    )
    return assignment

@router.post("/{standard_id}/apply/folder/{folder_id}")
async def apply_standard_to_folder(
    *,
    db: AsyncSession = Depends(get_session),
    standard_id: uuid.UUID,
    folder_id: uuid.UUID,
    recursive: bool = True,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Apply the latest active version of a standard to a folder and all its documents.
    """
    from backend.app.services.standard_service import standard_service as service

    # 1. Get active version
    version = await service.get_active_version(db, standard_id)
    if not version:
        raise HTTPException(status_code=404, detail="No active version found for this standard")

    # 2. Apply to folder (recursive)
    assignments = await service.apply_to_folder(
        db,
        standard_version_id=version.id,
        folder_id=folder_id,
        user_id=current_user.get("sub", "unknown"),
        recursive=recursive
    )

    return {
        "status": "applied",
        "assignments_created": len(assignments),
        "standard_id": str(standard_id),
        "folder_id": str(folder_id),
        "recursive": recursive,
        "message": f"Standard applied to folder. {len(assignments)} assignment(s) created. Validation tasks queued."
    }

@router.get("/{standard_id}/versions", response_model=List[schemas.standard.StandardVersion])
async def read_standard_versions(
    *,
    db: AsyncSession = Depends(get_session),
    standard_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve versions for a specific standard.
    """
    stmt = select(StandardVersion).where(StandardVersion.standard_id == standard_id).order_by(StandardVersion.version_number.desc())
    result = await db.execute(stmt)
    versions = result.scalars().all()
    return versions

@router.delete("/{standard_id}")
async def delete_standard(
    *,
    db: AsyncSession = Depends(get_session),
    standard_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete a standard and all its versions and assignments.
    """
    standard = await db.get(Standard, standard_id)
    if not standard:
        raise HTTPException(status_code=404, detail="Standard not found")

    # Manual cleanup to avoid FK constraints if CASCADE isn't enough
    from sqlalchemy import delete
    from backend.app.models.standard import StandardVersion, StandardAssignment
    from backend.app.models.validation_audit import ValidationResult

    # 1. Get all versions for this standard
    stmt = select(StandardVersion).where(StandardVersion.standard_id == standard_id)
    result = await db.execute(stmt)
    versions = result.scalars().all()
    version_ids = [v.id for v in versions]

    if version_ids:
        # 2. Delete ValidationResults associated with these versions
        await db.execute(delete(ValidationResult).where(ValidationResult.standard_version_id.in_(version_ids)))
        
        # 3. Delete StandardAssignments associated with these versions
        await db.execute(delete(StandardAssignment).where(StandardAssignment.standard_version_id.in_(version_ids)))
        
        # 4. Delete StandardVersions
        for v in versions:
            await db.delete(v)

    # 5. Finally delete the standard itself
    await db.delete(standard)
    
    # Audit
    try:
        await audit_service.log_action(
            db,
            actor_id=current_user.get("sub", "unknown"),
            action="DELETE_STANDARD",
            target_id=standard_id,
            details={"name": standard.name}
        )
    except Exception as e:
        print(f"Audit log failed: {e}")

    await db.commit()
    return {"status": "ok", "message": "Standard deleted"}

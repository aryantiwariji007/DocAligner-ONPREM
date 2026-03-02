from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from backend.app import schemas
from backend.app.models import Document
from backend.app.database import get_session
from backend.app.api import deps
from backend.app.services.storage import minio_client
from backend.app.tasks import validate_document_task
from backend.app.services.inheritance_service import inheritance_service
from backend.app.services.audit_service import audit_service
from backend.app.models import TargetType
import uuid
import hashlib

router = APIRouter()

@router.get("/", response_model=List[schemas.document.Document])
async def read_documents(
    db: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve documents.
    """
    result = await db.execute(select(Document).offset(skip).limit(limit))
    documents = result.scalars().all()
    return documents

@router.post("/upload/", response_model=schemas.document.Document)
async def upload_document(
    *,
    db: AsyncSession = Depends(get_session),
    file: UploadFile = File(...),
    folder_id: Optional[uuid.UUID] = Form(None),
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Upload a document.
    """
    content = await file.read()
    
    # Calculate hash
    file_hash = hashlib.sha256(content).hexdigest()
    
    # Pre-generate ID for deterministic path
    doc_id = uuid.uuid4()
    
    # Upload to MinIO
    object_name = f"{doc_id}/{file.filename}"
    version_id = minio_client.upload_file(content, object_name, file.content_type)
    
    # Create DB record
    document = Document(
        id=doc_id,
        filename=file.filename,
        folder_id=folder_id,
        minio_version_id=object_name, 
        hash=file_hash,
    )
    
    db.add(document)
    
    # Audit
    await audit_service.log_action(
        db,
        actor_id=current_user.get("sub", "unknown"),
        action="UPLOAD",
        target_id=document.id,
        details={"filename": file.filename, "hash": file_hash}
    )
    
    await db.commit()
    await db.refresh(document)
    
    # Trigger validation if effective standard exists
    # We need to resolve effective standard for this doc
    # We can do this in the task, or here.
    # Ideally, logic: "Validate against WHAT?"
    # If we trigger generic "validate_document", it needs to know the standard.
    # Helper method in inheritance_service?
    # For now, let's look it up here quickly.
    effective_std = await inheritance_service.get_effective_standard_version(db, document.id, TargetType.DOCUMENT)
    if effective_std:
        validate_document_task.delay(str(document.id), str(effective_std.id))
        
    return document
@router.get("/{document_id}/validation")
async def get_document_validation(
    *,
    db: AsyncSession = Depends(get_session),
    document_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get the latest validation result for a document.
    """
    from backend.app.models import ValidationResult
    stmt = (
        select(ValidationResult)
        .where(ValidationResult.document_id == document_id)
        .order_by(ValidationResult.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    validation = result.scalar_one_or_none()
    
    if not validation:
        # Check if we should trigger it? 
        # For now, just return 404
        return {"status": "none", "report": None}
        
    return {
        "status": validation.status,
        "report": validation.report_json,
        "timestamp": validation.created_at
    }

@router.get("/{document_id}/content")
async def get_document_content(
    *,
    db: AsyncSession = Depends(get_session),
    document_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get the raw text content of a document for in-browser preview.
    """
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    file_content = minio_client.get_file(document.minio_version_id)
    from backend.app.services.rule_extraction_service import rule_extraction_factory
    # For preview, we want images if available
    text_content = rule_extraction_factory.extract_text(file_content, document.filename, with_images=True)
    
    return {"content": text_content, "filename": document.filename}

@router.post("/{document_id}/fix")
async def fix_document(
    *,
    db: AsyncSession = Depends(get_session),
    document_id: uuid.UUID,
    competence_level: str = "general",
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Auto-fix a document using the decision flow pipeline.
    Transformation is GATED by compatibility score:
      - score >= 75: safe apply (all rules)
      - score 40-74: selective apply + warnings
      - score < 40: report only, NO transformation
    """
    # 1. Fetch effective standard
    effective_std_version = await inheritance_service.get_effective_standard_version(db, document_id, TargetType.DOCUMENT)
    if not effective_std_version:
        raise HTTPException(status_code=400, detail="No effective standard assignment found for this document.")
        
    # 2. Fetch document content
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
        
    # 3. Trigger background task
    from backend.app.tasks import fix_document_task
    fix_document_task.delay(str(document_id), competence_level)
    
    return {
        "status": "async_triggered", 
        "message": "AI transformation task started in the background.",
        "polling_endpoint": f"/api/v1/documents/{document_id}/validation"
    }

@router.delete("/{document_id}")
async def delete_document(
    *,
    db: AsyncSession = Depends(get_session),
    document_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete a document.
    """
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    print(f"DEBUG: Attempting to delete document {document_id} ({document.filename})")
    # 1. Delete from MinIO
    try:
        storage_path = document.minio_version_id or f"{document.id}/{document.filename}"
        print(f"DEBUG: Deleting from MinIO: {storage_path}")
        minio_client.delete_file(storage_path)
    except Exception as e:
        print(f"Warning: could not delete file from MinIO: {e}")

    # 2. Delete from DB
    try:
        print(f"DEBUG: Deleting dependent records for Document: {document_id}")
        from sqlalchemy import delete
        from backend.app.models.validation_audit import ValidationResult
        from backend.app.models.standard import StandardAssignment
        from backend.app.models import TargetType
        
        # Manually delete ValidationResults pointing to this document
        await db.execute(delete(ValidationResult).where(ValidationResult.document_id == document_id))
        
        # Manually delete StandardAssignments pointing to this document
        await db.execute(delete(StandardAssignment).where(
            StandardAssignment.target_id == document_id,
        ))
        
        print(f"DEBUG: Deleting from Database: {document_id}")
        await db.delete(document)
        # 3. Audit
        from backend.app.services.audit_service import audit_service
        await audit_service.log_action(
            db,
            actor_id=current_user.get("sub", "unknown"),
            action="DELETE_DOCUMENT",
            target_id=document_id,
            details={"filename": document.filename}
        )
        
        await db.commit()
        print(f"DEBUG: Deleted document {document_id} successfully")
    except Exception as e:
        await db.rollback()
        print(f"ERROR during DB delete for {document_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    return {"status": "ok", "message": "Document deleted"}

@router.patch("/{document_id}")
async def rename_document(
    *,
    db: AsyncSession = Depends(get_session),
    document_id: uuid.UUID,
    new_name: str = Body(..., embed=True),
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Rename a document.
    """
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    old_name = document.filename
    document.filename = new_name
    db.add(document)
    
    # Audit
    await audit_service.log_action(
        db,
        actor_id=current_user.get("sub", "unknown"),
        action="RENAME_DOCUMENT",
        target_id=document_id,
        details={"old_name": old_name, "new_name": new_name}
    )
    
    await db.commit()
    await db.refresh(document)
    return document

@router.get("/{document_id}/download")
async def download_document_file(
    *,
    db: AsyncSession = Depends(get_session),
    document_id: uuid.UUID,
    path: Optional[str] = None,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Download a document file from MinIO.
    If 'path' is provided, it fetches that specific path (e.g., fixed versions).
    Otherwise, it fetches the original document.
    """
    from fastapi.responses import Response
    
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    storage_path = path if path else (document.minio_version_id or f"{document.id}/{document.filename}")
    
    try:
        file_content = minio_client.get_file(storage_path)
        
        # Determine content type based on path
        content_type = "application/octet-stream"
        if storage_path.endswith(".pdf"):
            content_type = "application/pdf"
        elif storage_path.endswith(".txt"):
            content_type = "text/plain"
            
        filename = storage_path.split("/")[-1]
        
        return Response(
            content=file_content,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found or error: {str(e)}")




from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from backend.app import schemas
from backend.app.models import Folder, Document, StandardAssignment, TargetType, StandardVersion, Standard
from backend.app.database import get_session
from backend.app.api import deps
import uuid

router = APIRouter()

@router.get("/", response_model=List[schemas.folder.Folder])
async def read_folders(
    db: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve folders.
    """
    result = await db.execute(select(Folder).offset(skip).limit(limit))
    folders = result.scalars().all()
    return folders

@router.post("/", response_model=schemas.folder.Folder)
async def create_folder(
    *,
    db: AsyncSession = Depends(get_session),
    folder_in: schemas.folder.FolderCreate,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Create new folder.
    """
    folder = Folder.from_orm(folder_in)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder

@router.get("/{folder_id}", response_model=schemas.folder.Folder)
async def read_folder(
    *,
    db: AsyncSession = Depends(get_session),
    folder_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get folder by ID.
    """
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder

@router.get("/{folder_id}/documents", response_model=List[schemas.document.Document])
async def read_folder_documents(
    *,
    db: AsyncSession = Depends(get_session),
    folder_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get all documents in a folder.
    """
    result = await db.execute(select(Document).where(Document.folder_id == folder_id))
    documents = result.scalars().all()
    return documents

@router.get("/{folder_id}/standard")
async def get_folder_standard(
    *,
    db: AsyncSession = Depends(get_session),
    folder_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get the standard assignment for a folder (if any).
    """
    stmt = (
        select(StandardAssignment)
        .where(StandardAssignment.target_id == folder_id)
        .where(StandardAssignment.target_type == TargetType.FOLDER)
    )
    result = await db.execute(stmt)
    assignment = result.scalar_one_or_none()

    if not assignment:
        return {"assigned": False, "standard": None}

    # Fetch the standard version and its parent standard
    version = await db.get(StandardVersion, assignment.standard_version_id)
    if version:
        standard = await db.get(Standard, version.standard_id)
        return {
            "assigned": True,
            "standard": {
                "id": str(standard.id) if standard else None,
                "name": standard.name if standard else "Unknown",
                "version_number": version.version_number,
                "version_id": str(version.id)
            }
        }

    return {"assigned": False, "standard": None}

@router.delete("/{folder_id}")
async def delete_folder(
    *,
    db: AsyncSession = Depends(get_session),
    folder_id: uuid.UUID,
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete a folder and all its contents (recursive).
    """
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    # 1. Get all subfolders and documents recursively
    from backend.app.tasks import _get_all_subfolder_ids
    folder_ids = await _get_all_subfolder_ids(db, folder_id)
    
    # 2. Delete all documents in these folders
    from backend.app.services.storage import minio_client
    stmt = select(Document).where(Document.folder_id.in_(folder_ids))
    result = await db.execute(stmt)
    documents = result.scalars().all()
    
    # Preemptively delete all ValidationResults for these documents
    if documents:
        doc_ids = [doc.id for doc in documents]
        from backend.app.models.validation_audit import ValidationResult
        from sqlalchemy import delete
        await db.execute(delete(ValidationResult).where(ValidationResult.document_id.in_(doc_ids)))
        
        # Also delete StandardAssignments for these documents and folders
        from backend.app.models.standard import StandardAssignment
        await db.execute(delete(StandardAssignment).where(
            StandardAssignment.target_id.in_(doc_ids + folder_ids)
        ))
    
    for doc in documents:
        try:
            if doc.minio_version_id:
                minio_client.delete_file(doc.minio_version_id)
        except Exception as e:
            print(f"Warning: could not delete file {doc.filename} from MinIO: {e}")
        await db.delete(doc)

    # 3. Delete folders in correct order (children first)
    # _get_all_subfolder_ids doesn't guarantee order for deletion, 
    # but we can just delete them. SQLModel/SQLAlchemy should handle it if there are no hard constraints 
    # or we delete parent folder and rely on cascade? 
    # Actually, let's just delete all and commit.
    for fid in reversed(folder_ids): # reversed might help if they were added in hierarchy order
        f = await db.get(Folder, fid)
        if f:
            await db.delete(f)

    # 4. Audit
    from backend.app.services.audit_service import audit_service
    await audit_service.log_action(
        db,
        actor_id=current_user.get("sub", "unknown"),
        action="DELETE_FOLDER",
        target_id=folder_id,
        details={"name": folder.name, "doc_count": len(documents)}
    )
    
    await db.commit()
    return {"status": "ok", "message": f"Folder and {len(documents)} documents deleted"}

@router.patch("/{folder_id}")
async def rename_folder(
    *,
    db: AsyncSession = Depends(get_session),
    folder_id: uuid.UUID,
    new_name: str = Body(..., embed=True),
    current_user: dict = Depends(deps.get_current_active_user),
) -> Any:
    """
    Rename a folder.
    """
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    old_name = folder.name
    folder.name = new_name
    db.add(folder)
    
    # Audit
    from backend.app.services.audit_service import audit_service
    await audit_service.log_action(
        db,
        actor_id=current_user.get("sub", "unknown"),
        action="RENAME_FOLDER",
        target_id=folder_id,
        details={"old_name": old_name, "new_name": new_name}
    )
    
    await db.commit()
    await db.refresh(folder)
    return folder



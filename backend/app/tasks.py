from backend.app.worker import celery_app
from backend.app.models import Document, StandardVersion, ValidationResult, ValidationStatus, StandardAssignment, Folder
from backend.app.services.validation_service import validation_service
from backend.app.services.storage import minio_client
from backend.app.core.config import settings
from sqlmodel import select
import asyncio
import uuid
from asgiref.sync import async_to_sync
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

@celery_app.task(name="backend.app.tasks.validate_document_task")
def validate_document_task(document_id_str: str, standard_version_id_str: str):
    """
    Background task to validate a document.
    """
    async_to_sync(validate_document_async)(document_id_str, standard_version_id_str)

async def validate_document_async(document_id_str: str, standard_version_id_str: str):
    document_id = uuid.UUID(document_id_str)
    standard_version_id = uuid.UUID(standard_version_id_str)
    
    # Create local engine for task to avoid 'Event loop is closed' on Windows
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    try:
        async with async_session() as db:
            from sqlalchemy.orm import selectinload
            stmt = select(StandardVersion).where(StandardVersion.id == standard_version_id).options(selectinload(StandardVersion.standard))
            result = await db.execute(stmt)
            version = result.scalar_one_or_none()
            document = await db.get(Document, document_id)
            
            if not document or not version:
                return

            # O15. Mark as PENDING immediately to inform UI
            pending_result = ValidationResult(
                document_id=document_id,
                standard_version_id=standard_version_id,
                status=ValidationStatus.PENDING,
                report_json={"message": "AI Background evaluation in progress..."}
            )
            db.add(pending_result)
            await db.commit()
            await db.refresh(pending_result)

            # Get file
            try:
                # MinIO is sync, validation_service is mixed.
                storage_path = document.minio_version_id or f"{document.id}/{document.filename}"
                file_content = minio_client.get_file(storage_path)
                
                # Validate
                report = await validation_service.validate_document_async(file_content, version, document.filename)
                
                status_str = report.get("evaluation_status", "NON_COMPLIANT")
                try:
                    status = ValidationStatus(status_str)
                except ValueError:
                    status = ValidationStatus.FAIL # Fallback
                
                # Update the pending result instead of creating new one
                pending_result.status = status
                pending_result.report_json = report
                db.add(pending_result)
                await db.commit()
            except Exception as e:
                print(f"Validation failed for doc {document_id}: {e}")
    finally:
        await engine.dispose()

@celery_app.task(name="backend.app.tasks.revalidate_folder_task")
def revalidate_folder_task(folder_id_str: str, standard_version_id_str: str):
    async_to_sync(revalidate_folder_async)(folder_id_str, standard_version_id_str)

async def revalidate_folder_async(folder_id_str: str, standard_version_id_str: str):
    folder_id = uuid.UUID(folder_id_str)
    
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    try:
        async with async_session() as db:
            # 1. Get all folder IDs (recursive)
            folder_ids = await _get_all_subfolder_ids(db, folder_id)
            
            # 2. Get all documents in these folders
            from sqlmodel import col
            stmt = select(Document).where(col(Document.folder_id).in_(folder_ids))
            result = await db.execute(stmt)
            documents = result.scalars().all()
            
            # 3. Trigger validation for each
            for doc in documents:
                validate_document_task.delay(str(doc.id), standard_version_id_str)
    finally:
        await engine.dispose()

async def _get_all_subfolder_ids(db, folder_id):
    ids = [folder_id]
    stmt = select(Folder.id).where(Folder.parent_id == folder_id)
    result = await db.execute(stmt)
    children = result.scalars().all()
    for child_id in children:
        ids.extend(await _get_all_subfolder_ids(db, child_id))
    return ids


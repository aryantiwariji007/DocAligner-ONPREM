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

@celery_app.task(name="backend.app.tasks.fix_document_task")
def fix_document_task(document_id_str: str, competence_level: str):
    """
    Background task to fix/transform a document structure.
    """
    async_to_sync(fix_document_async)(document_id_str, competence_level)

async def fix_document_async(document_id_str: str, competence_level: str):
    document_id = uuid.UUID(document_id_str)
    
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    try:
        async with async_session() as db:
            from backend.app.services.decision_flow_service import decision_flow_service
            from backend.app.services.inheritance_service import inheritance_service, TargetType
            from backend.app.services.audit_service import audit_service
            from backend.app.services.pdf_service import pdf_service
            
            # 1. Fetch State
            document = await db.get(Document, document_id)
            effective_std_version = await inheritance_service.get_effective_standard_version(db, document_id, TargetType.DOCUMENT)
            
            if not document or not effective_std_version:
                return

            # 2. Update ValidationResult to PENDING
            # Find the latest or create one
            stmt = select(ValidationResult).where(ValidationResult.document_id == document_id).order_by(ValidationResult.created_at.desc())
            db_res = await db.execute(stmt)
            v = db_res.scalars().first()
            
            if not v:
                v = ValidationResult(document_id=document_id, standard_version_id=effective_std_version.id)
            
            v.status = ValidationStatus.PENDING
            v.report_json = {"message": "AI Structural Alignment in progress..."}
            db.add(v)
            await db.commit()

            # 3. Process
            storage_path = document.minio_version_id or f"{document.id}/{document.filename}"
            file_content = minio_client.get_file(storage_path)
            
            result = await decision_flow_service.apply(
                file_content, 
                document.filename, 
                effective_std_version.rules_json, 
                competence_level=competence_level
            )
            
            if "error" in result:
                 v.status = ValidationStatus.FAIL
                 v.report_json = {"error": result["error"]}
                 db.add(v)
                 await db.commit()
                 return

            # 4. Save Artifacts
            fixed_txt_name = f"fixed/{document_id}/{document.filename}.fixed.txt"
            fixed_pdf_name = f"fixed/{document_id}/{document.filename}.fixed.pdf"
            
            if result.get("transformed_content"):
                minio_client.upload_file(result["transformed_content"].encode("utf-8"), fixed_txt_name, "text/plain")
                
                if result.get("pdf_path") and os.path.exists(result["pdf_path"]):
                    with open(result["pdf_path"], "rb") as f:
                        minio_client.upload_file(f.read(), fixed_pdf_name, "application/pdf")
                    os.remove(result["pdf_path"])

                # 5. Finalize Result
                existing_report = v.report_json or {}
                existing_report["fixed_content"] = result["transformed_content"]
                existing_report["fixed_path"] = fixed_txt_name
                existing_report["fixed_pdf_path"] = fixed_pdf_name
                existing_report["decision_flow"] = {
                    "action": result["action"],
                    "score": result["score"],
                    "risk": result["risk"],
                    "alignment_details": result.get("alignment_details", {}),
                    "change_summary": result.get("change_summary", ""),
                }
                
                v.status = ValidationStatus.COMPLIANT if result["score"] >= 85 else ValidationStatus.NON_COMPLIANT
                v.report_json = existing_report
                db.add(v)
                
                # 6. Audit
                await audit_service.log_action(
                    db,
                    actor_id="system",
                    action=f"AI_FIX_{result['action'].upper()}",
                    target_id=document_id,
                    details={"score": result["score"]}
                )
                await db.commit()

    finally:
        await engine.dispose()

import os

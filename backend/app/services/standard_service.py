from typing import List, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from backend.app.models import Standard, StandardVersion, StandardAssignment, TargetType, Document, Folder
from backend.app.services.validation_service import validation_service
from backend.app.services.audit_service import audit_service


class StandardService:
    async def get_active_version(self, db: AsyncSession, standard_id: uuid.UUID) -> Optional[StandardVersion]:
        """Get the latest active version of a standard."""
        stmt = (
            select(StandardVersion)
            .where(StandardVersion.standard_id == standard_id)
            .where(StandardVersion.is_active == True)
            .order_by(StandardVersion.version_number.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def apply_to_document(
        self,
        db: AsyncSession,
        standard_version_id: uuid.UUID,
        document_id: uuid.UUID,
        user_id: str
    ) -> StandardAssignment:
        """
        Apply a standard version to a specific document.
        Creates an assignment and triggers validation via Celery background task.
        """
        # 1. Check if assignment already exists
        stmt = (
            select(StandardAssignment)
            .where(StandardAssignment.target_id == document_id)
            .where(StandardAssignment.target_type == TargetType.DOCUMENT)
            .where(StandardAssignment.standard_version_id == standard_version_id)
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Even if assignment exists, trigger re-validation
            self._trigger_document_validation(str(document_id), str(standard_version_id))
            return existing

        # 2. Create new assignment
        assignment = StandardAssignment(
            target_id=document_id,
            target_type=TargetType.DOCUMENT,
            standard_version_id=standard_version_id
        )
        db.add(assignment)

        # 3. Log Audit
        try:
            await audit_service.log_action(
                db,
                actor_id=user_id,
                action="APPLY_STANDARD_DOCUMENT",
                target_id=document_id,
                details={"standard_version_id": str(standard_version_id)}
            )
        except Exception as e:
            print(f"Audit log failed (non-critical): {e}")

        await db.commit()
        await db.refresh(assignment)

        # 4. Trigger background validation via Celery
        self._trigger_document_validation(str(document_id), str(standard_version_id))

        return assignment

    async def apply_to_folder(
        self,
        db: AsyncSession,
        standard_version_id: uuid.UUID,
        folder_id: uuid.UUID,
        user_id: str,
        recursive: bool = True
    ) -> List[StandardAssignment]:
        """
        Apply a standard to a folder and all its documents.
        If recursive=True, also applies to all subfolders and their documents.
        """
        assignments = []

        # 1. Assign to the folder itself
        folder_stmt = (
            select(StandardAssignment)
            .where(StandardAssignment.target_id == folder_id)
            .where(StandardAssignment.target_type == TargetType.FOLDER)
            .where(StandardAssignment.standard_version_id == standard_version_id)
        )
        result = await db.execute(folder_stmt)
        existing = result.scalar_one_or_none()

        if not existing:
            assignment = StandardAssignment(
                target_id=folder_id,
                target_type=TargetType.FOLDER,
                standard_version_id=standard_version_id
            )
            db.add(assignment)
            try:
                await audit_service.log_action(
                    db,
                    actor_id=user_id,
                    action="APPLY_STANDARD_FOLDER",
                    target_id=folder_id,
                    details={
                        "standard_version_id": str(standard_version_id),
                        "recursive": recursive
                    }
                )
            except Exception as e:
                print(f"Audit log failed (non-critical): {e}")
            assignments.append(assignment)
        else:
            # Update existing assignment to point to new version
            existing.standard_version_id = standard_version_id
            db.add(existing)
            assignments.append(existing)

        # 2. Gather all folder IDs (recursive or just this one)
        if recursive:
            folder_ids = await self._get_all_subfolder_ids(db, folder_id)
        else:
            folder_ids = [folder_id]

        # 3. Find all documents in these folders
        doc_stmt = select(Document).where(Document.folder_id.in_(folder_ids))
        doc_result = await db.execute(doc_stmt)
        docs = doc_result.scalars().all()

        # 4. Create/update assignments for each document
        doc_ids_to_validate = []
        for doc in docs:
            existing_doc_stmt = (
                select(StandardAssignment)
                .where(StandardAssignment.target_id == doc.id)
                .where(StandardAssignment.target_type == TargetType.DOCUMENT)
            )
            existing_doc_result = await db.execute(existing_doc_stmt)
            existing_doc_assignment = existing_doc_result.scalar_one_or_none()

            if existing_doc_assignment:
                existing_doc_assignment.standard_version_id = standard_version_id
                db.add(existing_doc_assignment)
            else:
                doc_assignment = StandardAssignment(
                    target_id=doc.id,
                    target_type=TargetType.DOCUMENT,
                    standard_version_id=standard_version_id
                )
                db.add(doc_assignment)
                assignments.append(doc_assignment)

            doc_ids_to_validate.append(str(doc.id))

        # 5. Commit all assignments
        await db.commit()

        # 6. Trigger background validation for each document via Celery
        sv_id_str = str(standard_version_id)
        for doc_id_str in doc_ids_to_validate:
            self._trigger_document_validation(doc_id_str, sv_id_str)

        return assignments

    async def _get_all_subfolder_ids(
        self, db: AsyncSession, folder_id: uuid.UUID
    ) -> List[uuid.UUID]:
        """Recursively collect this folder's ID and all descendant folder IDs."""
        ids = [folder_id]
        stmt = select(Folder.id).where(Folder.parent_id == folder_id)
        result = await db.execute(stmt)
        children = result.scalars().all()
        for child_id in children:
            ids.extend(await self._get_all_subfolder_ids(db, child_id))
        return ids

    @staticmethod
    def _trigger_document_validation(document_id_str: str, standard_version_id_str: str):
        """Trigger Celery background task for document validation."""
        try:
            from backend.app.tasks import validate_document_task
            validate_document_task.delay(document_id_str, standard_version_id_str)
        except Exception as e:
            print(f"WARNING: Could not enqueue validation task for doc {document_id_str}: {e}")


standard_service = StandardService()

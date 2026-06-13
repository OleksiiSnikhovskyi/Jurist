from sqlalchemy.orm import Session

from app.models.document import Document


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_document(self, document_id: str) -> Document | None:
        return self.db.get(Document, document_id)

    def create_document(
        self,
        *,
        workspace_id: str,
        uploaded_by: str,
        document_name: str,
        document_type: str | None,
        file_path: str,
        confidentiality_level: str,
    ) -> Document:
        document = Document(
            workspace_id=workspace_id,
            uploaded_by=uploaded_by,
            document_name=document_name,
            document_type=document_type,
            file_path=file_path,
            confidentiality_level=confidentiality_level,
        )
        self.db.add(document)
        self.db.flush()
        return document

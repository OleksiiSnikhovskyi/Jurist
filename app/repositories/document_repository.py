from sqlalchemy.orm import Session

from app.models.document import Document


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_document(self, document_id: str) -> Document | None:
        return self.db.get(Document, document_id)

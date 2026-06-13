from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk


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
        extracted_text: str | None = None,
    ) -> Document:
        document = Document(
            workspace_id=workspace_id,
            uploaded_by=uploaded_by,
            document_name=document_name,
            document_type=document_type,
            file_path=file_path,
            confidentiality_level=confidentiality_level,
            extracted_text=extracted_text,
        )
        self.db.add(document)
        self.db.flush()
        return document

    def delete_chunks_for_document(self, document_id: str) -> None:
        self.db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()

    def create_document_chunks(
        self,
        *,
        document_id: str,
        workspace_id: str,
        chunks: list[str],
    ) -> list[DocumentChunk]:
        document_chunks = [
            DocumentChunk(
                document_id=document_id,
                workspace_id=workspace_id,
                chunk_index=index,
                chunk_text=chunk_text,
            )
            for index, chunk_text in enumerate(chunks)
        ]
        self.db.add_all(document_chunks)
        self.db.flush()
        return document_chunks

    def list_chunks_for_document(self, document_id: str) -> list[DocumentChunk]:
        return (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )

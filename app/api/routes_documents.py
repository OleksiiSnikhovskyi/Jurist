from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas.document_schema import DocumentResponse
from app.services.access_control import AccessDeniedError
from app.services.document_upload_service import DocumentUploadCommand, DocumentUploadService


router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    workspace_id: str = Form(...),
    user_id: str = Form(...),
    document_type: str | None = Form(default=None),
    confidentiality_level: str = Form(default="private"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    try:
        return DocumentUploadService(db, get_settings().upload_dir).upload(
            DocumentUploadCommand(
                workspace_id=workspace_id,
                user_id=user_id,
                document_type=document_type,
                confidentiality_level=confidentiality_level,
            ),
            file,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

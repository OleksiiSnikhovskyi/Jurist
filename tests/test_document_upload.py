from collections.abc import Generator
from io import BytesIO
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import UploadFile

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.access_control import AccessDeniedError
from app.services.document_upload_service import DocumentUploadCommand, DocumentUploadService


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    Workspace.__table__.create(engine)
    WorkspaceMember.__table__.create(engine)
    Document.__table__.create(engine)
    AuditLog.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def upload_dir() -> Generator[Path, None, None]:
    path = Path("test_uploads") / str(uuid4())
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _seed_workspace(db: Session, *, role: str = "lawyer") -> None:
    db.add(User(id="user-1", email="user@example.com", role="lawyer"))
    db.add(Workspace(id="workspace-1", name="Workspace", owner_id="user-1", workspace_type="case"))
    db.add(
        WorkspaceMember(
            id="member-1",
            workspace_id="workspace-1",
            user_id="user-1",
            role=role,
        )
    )
    db.commit()


def test_document_upload_service_stores_file_metadata_and_audit(
    db_session: Session,
    upload_dir: Path,
) -> None:
    _seed_workspace(db_session)
    upload = UploadFile(filename="contract.txt", file=BytesIO(b"hello"))

    document = DocumentUploadService(db_session, upload_dir).upload(
        DocumentUploadCommand(workspace_id="workspace-1", user_id="user-1"),
        upload,
    )

    stored_path = Path(document.file_path or "")
    audit_log = db_session.query(AuditLog).one()
    assert document.document_name == "contract.txt"
    assert document.uploaded_by == "user-1"
    assert stored_path.exists()
    assert stored_path.read_bytes() == b"hello"
    assert audit_log.action == "document.uploaded"
    assert audit_log.object_id == document.id
    assert audit_log.metadata_json["document_name"] == "contract.txt"
    assert audit_log.metadata_json["extraction_status"] == "not_extracted"


def test_document_upload_service_extracts_docx_text(
    db_session: Session,
    upload_dir: Path,
) -> None:
    from docx import Document as DocxDocument

    _seed_workspace(db_session)
    docx_path = upload_dir / "source-contract.docx"
    docx = DocxDocument()
    docx.add_paragraph("Important DOCX clause")
    docx.save(docx_path)

    with docx_path.open("rb") as input_file:
        upload = UploadFile(filename="contract.docx", file=input_file)
        document = DocumentUploadService(db_session, upload_dir).upload(
            DocumentUploadCommand(
                workspace_id="workspace-1",
                user_id="user-1",
                document_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            upload,
        )

    assert document.extracted_text == "Important DOCX clause"


def test_document_upload_service_denies_viewer_write(
    db_session: Session,
    upload_dir: Path,
) -> None:
    _seed_workspace(db_session, role="viewer")
    upload = UploadFile(filename="contract.txt", file=BytesIO(b"hello"))

    with pytest.raises(AccessDeniedError):
        DocumentUploadService(db_session, upload_dir).upload(
            DocumentUploadCommand(workspace_id="workspace-1", user_id="user-1"),
            upload,
        )


def test_document_upload_endpoint(db_session: Session, upload_dir: Path, monkeypatch) -> None:
    _seed_workspace(db_session)
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        response = client.post(
            "/documents/upload",
            data={"workspace_id": "workspace-1", "user_id": "user-1"},
            files={"file": ("contract.txt", b"hello", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()

    assert response.status_code == 201
    body = response.json()
    assert body["document_name"] == "contract.txt"
    assert body["workspace_id"] == "workspace-1"
    assert db_session.query(Document).count() == 1

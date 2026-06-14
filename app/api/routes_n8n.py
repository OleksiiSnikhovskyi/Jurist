from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.n8n_schema import (
    N8nIntakeResponse,
    N8nLegalSourceUpsertRequest,
    N8nLegalSourceUpsertResponse,
    N8nObsidianNoteRequest,
    N8nObsidianNoteResponse,
    N8nProcessPackageRequest,
    N8nProcessPackageResponse,
    N8nTelegramBindingRequest,
    N8nTelegramBindingResponse,
    TelegramIntakeEvent,
)
from app.services.access_control import AccessDeniedError
from app.services.n8n_integration_service import (
    IntakePackageNotFoundError,
    LegalSourceValidationError,
    N8nIntegrationService,
)


router = APIRouter(prefix="/n8n", tags=["n8n"])


@router.post("/intake/telegram", response_model=N8nIntakeResponse)
def handle_telegram_intake(
    event: TelegramIntakeEvent,
    db: Session = Depends(get_db),
) -> N8nIntakeResponse:
    try:
        return N8nIntegrationService(db).handle_telegram_event(event)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/telegram/bindings", response_model=N8nTelegramBindingResponse)
def upsert_telegram_binding(
    request: N8nTelegramBindingRequest,
    db: Session = Depends(get_db),
) -> N8nTelegramBindingResponse:
    try:
        return N8nIntegrationService(db).upsert_telegram_binding(request)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/intake/process", response_model=N8nProcessPackageResponse)
def start_package_processing(
    request: N8nProcessPackageRequest,
    db: Session = Depends(get_db),
) -> N8nProcessPackageResponse:
    try:
        return N8nIntegrationService(db).start_package_processing(request)
    except IntakePackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/obsidian/sync-note", response_model=N8nObsidianNoteResponse)
def sync_obsidian_note(
    request: N8nObsidianNoteRequest,
    db: Session = Depends(get_db),
) -> N8nObsidianNoteResponse:
    try:
        return N8nIntegrationService(db).sync_obsidian_note(request)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/legal-sources/upsert", response_model=N8nLegalSourceUpsertResponse)
def upsert_legal_source(
    request: N8nLegalSourceUpsertRequest,
    db: Session = Depends(get_db),
) -> N8nLegalSourceUpsertResponse:
    try:
        return N8nIntegrationService(db).upsert_legal_source(request)
    except LegalSourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

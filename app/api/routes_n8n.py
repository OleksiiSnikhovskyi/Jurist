from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.n8n_schema import (
    N8nExtractedTextRequest,
    N8nExtractedTextResponse,
    N8nIntakeResponse,
    N8nLegalSourceUpsertRequest,
    N8nLegalSourceUpsertResponse,
    N8nObsidianNoteRequest,
    N8nObsidianNoteResponse,
    N8nOfficialSourceCandidateRequest,
    N8nOfficialSourceCandidateResponse,
    N8nOfficialSourceSearchPlanRequest,
    N8nOfficialSourceSearchPlanResponse,
    N8nOfficialSourceVerificationRequest,
    N8nOfficialSourceVerificationResponse,
    N8nProcessPackageRequest,
    N8nProcessPackageResponse,
    N8nReembedMissingChunksRequest,
    N8nReembedMissingChunksResponse,
    N8nTelegramBindingRequest,
    N8nTelegramBindingResponse,
    TelegramIntakeEvent,
)
from app.services.access_control import AccessDeniedError
from app.services.official_source_search_service import OfficialSourceSearchPlanner
from app.services.n8n_integration_service import (
    IntakeItemNotFoundError,
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


@router.post("/intake/extracted-text", response_model=N8nExtractedTextResponse)
def attach_extracted_text(
    request: N8nExtractedTextRequest,
    db: Session = Depends(get_db),
) -> N8nExtractedTextResponse:
    try:
        return N8nIntegrationService(db).attach_extracted_text(request)
    except (IntakeItemNotFoundError, IntakePackageNotFoundError) as exc:
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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/official-source-search/plan", response_model=N8nOfficialSourceSearchPlanResponse)
def build_official_source_search_plan(
    request: N8nOfficialSourceSearchPlanRequest,
    db: Session = Depends(get_db),
) -> N8nOfficialSourceSearchPlanResponse:
    try:
        return OfficialSourceSearchPlanner(db).build_plan(request)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post(
    "/legal-sources/verification-candidates",
    response_model=N8nOfficialSourceCandidateResponse,
)
def list_official_source_verification_candidates(
    request: N8nOfficialSourceCandidateRequest,
    db: Session = Depends(get_db),
) -> N8nOfficialSourceCandidateResponse:
    try:
        return N8nIntegrationService(db).list_official_source_verification_candidates(request)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post(
    "/legal-sources/verify-official-sources",
    response_model=N8nOfficialSourceVerificationResponse,
)
def record_official_source_verifications(
    request: N8nOfficialSourceVerificationRequest,
    db: Session = Depends(get_db),
) -> N8nOfficialSourceVerificationResponse:
    try:
        return N8nIntegrationService(db).record_official_source_verifications(request)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/maintenance/reembed-missing-chunks", response_model=N8nReembedMissingChunksResponse)
def reembed_missing_chunks(
    request: N8nReembedMissingChunksRequest,
    db: Session = Depends(get_db),
) -> N8nReembedMissingChunksResponse:
    try:
        return N8nIntegrationService(db).reembed_missing_chunks(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

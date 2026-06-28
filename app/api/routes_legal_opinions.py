from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.legal_opinion import LegalOpinion
from app.schemas.legal_opinion_schema import LegalOpinionResponse, LegalOpinionReviewUpdate
from app.services.access_control import AccessControlService, AccessDeniedError, WorkspacePermission


router = APIRouter(prefix="/legal-opinions", tags=["legal-opinions"])


def _get_opinion_or_404(db: Session, opinion_id: str) -> LegalOpinion:
    opinion = db.get(LegalOpinion, opinion_id)
    if opinion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal opinion not found")
    return opinion


@router.get("/by-workspace/{workspace_id}", response_model=list[LegalOpinionResponse])
def list_legal_opinions(
    workspace_id: str,
    user_id: str,
    review_status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[LegalOpinion]:
    try:
        AccessControlService(db).require_permission(
            workspace_id=workspace_id,
            user_id=user_id,
            permission=WorkspacePermission.READ,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    query = db.query(LegalOpinion).filter(LegalOpinion.workspace_id == workspace_id)
    if review_status:
        query = query.filter(LegalOpinion.review_status == review_status)
    return query.order_by(LegalOpinion.created_at.desc()).limit(max(1, min(limit, 200))).all()


@router.get("/{opinion_id}", response_model=LegalOpinionResponse)
def get_legal_opinion(
    opinion_id: str,
    user_id: str,
    db: Session = Depends(get_db),
) -> LegalOpinion:
    opinion = _get_opinion_or_404(db, opinion_id)
    try:
        AccessControlService(db).require_permission(
            workspace_id=opinion.workspace_id,
            user_id=user_id,
            permission=WorkspacePermission.READ,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return opinion


@router.patch("/{opinion_id}/review", response_model=LegalOpinionResponse)
def update_legal_opinion_review(
    opinion_id: str,
    request: LegalOpinionReviewUpdate,
    db: Session = Depends(get_db),
) -> LegalOpinion:
    opinion = _get_opinion_or_404(db, opinion_id)
    try:
        AccessControlService(db).require_permission(
            workspace_id=opinion.workspace_id,
            user_id=request.user_id,
            permission=WorkspacePermission.REVIEW_DOCUMENTS,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    opinion.review_status = request.review_status
    opinion.review_notes = request.review_notes
    if request.review_status == "draft":
        opinion.reviewed_by = None
        opinion.reviewed_at = None
    else:
        opinion.reviewed_by = request.user_id
        opinion.reviewed_at = datetime.now(UTC)
    db.commit()
    db.refresh(opinion)
    return opinion

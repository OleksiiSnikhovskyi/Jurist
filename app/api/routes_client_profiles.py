from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.client_profile import ClientProfile
from app.schemas.client_profile_schema import (
    ClientProfileCreate,
    ClientProfileResponse,
    ClientProfileUpdate,
)
from app.services.access_control import AccessControlService, AccessDeniedError, WorkspacePermission


router = APIRouter(prefix="/client-profiles", tags=["client-profiles"])


def _get_profile_or_404(db: Session, profile_id: str) -> ClientProfile:
    profile = db.get(ClientProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client profile not found")
    return profile


@router.post("", response_model=ClientProfileResponse, status_code=status.HTTP_201_CREATED)
def create_client_profile(
    request: ClientProfileCreate,
    db: Session = Depends(get_db),
) -> ClientProfile:
    try:
        AccessControlService(db).require_permission(
            workspace_id=request.workspace_id,
            user_id=request.created_by,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    profile = ClientProfile(**request.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/by-workspace/{workspace_id}", response_model=list[ClientProfileResponse])
def list_client_profiles(
    workspace_id: str,
    user_id: str,
    db: Session = Depends(get_db),
) -> list[ClientProfile]:
    try:
        AccessControlService(db).require_permission(
            workspace_id=workspace_id,
            user_id=user_id,
            permission=WorkspacePermission.READ,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return (
        db.query(ClientProfile)
        .filter(ClientProfile.workspace_id == workspace_id)
        .order_by(ClientProfile.created_at.desc())
        .all()
    )


@router.get("/{profile_id}", response_model=ClientProfileResponse)
def get_client_profile(
    profile_id: str,
    user_id: str,
    db: Session = Depends(get_db),
) -> ClientProfile:
    profile = _get_profile_or_404(db, profile_id)
    try:
        AccessControlService(db).require_permission(
            workspace_id=profile.workspace_id,
            user_id=user_id,
            permission=WorkspacePermission.READ,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return profile


@router.patch("/{profile_id}", response_model=ClientProfileResponse)
def update_client_profile(
    profile_id: str,
    request: ClientProfileUpdate,
    user_id: str,
    db: Session = Depends(get_db),
) -> ClientProfile:
    profile = _get_profile_or_404(db, profile_id)
    try:
        AccessControlService(db).require_permission(
            workspace_id=profile.workspace_id,
            user_id=user_id,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    for field_name, value in request.model_dump(exclude_unset=True).items():
        setattr(profile, field_name, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client_profile(
    profile_id: str,
    user_id: str,
    db: Session = Depends(get_db),
) -> Response:
    profile = _get_profile_or_404(db, profile_id)
    try:
        AccessControlService(db).require_permission(
            workspace_id=profile.workspace_id,
            user_id=user_id,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    db.delete(profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

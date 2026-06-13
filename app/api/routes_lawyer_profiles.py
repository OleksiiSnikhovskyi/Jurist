from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.lawyer_profile import LawyerProfile
from app.models.user import User
from app.schemas.lawyer_profile_schema import (
    LawyerProfileCreate,
    LawyerProfileResponse,
    LawyerProfileUpdate,
)


router = APIRouter(prefix="/lawyer-profiles", tags=["lawyer-profiles"])


def _get_profile_or_404(db: Session, profile_id: str) -> LawyerProfile:
    profile = db.get(LawyerProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lawyer profile not found")
    return profile


@router.post("", response_model=LawyerProfileResponse, status_code=status.HTTP_201_CREATED)
def create_lawyer_profile(
    request: LawyerProfileCreate,
    db: Session = Depends(get_db),
) -> LawyerProfile:
    if db.get(User, request.user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing_profile = (
        db.query(LawyerProfile).filter(LawyerProfile.user_id == request.user_id).one_or_none()
    )
    if existing_profile is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lawyer profile already exists for this user",
        )

    profile = LawyerProfile(**request.model_dump())
    db.add(profile)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lawyer profile could not be created",
        ) from exc
    db.refresh(profile)
    return profile


@router.get("/by-user/{user_id}", response_model=LawyerProfileResponse)
def get_lawyer_profile_by_user(user_id: str, db: Session = Depends(get_db)) -> LawyerProfile:
    profile = db.query(LawyerProfile).filter(LawyerProfile.user_id == user_id).one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lawyer profile not found")
    return profile


@router.get("/{profile_id}", response_model=LawyerProfileResponse)
def get_lawyer_profile(profile_id: str, db: Session = Depends(get_db)) -> LawyerProfile:
    return _get_profile_or_404(db, profile_id)


@router.patch("/{profile_id}", response_model=LawyerProfileResponse)
def update_lawyer_profile(
    profile_id: str,
    request: LawyerProfileUpdate,
    db: Session = Depends(get_db),
) -> LawyerProfile:
    profile = _get_profile_or_404(db, profile_id)
    update_data = request.model_dump(exclude_unset=True)
    if update_data.get("system_prompt") is None and "system_prompt" in update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="system_prompt cannot be null",
        )

    for field_name, value in update_data.items():
        setattr(profile, field_name, value)

    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lawyer_profile(profile_id: str, db: Session = Depends(get_db)) -> Response:
    profile = _get_profile_or_404(db, profile_id)
    db.delete(profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

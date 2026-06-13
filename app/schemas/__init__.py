"""Pydantic schemas for API requests and responses."""

from app.schemas.lawyer_profile_schema import (
    LawyerProfileCreate,
    LawyerProfileResponse,
    LawyerProfileUpdate,
)

__all__ = [
    "LawyerProfileCreate",
    "LawyerProfileResponse",
    "LawyerProfileUpdate",
]

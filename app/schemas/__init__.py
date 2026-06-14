"""Pydantic schemas for API requests and responses."""

from app.schemas.client_profile_schema import (
    ClientProfileCreate,
    ClientProfileResponse,
    ClientProfileUpdate,
)
from app.schemas.document_schema import DocumentResponse
from app.schemas.lawyer_profile_schema import (
    LawyerProfileCreate,
    LawyerProfileResponse,
    LawyerProfileUpdate,
)

__all__ = [
    "ClientProfileCreate",
    "ClientProfileResponse",
    "ClientProfileUpdate",
    "DocumentResponse",
    "LawyerProfileCreate",
    "LawyerProfileResponse",
    "LawyerProfileUpdate",
]

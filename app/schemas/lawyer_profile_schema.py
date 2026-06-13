from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LawyerProfileBase(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    system_prompt: str | None = None
    specialization: str | None = None
    jurisdictions: list[str] | None = None
    workplace_context: str | None = None
    represented_interests: str | None = None
    communication_style: str | None = None
    extra_context: dict[str, Any] | None = None


class LawyerProfileCreate(LawyerProfileBase):
    user_id: str
    system_prompt: str = Field(min_length=1)


class LawyerProfileUpdate(LawyerProfileBase):
    pass


class LawyerProfileResponse(LawyerProfileBase):
    id: str
    user_id: str
    system_prompt: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

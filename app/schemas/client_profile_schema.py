from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClientProfileBase(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    client_type: str | None = Field(default=None, max_length=100)
    matter_role: str | None = Field(default=None, max_length=255)
    interests: str | None = None
    risk_preferences: str | None = None
    communication_preferences: str | None = None
    factual_context: str | None = None
    extra_context: dict[str, Any] | None = None


class ClientProfileCreate(ClientProfileBase):
    workspace_id: str
    created_by: str
    display_name: str = Field(min_length=1, max_length=255)


class ClientProfileUpdate(ClientProfileBase):
    pass


class ClientProfileResponse(ClientProfileBase):
    id: str
    workspace_id: str
    created_by: str
    display_name: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

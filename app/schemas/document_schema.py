from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    id: str
    workspace_id: str
    uploaded_by: str
    document_name: str
    document_type: str | None = None
    file_path: str | None = None
    confidentiality_level: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

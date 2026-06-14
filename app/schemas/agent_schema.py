from pydantic import BaseModel, Field


class AgentQueryRequest(BaseModel):
    user_id: str
    workspace_id: str
    question: str = Field(min_length=1)
    document_id: str | None = None
    client_profile_id: str | None = None


class AgentWarning(BaseModel):
    code: str
    message: str


class AgentQueryResponse(BaseModel):
    answer: str
    sources_used: list[dict] = Field(default_factory=list)
    warnings: list[AgentWarning] = Field(default_factory=list)
    confidence_score: float | None = None

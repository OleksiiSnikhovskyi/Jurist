from fastapi import APIRouter

from app.agents.orchestrator import LegalPlatformOrchestrator
from app.schemas.agent_schema import AgentQueryRequest, AgentQueryResponse


router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/orchestrator/query", response_model=AgentQueryResponse)
def query_orchestrator(request: AgentQueryRequest) -> AgentQueryResponse:
    return LegalPlatformOrchestrator().answer(request)


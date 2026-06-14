from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.contract_review import ContractReviewAgent
from app.agents.legal_research import LegalResearchAgent
from app.agents.orchestrator import LegalPlatformOrchestrator
from app.agents.quality_control import QualityControlAgent
from app.database import get_db
from app.schemas.agent_schema import AgentQueryRequest, AgentQueryResponse
from app.services.agent_context_service import ClientProfileNotFoundError
from app.services.access_control import AccessDeniedError
from app.services.document_access_service import DocumentNotFoundError


router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/orchestrator/query", response_model=AgentQueryResponse)
def query_orchestrator(request: AgentQueryRequest) -> AgentQueryResponse:
    return LegalPlatformOrchestrator().answer(request)


@router.post("/contract-review/query", response_model=AgentQueryResponse)
def query_contract_review(
    request: AgentQueryRequest,
    db: Session = Depends(get_db),
) -> AgentQueryResponse:
    try:
        return ContractReviewAgent(db).review(request)
    except ClientProfileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/legal-research/query", response_model=AgentQueryResponse)
def query_legal_research(
    request: AgentQueryRequest,
    db: Session = Depends(get_db),
) -> AgentQueryResponse:
    try:
        return LegalResearchAgent(db).research(request)
    except ClientProfileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/quality-control/query", response_model=AgentQueryResponse)
def query_quality_control(
    request: AgentQueryRequest,
    db: Session = Depends(get_db),
) -> AgentQueryResponse:
    try:
        return QualityControlAgent(db).review(request)
    except ClientProfileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

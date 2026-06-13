"""Agent modules. Implementations must stay source-aware and workspace-scoped."""

from app.agents.contract_review import ContractReviewAgent
from app.agents.legal_research import LegalResearchAgent
from app.agents.orchestrator import LegalPlatformOrchestrator
from app.agents.quality_control import QualityControlAgent

__all__ = [
    "ContractReviewAgent",
    "LegalPlatformOrchestrator",
    "LegalResearchAgent",
    "QualityControlAgent",
]

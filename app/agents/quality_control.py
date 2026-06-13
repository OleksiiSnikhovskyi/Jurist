from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.schemas.agent_schema import AgentQueryRequest, AgentQueryResponse, AgentWarning
from app.services.document_access_service import DocumentAccessService
from app.services.vector_search_service import VectorSearchCommand, VectorSearchResult, VectorSearchService


QUALITY_CONTROL_QUERY = (
    "перевірка якості юридичний висновок джерела докази ризики застереження "
    "актуальність законодавство судова практика факти припущення рекомендації"
)

QC_RULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "Джерела": (
        "У чернетці бракує явних посилань на джерела або використані фрагменти.",
        ("джерел", "статт", "закон", "кодекс", "постанова", "документ"),
    ),
    "Застереження": (
        "У чернетці бракує застереження про попередній характер висновку та потребу людської перевірки.",
        ("попередн", "перевір", "юрист", "офіційн", "актуальн"),
    ),
    "Фактична база": (
        "У чернетці бракує опису фактів або доказів, на яких ґрунтується висновок.",
        ("факт", "доказ", "договір", "лист", "акт", "рахунок", "матеріал"),
    ),
    "Ризики": (
        "У чернетці бракує окремого блоку ризиків або умов, які можуть змінити відповідь.",
        ("ризик", "за умови", "може", "ймовір", "обмежен"),
    ),
}

OVERCONFIDENT_PHRASES: tuple[str, ...] = (
    "гарантовано",
    "безумовно",
    "точно виграє",
    "100%",
    "немає ризиків",
    "остаточно",
)


@dataclass(frozen=True)
class QualityControlFinding:
    category: str
    message: str
    severity: str


class QualityControlAgent:
    def __init__(
        self,
        db: Session,
        vector_search_service: VectorSearchService | None = None,
        document_access_service: DocumentAccessService | None = None,
    ) -> None:
        self.db = db
        self.vector_search_service = vector_search_service or VectorSearchService(db)
        self.document_access_service = document_access_service or DocumentAccessService(db)

    def review(self, request: AgentQueryRequest) -> AgentQueryResponse:
        if request.document_id:
            self.document_access_service.require_document_access(
                document_id=request.document_id,
                workspace_id=request.workspace_id,
                user_id=request.user_id,
            )

        results = self.vector_search_service.search(
            VectorSearchCommand(
                workspace_id=request.workspace_id,
                user_id=request.user_id,
                query=f"{request.question} {QUALITY_CONTROL_QUERY}",
                limit=8,
            )
        )
        findings = detect_quality_control_findings(request.question, results)
        answer = build_quality_control_answer(findings, results)
        return AgentQueryResponse(
            answer=answer,
            sources_used=[source_from_result(result) for result in results],
            warnings=[
                AgentWarning(
                    code="quality_gate_not_final_approval",
                    message="Quality Control Agent перевіряє структуру і ризики відповіді, але не замінює рев'ю юриста.",
                ),
                AgentWarning(
                    code="source_alignment_required",
                    message="Кожне правове твердження потрібно звірити з конкретним джерелом або матеріалом справи.",
                ),
            ],
            confidence_score=confidence_from_findings(findings, results),
        )


def detect_quality_control_findings(
    draft_text: str,
    results: list[VectorSearchResult],
) -> list[QualityControlFinding]:
    normalized_draft = draft_text.lower()
    findings: list[QualityControlFinding] = []

    for category, (message, keywords) in QC_RULES.items():
        if not any(keyword in normalized_draft for keyword in keywords):
            findings.append(
                QualityControlFinding(
                    category=category,
                    message=message,
                    severity="medium",
                )
            )

    if any(phrase in normalized_draft for phrase in OVERCONFIDENT_PHRASES):
        findings.append(
            QualityControlFinding(
                category="Надмірна категоричність",
                message="Чернетка містить категоричні формулювання, які варто замінити на обережні та джерельно підтверджені.",
                severity="high",
            )
        )

    if not results:
        findings.append(
            QualityControlFinding(
                category="Відсутні релевантні фрагменти",
                message="Не знайдено workspace-фрагментів, з якими можна звірити чернетку.",
                severity="high",
            )
        )

    if not findings:
        findings.append(
            QualityControlFinding(
                category="Базова якість",
                message="Базові структурні ознаки присутні. Потрібна фінальна перевірка фактів, норм і практики юристом.",
                severity="low",
            )
        )

    return findings


def build_quality_control_answer(
    findings: list[QualityControlFinding],
    results: list[VectorSearchResult],
) -> str:
    high = [finding for finding in findings if finding.severity == "high"]
    medium = [finding for finding in findings if finding.severity == "medium"]
    low = [finding for finding in findings if finding.severity == "low"]
    source_lines = [
        f"- document_id={result.document_id}, chunk_index={result.chunk_index}, score={result.score:.3f}"
        for result in results[:5]
    ]
    return "\n".join(
        [
            "1. Quality Control висновок.",
            _readiness_line(findings),
            "",
            "2. Блокуючі зауваження.",
            _format_findings(high) if high else "- Блокуючих зауважень автоматично не виявлено.",
            "",
            "3. Зауваження до покращення.",
            _format_findings(medium) if medium else "- Середніх зауважень автоматично не виявлено.",
            "",
            "4. Фінальні перевірки перед відправкою.",
            _format_findings(low) if low else "- Звірити джерела, факти, строки, юрисдикцію та актуальність права.",
            "",
            "5. Рекомендована дія.",
            _recommended_action(findings),
            "",
            "Використані фрагменти:",
            "\n".join(source_lines) if source_lines else "- Немає релевантних фрагментів.",
        ]
    )


def source_from_result(result: VectorSearchResult) -> dict:
    return {
        "document_id": result.document_id,
        "chunk_id": result.chunk_id,
        "chunk_index": result.chunk_index,
        "workspace_id": result.workspace_id,
        "score": result.score,
    }


def confidence_from_findings(
    findings: list[QualityControlFinding],
    results: list[VectorSearchResult],
) -> float:
    if not results:
        return 0.0
    if any(finding.severity == "high" for finding in findings):
        return 0.45
    if any(finding.severity == "medium" for finding in findings):
        return 0.6
    return 0.72


def _readiness_line(findings: list[QualityControlFinding]) -> str:
    if any(finding.severity == "high" for finding in findings):
        return "Чернетка не готова до відправки без виправлення блокуючих зауважень."
    if any(finding.severity == "medium" for finding in findings):
        return "Чернетка потребує доопрацювання перед відправкою клієнту або використанням у workflow."
    return "Чернетка виглядає придатною для фінального людського рев'ю."


def _recommended_action(findings: list[QualityControlFinding]) -> str:
    if any(finding.severity == "high" for finding in findings):
        return "- Повернути чернетку на доопрацювання та додати джерела/обмеження."
    if any(finding.severity == "medium" for finding in findings):
        return "- Додати відсутні структурні блоки й повторити Quality Control перевірку."
    return "- Передати юристу на фінальне затвердження."


def _format_findings(findings: list[QualityControlFinding]) -> str:
    return "\n".join(
        f"- [{finding.category}] {finding.message}"
        for finding in findings
    )

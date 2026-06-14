from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.schemas.agent_schema import AgentQueryRequest, AgentQueryResponse, AgentWarning
from app.services.agent_context_service import AgentContextService, ClientContext
from app.services.document_access_service import DocumentAccessService
from app.services.vector_search_service import VectorSearchCommand, VectorSearchResult, VectorSearchService


CONTRACT_REVIEW_QUERY = (
    "договір предмет сторони повноваження ціна оплата строки приймання "
    "відповідальність штраф пеня форс-мажор конфіденційність персональні дані "
    "розірвання юрисдикція суперечності ризики"
)

RISK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Оплата": ("оплата", "аванс", "передплата", "післяплата", "ціна", "рахунок"),
    "Строки": ("строк", "термін", "календар", "простроч"),
    "Відповідальність": ("штраф", "пеня", "відповідальність", "збитки", "неустой"),
    "Приймання": ("акт", "приймання", "передача", "зауваження"),
    "Конфіденційність": ("конфіденц", "таємниц", "персональн"),
    "Розірвання": ("розірван", "припинен", "відмова"),
    "Форс-мажор": ("форс", "непереборн"),
    "Юрисдикція": ("суд", "спір", "підсуд", "арбітраж"),
}


@dataclass(frozen=True)
class ContractReviewFinding:
    category: str
    message: str
    severity: str


class ContractReviewAgent:
    def __init__(
        self,
        db: Session,
        vector_search_service: VectorSearchService | None = None,
        document_access_service: DocumentAccessService | None = None,
        agent_context_service: AgentContextService | None = None,
    ) -> None:
        self.db = db
        self.vector_search_service = vector_search_service or VectorSearchService(db)
        self.document_access_service = document_access_service or DocumentAccessService(db)
        self.agent_context_service = agent_context_service or AgentContextService(db)

    def review(self, request: AgentQueryRequest) -> AgentQueryResponse:
        if request.document_id:
            self.document_access_service.require_document_access(
                document_id=request.document_id,
                workspace_id=request.workspace_id,
                user_id=request.user_id,
            )

        client_context = self.agent_context_service.load_client_context(
            client_profile_id=request.client_profile_id,
            workspace_id=request.workspace_id,
            user_id=request.user_id,
        )
        query = with_client_context(request.question, client_context)
        results = self.vector_search_service.search(
            VectorSearchCommand(
                workspace_id=request.workspace_id,
                user_id=request.user_id,
                query=f"{query} {CONTRACT_REVIEW_QUERY}",
                limit=8,
            )
        )
        findings = detect_contract_findings(results)
        answer = build_contract_review_answer(findings, results, client_context)
        return AgentQueryResponse(
            answer=answer,
            sources_used=[source_from_result(result) for result in results],
            warnings=[
                AgentWarning(
                    code="human_review_required",
                    message="Це попередній аналіз договору. Фінальний висновок має перевірити юрист.",
                ),
                AgentWarning(
                    code="law_freshness_not_checked",
                    message="Актуальність законодавства та судової практики ще не перевірена.",
                ),
            ],
            confidence_score=confidence_from_results(results),
        )


def detect_contract_findings(results: list[VectorSearchResult]) -> list[ContractReviewFinding]:
    combined_text = " ".join(result.chunk_text.lower() for result in results)
    findings: list[ContractReviewFinding] = []
    for category, keywords in RISK_KEYWORDS.items():
        if any(keyword in combined_text for keyword in keywords):
            findings.append(
                ContractReviewFinding(
                    category=category,
                    severity="medium",
                    message=f"Перевірити блок '{category}' на повноту, баланс інтересів сторін і узгодженість з додатками.",
                )
            )

    if not findings:
        findings.append(
            ContractReviewFinding(
                category="Недостатньо даних",
                severity="low",
                message="У знайдених фрагментах не виявлено достатньо договірних умов для змістовного аналізу.",
            )
        )
    return findings


def build_contract_review_answer(
    findings: list[ContractReviewFinding],
    results: list[VectorSearchResult],
    client_context: ClientContext | None = None,
) -> str:
    critical_risks = [finding for finding in findings if finding.severity == "critical"]
    medium_risks = [finding for finding in findings if finding.severity == "medium"]
    low_risks = [finding for finding in findings if finding.severity == "low"]
    source_lines = [
        f"- document_id={result.document_id}, chunk_index={result.chunk_index}, score={result.score:.3f}"
        for result in results[:5]
    ]
    return "\n".join(
        [
            "1. Загальний висновок.",
            "Попередній аналіз виконано за знайденими фрагментами договору в межах поточного workspace.",
            "",
            "1.1. Контекст клієнта.",
            client_context.text if client_context else "- Профіль клієнта не передано.",
            "",
            "2. Критичні ризики.",
            _format_findings(critical_risks) if critical_risks else "- Критичних ризиків автоматично не виявлено.",
            "",
            "3. Середні ризики.",
            _format_findings(medium_risks) if medium_risks else "- Середні ризики автоматично не виявлено.",
            "",
            "4. Технічні / редакційні помилки.",
            _format_findings(low_risks) if low_risks else "- Потрібна ручна перевірка нумерації, реквізитів, дат і посилань.",
            "",
            "5. Суперечності між документами.",
            "- Порівняння з додатками, ТЗ, календарним планом і кошторисом потребує окремого зіставлення всіх файлів пакета.",
            "",
            "6. Рекомендовані правки.",
            "- Уточнити істотні умови, відповідальність, строки, порядок приймання і процедуру розірвання.",
            "- Додати або звірити положення щодо конфіденційності, персональних даних і форс-мажору.",
            "",
            "7. Готові формулювання для вставки в договір.",
            "- Формулювання слід генерувати після підтвердження конкретного ризику юристом і перевірки актуального права.",
            "",
            "Використані фрагменти:",
            "\n".join(source_lines) if source_lines else "- Немає релевантних фрагментів.",
        ]
    )


def with_client_context(question: str, client_context: ClientContext | None) -> str:
    if client_context is None:
        return question
    return f"{question}\n\nКонтекст клієнта:\n{client_context.text}"


def source_from_result(result: VectorSearchResult) -> dict:
    return {
        "document_id": result.document_id,
        "chunk_id": result.chunk_id,
        "chunk_index": result.chunk_index,
        "workspace_id": result.workspace_id,
        "score": result.score,
    }


def confidence_from_results(results: list[VectorSearchResult]) -> float:
    if not results:
        return 0.0
    best_score = max(result.score for result in results)
    return max(0.0, min(0.75, round(best_score, 2)))


def _format_findings(findings: list[ContractReviewFinding]) -> str:
    return "\n".join(
        f"- [{finding.category}] {finding.message}"
        for finding in findings
    )

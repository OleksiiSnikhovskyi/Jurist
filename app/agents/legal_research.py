from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.schemas.agent_schema import AgentQueryRequest, AgentQueryResponse, AgentWarning
from app.services.document_access_service import DocumentAccessService
from app.services.vector_search_service import VectorSearchCommand, VectorSearchResult, VectorSearchService


LEGAL_RESEARCH_QUERY = (
    "закон кодекс стаття правова позиція судова практика постанова висновок "
    "строк позовна давність юрисдикція підсудність докази процедура ризики "
    "цивільний господарський адміністративний кримінальний податковий"
)

LEGAL_ISSUE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Норма права": ("закон", "кодекс", "стаття", "норма", "положення"),
    "Судова практика": ("постанова", "суд", "верховн", "правова позиція", "практик"),
    "Строки": ("строк", "термін", "позовна давність", "простроч"),
    "Юрисдикція": ("юрисдикц", "підсуд", "господарськ", "адміністративн", "цивільн"),
    "Докази": ("доказ", "акт", "лист", "рахунок", "договір", "підтвердж"),
    "Процедура": ("заява", "скарга", "позов", "клопотан", "процедур"),
}


@dataclass(frozen=True)
class LegalResearchIssue:
    category: str
    message: str


class LegalResearchAgent:
    def __init__(
        self,
        db: Session,
        vector_search_service: VectorSearchService | None = None,
        document_access_service: DocumentAccessService | None = None,
    ) -> None:
        self.db = db
        self.vector_search_service = vector_search_service or VectorSearchService(db)
        self.document_access_service = document_access_service or DocumentAccessService(db)

    def research(self, request: AgentQueryRequest) -> AgentQueryResponse:
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
                query=f"{request.question} {LEGAL_RESEARCH_QUERY}",
                limit=10,
            )
        )
        issues = detect_legal_research_issues(results)
        answer = build_legal_research_answer(issues, results, request.question)
        return AgentQueryResponse(
            answer=answer,
            sources_used=[source_from_result(result) for result in results],
            warnings=[
                AgentWarning(
                    code="official_sources_required",
                    message="Перед використанням відповіді потрібно перевірити актуальні тексти законів і судову практику в офіційних джерелах.",
                ),
                AgentWarning(
                    code="not_final_legal_opinion",
                    message="Це попереднє правове дослідження, а не фінальний юридичний висновок.",
                ),
            ],
            confidence_score=confidence_from_results(results),
        )


def detect_legal_research_issues(results: list[VectorSearchResult]) -> list[LegalResearchIssue]:
    combined_text = " ".join(result.chunk_text.lower() for result in results)
    issues: list[LegalResearchIssue] = []
    for category, keywords in LEGAL_ISSUE_KEYWORDS.items():
        if any(keyword in combined_text for keyword in keywords):
            issues.append(
                LegalResearchIssue(
                    category=category,
                    message=f"Знайдені фрагменти містять ознаки теми '{category}'. Потрібно звірити релевантні норми, факти та практику.",
                )
            )

    if not issues:
        issues.append(
            LegalResearchIssue(
                category="Недостатньо даних",
                message="У поточному workspace не знайдено достатньо релевантних фрагментів для змістовного правового дослідження.",
            )
        )
    return issues


def build_legal_research_answer(
    issues: list[LegalResearchIssue],
    results: list[VectorSearchResult],
    question: str,
) -> str:
    source_lines = [
        f"- document_id={result.document_id}, chunk_index={result.chunk_index}, score={result.score:.3f}"
        for result in results[:6]
    ]
    context_lines = [
        f"- {result.chunk_text[:240].strip()}"
        for result in results[:3]
        if result.chunk_text.strip()
    ]
    return "\n".join(
        [
            "1. Попередня відповідь.",
            f"Запит: {question}",
            "Відповідь сформована лише за матеріалами поточного workspace і потребує перевірки актуального права.",
            "",
            "2. Релевантні факти з матеріалів.",
            "\n".join(context_lines) if context_lines else "- Немає релевантних фрагментів.",
            "",
            "3. Правові питання.",
            _format_issues(issues),
            "",
            "4. Що потрібно перевірити в офіційних джерелах.",
            "- Чинну редакцію законів, кодексів і підзаконних актів на дату відповіді.",
            "- Актуальну практику Верховного Суду та релевантних судів за схожими обставинами.",
            "- Процесуальні строки, юрисдикцію, підсудність і вимоги до доказів.",
            "",
            "5. Наступні кроки.",
            "- Уточнити факти, яких бракує для правової кваліфікації.",
            "- Після перевірки джерел підготувати короткий юридичний висновок або процесуальний документ.",
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


def confidence_from_results(results: list[VectorSearchResult]) -> float:
    if not results:
        return 0.0
    best_score = max(result.score for result in results)
    return max(0.0, min(0.7, round(best_score, 2)))


def _format_issues(issues: list[LegalResearchIssue]) -> str:
    return "\n".join(
        f"- [{issue.category}] {issue.message}"
        for issue in issues
    )

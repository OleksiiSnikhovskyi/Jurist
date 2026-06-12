from app.schemas.agent_schema import AgentQueryRequest, AgentQueryResponse, AgentWarning


class LegalPlatformOrchestrator:
    """Routes legal tasks while preserving workspace isolation."""

    def answer(self, request: AgentQueryRequest) -> AgentQueryResponse:
        return AgentQueryResponse(
            answer=(
                "Запит прийнято до юридичного аналізу. "
                "MVP-каркас не формує юридичний висновок без перевірених джерел."
            ),
            warnings=[
                AgentWarning(
                    code="sources_not_checked",
                    message="Актуальність нормативних джерел ще не перевірена.",
                )
            ],
            confidence_score=0.0,
        )


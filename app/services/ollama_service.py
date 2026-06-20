import json
from dataclasses import dataclass, field
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.config import Settings, get_settings


class OllamaNotConfiguredError(Exception):
    pass


class OllamaRequestError(Exception):
    pass


@dataclass(frozen=True)
class SourceFragment:
    document_id: str
    chunk_index: int
    score: float
    text: str


@dataclass(frozen=True)
class LegalPackageAnalysisCommand:
    question: str
    package_text: str
    lawyer_system_prompt: str
    client_context: str | None = None
    source_fragments: list[SourceFragment] = field(default_factory=list)
    attachment_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LegalPackageAnalysisResult:
    answer: str
    model: str


class OllamaLegalAnalysisService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def is_configured(self) -> bool:
        return bool(self.settings.jur_ollama_base_url)

    def analyze_package(self, command: LegalPackageAnalysisCommand) -> LegalPackageAnalysisResult:
        if not self.settings.jur_ollama_base_url:
            raise OllamaNotConfiguredError("JUR_OLLAMA_BASE_URL is not configured")

        payload = {
            "model": self.settings.jur_ollama_model,
            "stream": False,
            "options": {
                "num_ctx": self.settings.jur_ollama_num_ctx,
                "num_predict": self.settings.jur_ollama_num_predict,
            },
            "messages": [
                {
                    "role": "system",
                    "content": build_system_prompt(command.lawyer_system_prompt),
                },
                {
                    "role": "user",
                    "content": build_user_prompt(command),
                },
            ],
        }
        response = self._post_json("/api/chat", payload)
        answer = extract_ollama_answer(response)
        return LegalPackageAnalysisResult(answer=answer, model=self.settings.jur_ollama_model)

    def _post_json(self, path: str, payload: dict) -> dict:
        base_url = self.settings.jur_ollama_base_url.rstrip("/")
        request = Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.jur_ollama_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise OllamaRequestError(str(exc)) from exc


def build_system_prompt(lawyer_system_prompt: str) -> str:
    return "\n".join(
        [
            lawyer_system_prompt.strip(),
            "",
            "Ти юридичний асистент для українського юриста.",
            "Відповідай українською мовою.",
            "Не вигадуй реквізити нормативних актів або судових рішень.",
            "Якщо джерел або тексту недостатньо, прямо вкажи, що потрібно перевірити.",
            "Факти з матеріалів пакета мають пріоритет над фрагментами бази знань.",
            "Не припускай державні закупівлі, державне майно, фінансовий лізинг, воєнний стан "
            "або спеціальний статус сторони, якщо це прямо не випливає з тексту документа чи профілю клієнта.",
            "Використовуй фрагменти бази знань тільки коли вони прямо релевантні встановленим фактам документа; "
            "нерелевантні фрагменти ігноруй і не згадуй у висновку.",
            "Відокремлюй факти, правову оцінку, ризики і рекомендовані наступні кроки.",
        ]
    )


def build_user_prompt(command: LegalPackageAnalysisCommand) -> str:
    source_lines = [
        (
            f"[{index}] document_id={fragment.document_id}, "
            f"chunk={fragment.chunk_index}, score={fragment.score:.3f}\n{fragment.text}"
        )
        for index, fragment in enumerate(command.source_fragments, start=1)
    ]
    attachment_lines = command.attachment_notes or ["- Немає вкладень без витягнутого тексту."]
    return "\n\n".join(
        [
            f"Запит юриста:\n{command.question.strip()}",
            (
                f"Контекст клієнта:\n{command.client_context.strip()}"
                if command.client_context
                else "Контекст клієнта: не обрано."
            ),
            f"Матеріали пакета:\n{command.package_text.strip()}",
            "Вкладення без текстового витягу:\n" + "\n".join(attachment_lines),
            "Релевантні фрагменти бази знань:\n"
            + ("\n\n".join(source_lines) if source_lines else "- Релевантні фрагменти не знайдено."),
            (
                "Підготуй відповідь у структурі:\n"
                "1. Короткий висновок.\n"
                "2. Факти, які враховано: сторони, їх правовий статус, предмет договору, ціна, строки, ключові обов'язки.\n"
                "3. Правова оцінка з посиланням на надані фрагменти тільки якщо вони прямо релевантні фактам документа.\n"
                "4. Ризики і слабкі місця.\n"
                "5. Що потрібно додатково перевірити в офіційних джерелах.\n"
                "6. Наступні дії для юриста."
                "\n\nПеред оцінкою спочатку визнач тип правовідносин лише з тексту документа. "
                "Якщо сторони є приватними/комерційними суб'єктами і в документі немає ознак державного замовника, "
                "не аналізуй державні закупівлі або державне майно."
            ),
        ]
    )


def extract_ollama_answer(response: dict) -> str:
    message = response.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"].strip()
    if isinstance(response.get("response"), str):
        return response["response"].strip()
    raise OllamaRequestError("Ollama response did not contain an answer")

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
    response_mode: str = "legal_analysis"


@dataclass(frozen=True)
class LegalPackageAnalysisResult:
    answer: str
    model: str


class OllamaLegalAnalysisService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def is_configured(self) -> bool:
        return bool(self.settings.jur_ollama_base_url) or self.is_openai_fallback_configured()

    def is_openai_fallback_configured(self) -> bool:
        return bool(self.settings.jur_openai_fallback_enabled and self._openai_api_key())

    def analyze_package(self, command: LegalPackageAnalysisCommand) -> LegalPackageAnalysisResult:
        if self.settings.jur_ollama_base_url:
            try:
                return self._analyze_with_ollama(command)
            except OllamaRequestError as exc:
                if not self.is_openai_fallback_configured():
                    raise
                try:
                    return self._analyze_with_openai_fallback(command)
                except OllamaRequestError as fallback_exc:
                    raise OllamaRequestError(
                        f"Ollama request failed: {exc}; OpenAI fallback failed: {fallback_exc}"
                    ) from fallback_exc

        if self.is_openai_fallback_configured():
            return self._analyze_with_openai_fallback(command)

        raise OllamaNotConfiguredError(
            "Neither JUR_OLLAMA_BASE_URL nor OpenAI fallback credentials are configured"
        )

    def _analyze_with_ollama(self, command: LegalPackageAnalysisCommand) -> LegalPackageAnalysisResult:
        payload = {
            "model": self.settings.jur_ollama_model,
            "stream": False,
            "think": self.settings.jur_ollama_think,
            "options": {
                "num_ctx": self.settings.jur_ollama_num_ctx,
                "num_predict": self.settings.jur_ollama_num_predict,
            },
            "messages": self._messages_for_command(command),
        }
        response = self._post_json("/api/chat", payload)
        answer = extract_ollama_answer(response)
        return LegalPackageAnalysisResult(answer=answer, model=self.settings.jur_ollama_model)

    def _analyze_with_openai_fallback(
        self,
        command: LegalPackageAnalysisCommand,
    ) -> LegalPackageAnalysisResult:
        payload = {
            "model": self.settings.jur_openai_fallback_model,
            "messages": self._messages_for_command(command),
            "temperature": 0.2,
            "max_tokens": self.settings.jur_openai_fallback_max_tokens,
        }
        response = self._post_openai_json("/chat/completions", payload)
        answer = extract_openai_chat_answer(response)
        return LegalPackageAnalysisResult(
            answer=answer,
            model=f"{self.settings.jur_openai_fallback_model} (openai-fallback)",
        )

    def _messages_for_command(self, command: LegalPackageAnalysisCommand) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": build_system_prompt(command.lawyer_system_prompt),
            },
            {
                "role": "user",
                "content": build_user_prompt(command),
            },
        ]

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

    def _post_openai_json(self, path: str, payload: dict) -> dict:
        api_key = self._openai_api_key()
        if not api_key:
            raise OllamaRequestError("OpenAI fallback API key is not configured")
        base_url = self.settings.jur_openai_fallback_base_url.rstrip("/")
        request = Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.jur_openai_fallback_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise OllamaRequestError(str(exc)) from exc

    def _openai_api_key(self) -> str | None:
        return self.settings.jur_openai_api_key or self.settings.openai_api_key


def build_system_prompt(lawyer_system_prompt: str) -> str:
    return "\n".join(
        [
            lawyer_system_prompt.strip(),
            "",
            "Ти юридичний асистент для українського юриста.",
            "Відповідай українською мовою.",
            "Не вигадуй реквізити нормативних актів або судових рішень.",
            "Не вказуй номери статей, пунктів, справ або реквізити актів з пам'яті. "
            "Точні реквізити можна наводити тільки якщо вони є в тексті документа або в релевантному фрагменті бази знань.",
            "Якщо джерел або тексту недостатньо, прямо вкажи, що потрібно перевірити.",
            "Факти з матеріалів пакета мають пріоритет над фрагментами бази знань.",
            "Не припускай державні закупівлі, державне майно, фінансовий лізинг, воєнний стан "
            "або спеціальний статус сторони, якщо це прямо не випливає з тексту документа чи профілю клієнта.",
            "Не згадуй відсутні в документі теми навіть у формі 'не застосовується', якщо користувач прямо не просив "
            "перевірити саме цю тему.",
            "Використовуй фрагменти бази знань тільки коли вони прямо релевантні встановленим фактам документа; "
            "нерелевантні фрагменти ігноруй і не згадуй у висновку.",
            "Відокремлюй факти, правову оцінку, ризики і рекомендовані наступні кроки.",
        ]
    )


def build_user_prompt(command: LegalPackageAnalysisCommand) -> str:
    if command.response_mode == "contract_clause_drafting":
        return build_contract_clause_drafting_prompt(command)
    return build_legal_analysis_prompt(command)


def _source_lines(command: LegalPackageAnalysisCommand) -> list[str]:
    return [
        (
            f"[{index}] document_id={fragment.document_id}, "
            f"chunk={fragment.chunk_index}, score={fragment.score:.3f}\n{fragment.text}"
        )
        for index, fragment in enumerate(command.source_fragments, start=1)
    ]


def _common_prompt_sections(command: LegalPackageAnalysisCommand) -> list[str]:
    source_lines = _source_lines(command)
    attachment_lines = command.attachment_notes or ["- Немає вкладень без витягнутого тексту."]
    return [
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
    ]


def build_legal_analysis_prompt(command: LegalPackageAnalysisCommand) -> str:
    return "\n\n".join(
        _common_prompt_sections(command)
        + [
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
                "не аналізуй і не згадуй державні закупівлі або державне майно. "
                "Якщо запит просить конкретну санкцію, суму, строк, дедлайн або інший числовий результат, "
                "дай пряму відповідь у першому реченні: сума/строк/умова застосування. "
                "Не відповідай розмито словами 'може варіюватися', якщо наданий фрагмент містить фіксовану санкцію. "
                "Якщо санкція залежить від повторності або статусу особи, дай коротку таблицю варіантів. "
                "Якщо релевантні фрагменти бази знань не знайдено, не наводь точні номери статей або реквізити з пам'яті; "
                "сформулюй правову оцінку загально і вкажи, які норми потрібно перевірити."
            ),
        ]
    )


def build_contract_clause_drafting_prompt(command: LegalPackageAnalysisCommand) -> str:
    return "\n\n".join(
        _common_prompt_sections(command)
        + [
            (
                "Підготуй практичну відповідь у режимі contract clause drafting / redline recommendations. "
                "Головна задача: дати юристу готові пункти договору, які можна вставити в документ з дотриманням "
                "існуючої нумерації.\n\n"
                "Формат відповіді:\n"
                "1. Короткий висновок\n"
                "Коротко перелічити, які блоки рекомендовано додати або уточнити.\n\n"
                "2. Як вставити в існуючу нумерацію\n"
                "Обов'язково дай markdown-таблицю з точними заголовками:\n"
                "| Куди вставити | Новий пункт | Мета |\n"
                "|---|---:|---|\n"
                "Якщо точна нумерація не очевидна з тексту, напиши: "
                "'Пропоную вставити після розділу/пункту X; якщо у вашій редакції інша нумерація, "
                "перенумеруйте відповідно'.\n\n"
                "3. Готові формулювання пунктів\n"
                "Дай готові редакції пунктів у форматі:\n"
                "**Пункт X.Y. Назва пункту**\n"
                "\"Текст пункту договору...\"\n\n"
                "4. Таблиця ризиків\n"
                "Обов'язково дай markdown-таблицю з точними заголовками:\n"
                "| Проблема в договорі | Ризик для клієнта | Як запропонований пункт це вирішує |\n"
                "|---|---|---|\n\n"
                "5. Що додатково перевірити\n"
                "Стислий список перевірок тільки за темами, які випливають з договору.\n\n"
                "6. Примітка щодо джерел\n"
                "Напиши, що джерела використовуються як допоміжний контекст і потребують перевірки за офіційним джерелом, "
                "якщо точні реквізити не наведені в матеріалах.\n\n"
                "Обмеження:\n"
                "- Не використовуй стандартний формат правового висновку з розділами 'Правова оцінка' та 'Наступні дії'.\n"
                "- Не давай загальні поради без готових формулювань пунктів.\n"
                "- Перед кожною пропозицією перевір, чи вже є схоже регулювання в договорі; якщо є, запропонуй "
                "редакцію існуючого пункту замість нового пункту.\n"
                "- Не дублюй однакові положення в різних розділах: об'єднуй повтори в один пункт або пояснюй, "
                "який існуючий пункт треба замінити/уточнити.\n"
                "- Нумерацію пропонуй тільки з урахуванням змісту відповідного розділу. Якщо назва або логіка розділу "
                "не очевидна, пиши 'орієнтовно після пункту X' і зазначай, що структуру договору потрібно перевірити.\n"
                "- Не формулюй категоричні обов'язки на кшталт 'Виконавець зобов'язаний завантажити до ЄДЕССБ', "
                "якщо такий обов'язок прямо не випливає з договору або наданого офіційного джерела; у таких випадках "
                "пиши умовно: 'якщо цей обов'язок покладено на Виконавця / якщо це необхідно для цілей договору'.\n"
                "- Для кожного запропонованого пункту коротко поясни, з якого положення договору або факту випливає його релевантність.\n"
                "- Не використовуй технічні посилання 'фрагмент 1', 'фрагмент 2' у фінальній відповіді; "
                "називай документ людською мовою або пиши 'потребує перевірки за офіційним джерелом'.\n"
                "- Не залишай порожні numbered items на кшталт '2.'.\n"
                "- Не повторюй одну й ту саму рекомендацію більше одного разу.\n"
                "- Не припускай державні закупівлі, державне майно, фінансовий лізинг або спеціальний статус сторони, "
                "якщо це прямо не випливає з тексту договору чи профілю клієнта."
            ),
        ]
    )


def extract_openai_chat_answer(response: dict) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"].strip()
    raise OllamaRequestError("OpenAI fallback response did not contain an answer")

def extract_ollama_answer(response: dict) -> str:
    message = response.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"].strip()
    if isinstance(response.get("response"), str):
        return response["response"].strip()
    raise OllamaRequestError("Ollama response did not contain an answer")

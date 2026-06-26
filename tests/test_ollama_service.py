from app.config import Settings
from app.services.ollama_service import (
    LegalPackageAnalysisCommand,
    OllamaLegalAnalysisService,
    build_system_prompt,
    build_user_prompt,
)


def test_ollama_prompt_prioritizes_document_facts_over_irrelevant_sources() -> None:
    system_prompt = build_system_prompt("Працюй як договірний юрист.")
    user_prompt = build_user_prompt(
        LegalPackageAnalysisCommand(
            question="Проаналізуй договір.",
            package_text="ПрАТ Л-КАПІТАЛ уклало договір з ФОП про надання консультаційних послуг.",
            lawyer_system_prompt="Працюй як договірний юрист.",
        )
    )

    assert "Факти з матеріалів пакета мають пріоритет" in system_prompt
    assert "Не припускай державні закупівлі" in system_prompt
    assert "Не вказуй номери статей" in system_prompt
    assert "Не згадуй відсутні в документі теми" in system_prompt
    assert "якщо сторони є приватними/комерційними суб'єктами" in user_prompt.lower()
    assert "не аналізуй і не згадуй державні закупівлі" in user_prompt.lower()


def test_ollama_payload_disables_qwen_thinking_for_telegram_answers() -> None:
    class CaptureService(OllamaLegalAnalysisService):
        def _post_json(self, path: str, payload: dict) -> dict:
            self.path = path
            self.payload = payload
            return {"message": {"content": "Готово."}}

    service = CaptureService(
        Settings(
            jur_ollama_base_url="http://ollama:11434",
            jur_ollama_model="qwen3:8b",
            jur_ollama_think=False,
            jur_ollama_num_ctx=16384,
            jur_ollama_num_predict=3072,
        )
    )

    result = service.analyze_package(
        LegalPackageAnalysisCommand(
            question="Проаналізуй договір.",
            package_text="Договір між двома комерційними компаніями.",
            lawyer_system_prompt="Працюй як договірний юрист.",
        )
    )

    assert result.answer == "Готово."
    assert service.path == "/api/chat"
    assert service.payload["model"] == "qwen3:8b"
    assert service.payload["think"] is False
    assert service.payload["options"]["num_ctx"] == 16384
    assert service.payload["options"]["num_predict"] == 3072


def test_clause_drafting_prompt_uses_practical_contract_format() -> None:
    user_prompt = build_user_prompt(
        LegalPackageAnalysisCommand(
            question="Які би ти додав пункти до договору з дотриманням існуючої нумерації?",
            package_text="Договір між Замовником і Виконавцем про надання консультаційних послуг.",
            lawyer_system_prompt="Працюй як договірний юрист.",
            response_mode="contract_clause_drafting",
        )
    )

    assert "contract clause drafting" in user_prompt
    assert "| Куди вставити | Новий пункт | Мета |" in user_prompt
    assert "Готові формулювання пунктів" in user_prompt
    assert "| Проблема в договорі | Ризик для клієнта | Як запропонований пункт це вирішує |" in user_prompt
    assert "Не використовуй технічні посилання 'фрагмент 1'" in user_prompt
    assert "Підготуй відповідь у структурі" not in user_prompt


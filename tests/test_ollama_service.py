import pytest

from app.config import Settings
from app.services.ollama_service import (
    LegalPackageAnalysisCommand,
    OllamaRequestError,
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


def test_ollama_service_falls_back_to_openai_when_ollama_fails() -> None:
    class FallbackService(OllamaLegalAnalysisService):
        def _post_json(self, path: str, payload: dict) -> dict:
            self.ollama_path = path
            self.ollama_payload = payload
            raise OllamaRequestError("timed out")

        def _post_openai_json(self, path: str, payload: dict) -> dict:
            self.openai_path = path
            self.openai_payload = payload
            return {"choices": [{"message": {"content": "Fallback answer."}}]}

    service = FallbackService(
        Settings(
            jur_ollama_base_url="http://miledy:11434",
            jur_ollama_model="qwen3:8b",
            jur_openai_api_key="test-key",
            jur_openai_fallback_enabled=True,
            jur_openai_fallback_model="gpt-4o-mini",
        )
    )

    result = service.analyze_package(
        LegalPackageAnalysisCommand(
            question="Проаналізуй договір.",
            package_text="Договір між двома комерційними компаніями.",
            lawyer_system_prompt="Працюй як договірний юрист.",
        )
    )

    assert result.answer == "Fallback answer."
    assert result.model == "gpt-4o-mini (openai-fallback)"
    assert service.ollama_path == "/api/chat"
    assert service.ollama_payload["model"] == "qwen3:8b"
    assert service.openai_path == "/chat/completions"
    assert service.openai_payload["model"] == "gpt-4o-mini"
    assert service.openai_payload["messages"][0]["role"] == "system"


def test_ollama_service_reraises_ollama_error_without_openai_key() -> None:
    class FailingService(OllamaLegalAnalysisService):
        def _post_json(self, path: str, payload: dict) -> dict:
            raise OllamaRequestError("timed out")

    service = FailingService(
        Settings(
            jur_ollama_base_url="http://miledy:11434",
            jur_ollama_model="qwen3:8b",
            jur_openai_fallback_enabled=True,
            jur_openai_api_key=None,
            openai_api_key=None,
        )
    )

    with pytest.raises(OllamaRequestError, match="timed out"):
        service.analyze_package(
            LegalPackageAnalysisCommand(
                question="Проаналізуй договір.",
                package_text="Договір між двома комерційними компаніями.",
                lawyer_system_prompt="Працюй як договірний юрист.",
            )
        )


def test_openai_fallback_requires_explicit_enable_flag() -> None:
    service = OllamaLegalAnalysisService(
        Settings(
            jur_ollama_base_url=None,
            jur_openai_api_key="test-key",
            jur_openai_fallback_enabled=False,
        )
    )

    assert service.is_configured() is False

def test_openai_fallback_can_be_primary_when_ollama_is_not_configured() -> None:
    class FallbackOnlyService(OllamaLegalAnalysisService):
        def _post_openai_json(self, path: str, payload: dict) -> dict:
            self.openai_path = path
            self.openai_payload = payload
            return {"choices": [{"message": {"content": "Fallback only."}}]}

    service = FallbackOnlyService(
        Settings(
            jur_ollama_base_url=None,
            jur_openai_api_key="test-key",
            jur_openai_fallback_enabled=True,
            jur_openai_fallback_model="gpt-4o-mini",
        )
    )

    assert service.is_configured() is True

    result = service.analyze_package(
        LegalPackageAnalysisCommand(
            question="Проаналізуй договір.",
            package_text="Договір між двома комерційними компаніями.",
            lawyer_system_prompt="Працюй як договірний юрист.",
        )
    )

    assert result.answer == "Fallback only."
    assert result.model == "gpt-4o-mini (openai-fallback)"
    assert service.openai_path == "/chat/completions"


def test_legal_analysis_prompt_requires_direct_numeric_sanction_answer() -> None:
    user_prompt = build_user_prompt(
        LegalPackageAnalysisCommand(
            question="який передбачено штраф і позбавлення прав?",
            package_text="Особа керувала мотоблоком у стані алкогольного сп'яніння.",
            lawyer_system_prompt="Працюй як юрист.",
        )
    )

    assert "дай пряму відповідь у першому реченні" in user_prompt
    assert "може варіюватися" in user_prompt
    assert "коротку таблицю варіантів" in user_prompt

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
    assert "якщо є, запропонуй редакцію існуючого пункту" in user_prompt
    assert "Не дублюй однакові положення" in user_prompt
    assert "Нумерацію пропонуй тільки з урахуванням змісту відповідного розділу" in user_prompt
    assert "не формулюй категоричні обов'язки" in user_prompt.lower()
    assert "Підготуй відповідь у структурі" not in user_prompt

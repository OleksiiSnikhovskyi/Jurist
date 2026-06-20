from app.services.ollama_service import LegalPackageAnalysisCommand, build_system_prompt, build_user_prompt


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

import json
from pathlib import Path


WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "n8n" / "workflows"


def test_n8n_workflow_templates_are_valid_json() -> None:
    workflow_files = sorted(WORKFLOW_DIR.glob("JUR_*.json"))

    assert workflow_files
    for workflow_file in workflow_files:
        workflow = json.loads(workflow_file.read_text(encoding="utf-8"))
        assert workflow["name"].startswith("JUR_")
        assert workflow_file.stem == workflow["name"]
        assert workflow["active"] is False
        assert workflow["settings"]["executionOrder"] == "v1"
        assert workflow["nodes"]
        assert workflow["connections"]


def test_telegram_intake_template_has_required_actions() -> None:
    workflow = json.loads((WORKFLOW_DIR / "JUR_Bot_Intake_Queue.json").read_text(encoding="utf-8"))
    workflow_text = json.dumps(workflow, ensure_ascii=False)

    for button_text in [
        "Додати фото або документ",
        "Додати голосове повідомлення",
        "Показати додані матеріали",
        "Почати обробку",
        "Статус обробки",
        "Очистити пакет",
        "Змінити системний промпт",
        "Клієнти",
        "Створити профіль клієнта",
        "Обрати клієнта",
        "Показати активного клієнта",
        "Змінити профіль клієнта",
        "Назад",
    ]:
        assert button_text in workflow_text


def test_obsidian_template_uses_batch_processing() -> None:
    workflow = json.loads((WORKFLOW_DIR / "JUR_Obsidian_Vault_Sync.json").read_text(encoding="utf-8"))
    node_types = {node["type"] for node in workflow["nodes"]}

    assert "n8n-nodes-base.webhook" in node_types
    assert "n8n-nodes-base.splitInBatches" in node_types
    assert "n8n-nodes-base.httpRequest" in node_types

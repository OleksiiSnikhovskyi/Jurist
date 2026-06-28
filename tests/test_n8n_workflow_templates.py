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
        "Пакетна обробка",
        "Додати фото або документ",
        "Додати голосове повідомлення",
        "Показати додані матеріали",
        "Почати обробку",
        "Статус обробки",
        "Очистити пакет",
        "Змінити системний промпт",
        "Клієнти",
        "Новий клієнт",
        "Створити профіль клієнта",
        "Обрати клієнта",
        "Показати активного клієнта",
        "Налаштування клієнта",
        "Змінити профіль клієнта",
        "Видалити клієнта",
        "Назад",
    ]:
        assert button_text in workflow_text
    assert "batch_processing_menu" in workflow_text
    assert "Telegram Batch Menu Reply" in workflow_text
    assert "Build Auto Process Request" in workflow_text
    assert "Process Auto Extracted Package" in workflow_text
    assert "Build Auto Analysis Reply" in workflow_text
    assert "Telegram Auto Analysis Reply" in workflow_text

    node_timeouts = {
        node["name"]: node.get("parameters", {}).get("options", {}).get("timeout")
        for node in workflow["nodes"]
    }
    assert node_timeouts["Send Intake Event To API"] == 900000
    assert node_timeouts["Process Auto Extracted Package"] == 900000


def test_obsidian_template_uses_batch_processing() -> None:
    workflow = json.loads((WORKFLOW_DIR / "JUR_Obsidian_Vault_Sync.json").read_text(encoding="utf-8"))
    workflow_text = json.dumps(workflow, ensure_ascii=False)
    node_types = {node["type"] for node in workflow["nodes"]}

    assert "n8n-nodes-base.webhook" in node_types
    assert "n8n-nodes-base.splitInBatches" in node_types
    assert "n8n-nodes-base.httpRequest" in node_types
    assert "parseFrontmatter" in workflow_text
    assert "frontmatter.aliases" in workflow_text
    assert "legal_source_aliases" in workflow_text
    assert "document_number" in workflow_text
    assert "source_url" in workflow_text

def test_rada_qwen_template_syncs_official_sources_through_api() -> None:
    workflow = json.loads((WORKFLOW_DIR / "JUR_Rada_Law_Sync_Qwen.json").read_text(encoding="utf-8"))
    workflow_text = json.dumps(workflow, ensure_ascii=False)
    node_types = {node["type"] for node in workflow["nodes"]}

    assert "n8n-nodes-base.scheduleTrigger" in node_types
    assert "n8n-nodes-base.splitInBatches" in node_types
    assert "n8n-nodes-base.code" in node_types
    assert "https://zakon.rada.gov.ua/laws/main/nn" in workflow_text
    assert "qwen3:8" in workflow_text
    assert "/api/chat" in workflow_text
    assert "/n8n/legal-sources/upsert" in workflow_text
    assert "JUR_RADA_SYNC_LIMIT" in workflow_text
    assert "JUR_RADA_SYNC_LIMIT || 3" in workflow_text
    assert "function validityStatus" in workflow_text
    assert "validity_status: validityStatus(details)" in workflow_text
    assert "validity_status: 'current'" not in workflow_text
    assert "new URL(" not in workflow_text
    assert "$helpers" not in workflow_text
    assert "source_type: source.source_type" in workflow_text

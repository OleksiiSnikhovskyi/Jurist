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


def test_jurist_api_http_nodes_send_n8n_api_key_header() -> None:
    workflow_files = sorted(WORKFLOW_DIR.glob("JUR_*.json"))

    checked_nodes = 0
    for workflow_file in workflow_files:
        workflow = json.loads(workflow_file.read_text(encoding="utf-8"))
        for node in workflow["nodes"]:
            parameters = node.get("parameters", {})
            if node.get("type") != "n8n-nodes-base.httpRequest":
                continue
            if "JUR_API_BASE_URL" not in str(parameters.get("url", "")):
                continue
            checked_nodes += 1
            assert parameters.get("sendHeaders") is True, node["name"]
            assert parameters.get("specifyHeaders") == "json", node["name"]
            assert "X-JUR-N8N-API-KEY" in parameters.get("jsonHeaders", ""), node["name"]
            assert "JUR_N8N_API_KEY" in parameters.get("jsonHeaders", ""), node["name"]

    assert checked_nodes > 0


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
    workflow = json.loads(
        (WORKFLOW_DIR / "JUR_Obsidian_Vault_Sync.json").read_text(encoding="utf-8")
    )
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
    workflow = json.loads(
        (WORKFLOW_DIR / "JUR_Rada_Law_Sync_Qwen.json").read_text(encoding="utf-8")
    )
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
    assert "JUR_RADA_FETCH_RELAY_URL" in workflow_text
    assert "X-JUR-RADA-FETCH-TOKEN" in workflow_text
    assert "function validityStatus" in workflow_text
    assert "validity_status: validityStatus(details)" in workflow_text
    assert "effective_date" in workflow_text
    assert "revision_date" in workflow_text
    assert "validity_note" in workflow_text
    assert "Reembed Missing Chunks" in workflow_text
    assert "/n8n/maintenance/reembed-missing-chunks" in workflow_text
    assert "validity_status: 'current'" not in workflow_text
    assert "new URL(" not in workflow_text
    assert "$helpers" not in workflow_text
    assert "source_type: source.source_type" in workflow_text


def test_official_source_verification_template_uses_api_and_official_domains() -> None:
    workflow = json.loads(
        (WORKFLOW_DIR / "JUR_Official_Source_Verification.json").read_text(encoding="utf-8")
    )
    workflow_text = json.dumps(workflow, ensure_ascii=False)
    node_types = {node["type"] for node in workflow["nodes"]}

    assert "n8n-nodes-base.scheduleTrigger" in node_types
    assert "n8n-nodes-base.httpRequest" in node_types
    assert "n8n-nodes-base.splitInBatches" in node_types
    assert "/n8n/legal-sources/verification-candidates" in workflow_text
    assert "/n8n/legal-sources/verify-official-sources" in workflow_text
    assert "JUR_OFFICIAL_SOURCE_VERIFY_LIMIT" in workflow_text
    assert "JUR_Official_Source_Verification" in workflow_text
    assert "new URL(" not in workflow_text
    assert "$helpers" not in workflow_text


def test_controlled_official_source_search_template_uses_plan_endpoint() -> None:
    workflow = json.loads(
        (WORKFLOW_DIR / "JUR_Controlled_Official_Source_Search.json").read_text(encoding="utf-8")
    )
    workflow_text = json.dumps(workflow, ensure_ascii=False)
    node_types = {node["type"] for node in workflow["nodes"]}

    assert "n8n-nodes-base.manualTrigger" in node_types
    assert "n8n-nodes-base.code" in node_types
    assert "n8n-nodes-base.httpRequest" in node_types
    assert "n8n-nodes-base.if" in node_types
    assert "/n8n/official-source-search/plan" in workflow_text
    assert "low_rag_confidence" in workflow_text
    assert "candidate_urls" in workflow_text
    assert "search_allowed" in workflow_text


def test_legal_opinion_export_template_uses_export_endpoint() -> None:
    workflow = json.loads(
        (WORKFLOW_DIR / "JUR_Legal_Opinion_Export.json").read_text(encoding="utf-8")
    )
    workflow_text = json.dumps(workflow, ensure_ascii=False)
    node_types = {node["type"] for node in workflow["nodes"]}

    assert "n8n-nodes-base.manualTrigger" in node_types
    assert "n8n-nodes-base.code" in node_types
    assert "n8n-nodes-base.httpRequest" in node_types
    assert "/legal-opinions/" in workflow_text
    assert "/export" in workflow_text
    assert "export_format" in workflow_text
    assert "JUR_EXPORT_LEGAL_OPINION_ID" in workflow_text

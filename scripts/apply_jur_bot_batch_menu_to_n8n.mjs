const baseUrl = process.env.N8N_BASE_URL || "https://n8n.csc-ua.tech";
const workflowId = process.env.N8N_WORKFLOW_ID || "nWAfwIrKQt1kBgnJ";
const apiKey = process.env.N8N_API_KEY;

if (!apiKey) {
  throw new Error("N8N_API_KEY is required");
}

const headers = {
  "Content-Type": "application/json",
  "X-N8N-API-KEY": apiKey,
};

const findNode = (workflow, name) => workflow.nodes.find((node) => node.name === name);

function applyBatchMenu(workflow) {
  const normalizeNode = findNode(workflow, "Normalize Telegram Update");
  if (!normalizeNode) {
    throw new Error("Normalize Telegram Update node not found");
  }
  if (!normalizeNode.parameters.jsCode.includes("'Пакетна обробка': 'batch_processing_menu'")) {
    normalizeNode.parameters.jsCode = normalizeNode.parameters.jsCode.replace(
      "const actionMap = {\n",
      "const actionMap = {\n  'Пакетна обробка': 'batch_processing_menu',\n",
    );
  }

  const mainReplyNode = findNode(workflow, "Telegram Intake Reply");
  if (!mainReplyNode) {
    throw new Error("Telegram Intake Reply node not found");
  }
  mainReplyNode.parameters.text = "={{$json.reply_text || 'Головне меню.'}}";
  mainReplyNode.parameters.replyKeyboard.rows = [
    {
      row: {
        buttons: [{ text: "Пакетна обробка" }, { text: "Клієнти" }],
      },
    },
    {
      row: {
        buttons: [{ text: "Змінити системний промпт" }],
      },
    },
  ];

  for (const nodeName of [
    "Send Intake Event To API",
    "Attach Document Extracted Text To API",
    "Attach Voice Extracted Text To API",
    "Process Auto Extracted Package",
  ]) {
    const httpNode = findNode(workflow, nodeName);
    if (httpNode) {
      httpNode.parameters.options = {
        ...(httpNode.parameters.options || {}),
        timeout: nodeName === "Process Auto Extracted Package" ? 900000 : 300000,
      };
    }
  }

  const prepareDocumentParseNode = findNode(workflow, "Prepare Document Parse Payload");
  if (!prepareDocumentParseNode) {
    throw new Error("Prepare Document Parse Payload node not found");
  }
  prepareDocumentParseNode.parameters.jsCode = `const item = $input.first();
const sourceJob = $('Route Voice Or Document').first().json || {};
const telegramFile = item.json || {};
const job = { ...sourceJob, telegram_file: telegramFile };
const binaryValues = Object.values(item.binary || {});
const binary = binaryValues[0] || {};
const binaryKey = Object.keys(item.binary || {})[0] || 'data';
const fileName = binary.fileName || job.file_name || (job.item_type + '-' + job.external_file_id);
const mimeType = binary.mimeType || job.mime_type || 'application/octet-stream';
const extension = (fileName.split('.').pop() || '').toLowerCase();
const sourceFormat = extension || (mimeType.split('/').pop() || 'bin');
const sourceBuffer = await this.helpers.getBinaryDataBuffer(0, binaryKey);

return [{
  json: {
    ...job,
    source_filename: fileName,
    source_mime: mimeType,
    source_size: binary.fileSize || job.file_size || null,
    source_format: sourceFormat,
    source_base64: sourceBuffer.toString('base64'),
    processing_lane: job.item_type === 'photo' || mimeType.startsWith('image/') ? 'ocr' : 'auto',
    document_type: job.item_type === 'photo' ? 'telegram_photo' : 'telegram_document'
  }
}];`;

  const buildVoiceExtractedTextNode = findNode(workflow, "Build Voice Extracted Text Payload");
  if (buildVoiceExtractedTextNode) {
    buildVoiceExtractedTextNode.parameters.jsCode = `const transcription = $input.first().json || {};
const sourceJob = $('Route Voice Or Document').first().json || {};
const telegramFile = $('Download Telegram Voice').first().json || {};
const job = { ...sourceJob, telegram_file: telegramFile };
const text = transcription.text || transcription.transcript || transcription.output || '';

if (!String(text).trim()) {
  return [];
}

return [{
  json: {
    package_id: job.package_id,
    external_file_id: job.external_file_id,
    workspace_id: job.workspace_id,
    user_id: job.user_id,
    extracted_text: String(text).trim(),
    file_name: job.file_name || ('voice-' + job.external_file_id + '.oga'),
    mime_type: job.mime_type || 'audio/ogg',
    extraction_method: 'telegram.voice_transcription',
    document_type: 'telegram_voice',
    metadata: {
      item_type: 'voice',
      duration: job.duration || null,
      source_size: job.file_size || null
    }
  }
}];`;
  }

  const clientReplyNode = findNode(workflow, "Telegram Client Menu Reply");
  if (!clientReplyNode) {
    throw new Error("Telegram Client Menu Reply node not found");
  }
  if (!findNode(workflow, "Telegram Batch Menu Reply")) {
    const batchReplyNode = JSON.parse(JSON.stringify(clientReplyNode));
    batchReplyNode.id = "jur-telegram-batch-menu-reply";
    batchReplyNode.name = "Telegram Batch Menu Reply";
    batchReplyNode.position = [120, 300];
    workflow.nodes.push(batchReplyNode);
  }

  const batchReplyNode = findNode(workflow, "Telegram Batch Menu Reply");
  batchReplyNode.parameters.text =
    '={{$json.reply_text || \'Пакетна обробка. Додайте матеріали та натисніть "Почати обробку".\'}}';
  batchReplyNode.parameters.replyKeyboard.rows = [
    {
      row: {
        buttons: [{ text: "Додати фото або документ" }, { text: "Додати голосове повідомлення" }],
      },
    },
    {
      row: {
        buttons: [{ text: "Показати додані матеріали" }, { text: "Почати обробку" }],
      },
    },
    {
      row: {
        buttons: [{ text: "Статус обробки" }, { text: "Очистити пакет" }],
      },
    },
    {
      row: {
        buttons: [{ text: "Назад" }],
      },
    },
  ];

  if (!findNode(workflow, "Route Batch Reply Menu")) {
    workflow.nodes.push({
      parameters: {
        conditions: {
          options: {
            caseSensitive: true,
            leftValue: "",
            typeValidation: "strict",
            version: 2,
          },
          conditions: [
            {
              id: "jur-reply-menu-batch",
              leftValue: "={{$json.reply_menu}}",
              rightValue: "batch",
              operator: {
                type: "string",
                operation: "equals",
              },
            },
          ],
          combinator: "and",
        },
        options: {},
      },
      id: "jur-route-batch-reply-menu",
      name: "Route Batch Reply Menu",
      type: "n8n-nodes-base.if",
      typeVersion: 2.2,
      position: [-20, 120],
    });
  }

  workflow.connections["Route Reply Menu"].main[1] = [
    {
      node: "Route Batch Reply Menu",
      type: "main",
      index: 0,
    },
  ];
  workflow.connections["Route Batch Reply Menu"] = {
    main: [
      [
        {
          node: "Telegram Batch Menu Reply",
          type: "main",
          index: 0,
        },
      ],
      [
        {
          node: "Telegram Intake Reply",
          type: "main",
          index: 0,
        },
      ],
    ],
  };

  if (!findNode(workflow, "Build Auto Process Request")) {
    workflow.nodes.push({
      parameters: {
        mode: "runOnceForAllItems",
        jsCode:
          "const result = $input.first().json || {};\nif (result.status !== 'queued') {\n  return [];\n}\nreturn [{ json: { package_id: result.package_id, requested_agent: 'orchestrator', question: 'Проаналізуй надісланий документ.' } }];",
      },
      id: "jur-build-auto-process-request",
      name: "Build Auto Process Request",
      type: "n8n-nodes-base.code",
      typeVersion: 2,
      position: [1680, 260],
    });
  }

  if (!findNode(workflow, "Process Auto Extracted Package")) {
    workflow.nodes.push({
      parameters: {
        method: "POST",
        url: "={{$env.JUR_API_BASE_URL}}/n8n/intake/process",
        sendBody: true,
        specifyBody: "json",
        jsonBody: "={{$json}}",
        options: {
          timeout: 900000,
        },
      },
      id: "jur-process-auto-extracted-package",
      name: "Process Auto Extracted Package",
      type: "n8n-nodes-base.httpRequest",
      typeVersion: 4.2,
      position: [1920, 260],
    });
  }

  if (!findNode(workflow, "Build Auto Analysis Reply")) {
    workflow.nodes.push({
      parameters: {
        mode: "runOnceForAllItems",
        jsCode:
          "const result = $input.first().json || {};\nconst event = $('Normalize Telegram Update').first().json || {};\nconst fallbackStatuses = new Set(['llm_error', 'waiting_for_text_extraction', 'needs_identity']);\nconst replyText = result.answer || (fallbackStatuses.has(result.status) ? result.message : '');\nif (!replyText) {\n  return [];\n}\nreturn [{ json: { chat_id: event.chat_id, reply_text: replyText } }];",
      },
      id: "jur-build-auto-analysis-reply",
      name: "Build Auto Analysis Reply",
      type: "n8n-nodes-base.code",
      typeVersion: 2,
      position: [2160, 260],
    });
  }
  findNode(workflow, "Build Auto Analysis Reply").parameters.jsCode =
    "const result = $input.first().json || {};\nconst event = $('Normalize Telegram Update').first().json || {};\nconst fallbackStatuses = new Set(['llm_error', 'waiting_for_text_extraction', 'needs_identity']);\nconst replyText = result.answer || (fallbackStatuses.has(result.status) ? result.message : '');\nif (!replyText) {\n  return [];\n}\nreturn [{ json: { chat_id: event.chat_id, reply_text: replyText } }];";

  if (!findNode(workflow, "Telegram Auto Analysis Reply")) {
    const autoReplyNode = JSON.parse(JSON.stringify(mainReplyNode));
    autoReplyNode.id = "jur-telegram-auto-analysis-reply";
    autoReplyNode.name = "Telegram Auto Analysis Reply";
    autoReplyNode.position = [2400, 260];
    workflow.nodes.push(autoReplyNode);
  }
  const autoReplyNode = findNode(workflow, "Telegram Auto Analysis Reply");
  autoReplyNode.parameters.text = "={{$json.reply_text || 'Аналіз завершено.'}}";

  workflow.connections["Attach Document Extracted Text To API"] = {
    main: [[{ node: "Build Auto Process Request", type: "main", index: 0 }]],
  };
  workflow.connections["Attach Voice Extracted Text To API"] = {
    main: [[{ node: "Build Auto Process Request", type: "main", index: 0 }]],
  };
  workflow.connections["Build Auto Process Request"] = {
    main: [[{ node: "Process Auto Extracted Package", type: "main", index: 0 }]],
  };
  workflow.connections["Process Auto Extracted Package"] = {
    main: [[{ node: "Build Auto Analysis Reply", type: "main", index: 0 }]],
  };
  workflow.connections["Build Auto Analysis Reply"] = {
    main: [[{ node: "Telegram Auto Analysis Reply", type: "main", index: 0 }]],
  };
}

const workflowResponse = await fetch(`${baseUrl}/api/v1/workflows/${workflowId}`, { headers });
if (!workflowResponse.ok) {
  throw new Error(`Failed to fetch workflow: ${workflowResponse.status} ${await workflowResponse.text()}`);
}

const workflow = await workflowResponse.json();
const wasActive = workflow.active;
applyBatchMenu(workflow);

const payload = {
  name: workflow.name,
  nodes: workflow.nodes,
  connections: workflow.connections,
  settings: {
    executionOrder: workflow.settings?.executionOrder || "v1",
  },
  staticData: workflow.staticData,
  pinData: workflow.pinData,
};

const updateResponse = await fetch(`${baseUrl}/api/v1/workflows/${workflowId}`, {
  method: "PUT",
  headers,
  body: JSON.stringify(payload),
});
if (!updateResponse.ok) {
  throw new Error(`Failed to update workflow: ${updateResponse.status} ${await updateResponse.text()}`);
}

if (wasActive) {
  let activateResponse;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    activateResponse = await fetch(`${baseUrl}/api/v1/workflows/${workflowId}/activate`, {
      method: "POST",
      headers,
    });
    const responseText = await activateResponse.clone().text();
    const isRateLimited =
      activateResponse.status === 429 ||
      (activateResponse.status === 400 && responseText.includes("Too Many Requests"));
    if (!isRateLimited) {
      break;
    }
    const retryAfter = Number(activateResponse.headers.get("retry-after") || "2");
    await new Promise((resolve) => setTimeout(resolve, retryAfter * 1000));
  }
  if (!activateResponse?.ok) {
    throw new Error(`Failed to activate workflow: ${activateResponse.status} ${await activateResponse.text()}`);
  }
}

const updated = await updateResponse.json();
console.log(JSON.stringify({ ok: true, id: updated.id, name: updated.name, active: wasActive }, null, 2));

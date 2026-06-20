import fs from "node:fs";

const workflowPath = "n8n/workflows/JUR_Bot_Intake_Queue.json";
const workflow = JSON.parse(fs.readFileSync(workflowPath, "utf8"));

const findNode = (name) => workflow.nodes.find((node) => node.name === name);

const normalizeNode = findNode("Normalize Telegram Update");
if (!normalizeNode.parameters.jsCode.includes("'Пакетна обробка': 'batch_processing_menu'")) {
  normalizeNode.parameters.jsCode = normalizeNode.parameters.jsCode.replace(
    "const actionMap = {\n",
    "const actionMap = {\n  'Пакетна обробка': 'batch_processing_menu',\n",
  );
}

const mainReplyNode = findNode("Telegram Intake Reply");
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

const longTimeoutNodes = new Set(["Send Intake Event To API", "Process Auto Extracted Package"]);

for (const nodeName of [
  "Send Intake Event To API",
  "Attach Document Extracted Text To API",
  "Attach Voice Extracted Text To API",
  "Process Auto Extracted Package",
]) {
  const httpNode = findNode(nodeName);
  if (httpNode) {
    httpNode.parameters.options = {
      ...(httpNode.parameters.options || {}),
      timeout: longTimeoutNodes.has(nodeName) ? 900000 : 300000,
    };
  }
}

const prepareDocumentParseNode = findNode("Prepare Document Parse Payload");
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

const buildVoiceExtractedTextNode = findNode("Build Voice Extracted Text Payload");
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

const clientReplyNode = findNode("Telegram Client Menu Reply");
if (!findNode("Telegram Batch Menu Reply")) {
  const batchReplyNode = JSON.parse(JSON.stringify(clientReplyNode));
  batchReplyNode.id = "jur-telegram-batch-menu-reply";
  batchReplyNode.name = "Telegram Batch Menu Reply";
  batchReplyNode.position = [120, 300];
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
  workflow.nodes.push(batchReplyNode);
}

if (!findNode("Route Batch Reply Menu")) {
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

if (!findNode("Build Auto Process Request")) {
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

if (!findNode("Process Auto Extracted Package")) {
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

if (!findNode("Build Auto Analysis Reply")) {
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

findNode("Build Auto Analysis Reply").parameters.jsCode =
  "const result = $input.first().json || {};\nconst event = $('Normalize Telegram Update').first().json || {};\nconst fallbackStatuses = new Set(['llm_error', 'waiting_for_text_extraction', 'needs_identity']);\nconst replyText = result.answer || (fallbackStatuses.has(result.status) ? result.message : '');\nif (!replyText) {\n  return [];\n}\nreturn [{ json: { chat_id: event.chat_id, reply_text: replyText } }];";

if (!findNode("Telegram Auto Analysis Reply")) {
  const autoReplyNode = JSON.parse(JSON.stringify(mainReplyNode));
  autoReplyNode.id = "jur-telegram-auto-analysis-reply";
  autoReplyNode.name = "Telegram Auto Analysis Reply";
  autoReplyNode.position = [2400, 260];
  autoReplyNode.parameters.text = "={{$json.reply_text || 'Аналіз завершено.'}}";
  workflow.nodes.push(autoReplyNode);
}

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

fs.writeFileSync(workflowPath, `${JSON.stringify(workflow, null, 2)}\n`);

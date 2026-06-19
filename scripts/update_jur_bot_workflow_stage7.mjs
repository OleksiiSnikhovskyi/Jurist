import fs from "node:fs";
import path from "node:path";

const workflowPath = path.join(process.cwd(), "n8n", "workflows", "JUR_Bot_Intake_Queue.json");
const workflow = JSON.parse(fs.readFileSync(workflowPath, "utf8"));

const generatedIds = new Set([
  "jur-build-extraction-jobs",
  "jur-has-extraction-jobs",
  "jur-route-voice-document",
  "jur-download-document-file",
  "jur-prepare-document-parse",
  "jur-parse-document-linguistpro",
  "jur-build-document-extracted-text",
  "jur-attach-document-extracted-text",
  "jur-download-voice-file",
  "jur-transcribe-voice",
  "jur-build-voice-extracted-text",
  "jur-attach-voice-extracted-text",
]);

workflow.nodes = workflow.nodes.filter((node) => !generatedIds.has(node.id));

const telegramCredentials =
  workflow.nodes.find((node) => node.name === "Telegram Trigger")?.credentials ?? {
    telegramApi: {
      id: "__TELEGRAM_CREDENTIAL_ID__",
      name: "__TELEGRAM_CREDENTIAL_NAME__",
    },
  };

const openAiCredentials = {
  openAiApi: {
    id: "__OPENAI_CREDENTIAL_ID__",
    name: "__OPENAI_CREDENTIAL_NAME__",
  },
};

function node(id, name, type, typeVersion, position, parameters, credentials) {
  const result = { parameters, id, name, type, typeVersion, position };
  if (credentials) result.credentials = credentials;
  return result;
}

const buildJobsCode = String.raw`const intake = $input.first().json || {};
const event = $('Normalize Telegram Update').first().json || {};
const attachments = Array.isArray(event.attachments) ? event.attachments : [];

if (!intake.ok || !intake.package_id || attachments.length === 0) {
  return [];
}

return attachments
  .filter((attachment) => attachment && attachment.file_id)
  .map((attachment) => ({
    json: {
      package_id: intake.package_id,
      chat_id: intake.chat_id || event.chat_id,
      workspace_id: intake.workspace_id || event.workspace_id || null,
      user_id: intake.user_id || event.user_id || null,
      item_type: attachment.type,
      external_file_id: attachment.file_id,
      file_name: attachment.file_name || (attachment.type + '-' + attachment.file_id),
      mime_type: attachment.mime_type || null,
      file_size: attachment.file_size || null,
      duration: attachment.duration || null,
      extraction_requested_at: new Date().toISOString()
    }
  }));`;

const prepareDocumentParseCode = String.raw`const item = $input.first();
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

const buildDocumentExtractedTextCode = String.raw`const parsed = $input.first().json || {};
const job = $('Prepare Document Parse Payload').first().json || {};
const nodes = Array.isArray(parsed.nodes) ? parsed.nodes : [];
const nodeText = nodes.map((node) => node.source_text || node.text || '').filter(Boolean).join('\n\n');
const extractedText = parsed.full_text || parsed.extracted_text || parsed.text || parsed.source_text || nodeText;

if (!extractedText || !String(extractedText).trim()) {
  return [];
}

return [{
  json: {
    package_id: job.package_id,
    external_file_id: job.external_file_id,
    workspace_id: job.workspace_id,
    user_id: job.user_id,
    extracted_text: String(extractedText).trim(),
    file_name: job.source_filename || job.file_name,
    mime_type: job.source_mime || job.mime_type,
    extraction_method: 'linguistproai.parse_document',
    document_type: job.document_type,
    metadata: {
      item_type: job.item_type,
      source_size: job.source_size,
      processing_lane: job.processing_lane,
      parsed_doc_id: parsed.doc_id || null,
      parsed_node_count: nodes.length
    }
  }
}];`;

const buildVoiceExtractedTextCode = String.raw`const transcription = $input.first().json || {};
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

const extractionNodes = [
  node("jur-build-extraction-jobs", "Build Extraction Jobs", "n8n-nodes-base.code", 2, [0, 300], {
    mode: "runOnceForAllItems",
    jsCode: buildJobsCode,
  }),
  node("jur-has-extraction-jobs", "Has Extraction Jobs", "n8n-nodes-base.if", 2.2, [220, 300], {
    conditions: {
      options: { caseSensitive: true, leftValue: "", typeValidation: "strict", version: 2 },
      conditions: [
        {
          id: "jur-has-file-id",
          leftValue: "={{$json.external_file_id}}",
          rightValue: "",
          operator: { type: "string", operation: "notEmpty", singleValue: true },
        },
      ],
      combinator: "and",
    },
    options: {},
  }),
  node("jur-route-voice-document", "Route Voice Or Document", "n8n-nodes-base.if", 2.2, [440, 300], {
    conditions: {
      options: { caseSensitive: true, leftValue: "", typeValidation: "strict", version: 2 },
      conditions: [
        {
          id: "jur-is-voice",
          leftValue: "={{$json.item_type}}",
          rightValue: "voice",
          operator: { type: "string", operation: "equals" },
        },
      ],
      combinator: "and",
    },
    options: {},
  }),
  node(
    "jur-download-document-file",
    "Download Telegram Document",
    "n8n-nodes-base.telegram",
    1.2,
    [680, 430],
    { resource: "file", fileId: "={{$json.external_file_id}}", additionalFields: {} },
    telegramCredentials,
  ),
  node("jur-prepare-document-parse", "Prepare Document Parse Payload", "n8n-nodes-base.code", 2, [920, 430], {
    mode: "runOnceForAllItems",
    jsCode: prepareDocumentParseCode,
  }),
  node("jur-parse-document-linguistpro", "Parse Document With LinguistProAi", "n8n-nodes-base.httpRequest", 4.2, [1160, 430], {
    method: "POST",
    url: "http://linguistproai-internal-ai:8011/internal/v2/parse-document",
    sendBody: true,
    specifyBody: "json",
    jsonBody:
      "={{ { doc_id: $json.external_file_id, source_filename: $json.source_filename, source_format: $json.source_format, source_base64: $json.source_base64, source_mime: $json.source_mime, source_size: $json.source_size, processing_lane: $json.processing_lane, preserve_layout: true, preserve_fonts: true, extract_images: false } }}",
    options: { timeout: 240000 },
  }),
  node("jur-build-document-extracted-text", "Build Document Extracted Text Payload", "n8n-nodes-base.code", 2, [1400, 430], {
    mode: "runOnceForAllItems",
    jsCode: buildDocumentExtractedTextCode,
  }),
  node("jur-attach-document-extracted-text", "Attach Document Extracted Text To API", "n8n-nodes-base.httpRequest", 4.2, [1640, 430], {
    method: "POST",
    url: "={{$env.JUR_API_BASE_URL}}/n8n/intake/extracted-text",
    sendBody: true,
    specifyBody: "json",
    jsonBody: "={{$json}}",
    options: { timeout: 60000 },
  }),
  node(
    "jur-download-voice-file",
    "Download Telegram Voice",
    "n8n-nodes-base.telegram",
    1.2,
    [680, 170],
    { resource: "file", fileId: "={{$json.external_file_id}}", additionalFields: {} },
    telegramCredentials,
  ),
  node(
    "jur-transcribe-voice",
    "Transcribe Telegram Voice",
    "@n8n/n8n-nodes-langchain.openAi",
    1.8,
    [920, 170],
    { resource: "audio", operation: "transcribe", options: {} },
    openAiCredentials,
  ),
  node("jur-build-voice-extracted-text", "Build Voice Extracted Text Payload", "n8n-nodes-base.code", 2, [1160, 170], {
    mode: "runOnceForAllItems",
    jsCode: buildVoiceExtractedTextCode,
  }),
  node("jur-attach-voice-extracted-text", "Attach Voice Extracted Text To API", "n8n-nodes-base.httpRequest", 4.2, [1400, 170], {
    method: "POST",
    url: "={{$env.JUR_API_BASE_URL}}/n8n/intake/extracted-text",
    sendBody: true,
    specifyBody: "json",
    jsonBody: "={{$json}}",
    options: { timeout: 60000 },
  }),
];

workflow.nodes.push(...extractionNodes);

workflow.connections["Send Intake Event To API"].main[0] = [
  { node: "Route Reply Menu", type: "main", index: 0 },
  { node: "Build Extraction Jobs", type: "main", index: 0 },
];
workflow.connections["Build Extraction Jobs"] = {
  main: [[{ node: "Has Extraction Jobs", type: "main", index: 0 }]],
};
workflow.connections["Has Extraction Jobs"] = {
  main: [[{ node: "Route Voice Or Document", type: "main", index: 0 }], []],
};
workflow.connections["Route Voice Or Document"] = {
  main: [
    [{ node: "Download Telegram Voice", type: "main", index: 0 }],
    [{ node: "Download Telegram Document", type: "main", index: 0 }],
  ],
};
workflow.connections["Download Telegram Document"] = {
  main: [[{ node: "Prepare Document Parse Payload", type: "main", index: 0 }]],
};
workflow.connections["Prepare Document Parse Payload"] = {
  main: [[{ node: "Parse Document With LinguistProAi", type: "main", index: 0 }]],
};
workflow.connections["Parse Document With LinguistProAi"] = {
  main: [[{ node: "Build Document Extracted Text Payload", type: "main", index: 0 }]],
};
workflow.connections["Build Document Extracted Text Payload"] = {
  main: [[{ node: "Attach Document Extracted Text To API", type: "main", index: 0 }]],
};
workflow.connections["Download Telegram Voice"] = {
  main: [[{ node: "Transcribe Telegram Voice", type: "main", index: 0 }]],
};
workflow.connections["Transcribe Telegram Voice"] = {
  main: [[{ node: "Build Voice Extracted Text Payload", type: "main", index: 0 }]],
};
workflow.connections["Build Voice Extracted Text Payload"] = {
  main: [[{ node: "Attach Voice Extracted Text To API", type: "main", index: 0 }]],
};

fs.writeFileSync(workflowPath, `${JSON.stringify(workflow, null, 2)}\n`, "utf8");

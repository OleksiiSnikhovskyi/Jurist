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

for (const nodeName of [
  "Send Intake Event To API",
  "Attach Document Extracted Text To API",
  "Attach Voice Extracted Text To API",
]) {
  const httpNode = findNode(nodeName);
  if (httpNode) {
    httpNode.parameters.options = {
      ...(httpNode.parameters.options || {}),
      timeout: 300000,
    };
  }
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

if (!findNode("Build Auto Analysis Reply")) {
  workflow.nodes.push({
    parameters: {
      mode: "runOnceForAllItems",
      jsCode:
        "const result = $input.first().json || {};\nconst event = $('Normalize Telegram Update').first().json || {};\nif (!result.answer) {\n  return [];\n}\nreturn [{ json: { chat_id: event.chat_id, reply_text: result.answer } }];",
    },
    id: "jur-build-auto-analysis-reply",
    name: "Build Auto Analysis Reply",
    type: "n8n-nodes-base.code",
    typeVersion: 2,
    position: [1680, 260],
  });
}

if (!findNode("Telegram Auto Analysis Reply")) {
  const autoReplyNode = JSON.parse(JSON.stringify(mainReplyNode));
  autoReplyNode.id = "jur-telegram-auto-analysis-reply";
  autoReplyNode.name = "Telegram Auto Analysis Reply";
  autoReplyNode.position = [1920, 260];
  autoReplyNode.parameters.text = "={{$json.reply_text || 'Аналіз завершено.'}}";
  workflow.nodes.push(autoReplyNode);
}

workflow.connections["Attach Document Extracted Text To API"] = {
  main: [[{ node: "Build Auto Analysis Reply", type: "main", index: 0 }]],
};
workflow.connections["Attach Voice Extracted Text To API"] = {
  main: [[{ node: "Build Auto Analysis Reply", type: "main", index: 0 }]],
};
workflow.connections["Build Auto Analysis Reply"] = {
  main: [[{ node: "Telegram Auto Analysis Reply", type: "main", index: 0 }]],
};

fs.writeFileSync(workflowPath, `${JSON.stringify(workflow, null, 2)}\n`);

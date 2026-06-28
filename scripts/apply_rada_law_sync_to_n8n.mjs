import fs from "node:fs";
import path from "node:path";

const baseUrl = process.env.N8N_BASE_URL || "https://n8n.csc-ua.tech";
const workflowId = process.env.N8N_RADA_WORKFLOW_ID || process.env.N8N_WORKFLOW_ID || "idhN3BnLzF6VtTyp";
const apiKey = process.env.N8N_API_KEY;

if (!apiKey) {
  throw new Error("N8N_API_KEY is required");
}

const headers = {
  "Content-Type": "application/json",
  "X-N8N-API-KEY": apiKey,
};

const templatePath = path.join(process.cwd(), "n8n", "workflows", "JUR_Rada_Law_Sync_Qwen.json");
const template = JSON.parse(fs.readFileSync(templatePath, "utf8"));

const workflowResponse = await fetch(`${baseUrl}/api/v1/workflows/${workflowId}`, { headers });
if (!workflowResponse.ok) {
  throw new Error(`Failed to fetch workflow: ${workflowResponse.status} ${await workflowResponse.text()}`);
}

const workflow = await workflowResponse.json();
const wasActive = workflow.active;
const payload = {
  name: template.name,
  nodes: template.nodes,
  connections: template.connections,
  settings: {
    executionOrder: template.settings?.executionOrder || workflow.settings?.executionOrder || "v1",
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
  const activateResponse = await fetch(`${baseUrl}/api/v1/workflows/${workflowId}/activate`, {
    method: "POST",
    headers,
  });
  if (!activateResponse.ok) {
    const responseText = await activateResponse.text();
    if (!responseText.includes("already active")) {
      throw new Error(`Failed to activate workflow: ${activateResponse.status} ${responseText}`);
    }
  }
}

const updated = await updateResponse.json();
const parseNode = template.nodes.find((node) => node.name === "Parse Rada Daily");
console.log(
  JSON.stringify(
    {
      ok: true,
      id: updated.id,
      name: updated.name,
      active_before_update: wasActive,
      parses_validity_status: Boolean(parseNode?.parameters?.jsCode?.includes("function validityStatus")),
    },
    null,
    2,
  ),
);

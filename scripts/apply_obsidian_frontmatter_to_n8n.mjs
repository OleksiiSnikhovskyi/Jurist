import fs from "node:fs";
import path from "node:path";

const baseUrl = process.env.N8N_BASE_URL || "https://n8n.csc-ua.tech";
const workflowId = process.env.N8N_WORKFLOW_ID || "NGubhhjGjGp8lh57";
const apiKey = process.env.N8N_API_KEY;

if (!apiKey) {
  throw new Error("N8N_API_KEY is required");
}

const headers = {
  "Content-Type": "application/json",
  "X-N8N-API-KEY": apiKey,
};

const templatePath = path.join(process.cwd(), "n8n", "workflows", "JUR_Obsidian_Vault_Sync.json");
const template = JSON.parse(fs.readFileSync(templatePath, "utf8"));
const templateNode = template.nodes.find((node) => node.name === "Normalize Obsidian Notes");
if (!templateNode) {
  throw new Error("Normalize Obsidian Notes node not found in template");
}

const workflowResponse = await fetch(`${baseUrl}/api/v1/workflows/${workflowId}`, { headers });
if (!workflowResponse.ok) {
  throw new Error(`Failed to fetch workflow: ${workflowResponse.status} ${await workflowResponse.text()}`);
}

const workflow = await workflowResponse.json();
const wasActive = workflow.active;
const normalizeNode = workflow.nodes.find((node) => node.name === "Normalize Obsidian Notes");
if (!normalizeNode) {
  throw new Error("Normalize Obsidian Notes node not found in remote workflow");
}

normalizeNode.parameters = {
  ...normalizeNode.parameters,
  mode: "runOnceForAllItems",
  jsCode: templateNode.parameters.jsCode,
};

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
console.log(
  JSON.stringify(
    {
      ok: true,
      id: updated.id,
      name: updated.name,
      active_before_update: wasActive,
      normalized_frontmatter_parser: normalizeNode.parameters.jsCode.includes("parseFrontmatter"),
    },
    null,
    2,
  ),
);

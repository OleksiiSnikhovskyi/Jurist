import fs from "node:fs";
import path from "node:path";

const workflowPath = path.join(process.cwd(), "n8n", "workflows", "JUR_Obsidian_Vault_Sync.json");
const workflow = JSON.parse(fs.readFileSync(workflowPath, "utf8"));

const normalizeCode = String.raw`function parseScalar(value) {
  const trimmed = String(value ?? '').trim().replace(/^['"]|['"]$/g, '');
  if (trimmed === 'true') return true;
  if (trimmed === 'false') return false;
  return trimmed;
}

function parseInlineList(value) {
  const trimmed = String(value ?? '').trim();
  if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) return null;
  return trimmed
    .slice(1, -1)
    .split(',')
    .map((part) => parseScalar(part))
    .filter((part) => String(part).trim());
}

function parseFrontmatter(markdown) {
  const normalized = String(markdown || '').replace(/\r\n/g, '\n');
  if (!normalized.startsWith('---\n')) {
    return { frontmatter: {}, body: normalized };
  }
  const endIndex = normalized.indexOf('\n---\n', 4);
  if (endIndex === -1) {
    return { frontmatter: {}, body: normalized };
  }

  const frontmatterText = normalized.slice(4, endIndex);
  const body = normalized.slice(endIndex + '\n---\n'.length);
  const frontmatter = {};
  let activeKey = null;

  for (const rawLine of frontmatterText.split('\n')) {
    const line = rawLine.trimEnd();
    if (!line.trim()) continue;
    if (line.trimStart().startsWith('- ') && activeKey) {
      if (!Array.isArray(frontmatter[activeKey])) {
        frontmatter[activeKey] = [];
      }
      frontmatter[activeKey].push(parseScalar(line.trimStart().slice(2)));
      continue;
    }
    const separatorIndex = line.indexOf(':');
    if (separatorIndex === -1) continue;
    activeKey = line.slice(0, separatorIndex).trim();
    const rawValue = line.slice(separatorIndex + 1).trim();
    if (!rawValue) {
      frontmatter[activeKey] = [];
      continue;
    }
    const listValue = parseInlineList(rawValue);
    frontmatter[activeKey] = listValue ?? parseScalar(rawValue);
  }

  return { frontmatter, body };
}

function normalizeList(value) {
  if (Array.isArray(value)) return value.map(String).filter((item) => item.trim());
  if (typeof value === 'string' && value.trim()) return [value.trim()];
  return [];
}

const body = $input.first().json.body || $input.first().json;
const notes = Array.isArray(body.notes) ? body.notes : [body];

return notes.map((note, index) => {
  const markdown = note.markdown || note.body || '';
  const parsed = parseFrontmatter(markdown);
  const frontmatter = {
    ...parsed.frontmatter,
    ...(note.frontmatter || {}),
  };
  for (const field of ['document_number', 'source_name', 'source_url']) {
    if (note[field] && !frontmatter[field]) {
      frontmatter[field] = note[field];
    }
  }
  const tags = normalizeList(note.tags).length ? normalizeList(note.tags) : normalizeList(frontmatter.tags);
  const aliases = normalizeList(frontmatter.aliases || frontmatter.alias || frontmatter.legal_aliases || frontmatter.legal_source_aliases);
  if (aliases.length && !frontmatter.aliases) {
    frontmatter.aliases = aliases;
  }

  return {
    json: {
      workspace_id: body.workspace_id || note.workspace_id,
      user_id: body.user_id || note.user_id,
      note_path: note.note_path || note.path || ('obsidian-note-' + index + '.md'),
      title: note.title || frontmatter.title || null,
      markdown,
      frontmatter,
      tags,
      links: note.links || [],
      sync_mode: body.sync_mode || note.sync_mode || 'manual',
      synced_at: note.synced_at || new Date().toISOString()
    }
  };
});`;

const node = workflow.nodes.find((candidate) => candidate.name === "Normalize Obsidian Notes");
if (!node) {
  throw new Error("Normalize Obsidian Notes node not found");
}
node.parameters.mode = "runOnceForAllItems";
node.parameters.jsCode = normalizeCode;

fs.writeFileSync(workflowPath, JSON.stringify(workflow, null, 2) + "\n", "utf8");
console.log(JSON.stringify({ ok: true, workflow: workflow.name, node: node.name }, null, 2));



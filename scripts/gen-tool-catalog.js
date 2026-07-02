#!/usr/bin/env node
/**
 * Generate docs/TOOL-CATALOG.md from the tool registrations in src/server.ts.
 *
 * Why: the human-written skill / docs drifted stale more than once (claimed
 * "Standard only", "SA not implemented", etc.). This extracts the ground truth
 * -- every s.tool('name', 'description', ...) -- straight from source, so the
 * catalog can never lie about what tools exist. Run as part of `npm run build`.
 *
 * Deliberately a dumb regex scan (no TS parse): tool registrations follow a
 * fixed shape `s.tool(\n 'name',\n "description...",`. If that shape changes,
 * this will under-report -- acceptable for a doc generator, and the count is
 * printed so a regression is visible.
 */
const fs = require('fs');
const path = require('path');

const serverPath = path.join(__dirname, '..', 'src', 'server.ts');
const outPath = path.join(__dirname, '..', 'docs', 'TOOL-CATALOG.md');

const src = fs.readFileSync(serverPath, 'utf-8');

// Match:  s.tool(  'name',  '<desc>' | "<desc>" | `<desc>`
// The name is a single-quoted identifier; the description is the next string
// literal (any of the three quote styles), possibly spanning lines.
const re = /\b[s]\.tool\(\s*['"]([a-z0-9_]+)['"]\s*,\s*(['"`])([\s\S]*?)\2/gi;

const tools = [];
let m;
while ((m = re.exec(src)) !== null) {
  const name = m[1];
  // Collapse whitespace/newlines in the description to one line.
  const desc = m[3].replace(/\s+/g, ' ').trim();
  tools.push({ name, desc });
}

tools.sort((a, b) => a.name.localeCompare(b.name));

const lines = [];
lines.push('# Tool catalog (auto-generated)');
lines.push('');
lines.push('> Generated from `src/server.ts` by `scripts/gen-tool-catalog.js` (runs during `npm run build`).');
lines.push('> Do NOT edit by hand -- your changes will be overwritten. Fix the tool description in `server.ts` instead.');
lines.push('');
lines.push(`**${tools.length} tools.**`);
lines.push('');
lines.push('| Tool | Description |');
lines.push('|---|---|');
for (const t of tools) {
  // Escape pipes in the description so the table doesn't break.
  const d = t.desc.replace(/\|/g, '\\|');
  lines.push(`| \`${t.name}\` | ${d} |`);
}
lines.push('');

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, lines.join('\n'), 'utf-8');

process.stderr.write(`gen-tool-catalog: wrote ${tools.length} tools to ${path.relative(process.cwd(), outPath)}\n`);

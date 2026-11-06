#!/usr/bin/env node
/**
 * Generate docs/TOOL-CATALOG.md from the tool registrations in src/server.ts.
 *
 * The catalog is the written list of the tool part of the public API
 * (docs/PUBLIC-API.md): every tool with every parameter's name, type,
 * required-ness and allowed values. It is generated so it cannot drift from
 * the code -- hand-written docs claimed tools and limits that were no longer
 * true more than once. Runs in `npm run build` and as `npm run docs`; the
 * output depends only on src/server.ts, so running it twice changes nothing.
 */
const fs = require('fs');
const path = require('path');
const { extractTools } = require('./lib/tool-api');

const root = path.join(__dirname, '..');
const outPath = path.join(root, 'docs', 'TOOL-CATALOG.md');
const tools = extractTools(fs.readFileSync(path.join(root, 'src', 'server.ts'), 'utf-8'));
const nParams = tools.reduce((n, t) => n + t.params.length, 0);

const cell = (s) => String(s ?? '').replace(/\|/g, '\\|').replace(/\s+/g, ' ').trim();
const typeOf = (p) => (p.values ? p.values.map((v) => `'${v}'`).join(' \\| ') : cell(p.type));

const lines = [];
lines.push('# Tool catalog (auto-generated)');
lines.push('');
lines.push('> Generated from `src/server.ts` by `scripts/gen-tool-catalog.js` (`npm run docs`, also run by `npm run build`).');
lines.push('> Do not edit by hand: fix the tool registration in `server.ts` and regenerate.');
lines.push('');
lines.push(`**${tools.length} tools, ${nParams} parameters.** Tool names, parameter names, types, required-ness and allowed values are part of the public API -- see [PUBLIC-API.md](PUBLIC-API.md) for what that guarantees. Optional parameters are marked \`?\`.`);
lines.push('');
lines.push('| Tool | Parameters |');
lines.push('|---|---|');
for (const t of tools) {
  const sig = t.params.length
    ? t.params.map((p) => `\`${p.name}${p.required ? '' : '?'}\``).join(', ')
    : '--';
  lines.push(`| [\`${t.name}\`](#${t.name}) | ${sig} |`);
}
lines.push('');
for (const t of tools) {
  lines.push(`## ${t.name}`);
  lines.push('');
  lines.push(cell(t.description) || '_No description._');
  lines.push('');
  if (!t.params.length) {
    lines.push('No parameters.');
    lines.push('');
    continue;
  }
  lines.push('| Parameter | Type | Required | Constraints | Description |');
  lines.push('|---|---|---|---|---|');
  for (const p of t.params) {
    lines.push(`| \`${p.name}\` | ${typeOf(p)} | ${p.required ? 'yes' : 'no'} | ${cell(p.constraints.join(', '))} | ${cell(p.description)} |`);
  }
  lines.push('');
}

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, lines.join('\n'), 'utf-8');
process.stderr.write(`gen-tool-catalog: wrote ${tools.length} tools, ${nParams} parameters to ${path.relative(process.cwd(), outPath)}\n`);

// Minimal MCP client probe: spawns the server with --no-auto-launch,
// sends initialize + tools/list + resources/list, prints the catalog
// without ever touching the CODESYS / AutomationBuilder process.

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const transport = new StdioClientTransport({
  command: 'codesys-mcp-persistent',
  args: [
    '--codesys-path',
    'C:\\Program Files\\ABB\\AB2.9\\AutomationBuilder\\Common\\AutomationBuilder.exe',
    '--codesys-profile',
    'Automation Builder 2.9',
    '--mode',
    'persistent',
    '--no-auto-launch', // critical: keep the probe inert
  ],
});

const client = new Client({ name: 'probe', version: '0.0.1' }, { capabilities: {} });

await client.connect(transport);

const tools = await client.listTools();
console.log('=== TOOLS (' + tools.tools.length + ') ===');
for (const t of tools.tools) console.log('  - ' + t.name);

try {
  const resources = await client.listResources();
  console.log('\n=== RESOURCES (' + resources.resources.length + ') ===');
  for (const r of resources.resources) console.log('  - ' + r.uri + ' (' + r.name + ')');
} catch (e) {
  console.log('\n=== RESOURCES === (none or unsupported)');
}

try {
  const tmpls = await client.listResourceTemplates();
  console.log('\n=== RESOURCE TEMPLATES (' + tmpls.resourceTemplates.length + ') ===');
  for (const t of tmpls.resourceTemplates) console.log('  - ' + t.uriTemplate);
} catch (e) {
  console.log('\n=== RESOURCE TEMPLATES === (none or unsupported)');
}

await client.close();
process.exit(0);

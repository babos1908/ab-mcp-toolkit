import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { createRequire } from 'module';
import { readBuildInfo, restartNeeded } from '../../src/build-info';

const req = createRequire(import.meta.url);
const { extractTools, diffApi } = req('../../scripts/lib/tool-api.js');
const { parseSemver, compareSemver, bumpSatisfies, requiredVersion, contentHash } = req('../../scripts/lib/release-lib.js');

const SAMPLE = `
const s = server as any;
const shared = {
  level: z.number().int().min(0).max(31).describe("Level.").optional(),
};
s.tool(
  'alpha',
  "First " + "tool.",
  {
    path: z.string().describe("A path."),
    mode: z.enum(['fast', 'safe']).optional(),
    names: z.array(z.string().min(1)).optional(),
    id: z.union([z.number(), z.string()]).describe("Id."),
    ...shared,
  },
  async () => ({})
);
s.tool('beta', 'No params.', async () => ({}));
`;

describe('tool API extraction (scripts/lib/tool-api.js)', () => {
  it('reads names, types, required-ness, enums, arrays, unions and spread constants', () => {
    const tools = extractTools(SAMPLE);
    expect(tools.map((t: any) => t.name)).toEqual(['alpha', 'beta']);
    const a = tools[0];
    expect(a.description).toBe('First tool.');
    const p = Object.fromEntries(a.params.map((x: any) => [x.name, x]));
    expect(p.path).toMatchObject({ type: 'string', required: true, description: 'A path.' });
    expect(p.mode).toMatchObject({ type: 'enum', required: false, values: ['fast', 'safe'] });
    expect(p.names).toMatchObject({ type: 'string[]', required: false });
    expect(p.id).toMatchObject({ type: 'number | string', required: true });
    expect(p.level).toMatchObject({ type: 'number', required: false, constraints: ['int', 'min 0', 'max 31'] });
    expect(tools[1].params).toEqual([]);
  });

  it('finds every tool of the real server, including spread task knobs', () => {
    const tools = extractTools(fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'server.ts'), 'utf-8'));
    expect(tools.length).toBeGreaterThanOrEqual(76);
    const all = tools.flatMap((t: any) => t.params);
    expect(all.filter((q: any) => q.type === 'unknown')).toEqual([]);
    const stp = tools.find((t: any) => t.name === 'set_task_parameter');
    expect(stp.params.map((q: any) => q.name)).toEqual(expect.arrayContaining(['cycleTimeMs', 'watchdogEnabled', 'kind', 'addPous']));
    expect(tools.find((t: any) => t.name === 'get_mcp_version').params).toEqual([]);
  });

  it('classifies API changes by the SemVer level they need', () => {
    const before = extractTools(SAMPLE);
    const same = diffApi(before, extractTools(SAMPLE.replace('A path.', 'Another wording.')));
    expect(same.level).toBe('none'); // descriptions are not API

    const added = diffApi(before, extractTools(SAMPLE.replace("names:", "extra: z.boolean().optional(),\n    names:")));
    expect(added.level).toBe('minor');
    expect(added.minor).toContain('alpha: optional parameter added: extra');

    const required = diffApi(before, extractTools(SAMPLE.replace("mode: z.enum(['fast', 'safe']).optional()", "mode: z.enum(['fast', 'safe'])")));
    expect(required.level).toBe('major');
    expect(required.major).toContain('alpha.mode: optional -> required');

    const removedValue = diffApi(before, extractTools(SAMPLE.replace("['fast', 'safe']", "['fast']")));
    expect(removedValue.major).toContain('alpha.mode: value removed: safe');

    const removedTool = diffApi(before, extractTools(SAMPLE.replace("s.tool('beta', 'No params.', async () => ({}));", '')));
    expect(removedTool.major).toContain('tool removed: beta');

    const newTool = diffApi(before, extractTools(SAMPLE + "\ns.tool('gamma', 'New.', async () => ({}));"));
    expect(newTool).toMatchObject({ level: 'minor', minor: ['tool added: gamma'] });
  });
});

describe('SemVer helpers (scripts/lib/release-lib.js)', () => {
  it('accepts only MAJOR.MINOR.PATCH with optional pre-release and build metadata', () => {
    for (const ok of ['1.0.0', '0.6.2', '1.10.0', '2.0.0-rc.1', '1.4.0+20261106', '1.0.0-alpha.1+exp.sha.5114f85']) {
      expect(parseSemver(ok), ok).not.toBeNull();
    }
    for (const bad of ['1.0.0.0', '1.0', '01.0.0', '1.02.0', 'v1.0.0', '1.0.0-', '1.0.0-01']) {
      expect(parseSemver(bad), bad).toBeNull();
    }
  });

  it('orders versions as the specification does', () => {
    const order = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta', '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0',
      '1.9.0', '1.10.0', '2.0.0-rc.1', '2.0.0'];
    for (let i = 1; i < order.length; i++) {
      expect(compareSemver(parseSemver(order[i - 1]), parseSemver(order[i])), `${order[i - 1]} < ${order[i]}`).toBe(-1);
    }
    expect(compareSemver(parseSemver('1.4.0+a'), parseSemver('1.4.0+b'))).toBe(0); // build metadata ignored
  });

  it('knows which bump each API change needs, relaxed during 0.y.z', () => {
    const v = parseSemver;
    expect(bumpSatisfies(v('1.0.0'), v('1.0.1'), 'minor')).toBe(false);
    expect(bumpSatisfies(v('1.0.0'), v('1.1.0'), 'minor')).toBe(true);
    expect(bumpSatisfies(v('1.0.0'), v('1.1.0-rc.1'), 'minor')).toBe(true);
    expect(bumpSatisfies(v('1.4.2'), v('1.5.0'), 'major')).toBe(false);
    expect(bumpSatisfies(v('1.4.2'), v('2.0.0'), 'major')).toBe(true);
    expect(bumpSatisfies(v('0.6.2'), v('0.7.0'), 'major')).toBe(true);
    expect(bumpSatisfies(v('1.0.0'), v('1.0.0'), 'none')).toBe(true);
    expect(requiredVersion(v('1.4.2'), 'major')).toBe('2.0.0');
    expect(requiredVersion(v('1.4.2'), 'minor')).toBe('1.5.0');
  });

  it('hashes build content the same regardless of line endings', () => {
    const mk = (eol: string) => {
      const d = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-hash-'));
      fs.mkdirSync(path.join(d, 'src'));
      fs.writeFileSync(path.join(d, 'src', 'a.ts'), `one${eol}two${eol}`);
      fs.writeFileSync(path.join(d, 'package.json'), `{"version":"1.0.0"}${eol}`);
      return d;
    };
    const lf = mk('\n');
    const crlf = mk('\r\n');
    try {
      expect(contentHash(lf)).toBe(contentHash(crlf));
      fs.writeFileSync(path.join(lf, 'src', 'a.ts'), 'one\nthree\n');
      expect(contentHash(lf)).not.toBe(contentHash(crlf));
    } finally {
      fs.rmSync(lf, { recursive: true, force: true });
      fs.rmSync(crlf, { recursive: true, force: true });
    }
  });
});

describe('build identity (src/build-info.ts)', () => {
  let dir: string;
  beforeEach(() => { dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-buildinfo-')); });
  afterEach(() => { fs.rmSync(dir, { recursive: true, force: true }); });

  it('reads the stamped build and tolerates a missing or broken file', () => {
    expect(readBuildInfo(dir)).toBeNull();
    fs.writeFileSync(path.join(dir, 'build-info.json'), '{not json');
    expect(readBuildInfo(dir)).toBeNull();
    fs.writeFileSync(path.join(dir, 'build-info.json'), JSON.stringify({ version: '1.0.0', commit: 'abc', builtAt: 't', dirty: false }));
    expect(readBuildInfo(dir)).toEqual({ version: '1.0.0', commit: 'abc', builtAt: 't', dirty: false });
  });

  it('flags a restart when the scripts on disk come from another build', () => {
    const loaded = { version: '1.0.0', commit: 'abc', builtAt: null, dirty: false };
    expect(restartNeeded(loaded, null)).toBe(false);
    expect(restartNeeded(loaded, { ...loaded })).toBe(false);
    expect(restartNeeded(loaded, { ...loaded, commit: 'def' })).toBe(true);
    expect(restartNeeded(loaded, { ...loaded, version: '1.1.0' })).toBe(true);
  });
});

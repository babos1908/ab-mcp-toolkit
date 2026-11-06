import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { spawnSync } from 'child_process';

// The release guard on throw-away git repositories: one scenario per rule.
// It is the first step of `npm run build`, and a build of this project is a
// release (npm link serves it to every session on the machine).

const GUARD = path.join(__dirname, '..', '..', 'scripts', 'release-guard.js');
const HAS_GIT = spawnSync('git', ['--version']).status === 0;

const ENV = {
  ...process.env,
  GIT_AUTHOR_NAME: 'test', GIT_AUTHOR_EMAIL: 'test@example.invalid',
  GIT_COMMITTER_NAME: 'test', GIT_COMMITTER_EMAIL: 'test@example.invalid',
};

const tool = (name: string, params = "path: z.string()") =>
  `s.tool('${name}', 'desc', { ${params} }, async () => ({}));\n`;
const BASE = tool('alpha') + tool('beta');

let root: string;

function git(...args: string[]) {
  const r = spawnSync('git', ['-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false', '-c', 'core.autocrlf=false', ...args],
    { cwd: root, env: ENV, encoding: 'utf-8' });
  if (r.status !== 0) throw new Error(`git ${args.join(' ')}: ${r.stderr}`);
  return r.stdout.trim();
}
function write(version: string, server: string) {
  fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({ name: 'x', version }, null, 2));
  fs.mkdirSync(path.join(root, 'src'), { recursive: true });
  fs.writeFileSync(path.join(root, 'src', 'server.ts'), `const s = server as any;\n${server}`);
}
function commit(msg: string) { git('add', '-A'); git('commit', '-q', '-m', msg); }
function release(version: string, server: string) { write(version, server); commit(version); git('tag', `v${version}`); }
function guard() {
  const r = spawnSync(process.execPath, [GUARD, root], { encoding: 'utf-8' });
  return { ok: r.status === 0, out: r.stderr + r.stdout };
}

describe.skipIf(!HAS_GIT)('release guard', () => {
  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-guard-'));
    git('init', '-q');
  });
  afterEach(() => { fs.rmSync(root, { recursive: true, force: true }); });

  it('lets the first release through', () => {
    write('1.0.0', BASE); commit('init');
    const r = guard();
    expect(r.ok, r.out).toBe(true);
    expect(r.out).toContain('first release');
  });

  it('refuses a version that is not SemVer (four numbers)', () => {
    write('1.0.0.0', BASE); commit('init');
    const r = guard();
    expect(r.ok).toBe(false);
    expect(r.out).toContain('not a SemVer 2.0.0 version');
  });

  it('refuses uncommitted changes in src', () => {
    write('1.0.0', BASE); commit('init');
    fs.appendFileSync(path.join(root, 'src', 'server.ts'), '// edit\n');
    const r = guard();
    expect(r.ok).toBe(false);
    expect(r.out).toContain('uncommitted changes');
  });

  it('refuses to reuse a released number for different content -- the 0.6.2 problem', () => {
    release('1.0.0', BASE);
    write('1.0.0', BASE + '// a fix\n'); commit('fix without a bump');
    const r = guard();
    expect(r.ok).toBe(false);
    expect(r.out).toContain('v1.0.0 is already released with different content');
  });

  it('allows rebuilding a released version from identical content', () => {
    release('1.0.0', BASE);
    fs.writeFileSync(path.join(root, 'README.md'), 'docs only\n'); commit('docs');
    expect(guard().ok).toBe(true);
  });

  it('accepts a PATCH for a fix that does not touch the tool API', () => {
    release('1.0.0', BASE);
    write('1.0.1', BASE + '// a fix\n'); commit('fix');
    expect(guard().ok).toBe(true);
  });

  it('refuses a PATCH that adds a tool, and names the version needed', () => {
    release('1.0.0', BASE);
    write('1.0.1', BASE + tool('gamma')); commit('new tool');
    const r = guard();
    expect(r.ok).toBe(false);
    expect(r.out).toContain('Needs at least 1.1.0');
    expect(r.out).toContain('MINOR  tool added: gamma');
  });

  it('accepts a MINOR, or a MINOR pre-release, that adds a tool', () => {
    release('1.0.0', BASE);
    write('1.1.0-rc.1', BASE + tool('gamma')); commit('new tool');
    expect(guard().ok).toBe(true);
  });

  it('refuses a MINOR that removes a tool; accepts the MAJOR', () => {
    release('1.0.0', BASE);
    write('1.1.0', tool('alpha')); commit('drop beta');
    const r = guard();
    expect(r.ok).toBe(false);
    expect(r.out).toContain('Needs at least 2.0.0');
    expect(r.out).toContain('MAJOR  tool removed: beta');
    write('2.0.0', tool('alpha')); commit('major');
    expect(guard().ok).toBe(true);
  });

  it('refuses a version lower than the last release', () => {
    release('1.0.0', BASE);
    write('0.9.0', BASE); commit('down');
    const r = guard();
    expect(r.ok).toBe(false);
    expect(r.out).toContain('lower than the last release');
  });

  it('refuses rebuilding a number already built here from other content', () => {
    write('1.1.0-rc.1', BASE); commit('rc');
    fs.mkdirSync(path.join(root, 'dist'));
    fs.writeFileSync(path.join(root, 'dist', 'build-info.json'),
      JSON.stringify({ version: '1.1.0-rc.1', commit: 'abc1234', contentHash: 'deadbeef', builtAt: 'yesterday' }));
    const r = guard();
    expect(r.ok).toBe(false);
    expect(r.out).toContain('already built here from different content');
  });
});

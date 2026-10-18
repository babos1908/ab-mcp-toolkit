import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { CodesysLauncher } from '../../src/launcher';
import { IpcClient, DEFAULT_IPC_CONFIG } from '../../src/ipc';

// 2026-10-18: a live session's IPC dir was deleted from under its watcher.
// These tests pin the rules that stop one MCP server from taking over or
// breaking another server's live AB session. They run on a PRIVATE session
// folder (sessionBaseDir): the default one is shared by every server on the
// machine, and adoption/cleanup act on whatever lives there.

const DEAD_PID = 999_999; // treated as dead by isPidAlive on any sane machine

let base: string;
let launchers: CodesysLauncher[] = [];
let probed: string[] = [];

function makeLauncher(projects: Record<string, string | null> = {}): CodesysLauncher {
  const l = new CodesysLauncher({
    codesysPath: 'C:\\nonexistent\\AutomationBuilder.exe',
    profileName: 'Test Profile',
    workspaceDir: base,
    sessionBaseDir: base,
  });
  // No real watcher here: answer the live probe from a table.
  (l as any).probeSession = async (dir: string) => {
    const id = path.basename(dir);
    probed.push(id);
    return { alive: true, projectPath: projects[id] ?? null };
  };
  launchers.push(l);
  return l;
}

function makeSession(id: string, opts: {
  owner?: { serverPid: number | null } | 'none';
  abPid?: number | null;
  heartbeatAgeS?: number;
} = {}): string {
  const dir = path.join(base, id);
  fs.mkdirSync(path.join(dir, 'commands'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'results'), { recursive: true });
  const hb = path.join(dir, 'heartbeat.signal');
  fs.writeFileSync(hb, String(Date.now()));
  if (opts.heartbeatAgeS) {
    const t = (Date.now() - opts.heartbeatAgeS * 1000) / 1000;
    fs.utimesSync(hb, t, t);
  }
  const abPid = opts.abPid === undefined ? process.pid : opts.abPid; // an alive pid
  if (abPid !== null) fs.writeFileSync(path.join(dir, 'ready.signal'), JSON.stringify({ pid: abPid }));
  const owner = opts.owner ?? 'none';
  if (owner !== 'none') fs.writeFileSync(path.join(dir, 'owner.json'), JSON.stringify(owner));
  return dir;
}

const ownerOf = (dir: string) => JSON.parse(fs.readFileSync(path.join(dir, 'owner.json'), 'utf-8'));

beforeEach(() => {
  base = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-sessions-test-'));
  launchers = [];
  probed = [];
});

afterEach(() => {
  for (const l of launchers) (l as any).stopHealthMonitor?.();
  fs.rmSync(base, { recursive: true, force: true });
});

describe('adoptExisting owner-guard', () => {
  it('never adopts a session driven by another LIVE MCP server, even when its project matches', async () => {
    makeSession('other-agent', { owner: { serverPid: process.ppid } });
    const l = makeLauncher({ 'other-agent': 'C:\\p\\MPLUS_IO.project' });
    expect(await l.adoptExisting('C:\\p\\MPLUS_IO.project')).toBe(false);
    expect(await l.adoptExisting()).toBe(false);
    expect(probed).toEqual([]); // not even probed
    expect(l.lastAdoptionSkips[0].reason).toMatch(/another live MCP server/);
  });

  it('without a project, does not adopt a session with a project open and no ownership marker (the 2026-10-18 hole)', async () => {
    makeSession('legacy-busy');
    const l = makeLauncher({ 'legacy-busy': 'C:\\p\\Other.project' });
    expect(await l.adoptExisting()).toBe(false);
    expect(l.lastAdoptionSkips[0]).toMatchObject({ sessionId: 'legacy-busy', projectPath: 'C:\\p\\Other.project' });
  });

  it('without a project, adopts a session released by a keep-alive detach (the recycle case)', async () => {
    const dir = makeSession('released', { owner: { serverPid: null } });
    const l = makeLauncher({ released: 'C:\\p\\Mine.project' });
    expect(await l.adoptExisting()).toBe(true);
    expect(ownerOf(dir).serverPid).toBe(process.pid); // and now it is ours
  });

  it('without a project, adopts an orphan whose server died', async () => {
    makeSession('orphan', { owner: { serverPid: DEAD_PID } });
    const l = makeLauncher({ orphan: 'C:\\p\\Mine.project' });
    expect(await l.adoptExisting()).toBe(true);
  });

  it('without a project, still adopts an idle session from an older server (no marker, nothing open)', async () => {
    makeSession('legacy-idle');
    const l = makeLauncher({ 'legacy-idle': null });
    expect(await l.adoptExisting()).toBe(true);
  });

  it('with a project, adopts the session that has it open and passes over the one that has another', async () => {
    makeSession('theirs');
    const mine = makeSession('mine');
    const l = makeLauncher({ theirs: 'C:\\p\\Theirs.project', mine: 'C:\\p\\Mine.project' });
    expect(await l.adoptExisting('C:\\p\\Mine.project')).toBe(true);
    expect(l.getStatus().ipcDir).toBe(mine);
  });

  it('a keep-alive detach releases ownership so the next server can adopt without a project', async () => {
    const dir = makeSession('s', { owner: { serverPid: null } });
    const first = makeLauncher({ s: 'C:\\p\\Mine.project' });
    expect(await first.adoptExisting()).toBe(true);
    expect(ownerOf(dir).serverPid).toBe(process.pid);
    await first.detachKeepAlive();
    expect(ownerOf(dir).serverPid).toBeNull();
    const next = makeLauncher({ s: 'C:\\p\\Mine.project' });
    expect(await next.adoptExisting()).toBe(true);
  });
});

describe('IPC dir cleanup never removes a live watcher\'s folder', () => {
  async function adopted(dir: string, id: string) {
    const l = makeLauncher({ [id]: null });
    expect(await l.adoptExisting()).toBe(true);
    expect(l.getStatus().ipcDir).toBe(dir);
    return l;
  }

  it('keeps the folder while the AB process is alive', async () => {
    const dir = makeSession('alive', { owner: { serverPid: null } });
    const l = await adopted(dir, 'alive');
    await (l as any).cleanupIpcDirIfWatcherGone('test');
    expect(fs.existsSync(dir)).toBe(true);
    expect(ownerOf(dir).serverPid).toBeNull(); // released instead
  });

  it('pid unknown: keeps the folder while the heartbeat is fresh, removes it once the watcher is gone', async () => {
    const dir = makeSession('nopid', { owner: { serverPid: null }, abPid: null });
    const l = await adopted(dir, 'nopid');
    await (l as any).cleanupIpcDirIfWatcherGone('test');
    expect(fs.existsSync(dir)).toBe(true);
    const old = (Date.now() - 120_000) / 1000;
    fs.utimesSync(path.join(dir, 'heartbeat.signal'), old, old);
    await (l as any).cleanupIpcDirIfWatcherGone('test');
    expect(fs.existsSync(dir)).toBe(false);
  });

  it('removes the folder once the AB process has exited', async () => {
    const dir = makeSession('exited', { owner: { serverPid: null } });
    const l = await adopted(dir, 'exited');
    (l as any).pid = DEAD_PID;
    await (l as any).cleanupIpcDirIfWatcherGone('test');
    expect(fs.existsSync(dir)).toBe(false);
  });
});

describe('a session folder deleted from under a live watcher', () => {
  it('diagnose() reports it MISSING instead of "Healthy"', async () => {
    const dir = makeSession('gone', { owner: { serverPid: null } });
    const l = makeLauncher({ gone: null });
    expect(await l.adoptExisting()).toBe(true);
    fs.rmSync(dir, { recursive: true, force: true });
    const d = await l.diagnose();
    expect(d.ipcDirIntact).toBe(false);
    expect(d.interpretation).toMatch(/MISSING/);
    expect(d.interpretation).not.toMatch(/^Healthy/);
  });

  it('the IPC client recreates commands/ and results/ on the next send instead of failing with ENOENT', async () => {
    const dir = path.join(base, 'selfheal');
    const ipc = new IpcClient({ baseDir: dir, ...DEFAULT_IPC_CONFIG, commandTimeoutMs: 300 });
    await ipc.ensureDirectories();
    fs.rmSync(dir, { recursive: true, force: true });
    let err: unknown = null;
    try {
      await ipc.sendCommand('print("x")', 300); // no watcher here: it times out
    } catch (e) {
      err = e;
    }
    expect(String(err ?? '')).not.toMatch(/ENOENT/);
    expect(fs.existsSync(path.join(dir, 'commands'))).toBe(true);
    expect(fs.existsSync(path.join(dir, 'results'))).toBe(true);
  });
});

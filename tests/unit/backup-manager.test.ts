import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { BackupManager } from '../../src/backup-manager';

// Five timestamped auto-backups of one project plus files that must never be
// touched: the project itself, a manual '.backup' and an unrelated file.
function seed(dir: string): void {
  fs.writeFileSync(path.join(dir, 'P.project'), 'current');
  for (let i = 1; i <= 5; i++) {
    fs.writeFileSync(path.join(dir, `P.project.backup-2026101${i}T120000Z`), `v${i}`);
  }
  fs.writeFileSync(path.join(dir, 'P.project.backup'), 'manual');
  fs.writeFileSync(path.join(dir, 'notes.txt'), 'x');
}

function autoBackups(dir: string): string[] {
  return fs.readdirSync(dir).filter((n) => /\.backup-\d{8}T\d{6}Z$/.test(n)).sort();
}

describe('BackupManager.cleanupDir', () => {
  let dir: string;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'codesys-mcp-backup-'));
    seed(dir);
  });
  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('keep=0 deletes every auto-backup (regression: answered "removed 0")', () => {
    const mgr = new BackupManager({ autoBackup: true, retention: 5 });
    const s = mgr.cleanupDir(dir, 0);
    expect(s).toMatchObject({ examined: 5, removed: 5, kept: 0 });
    expect(autoBackups(dir)).toEqual([]);
    // Never touched: the source, the manual backup, unrelated files.
    expect(fs.existsSync(path.join(dir, 'P.project'))).toBe(true);
    expect(fs.existsSync(path.join(dir, 'P.project.backup'))).toBe(true);
    expect(fs.existsSync(path.join(dir, 'notes.txt'))).toBe(true);
  });

  it('keep=N keeps the newest N', () => {
    const mgr = new BackupManager({ autoBackup: true, retention: 5 });
    const s = mgr.cleanupDir(dir, 2);
    expect(s).toMatchObject({ examined: 5, removed: 3, kept: 2 });
    expect(autoBackups(dir)).toEqual([
      'P.project.backup-20261014T120000Z',
      'P.project.backup-20261015T120000Z',
    ]);
  });

  it('default keep follows the retention setting', () => {
    const mgr = new BackupManager({ autoBackup: true, retention: 3 });
    expect(mgr.cleanupDir(dir)).toMatchObject({ removed: 2, kept: 3 });
  });

  it('default with unbounded retention (<= 0) keeps everything', () => {
    const mgr = new BackupManager({ autoBackup: true, retention: 0 });
    expect(mgr.cleanupDir(dir)).toMatchObject({ examined: 5, removed: 0, kept: 5 });
    expect(autoBackups(dir)).toHaveLength(5);
  });
});

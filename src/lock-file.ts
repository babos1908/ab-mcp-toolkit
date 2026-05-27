/**
 * Lock-file utilities for CODESYS .project / .library files.
 *
 * CODESYS writes a sibling `<name>.lock` (or sometimes `<name>.project.~u`,
 * `<name>.~u`) when it has a project open, and removes them on clean
 * shutdown. After a hard kill (taskkill, BSOD, force_reset_watcher) these
 * stale files survive and cause "selected project is currently in use by
 * 'X' on 'Y'" on the next open_project attempt.
 *
 * The lock file format is loosely documented; what we know empirically:
 *
 *   - It's typically a text file containing at minimum the username + host
 *     that wrote it. Some builds also include the PID of the CODESYS
 *     process holding the lock; others don't.
 *   - The naming pattern is `<base>.lock` next to `<base>.project` or
 *     `<base>.library`.
 *
 * Strategy:
 *
 *   1. If we can extract a PID from the lock file content AND that PID is
 *      not alive, the lock is stale -- safe to delete.
 *   2. If we cannot extract a PID, we can't be 100% sure the lock is
 *      stale. We fall back to checking whether ANY CODESYS-like process
 *      is alive on this machine; if none, the lock is almost certainly
 *      stale and we delete it.
 *   3. If neither check resolves cleanly, leave the file alone and let
 *      the caller surface a clear error to the user.
 */
import * as fs from 'fs';
import * as path from 'path';
import { launcherLog } from './logger';

export interface LockInfo {
  path: string;
  pid: number | null;
  user: string | null;
  host: string | null;
  /** Raw file contents, capped at first 512 bytes for diagnostics. */
  rawSample: string;
}

/**
 * Look up the .lock file next to a .project/.library file. Returns null
 * if no lock exists.
 */
export function findLockFor(projectFilePath: string): LockInfo | null {
  const ext = path.extname(projectFilePath);
  const base = projectFilePath.slice(0, projectFilePath.length - ext.length);
  const candidates = [
    `${base}.lock`,
    `${projectFilePath}.lock`, // less common, but seen in some builds
  ];
  for (const lp of candidates) {
    if (fs.existsSync(lp)) {
      return readLockFile(lp);
    }
  }
  return null;
}

/**
 * Parse a .lock file into structured fields. Tolerant of unknown formats:
 * returns nulls for anything we can't extract.
 */
export function readLockFile(lockPath: string): LockInfo {
  let raw = '';
  try {
    raw = fs.readFileSync(lockPath, 'utf-8');
  } catch {
    // Fall through with empty raw.
  }
  // Common patterns observed:
  //   user=Admin
  //   host=XCORE360
  //   pid=12345
  //   PID:12345
  // The fields can appear in any order; do simple regex scans.
  const pidMatch = raw.match(/\bpid\s*[:=]\s*(\d+)/i);
  const userMatch = raw.match(/\buser\s*[:=]\s*([^\s\r\n]+)/i);
  const hostMatch = raw.match(/\bhost\s*[:=]\s*([^\s\r\n]+)/i);
  return {
    path: lockPath,
    pid: pidMatch ? parseInt(pidMatch[1], 10) : null,
    user: userMatch ? userMatch[1] : null,
    host: hostMatch ? hostMatch[1] : null,
    rawSample: raw.slice(0, 512),
  };
}

/**
 * Check whether a PID is currently alive on this machine. Returns true if
 * the process exists, false if not, and null if we cannot determine
 * (permission denied, etc.).
 */
export function isPidAlive(pid: number): boolean | null {
  if (!Number.isFinite(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0); // signal 0 = check existence
    return true;
  } catch (err: any) {
    if (err && err.code === 'ESRCH') return false;
    if (err && err.code === 'EPERM') return true; // exists but we can't signal
    return null;
  }
}

/**
 * Decide whether a lock is stale (safe to delete).
 *
 *   - PID extracted AND dead -> stale
 *   - PID extracted AND alive -> NOT stale
 *   - PID not extractable -> 'unknown' (caller decides; usually leave alone)
 */
export type LockStaleness = 'stale' | 'live' | 'unknown';

export function classifyLock(info: LockInfo): LockStaleness {
  if (info.pid !== null) {
    const alive = isPidAlive(info.pid);
    if (alive === false) return 'stale';
    if (alive === true) return 'live';
    return 'unknown';
  }
  return 'unknown';
}

/**
 * Best-effort removal of a stale lock file. Returns true on success.
 * Logs but does not throw on permission errors -- the caller will surface
 * a clear "still locked" error if subsequent open_project still fails.
 */
export function removeLockFile(lockPath: string): boolean {
  try {
    fs.unlinkSync(lockPath);
    launcherLog.info(`Removed stale lock file: ${lockPath}`);
    return true;
  } catch (err) {
    launcherLog.warn(`Could not remove lock file ${lockPath}: ${err}`);
    return false;
  }
}

/**
 * Sweep a directory for *.lock files belonging to .project/.library siblings
 * and remove the ones that look stale. Used at launch_codesys startup to
 * preemptively clean up after a previous crashed session.
 *
 * Walks only the top level of the dir (no recursion) -- agents typically
 * know which workspace they care about, and broad recursion is risky.
 */
export function sweepStaleLocks(dir: string): {
  examined: number;
  removed: number;
  liveSkipped: number;
  unknownSkipped: number;
} {
  const summary = { examined: 0, removed: 0, liveSkipped: 0, unknownSkipped: 0 };
  let entries: string[] = [];
  try {
    entries = fs.readdirSync(dir);
  } catch {
    return summary;
  }
  for (const fn of entries) {
    if (!fn.toLowerCase().endsWith('.lock')) continue;
    const lockPath = path.join(dir, fn);
    summary.examined++;
    let info: LockInfo;
    try {
      info = readLockFile(lockPath);
    } catch {
      continue;
    }
    const cls = classifyLock(info);
    if (cls === 'stale') {
      if (removeLockFile(lockPath)) summary.removed++;
    } else if (cls === 'live') {
      summary.liveSkipped++;
    } else {
      summary.unknownSkipped++;
    }
  }
  if (summary.examined > 0) {
    launcherLog.info(
      `sweepStaleLocks(${dir}): examined=${summary.examined} removed=${summary.removed} ` +
      `liveSkipped=${summary.liveSkipped} unknownSkipped=${summary.unknownSkipped}`
    );
  }
  return summary;
}

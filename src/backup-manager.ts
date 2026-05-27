/**
 * BackupManager - takes filesystem snapshots of .project / .library files
 * BEFORE destructive MCP tools touch them. Recovery story:
 *
 *   1. Agent calls set_pou_code on the wrong POU.
 *   2. server.ts handler routes through BackupManager.snapshot(projectPath)
 *      BEFORE running the IronPython script.
 *   3. BackupManager copies the .project (and .library if a sibling
 *      <name>.library file is the actual target) to
 *      <path>.backup-YYYYMMDDTHHMMSSZ before the script runs.
 *   4. Agent or user discovers the mistake; they `cp <backup> <original>`
 *      manually to restore. The MCP doesn't auto-restore on error because
 *      that's domain-specific (the IronPython script may have partially
 *      succeeded and the user might prefer to keep partial work).
 *
 * Design notes:
 *
 *   - Snapshots live next to the source file (same dir) so they're easy
 *     to find. They're NOT auto-deleted; the agent/user owns cleanup.
 *   - The "destructive" classification is a hardcoded allowlist of tool
 *     names, not an open contract -- BackupManager itself just exposes
 *     snapshot(path). server.ts decides which tools call it.
 *   - Disabled via config.autoBackup === false (CLI: --no-auto-backup).
 *   - Multiple snapshots per session are fine; each gets a unique
 *     timestamp suffix. Disk-space cleanup is out of scope (could be a
 *     separate `cleanup_backups` tool if it becomes a problem).
 *   - We snapshot the .project file AND any sibling <basename>.library if
 *     present, because some destructive ops (install_library_to_repository,
 *     rebuild_library) modify the .library on disk.
 */
import * as fs from 'fs';
import * as path from 'path';
import { launcherLog } from './logger';

export interface BackupConfig {
  /** When false, snapshot() is a no-op. Default: true. */
  autoBackup: boolean;
}

export interface BackupResult {
  /** Whether a snapshot was actually taken (false = autoBackup off or path missing). */
  taken: boolean;
  /** Absolute paths of the backup files created (empty when taken=false). */
  backupPaths: string[];
  /** ISO timestamp suffix used for this snapshot batch. */
  timestamp: string;
}

export class BackupManager {
  constructor(private cfg: BackupConfig) {}

  /**
   * Take a filesystem snapshot of the given project/library file (and the
   * sibling .library if it exists) before a destructive operation runs.
   *
   * Best-effort: failures (read-only filesystem, permissions, disk full) are
   * logged as warnings and do NOT throw. The rationale is that a snapshot
   * failure should not block the user from completing legitimate work; if
   * they care enough to require backups, they can verify via the returned
   * BackupResult.
   *
   * @param sourcePath the .project or .library file the destructive op will modify
   */
  async snapshot(sourcePath: string): Promise<BackupResult> {
    const timestamp = isoTimestampForFilename(new Date());
    const result: BackupResult = { taken: false, backupPaths: [], timestamp };

    if (!this.cfg.autoBackup) {
      return result;
    }

    if (!sourcePath) {
      launcherLog.debug('BackupManager.snapshot called with empty path -- skipping');
      return result;
    }

    // Build list of files to snapshot: the source + sibling .library if any.
    const filesToBackup = new Set<string>();
    filesToBackup.add(sourcePath);
    // If sourcePath ends in .project, also snapshot any .library next to it.
    // If sourcePath ends in .library, snapshot it and also any sibling .project.
    try {
      const dir = path.dirname(sourcePath);
      const base = path.basename(sourcePath, path.extname(sourcePath));
      const projectVariant = path.join(dir, `${base}.project`);
      const libraryVariant = path.join(dir, `${base}.library`);
      if (fs.existsSync(projectVariant) && projectVariant !== sourcePath) {
        filesToBackup.add(projectVariant);
      }
      if (fs.existsSync(libraryVariant) && libraryVariant !== sourcePath) {
        filesToBackup.add(libraryVariant);
      }
    } catch (err) {
      launcherLog.debug(`BackupManager could not enumerate siblings: ${err}`);
    }

    for (const src of filesToBackup) {
      try {
        if (!fs.existsSync(src)) {
          // Project file doesn't exist yet (e.g. set_project_info on a freshly
          // created project that hasn't been saved). Skip silently.
          continue;
        }
        const dst = `${src}.backup-${timestamp}`;
        fs.copyFileSync(src, dst);
        result.backupPaths.push(dst);
        result.taken = true;
        launcherLog.info(`BackupManager: snapshot ${path.basename(src)} -> ${path.basename(dst)}`);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        launcherLog.warn(`BackupManager: failed to snapshot ${src}: ${msg}`);
      }
    }

    return result;
  }
}

/**
 * Render an ISO-8601-ish timestamp suitable for a filename suffix. Format:
 *     YYYYMMDDTHHMMSSZ
 * (UTC, no separators, terminated with Z). Sortable lexicographically.
 */
function isoTimestampForFilename(d: Date): string {
  const pad2 = (n: number): string => String(n).padStart(2, '0');
  const yyyy = d.getUTCFullYear();
  const mm = pad2(d.getUTCMonth() + 1);
  const dd = pad2(d.getUTCDate());
  const hh = pad2(d.getUTCHours());
  const mi = pad2(d.getUTCMinutes());
  const ss = pad2(d.getUTCSeconds());
  return `${yyyy}${mm}${dd}T${hh}${mi}${ss}Z`;
}

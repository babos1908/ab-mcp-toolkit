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
 *     to find.
 *   - The "destructive" classification is a hardcoded allowlist of tool
 *     names, not an open contract -- BackupManager itself just exposes
 *     snapshot(path). server.ts decides which tools call it.
 *   - Disabled via config.autoBackup === false (CLI: --no-auto-backup).
 *   - We snapshot the .project file AND any sibling <basename>.library if
 *     present, because some destructive ops (install_library_to_repository,
 *     rebuild_library) modify the .library on disk.
 *
 * Retention + dedup (2026-06-12): a dev session runs dozens of destructive
 * tools, and naively one snapshot per call left dozens of near-identical
 * <file>.backup-* files piling up forever -- pure clutter the user had to
 * clean by hand. Two bounds fix this at the root:
 *   1. DEDUP: if the source is byte-identical to the newest existing
 *      backup for that file, skip -- no point snapshotting an unchanged file
 *      (a set that read-back-verified to the same value, a repeated no-op).
 *   2. RETENTION: after writing, prune the file's own backups down to the
 *      newest `retention` (default 5). Only files matching this manager's
 *      exact `<basename>.backup-<TS>Z` pattern are ever deleted -- a manual
 *      `<name>.backup` or anything else is never touched.
 */
import * as fs from 'fs';
import * as path from 'path';
import { launcherLog } from './logger';

/** Default number of snapshots kept per source file. */
export const DEFAULT_BACKUP_RETENTION = 5;

/** Matches exactly the suffix this manager appends: `.backup-YYYYMMDDTHHMMSSZ`. */
const BACKUP_SUFFIX_RE = /\.backup-\d{8}T\d{6}Z$/;

export interface BackupConfig {
  /** When false, snapshot() is a no-op. Default: true. */
  autoBackup: boolean;
  /**
   * How many snapshots to keep per source file (newest wins). Older ones are
   * pruned after each snapshot. <= 0 disables pruning (unbounded, old
   * behaviour). Default: DEFAULT_BACKUP_RETENTION.
   */
  retention?: number;
}

export interface BackupResult {
  /** Whether a snapshot was actually taken (false = autoBackup off, path missing, or deduped). */
  taken: boolean;
  /** Absolute paths of the backup files created (empty when taken=false). */
  backupPaths: string[];
  /** ISO timestamp suffix used for this snapshot batch. */
  timestamp: string;
  /** Number of old backup files pruned by retention this call. */
  pruned: number;
}

export class BackupManager {
  constructor(private cfg: BackupConfig) {}

  private get retention(): number {
    return this.cfg.retention === undefined ? DEFAULT_BACKUP_RETENTION : this.cfg.retention;
  }

  /**
   * Take a filesystem snapshot of the given project/library file (and the
   * sibling .library if it exists) before a destructive operation runs.
   *
   * Best-effort: failures (read-only filesystem, permissions, disk full) are
   * logged as warnings and do NOT throw -- a snapshot failure must not block
   * legitimate work.
   *
   * @param sourcePath the .project or .library file the destructive op will modify
   */
  async snapshot(sourcePath: string): Promise<BackupResult> {
    const timestamp = isoTimestampForFilename(new Date());
    const result: BackupResult = { taken: false, backupPaths: [], timestamp, pruned: 0 };

    if (!this.cfg.autoBackup) {
      return result;
    }
    if (!sourcePath) {
      launcherLog.debug('BackupManager.snapshot called with empty path -- skipping');
      return result;
    }

    // Build list of files to snapshot: the source + sibling .library/.project.
    const filesToBackup = new Set<string>();
    filesToBackup.add(sourcePath);
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
        // DEDUP: if the newest existing backup is byte-identical to the source,
        // there's nothing new to preserve -- skip. This is what kills the bulk
        // of the clutter (read-back-verified sets, repeated no-op edits).
        const existing = this.listOwnBackups(src);
        if (existing.length > 0 && filesAreEqual(src, existing[0].full)) {
          launcherLog.debug(`BackupManager: ${path.basename(src)} unchanged vs newest backup -- skipping snapshot`);
        } else {
          const dst = `${src}.backup-${timestamp}`;
          fs.copyFileSync(src, dst);
          result.backupPaths.push(dst);
          result.taken = true;
          launcherLog.info(`BackupManager: snapshot ${path.basename(src)} -> ${path.basename(dst)}`);
        }
        // RETENTION: prune this file's own backups to the newest N regardless
        // of whether we just wrote one (handles a config that lowered N too).
        result.pruned += this.pruneOldBackups(src);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        launcherLog.warn(`BackupManager: failed to snapshot ${src}: ${msg}`);
      }
    }

    return result;
  }

  /**
   * List backups THIS manager created for a source file, newest first. Only
   * files matching `<basename>.backup-<TS>Z` exactly -- never a manual
   * `<name>.backup` or unrelated file. Returns {name, full} sorted desc by the
   * (lexicographically sortable) timestamp.
   */
  private listOwnBackups(src: string): Array<{ name: string; full: string }> {
    const dir = path.dirname(src);
    const prefix = `${path.basename(src)}.backup-`;
    let entries: string[] = [];
    try {
      entries = fs.readdirSync(dir);
    } catch {
      return [];
    }
    return entries
      .filter((n) => n.startsWith(prefix) && BACKUP_SUFFIX_RE.test(n))
      .map((n) => ({ name: n, full: path.join(dir, n) }))
      .sort((a, b) => (a.name < b.name ? 1 : a.name > b.name ? -1 : 0)); // newest first
  }

  /**
   * One-shot sweep of an existing pile of auto-backups (the new retention
   * only prunes going forward; past sessions left files behind). For every
   * source file in `dir` that has auto-backups, keep the newest `keep` and
   * delete the rest. Only `<basename>.backup-<TS>Z` files are ever deleted;
   * manual `<name>.backup` and unrelated files are never touched.
   *
   * @param dir directory to sweep (typically the project folder)
   * @param keep how many newest backups to keep per source (default: retention)
   * @returns summary of what was removed
   */
  cleanupDir(dir: string, keep?: number): { examined: number; removed: number; kept: number; perFile: Array<{ source: string; removed: number; kept: number }> } {
    const keepN = keep === undefined ? this.retention : keep;
    const summary = { examined: 0, removed: 0, kept: 0, perFile: [] as Array<{ source: string; removed: number; kept: number }> };
    let entries: string[] = [];
    try {
      entries = fs.readdirSync(dir);
    } catch (err) {
      launcherLog.warn(`BackupManager.cleanupDir: cannot read ${dir}: ${err}`);
      return summary;
    }
    // Group backup files by the source they belong to: name is
    // '<source>.backup-<TS>Z' -> source = everything before '.backup-<TS>Z'.
    const bySource = new Map<string, Array<{ name: string }>>();
    for (const n of entries) {
      const m = n.match(/^(.*)\.backup-\d{8}T\d{6}Z$/);
      if (!m) continue; // not our pattern (manual .backup, unrelated) -> skip
      const source = m[1];
      if (!bySource.has(source)) bySource.set(source, []);
      bySource.get(source)!.push({ name: n });
    }
    for (const [source, list] of bySource) {
      summary.examined += list.length;
      list.sort((a, b) => (a.name < b.name ? 1 : a.name > b.name ? -1 : 0)); // newest first
      const toRemove = keepN <= 0 ? [] : list.slice(keepN);
      let removedHere = 0;
      for (const b of toRemove) {
        try {
          fs.unlinkSync(path.join(dir, b.name));
          removedHere++;
        } catch (err) {
          launcherLog.debug(`BackupManager.cleanupDir: could not delete ${b.name}: ${err}`);
        }
      }
      summary.removed += removedHere;
      const keptHere = list.length - removedHere;
      summary.kept += keptHere;
      summary.perFile.push({ source, removed: removedHere, kept: keptHere });
    }
    launcherLog.info(`BackupManager.cleanupDir(${dir}): examined=${summary.examined} removed=${summary.removed} kept=${summary.kept}`);
    return summary;
  }

  /**
   * Delete old backups for `src` beyond `retention`. Returns the count pruned.
   * No-op when retention <= 0. Public-ish via snapshot(); also reusable by a
   * cleanup tool.
   */
  pruneOldBackups(src: string): number {
    const keep = this.retention;
    if (keep <= 0) return 0;
    const backups = this.listOwnBackups(src);
    if (backups.length <= keep) return 0;
    let pruned = 0;
    for (const b of backups.slice(keep)) {
      try {
        fs.unlinkSync(b.full);
        pruned++;
      } catch (err) {
        launcherLog.debug(`BackupManager: could not prune ${b.name}: ${err}`);
      }
    }
    if (pruned > 0) {
      launcherLog.info(`BackupManager: pruned ${pruned} old backup(s) of ${path.basename(src)} (kept newest ${keep})`);
    }
    return pruned;
  }
}

/** Byte-compare two files. Cheap size check first, then buffer compare. */
function filesAreEqual(a: string, b: string): boolean {
  try {
    const sa = fs.statSync(a);
    const sb = fs.statSync(b);
    if (sa.size !== sb.size) return false;
    return fs.readFileSync(a).equals(fs.readFileSync(b));
  } catch {
    return false;
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

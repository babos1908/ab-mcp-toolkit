/**
 * Which build is this? dist/build-info.json is written by
 * scripts/write-build-info.js at the end of every `npm run build`.
 *
 * The server reads it ONCE at startup: that is the build its TypeScript
 * came from. The Python scripts, however, are re-read from dist/scripts on
 * every call, so after a newer build they belong to that build while the
 * server keeps its old handlers until Claude Code restarts. Reading the
 * file again at call time shows that skew.
 */
import * as fs from 'fs';
import * as path from 'path';

export interface BuildInfo {
  version: string;
  commit: string | null;
  builtAt: string | null;
  dirty: boolean | null;
}

export function readBuildInfo(distDir: string): BuildInfo | null {
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(distDir, 'build-info.json'), 'utf-8'));
    if (typeof raw.version !== 'string' || !raw.version) return null;
    return {
      version: raw.version,
      commit: typeof raw.commit === 'string' ? raw.commit : null,
      builtAt: typeof raw.builtAt === 'string' ? raw.builtAt : null,
      dirty: typeof raw.dirty === 'boolean' ? raw.dirty : null,
    };
  } catch {
    return null;
  }
}

/** True when the build on disk is not the one this process started with. */
export function restartNeeded(loaded: BuildInfo, onDisk: BuildInfo | null): boolean {
  if (!onDisk) return false;
  return onDisk.version !== loaded.version || onDisk.commit !== loaded.commit;
}

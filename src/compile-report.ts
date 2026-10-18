/**
 * Parsing + formatting for what compile_project / get_compile_messages print
 * besides the error/warning list: the memory-usage lines and the build-cache
 * file report.
 *
 * Memory lines (field-captured 2026-10-17, AB 2.9 SP19, AC500 V3 PM5032; the
 * decimal separator follows the Windows locale, so "50,53%" and "50.53%" both
 * occur). Category "Memory Usage" (ee56da69-d42b-478e-bd3c-2b4494e512c6):
 *   User program code and data: Variables = 216955, POUs = 47952, Total = 264907 bytes (50,53%) Further details available in Statistics view.
 *   Total maximum downloadable application size: 1144344 bytes from 5242880 bytes (21,83%) Further details available in Statistics view.
 * Category "Build" (severity info):
 *   Memory usage on device, not used for licensing purposes:
 *   Memory area 0 contains  Data, Input, Output, Code and Nonsafe data: size: 5242880 bytes, highest used address: 1144344, largest contiguous memory gap: 4098536 bytes (78 %)
 *   Memory area 2 contains  Retain data and Persistent data: size: 16296 bytes, largest contiguous memory gap: 16287 bytes (99 %)
 * They are info-severity, so the error/warning filter used to drop them and
 * the only way to read them was a screenshot of the Messages window.
 */

export interface CompileMessage {
  severity: string;
  text: string;
  object?: string;
  line?: number;
  category?: string;
  code?: string;
}

export interface MemoryArea {
  area: number;
  contains: string;
  sizeBytes: number | null;
  highestUsedAddress: number | null;
  largestGapBytes: number | null;
  /** Percentage printed after the gap (the gap as a share of the area). */
  largestGapPercent: number | null;
}

export interface MemoryUsage {
  /** "User program code and data" line. */
  userProgram?: {
    variablesBytes: number;
    pousBytes: number;
    totalBytes: number;
    percent: number | null;
  };
  /** "Total maximum downloadable application size" line. */
  downloadable?: {
    usedBytes: number;
    maxBytes: number;
    percent: number | null;
  };
  areas: MemoryArea[];
  /** Every memory line verbatim, in the order received (nothing is lost if a format changes). */
  raw: string[];
}

export interface CacheFileReport {
  incremental: boolean;
  before: string[];
  afterClean?: string[] | null;
  after: string[];
  /** Present before the call, missing after it. */
  removed: string[];
}

/** Percentages only ("50,53" or "50.53" depending on the locale). */
function num(s: string | undefined): number | null {
  if (s === undefined) return null;
  const n = Number(s.replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

const RE_USER = /User program code and data:\s*Variables\s*=\s*(\d+),\s*POUs\s*=\s*(\d+),\s*Total\s*=\s*(\d+)\s*bytes(?:\s*\(\s*([\d.,]+)\s*%\s*\))?/i;
const RE_DOWNLOADABLE = /Total maximum downloadable application size:\s*(\d+)\s*bytes\s*from\s*(\d+)\s*bytes(?:\s*\(\s*([\d.,]+)\s*%\s*\))?/i;
const RE_AREA = /Memory area\s+(\d+)\s+contains\s+(.*?):\s*size:\s*(\d+)\s*bytes/i;
const RE_HIGHEST = /highest used address:\s*(\d+)/i;
const RE_GAP = /largest contiguous memory gap:\s*(\d+)\s*bytes(?:\s*\(\s*([\d.,]+)\s*%\s*\))?/i;

/** True for a message line that belongs to the memory report. */
export function isMemoryLine(text: string): boolean {
  return (
    /User program code and data:/i.test(text) ||
    /Total maximum downloadable application size:/i.test(text) ||
    /^\s*Memory area\s+\d+\s+contains/i.test(text) ||
    /^\s*Memory usage on device/i.test(text)
  );
}

/**
 * Turn the raw memory lines into a structured object. Returns null when no
 * line is a memory line (e.g. a build that failed before code generation).
 * Duplicate lines (the same message read from two categories) are collapsed.
 */
export function parseMemoryUsage(lines: string[]): MemoryUsage | null {
  const raw: string[] = [];
  const seen = new Set<string>();
  for (const l of lines) {
    const t = String(l ?? '').trim();
    if (!t || !isMemoryLine(t) || seen.has(t)) continue;
    seen.add(t);
    raw.push(t);
  }
  if (raw.length === 0) return null;

  const mu: MemoryUsage = { areas: [], raw };
  const areaSeen = new Set<number>();
  for (const t of raw) {
    let m = RE_USER.exec(t);
    if (m) {
      mu.userProgram = {
        variablesBytes: Number(m[1]),
        pousBytes: Number(m[2]),
        totalBytes: Number(m[3]),
        percent: num(m[4]),
      };
      continue;
    }
    m = RE_DOWNLOADABLE.exec(t);
    if (m) {
      mu.downloadable = { usedBytes: Number(m[1]), maxBytes: Number(m[2]), percent: num(m[3]) };
      continue;
    }
    m = RE_AREA.exec(t);
    if (m) {
      const area = Number(m[1]);
      if (areaSeen.has(area)) continue;
      areaSeen.add(area);
      const hi = RE_HIGHEST.exec(t);
      const gap = RE_GAP.exec(t);
      mu.areas.push({
        area,
        contains: m[2].replace(/\s+/g, ' ').trim(),
        sizeBytes: Number(m[3]),
        highestUsedAddress: hi ? Number(hi[1]) : null,
        largestGapBytes: gap ? Number(gap[1]) : null,
        largestGapPercent: gap ? num(gap[2]) : null,
      });
    }
  }
  mu.areas.sort((a, b) => a.area - b.area);
  return mu;
}

/** One- or two-line human summary for the tool response. */
export function formatMemorySummary(mu: MemoryUsage): string {
  const parts: string[] = [];
  if (mu.userProgram) {
    const p = mu.userProgram.percent != null ? ` (${mu.userProgram.percent}%)` : '';
    parts.push(
      `user program ${mu.userProgram.totalBytes} B${p} = variables ${mu.userProgram.variablesBytes} + POUs ${mu.userProgram.pousBytes}`
    );
  }
  if (mu.downloadable) {
    const p = mu.downloadable.percent != null ? ` (${mu.downloadable.percent}%)` : '';
    parts.push(`downloadable ${mu.downloadable.usedBytes} of ${mu.downloadable.maxBytes} B${p}`);
  }
  for (const a of mu.areas) {
    const gap = a.largestGapBytes != null ? `, largest gap ${a.largestGapBytes} B` : '';
    parts.push(`area ${a.area} (${a.contains}) ${a.sizeBytes ?? '?'} B${gap}`);
  }
  return parts.length ? `Memory: ${parts.join('; ')}` : `Memory: ${mu.raw.join(' | ')}`;
}

/** Report on .compileinfo / .bootinfo / .precompilecache files touched by the build. */
export function formatCacheReport(c: CacheFileReport): string {
  if (c.removed.length === 0) {
    return c.incremental
      ? 'Build cache files: incremental build, nothing removed.'
      : 'Build cache files: clean() ran, no cache file was removed.';
  }
  return (
    `Build cache files REMOVED by clean() and not regenerated (${c.removed.length}): ${c.removed.join(', ')}. ` +
    'A scripted build does not rewrite them -- only a download / online change (.compileinfo) or a boot ' +
    'application (.bootinfo) does; restore tracked copies with git, or pass incremental=true to skip clean().'
  );
}

/** Parse the ### COMPILE_MESSAGES_START/END ### block both compile tools print. */
export function parseCompileMessagesBlock(output: string): CompileMessage[] {
  const start = '### COMPILE_MESSAGES_START ###';
  const end = '### COMPILE_MESSAGES_END ###';
  const s = output.indexOf(start);
  const e = output.indexOf(end);
  if (s === -1 || e === -1 || s >= e) return [];
  try {
    const parsed = JSON.parse(output.substring(s + start.length, e).trim());
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

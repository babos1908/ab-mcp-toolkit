import { describe, it, expect } from 'vitest';
import {
  parseMemoryUsage,
  formatMemorySummary,
  formatCacheReport,
  isMemoryLine,
  parseCompileMessagesBlock,
} from '../../src/compile-report';

// Verbatim from a live build of an AC500 V3 PM5032 project (AB 2.9 SP19,
// Italian Windows locale -> decimal comma), 2026-10-17.
const LIVE_LINES = [
  'Memory usage on device, not used for licensing purposes:',
  'Memory area 0 contains  Data, Input, Output, Code and Nonsafe data: size: 5242880 bytes, highest used address: 1144344, largest contiguous memory gap: 4098536 bytes (78 %)',
  'Memory area 1 contains  Memory: size: 16384 bytes, highest used address: 16384, largest contiguous memory gap: 0 bytes (0 %)',
  'Memory area 2 contains  Retain data and Persistent data: size: 16296 bytes, largest contiguous memory gap: 16287 bytes (99 %)',
  'User program code and data: Variables = 216955, POUs = 47952, Total = 264907 bytes (50,53%) Further details available in Statistics view.',
  'Total maximum downloadable application size: 1144344 bytes from 5242880 bytes (21,83%) Further details available in Statistics view.',
];

describe('parseMemoryUsage', () => {
  it('parses the live AB 2.9 memory lines', () => {
    const mu = parseMemoryUsage(LIVE_LINES)!;
    expect(mu.userProgram).toEqual({ variablesBytes: 216955, pousBytes: 47952, totalBytes: 264907, percent: 50.53 });
    expect(mu.downloadable).toEqual({ usedBytes: 1144344, maxBytes: 5242880, percent: 21.83 });
    expect(mu.areas).toHaveLength(3);
    expect(mu.areas[0]).toEqual({
      area: 0,
      contains: 'Data, Input, Output, Code and Nonsafe data',
      sizeBytes: 5242880,
      highestUsedAddress: 1144344,
      largestGapBytes: 4098536,
      largestGapPercent: 78,
    });
    // Area 2 has no "highest used address" in the real output.
    expect(mu.areas[2]).toMatchObject({ area: 2, contains: 'Retain data and Persistent data', highestUsedAddress: null, largestGapBytes: 16287 });
    expect(mu.raw).toHaveLength(6);
  });

  it('accepts a decimal point locale too', () => {
    const mu = parseMemoryUsage(['User program code and data: Variables = 1, POUs = 2, Total = 3 bytes (12.5%)'])!;
    expect(mu.userProgram?.percent).toBe(12.5);
  });

  it('collapses duplicates (same line read from two categories) and ignores non-memory lines', () => {
    const mu = parseMemoryUsage([
      '------ Build started: Application: PLC_AC500_V3.Application -------',
      LIVE_LINES[5],
      LIVE_LINES[5],
      'Build complete -- 0 errors, 2 warnings : Ready for download',
    ])!;
    expect(mu.raw).toEqual([LIVE_LINES[5]]);
    expect(mu.userProgram).toBeUndefined();
    expect(mu.areas).toEqual([]);
  });

  it('returns null when there is no memory line (failed build)', () => {
    expect(parseMemoryUsage(['Build complete -- 2 errors, 2 warnings : No download possible'])).toBeNull();
    expect(parseMemoryUsage([])).toBeNull();
  });

  it('keeps an unknown memory-line format in raw instead of dropping it', () => {
    const odd = 'Memory area 7 contains something new';
    const mu = parseMemoryUsage([odd])!;
    expect(mu.raw).toEqual([odd]);
    expect(mu.areas).toEqual([]);
    expect(formatMemorySummary(mu)).toContain(odd);
  });

  it('summary names the numbers a user looks for', () => {
    const s = formatMemorySummary(parseMemoryUsage(LIVE_LINES)!);
    expect(s).toContain('user program 264907 B (50.53%)');
    expect(s).toContain('downloadable 1144344 of 5242880 B (21.83%)');
    expect(s).toContain('area 0 (Data, Input, Output, Code and Nonsafe data) 5242880 B');
  });
});

describe('isMemoryLine', () => {
  it('does not match ordinary build text', () => {
    expect(isMemoryLine('Generate code...')).toBe(false);
    expect(isMemoryLine('The application is up to date')).toBe(false);
  });
});

describe('formatCacheReport', () => {
  it('names the removed files and why they stay missing', () => {
    const txt = formatCacheReport({
      incremental: false,
      before: ['P.Dev.App.x.compileinfo', 'P_project.precompilecache'],
      after: ['P_project.precompilecache'],
      removed: ['P.Dev.App.x.compileinfo'],
    });
    expect(txt).toContain('P.Dev.App.x.compileinfo');
    expect(txt).toContain('incremental=true');
  });

  it('is quiet when nothing was removed', () => {
    expect(formatCacheReport({ incremental: true, before: [], after: [], removed: [] })).toMatch(/nothing removed/);
  });
});

describe('parseCompileMessagesBlock', () => {
  it('reads the marker block and tolerates garbage', () => {
    const out = 'DEBUG: x\n### COMPILE_MESSAGES_START ###\n[{"severity":"error","text":"boom"}]\n### COMPILE_MESSAGES_END ###\n';
    expect(parseCompileMessagesBlock(out)).toEqual([{ severity: 'error', text: 'boom' }]);
    expect(parseCompileMessagesBlock('no block')).toEqual([]);
    expect(parseCompileMessagesBlock('### COMPILE_MESSAGES_START ###\n{bad\n### COMPILE_MESSAGES_END ###')).toEqual([]);
  });
});

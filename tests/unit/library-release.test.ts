import { describe, it, expect } from 'vitest';
import { releaseLibraryVersion, LIBRARY_VERSION_RE } from '../../src/library-release';
import { IpcResult } from '../../src/types';

// release_library_version (2.0.0) with a fake executor: which scripts run,
// in which order, with which parameters, and where it stops.

type Call = { script: string; params: Record<string, string> };

function harness(failAt?: { script: string; nth?: number; code: string }) {
  const calls: Call[] = [];
  const snapshots: string[] = [];
  const seen: Record<string, number> = {};
  const deps = {
    prepare: (script: string, params: Record<string, string>) => JSON.stringify({ script, params }),
    snapshot: async (p: string) => { snapshots.push(p); },
    executor: {
      executeScript: async (content: string): Promise<IpcResult> => {
        const c = JSON.parse(content) as Call;
        calls.push(c);
        seen[c.script] = (seen[c.script] ?? 0) + 1;
        const fail = failAt && failAt.script === c.script && (failAt.nth ?? 1) === seen[c.script];
        return {
          requestId: 'x', timestamp: 0, error: '',
          success: !fail,
          output: fail ? `boom\nSCRIPT_ERROR_CODE: ${failAt!.code}\nSCRIPT_ERROR: boom` : 'SCRIPT_SUCCESS: ok',
        };
      },
    },
  };
  return { deps, calls, snapshots };
}

const ARGS = { libPath: 'C:/lib/WebLib.library', version: '1.3.1' };

describe('release_library_version (src/library-release.ts)', () => {
  it('runs precheck, set version + clear Released, rebuild, mark Released, install -- in that order', async () => {
    const h = harness();
    const r = await releaseLibraryVersion(ARGS, h.deps);
    expect(r.released).toBe(true);
    expect(r.errorCode).toBeNull();
    expect(h.calls.map((c) => c.script)).toEqual([
      'library_release_precheck', 'set_project_info', 'rebuild_library', 'set_project_info', 'install_library_to_repository',
    ]);
    expect(h.calls[0].params).toMatchObject({ VERSION: '1.3.1', PROJECT_FILE_PATH: ARGS.libPath });
    expect(h.calls[1].params).toMatchObject({ VERSION: '1.3.1', RELEASED: 'false' });
    expect(h.calls[3].params).toMatchObject({ VERSION: '', RELEASED: 'true' });
    expect(r.steps.map((s) => s.name)).toEqual(['precheck', 'set_version', 'rebuild_library', 'mark_released', 'install_library_to_repository']);
  });

  it('a taken number stops at the precheck: the library is not touched, not even snapshotted', async () => {
    const h = harness({ script: 'library_release_precheck', code: 'ERR_LIB_EXISTS' });
    const r = await releaseLibraryVersion(ARGS, h.deps);
    expect(r.released).toBe(false);
    expect(r.errorCode).toBe('ERR_LIB_EXISTS');
    expect(h.calls.map((c) => c.script)).toEqual(['library_release_precheck']);
    expect(h.snapshots).toEqual([]);
  });

  it('refuses a fourth number, a pre-release suffix and leading zeros before running anything', async () => {
    for (const version of ['1.3.1.0', '1.4.0-rc.1', '01.3.1', '1.3']) {
      const h = harness();
      const r = await releaseLibraryVersion({ ...ARGS, version }, h.deps);
      expect(r.errorCode, version).toBe('ERR_BAD_INPUT');
      expect(h.calls, version).toEqual([]);
    }
    expect(LIBRARY_VERSION_RE.test('1.10.0')).toBe(true);
  });

  it('a step that fails stops the sequence and passes its error code up', async () => {
    const h = harness({ script: 'install_library_to_repository', code: 'ERR_LIB_NOT_RELEASED' });
    const r = await releaseLibraryVersion(ARGS, h.deps);
    expect(r.released).toBe(false);
    expect(r.errorCode).toBe('ERR_LIB_NOT_RELEASED');
    const failMark = harness({ script: 'set_project_info', nth: 2, code: 'ERR_WRITE_DID_NOT_STICK' });
    const r2 = await releaseLibraryVersion(ARGS, failMark.deps);
    expect(r2.errorCode).toBe('ERR_WRITE_DID_NOT_STICK');
    expect(failMark.calls.map((c) => c.script)).not.toContain('install_library_to_repository');
  });
});

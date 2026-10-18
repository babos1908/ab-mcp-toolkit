/**
 * Runs the REAL tool scripts (helpers + template, prepared by ScriptManager
 * exactly as the server does) under CPython 2.7 against the fake
 * scriptengine in tests/py/fake_scriptengine. CPython 2.7 is the closest
 * interpreter to CODESYS' IronPython 2.7 that runs without AB; Automation
 * Builder ships one. Skipped when no 2.7 interpreter is found
 * (CODESYS_MCP_PY27 overrides the lookup).
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { spawnSync } from 'child_process';
import { ScriptManager } from '../../src/script-manager';
import { parseResultJson } from '../../src/result-parser';

const ROOT = path.join(__dirname, '..', '..');
const SCRIPTS = path.join(ROOT, 'src', 'scripts');
const RUNNER = path.join(ROOT, 'tests', 'py', 'run_script.py');

function findPy27(): string | null {
  const candidates = [
    process.env.CODESYS_MCP_PY27,
    'C:\\Program Files\\ABB\\AB2.9\\AutomationBuilder\\PythonInterpreter\\python.exe',
    'C:\\Python27\\python.exe',
  ].filter((p): p is string => !!p);
  for (const c of candidates) {
    if (!fs.existsSync(c)) continue;
    const v = spawnSync(c, ['-c', 'import sys; print(sys.version_info[0])'], { encoding: 'utf-8' });
    if (v.stdout && v.stdout.trim() === '2') return c;
  }
  return null;
}
const PY27 = findPy27();

const mgr = new ScriptManager(SCRIPTS);

interface Run {
  output: string;
  state: Record<string, any>;
  result: any;
  code: string | null;
}

/**
 * fixture: python run inside the runner with `se` (fake module) in scope;
 * `from worlds import *` is available. Define dump() to export state.
 */
function run(script: string, params: Record<string, string>, fixture: string, helpers = ['_text_utils', 'ensure_project_open']): Run {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-fake-'));
  try {
    const code = mgr.prepareScriptWithHelpers(script, params, helpers);
    const scriptPath = path.join(dir, 'script.py');
    const fixturePath = path.join(dir, 'fixture.py');
    fs.writeFileSync(scriptPath, code, 'utf-8');
    fs.writeFileSync(fixturePath, fixture, 'utf-8');
    const r = spawnSync(PY27!, ['-E', '-s', RUNNER, fixturePath, scriptPath], {
      encoding: 'utf-8',
      env: { ...process.env, FAKE_ROOT: path.join(dir, 'root') },
      timeout: 60_000,
    });
    const out = (r.stdout || '') + (r.stderr ? '\n[stderr]\n' + r.stderr : '');
    const m = out.match(/### STATE ### ([^\r\n]*)/); // Windows stdout ends lines with \r\n
    const state = m ? JSON.parse(m[1]) : {};
    const parsed = parseResultJson<any>(out);
    const cm = out.match(/SCRIPT_ERROR_CODE: (\w+)/g);
    return {
      output: out,
      state,
      result: parsed.ok ? parsed.data : null,
      code: cm ? cm[cm.length - 1].replace('SCRIPT_ERROR_CODE: ', '') : null,
    };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

const ok = (r: Run) => r.output.includes('SCRIPT_SUCCESS') && r.state.exitCode === 0;

const WORLD = (args = '') => `
from worlds import *
w = ac500_project(${args})
def libs(lm):
    return [r.name for r in lm._refs]
`;

describe.skipIf(!PY27)('tool scripts against the fake AB 2.9 scriptengine', () => {
  // ------------------------------------------------------------ #1 remove_library
  describe('remove_library', () => {
    it('removes a USER placeholder asked for without the # (the 2026-10-17 regression)', () => {
      const r = runRemoveFixed('LogiQ');
      expect(ok(r)).toBe(true);
      expect(r.result.removed).toBe('#LogiQ');
      expect(r.state.app).not.toContain('#LogiQ');
      expect(r.state.calls).toContainEqual(['remove_library', '#LogiQ']);
      expect(r.state.saves).toBe(1);
    });

    it('resolves a placeholder by the library it resolves to', () => {
      const r = runRemoveFixed('MProtocol-library');
      expect(ok(r)).toBe(true);
      expect(r.result.removed).toBe('#MProtocol');
    });

    it('removes a managed reference by its base name or list_project_libraries form', () => {
      expect(runRemoveFixed('AC500-V3-utilities-ip').result.removed).toBe('AC500-V3-utilities-ip, 1.0.2 (ABB)');
      expect(runRemoveFixed('AC500-V3-utilities-ip (v1.0.2) [ABB]').result.removed).toBe('AC500-V3-utilities-ip, 1.0.2 (ABB)');
    });

    it('finds references in the project-root Library Manager too', () => {
      const r = runRemoveFixed('CmpSchedule');
      expect(ok(r)).toBe(true);
      expect(r.state.root).not.toContain('#CmpSchedule');
    });

    it('refuses a SYSTEM reference', () => {
      const r = runRemoveFixed('Standard');
      expect(ok(r)).toBe(false);
      expect(r.code).toBe('ERR_BAD_INPUT');
      expect(r.output).toContain('SYSTEM library reference');
      expect(r.state.app).toContain('#Standard');
    });

    it('refuses an ambiguous substring instead of picking one', () => {
      const r = runRemoveFixed('utilities');
      expect(ok(r)).toBe(false);
      expect(r.code).toBe('ERR_BAD_INPUT');
      expect(r.output).toContain('Ambiguous');
    });

    it('a Released (read-only) project fails with ERR_PROJECT_READ_ONLY and the fix', () => {
      const r = runRemoveFixed('LogiQ', 'released=True');
      expect(ok(r)).toBe(false);
      expect(r.code).toBe('ERR_PROJECT_READ_ONLY');
      expect(r.output).toContain('set_project_info(released=false)');
    });
  });

  // ------------------------------------------------------ #6 library parameters
  describe('library parameters', () => {
    it('set_library_parameter: managed ref with NO overrides, name validated from the .library source', () => {
      const r = runFixed('set_library_parameter',
        { LIBRARY_NAME: 'AC500-V3-utilities-web', PARAMETER_NAME: 'GC_UDIPAGEMAX', PARAMETER_VALUE: '65536' },
        WORLD() + `
def dump():
    p = ref(w['app_lm'], 'AC500-V3-utilities-web, 1.0.0 (ABB)').parameters
    return {'overrides': dict((k, p[k]) for k in p), 'saves': w['project'].saves,
            'webSrcClosed': w['web_src'].closed, 'primary': se.projects.primary.path == PROJECT}
`);
      expect(ok(r)).toBe(true);
      expect(r.result).toMatchObject({
        library: 'AC500-V3-utilities-web, 1.0.0 (ABB)',
        parameter: 'gc_udiPageMax', // the library's own spelling
        valueReadback: '65536',
        libraryDefault: '262144',
        nameValidated: true,
      });
      expect(r.state.overrides).toEqual({ GC_UDIPAGEMAX: '65536' });
      expect(r.state.saves).toBe(1);
      expect(r.state.webSrcClosed).toBe(true); // secondary project closed again
      expect(r.state.primary).toBe(true); // primary untouched
    });

    it('set_library_parameter: a typo is refused, nothing written', () => {
      const r = runFixed('set_library_parameter',
        { LIBRARY_NAME: 'AC500-V3-utilities-web, 1.0.0 (ABB)', PARAMETER_NAME: 'gc_udiPagMax', PARAMETER_VALUE: '65536' },
        WORLD() + `
def dump():
    p = ref(w['app_lm'], 'AC500-V3-utilities-web, 1.0.0 (ABB)').parameters
    return {'n': len(p), 'saves': w['project'].saves}
`);
      expect(ok(r)).toBe(false);
      expect(r.code).toBe('ERR_LIB_PARAM_NOT_FOUND');
      expect(r.output).toContain('gc_udiPageMax');
      expect(r.state).toMatchObject({ n: 0, saves: 0 });
    });

    it('set_library_parameter: compiled library -> written, but nameValidated=false with a warning', () => {
      const r = runFixed('set_library_parameter',
        { LIBRARY_NAME: 'Util', PARAMETER_NAME: 'iBlockSize', PARAMETER_VALUE: '30000' },
        WORLD() + `
def dump():
    p = ref(w['app_lm'], '#Util').parameters
    return {'v': p['IBLOCKSIZE']}
`);
      expect(ok(r)).toBe(true);
      expect(r.result.nameValidated).toBe(false);
      expect(r.result.previousOverride).toBe('22800');
      expect(r.result.warning).toMatch(/compiled library/);
      expect(r.state.v).toBe('30000');
    });

    it('get_library_parameters with a filter lists declared parameters, defaults and overrides', () => {
      const r = runFixed('get_library_parameters', { LIBRARY_NAME: 'utilities-web' },
        WORLD("web_overrides={'gc_udiPageMax': '65536'}"));
      expect(ok(r)).toBe(true);
      const lib = r.result.libraries[0];
      expect(lib.libraryName).toBe('AC500-V3-utilities-web, 1.0.0 (ABB)');
      const page = lib.parameters.find((p: any) => p.name === 'gc_udiPageMax');
      expect(page).toMatchObject({ value: '65536', defaultValue: '262144', isOverridden: true, type: 'UDINT' });
      const slots = lib.parameters.find((p: any) => p.name === 'gc_uiSlots');
      expect(slots).toMatchObject({ value: '3', isOverridden: false });
    });

    it('get_library_parameters without a filter lists only references with overrides', () => {
      const r = runFixed('get_library_parameters', { LIBRARY_NAME: '' }, WORLD());
      expect(ok(r)).toBe(true);
      expect(r.result.libraries.map((l: any) => l.libraryName)).toEqual(['#Util']);
    });

    it("reset_library_parameter neutralises the override by writing '' (tombstone stays listed)", () => {
      // Live AB keeps the name listed after params[name] = '' and raises
      // KeyError on read; the default applies again. The reset must count
      // that as success -- it used to report a false ERR_RESET_DID_NOT_STICK.
      const r = runFixed('reset_library_parameter', { LIBRARY_NAME: '#Util', PARAMETER_NAME: 'iblocksize' },
        WORLD() + `
def dump():
    p = ref(w['app_lm'], '#Util').parameters
    try:
        p['IBLOCKSIZE']
        readable = True
    except KeyError:
        readable = False
    return {'n': len(p), 'readable': readable}
`);
      expect(ok(r)).toBe(true);
      expect(r.result.previousOverride).toBe('22800');
      expect(r.result.overridesAfter).toEqual({});
      expect(r.state.n).toBe(1);            // still listed, as on real AB
      expect(r.state.readable).toBe(false); // but unreadable
    });

    it('get_library_parameters does not report a reset (tombstoned) parameter as overridden', () => {
      const r = runFixed('get_library_parameters', { LIBRARY_NAME: '' },
        WORLD() + `
ref(w['app_lm'], '#Util').parameters['IBLOCKSIZE'] = ''
`);
      expect(ok(r)).toBe(true);
      // #Util's only override was neutralised, so no library carries one now.
      expect(r.result.libraries).toEqual([]);
    });

    it('reset_library_parameter with no override is a no-op success', () => {
      const r = runFixed('reset_library_parameter', { LIBRARY_NAME: 'AC500-V3-utilities-web', PARAMETER_NAME: 'gc_udiPageMax' }, WORLD());
      expect(ok(r)).toBe(true);
      expect(r.result.resetVia).toBeNull();
    });
  });

  // ------------------------------------------------- #2 install_library_to_repository
  describe('install_library_to_repository', () => {
    const LIBFX = (opts: { open: boolean; released: boolean; dirty: boolean }) => `
from worlds import *
lib = se.Project(WEB_LIB, [], released=${opts.released ? 'True' : 'False'})
lib.dirty = ${opts.dirty ? 'True' : 'False'}
other = se.Project(PROJECT, [])
se.projects.primary = ${opts.open ? 'lib' : 'other'}
se.projects.all = [se.projects.primary]
def dump():
    return {'installed': se.librarymanager.installed, 'opens': se.projects.open_calls,
            'libSaves': lib.saves, 'primaryIsOther': se.projects.primary is other}
`;
    const runInstall = (opts: { open: boolean; released: boolean; dirty: boolean }) =>
      runWithLibPath('install_library_to_repository', { REPOSITORY_NAME: '' }, LIBFX(opts));

    it('not open: installs from the file without opening anything', () => {
      const r = runInstall({ open: false, released: true, dirty: false });
      expect(ok(r)).toBe(true);
      expect(r.state.installed).toHaveLength(1);
      expect(r.state.opens).toEqual([]);
      expect(r.state.primaryIsOther).toBe(true);
      expect(r.output).toContain('not open: installed from the file');
    });

    it('open, Released, no unsaved changes: save skipped, install works (was: read-only save error)', () => {
      const r = runInstall({ open: true, released: true, dirty: false });
      expect(ok(r)).toBe(true);
      expect(r.state.libSaves).toBe(0);
      expect(r.state.installed).toHaveLength(1);
    });

    it('open with unsaved changes: saved first', () => {
      const r = runInstall({ open: true, released: false, dirty: true });
      expect(ok(r)).toBe(true);
      expect(r.state.libSaves).toBe(1);
    });

    it('open, Released AND dirty: refuses with ERR_PROJECT_READ_ONLY (edits would not be installed)', () => {
      const r = runInstall({ open: true, released: true, dirty: true });
      expect(ok(r)).toBe(false);
      expect(r.code).toBe('ERR_PROJECT_READ_ONLY');
      expect(r.state.installed).toEqual([]);
    });
  });

  // ------------------------------------------------------------- #7 set_project_info
  describe('set_project_info released', () => {
    const P = (extra: Record<string, string>) => ({ VERSION: '', TITLE: '', AUTHOR: '', COMPANY: '', DESCRIPTION: '', ...extra });
    const FX = (released: boolean) => WORLD(released ? 'released=True' : '') + `
def dump():
    i = w['project'].info
    return {'released': i.released, 'version': i.version, 'saves': w['project'].saves}
`;
    it('released=false unlocks a Released project so the same call can save other fields', () => {
      const r = runFixed('set_project_info', P({ RELEASED: 'false', VERSION: '1.5.0' }), FX(true));
      expect(ok(r)).toBe(true);
      expect(r.state).toMatchObject({ released: false, version: '1.5.0', saves: 1 });
    });

    it('released=true marks it released (after the other fields)', () => {
      const r = runFixed('set_project_info', P({ RELEASED: 'true', VERSION: '2.0.0' }), FX(false));
      expect(ok(r)).toBe(true);
      expect(r.state).toMatchObject({ released: true, version: '2.0.0', saves: 1 });
    });

    it('editing a Released project without released=false fails clearly', () => {
      const r = runFixed('set_project_info', P({ RELEASED: '', VERSION: '9.9.9' }), FX(true));
      expect(ok(r)).toBe(false);
      expect(r.code).toBe('ERR_PROJECT_READ_ONLY');
    });

    it('an older server that does not pass RELEASED leaves the flag alone', () => {
      // No RELEASED key: the literal "{RELEASED}" stays in the script.
      const r = runFixed('set_project_info', { VERSION: '1.0.1', TITLE: '', AUTHOR: '', COMPANY: '', DESCRIPTION: '' }, FX(false));
      expect(ok(r)).toBe(true);
      expect(r.state).toMatchObject({ released: false, version: '1.0.1' });
      expect(r.output).toContain('was not substituted');
    });
  });

  // ------------------------------------------------------------- #8 create_task
  describe('create_task / set_task_parameter', () => {
    const T = (extra: Record<string, string>) => ({
      TASK_NAME: 'WebTask', CYCLE_TIME_MS: '', WATCHDOG_TIME_MS: '', WATCHDOG_ENABLED: '',
      WATCHDOG_SENSITIVITY: '', PRIORITY: '', STACK_SIZE_BYTES: '', CREATE_TASK: 'false',
      TASK_KIND: '', ADD_POUS: '', ...extra,
    });
    const FX = WORLD() + `
def dump():
    out = {}
    for t in w['tc'].get_children(False):
        out[t.get_name()] = {'interval': t.interval, 'priority': t.priority, 'wd': t.watchdog.enabled,
                             'wdTime': t.watchdog.time, 'sens': t.watchdog.sensitivity,
                             'pous': [t.pous[i][0] for i in range(len(t.pous))], 'kind': str(t.kind_of_task)}
    return {'tasks': out, 'saves': w['project'].saves}
`;

    it('creates WebTask 20 ms, priority 16, watchdog OFF, calling WEB_PRG', () => {
      const r = runFixed('set_task_parameter', T({
        CREATE_TASK: 'true', TASK_KIND: 'cyclic', CYCLE_TIME_MS: '20', PRIORITY: '16',
        WATCHDOG_ENABLED: 'false', ADD_POUS: 'WEB_PRG',
      }), FX);
      expect(ok(r)).toBe(true);
      expect(r.state.tasks.WebTask).toEqual({
        interval: 't#20ms', priority: '16', wd: false, wdTime: 't#20ms', sens: '1', pous: ['WEB_PRG'], kind: 'Cyclic',
      });
      expect(r.result).toMatchObject({ created: true, taskConfiguration: 'TaskConfiguration', warnings: [] });
      expect(r.state.saves).toBe(1);
    });

    it('refuses to create a task that exists', () => {
      const r = runFixed('set_task_parameter', T({ TASK_NAME: 'MainTask', CREATE_TASK: 'true' }), FX);
      expect(ok(r)).toBe(false);
      expect(r.code).toBe('ERR_OBJECT_EXISTS');
    });

    it('priority and sensitivity are string properties on AC500 V3: written and verified (always failed before)', () => {
      const r = runFixed('set_task_parameter', T({ TASK_NAME: 'MainTask', PRIORITY: '3', WATCHDOG_SENSITIVITY: '2' }), FX);
      expect(ok(r)).toBe(true);
      expect(r.state.tasks.MainTask).toMatchObject({ priority: '3', sens: '2' });
    });

    it('addPous skips a call that is already there and warns about an unknown program', () => {
      const r = runFixed('set_task_parameter', T({ TASK_NAME: 'MainTask', ADD_POUS: 'WEB_PRG\nWEB_PRG\nLibProg' }), FX);
      expect(ok(r)).toBe(true);
      expect(r.state.tasks.MainTask.pous).toEqual(['WEB_PRG', 'LibProg']);
      expect(r.result.warnings.join(' ')).toContain('LibProg');
    });

    it('an older server (no CREATE_TASK/TASK_KIND/ADD_POUS) behaves as before', () => {
      const params: Record<string, string> = T({ TASK_NAME: 'MainTask', CYCLE_TIME_MS: '50' });
      delete params.CREATE_TASK; delete params.TASK_KIND; delete params.ADD_POUS;
      const r = runFixed('set_task_parameter', params, FX);
      expect(ok(r)).toBe(true);
      expect(r.state.tasks.MainTask.interval).toBe('t#50ms');
      expect(Object.keys(r.state.tasks)).toEqual(['MainTask']);
    });
  });

  // ------------------------------------------------------- #9 inspect_project_tree
  describe('inspect_project_tree', () => {
    it('reports the ImagePool (was dropped) in others with its raw type', () => {
      const r = runFixed('inspect_project_tree', { INCLUDE_SYMBOLS: 'false', CHILDREN_OF: '' }, WORLD());
      expect(ok(r)).toBe(true);
      const ip = r.result.others.find((o: any) => o.name === 'ImagePool');
      expect(ip).toMatchObject({ kind: 'ImagePool', typeGuid: 'bb0b9044-714e-4614-ad3e-33cbdf34d16b' });
      expect(r.result.counts.others).toBeGreaterThan(0);
    });

    it('childrenOf lists one folder with kinds and raw types', () => {
      const r = runFixed('inspect_project_tree', { INCLUDE_SYMBOLS: 'false', CHILDREN_OF: 'App/Visu' }, WORLD());
      expect(ok(r)).toBe(true);
      expect(r.result.childrenOf.path).toBe('PLC_AC500_V3/Plc Logic/Application/App/Visu');
      expect(r.result.children).toEqual([expect.objectContaining({
        name: 'ImagePool', kind: 'ImagePool', typeName: 'ImagePool', typeGuid: 'bb0b9044-714e-4614-ad3e-33cbdf34d16b', childCount: 0,
      })]);
    });

    it('childrenOf with an unknown path fails with ERR_OBJECT_NOT_FOUND', () => {
      const r = runFixed('inspect_project_tree', { INCLUDE_SYMBOLS: 'false', CHILDREN_OF: 'Nope/Missing' }, WORLD());
      expect(r.code).toBe('ERR_OBJECT_NOT_FOUND');
    });
  });

  // ---------------------------------------------------- #3 #4 compile_project
  describe('compile_project', () => {
    const FX = `
from worlds import *
import os
w = ac500_project()
d = os.path.dirname(PROJECT)
CACHE = ['MPLUS_IO.PLC_AC500_V3.Application.x.compileinfo', 'MPLUS_IO.PLC_AC500_V3.Application.x.bootinfo',
         'MPLUS_IO_project.precompilecache']
for n in CACHE:
    open(os.path.join(d, n), 'wb').close()
app = w['project'].active_application
app.cleaned = 0
def _clean():
    app.cleaned += 1
    for n in CACHE[:2]:
        p = os.path.join(d, n)
        if os.path.exists(p):
            os.remove(p)
app.clean = _clean
app.build = lambda: None
app.generate_code = lambda: None
S = se.Severity
se.system.categories = {
    '97f48d64-a2a3-4856-b640-75c046e37ea9': ('Build', [
        se.Message(S.Text, '------ Build started: Application: PLC_AC500_V3.Application -------'),
        se.Message(S.Warning, 'The FTP server configuration allows insecure access.', number=373),
        se.Message(S.Information, 'Memory area 0 contains  Data, Input, Output, Code and Nonsafe data: size: 5242880 bytes, highest used address: 1144344, largest contiguous memory gap: 4098536 bytes (78 %)'),
        se.Message(S.Text, 'Build complete -- 0 errors, 1 warnings : Ready for download'),
    ]),
    'ee56da69-d42b-478e-bd3c-2b4494e512c6': ('Memory Usage', [
        se.Message(S.Information, 'User program code and data: Variables = 216955, POUs = 47952, Total = 264907 bytes (50,53%) Further details available in Statistics view.', prefix=None),
    ]),
}
def dump():
    return {'cleaned': app.cleaned, 'files': sorted(os.listdir(d))}
`;
    it('default: clean() runs, removed cache files and memory lines are reported apart from warnings', () => {
      const r = runFixed('compile_project', { INCREMENTAL: 'false' }, FX);
      expect(ok(r)).toBe(true);
      expect(r.state.cleaned).toBe(1);
      expect(r.result.cacheFiles.removed).toEqual([
        'MPLUS_IO.PLC_AC500_V3.Application.x.bootinfo',
        'MPLUS_IO.PLC_AC500_V3.Application.x.compileinfo',
      ]);
      expect(r.result.memoryLines).toHaveLength(2);
      expect(r.result.buildSummary).toEqual(['Build complete -- 0 errors, 1 warnings : Ready for download']);
      // The compile-message list still carries only errors/warnings.
      const block = r.output.split('### COMPILE_MESSAGES_START ###')[1].split('### COMPILE_MESSAGES_END ###')[0];
      const msgs = JSON.parse(block);
      expect(msgs.map((m: any) => m.severity)).toEqual(['warning']);
    });

    it('incremental=true skips clean() and removes nothing', () => {
      const r = runFixed('compile_project', { INCREMENTAL: 'true' }, FX);
      expect(ok(r)).toBe(true);
      expect(r.state.cleaned).toBe(0);
      expect(r.result.incremental).toBe(true);
      expect(r.result.cacheFiles.removed).toEqual([]);
      expect(r.state.files).toContain('MPLUS_IO.PLC_AC500_V3.Application.x.compileinfo');
    });

    it('an older server that does not pass INCREMENTAL keeps the clean build', () => {
      const r = runFixed('compile_project', {}, FX);
      expect(ok(r)).toBe(true);
      expect(r.state.cleaned).toBe(1);
    });
  });
});

// ---------------------------------------------------------------- helpers
// The fake project path lives under a per-run temp root that only the fixture
// knows; these wrappers make the script read PROJECT_FILE_PATH from the
// fixture's worlds module, mirroring a server that passes the real path.
function runFixed(script: string, params: Record<string, string>, fixture: string): Run {
  return run(script, { ...params, PROJECT_FILE_PATH: '%%PROJECT%%' }, fixture + '\n' + SUBST);
}
function runRemoveFixed(name: string, worldArgs = ''): Run {
  return runFixed('remove_library', { LIBRARY_NAME: name }, WORLD(worldArgs) + `
def dump():
    return {'app': libs(w['app_lm']), 'root': libs(w['root_lm']), 'saves': w['project'].saves}
`);
}
function runWithLibPath(script: string, params: Record<string, string>, fixture: string): Run {
  return run(script, { ...params, PROJECT_FILE_PATH: '%%WEB_LIB%%' }, fixture + '\n' + SUBST);
}
// Rewrites the prepared script in place (before it runs) so '%%PROJECT%%' /
// '%%WEB_LIB%%' become the fixture's real temp paths.
const SUBST = `
import sys as _sys
_sp = _sys.argv[2]
_src = open(_sp, 'rb').read()
_bs = chr(92)  # backslash, doubled for the Python string literal it lands in
_src = _src.replace('%%PROJECT%%', PROJECT.replace(_bs, _bs * 2)).replace('%%WEB_LIB%%', WEB_LIB.replace(_bs, _bs * 2))
open(_sp, 'wb').write(_src)
`;

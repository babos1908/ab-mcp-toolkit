/**
 * release_library_version, as a function of its dependencies so it can be
 * unit-tested with a fake executor and run live with a headless one.
 *
 * 2.0.0 sequence -- the versioning rule (SemVer 2.0.0, global CLAUDE.md): a
 * library is installed already Released, and every installed build has its
 * own MAJOR.MINOR.PATCH number:
 *   0. the version must be MAJOR.MINOR.PATCH (AB's Version field takes
 *      numbers only; a fourth number is a defect);
 *   1. precheck: that number must not be installed yet -- checked BEFORE the
 *      library is touched, so a taken number leaves the file as it was;
 *   2. set the version and clear Released (a library left Released by its
 *      previous release opens read-only and could not be edited);
 *   3. rebuild;
 *   4. mark Released;
 *   5. install (install_library_to_repository refuses non-Released or taken
 *      numbers on its own, and reads the install back);
 *   6. optional: copy to distFolder, git tag, gh release.
 * Until 1.0.0 the library was installed WITHOUT Released and a re-run with
 * the same number overwrote the installed build.
 */
import * as fs from 'fs';
import * as path from 'path';
import { ScriptExecutor } from './types';
import { extractErrorCode } from './result-parser';

export const LIBRARY_VERSION_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;

export interface LibraryReleaseArgs {
  libPath: string;
  version: string;
  distFolder?: string;
  gitTag?: boolean;
  ghRelease?: boolean;
}

export interface LibraryReleaseDeps {
  executor: ScriptExecutor;
  prepare: (name: string, params: Record<string, string>, helpers: string[]) => string;
  snapshot?: (filePath: string) => Promise<unknown>;
  run?: (cmd: string, cwd: string, timeoutMs: number) => void;
}

export interface LibraryReleaseStep { name: string; ok: boolean; detail: string; code?: string | null }

export interface LibraryReleaseResult {
  released: boolean;
  version: string;
  errorCode: string | null;
  steps: LibraryReleaseStep[];
}

const HELPERS = ['_text_utils', 'ensure_project_open'];

export async function releaseLibraryVersion(args: LibraryReleaseArgs, deps: LibraryReleaseDeps): Promise<LibraryReleaseResult> {
  const steps: LibraryReleaseStep[] = [];
  const done = (errorCode: string | null): LibraryReleaseResult =>
    ({ released: errorCode === null && steps.every((s) => s.ok), version: args.version, errorCode, steps });

  if (!LIBRARY_VERSION_RE.test(args.version)) {
    steps.push({
      name: 'validate_version', ok: false, code: 'ERR_BAD_INPUT',
      detail: `'${args.version}' is not MAJOR.MINOR.PATCH: three numbers, no leading zeros, no fourth number. AB's Version field takes numbers only, so no pre-release suffix either.`,
    });
    return done('ERR_BAD_INPUT');
  }

  const script = async (name: string, script: string, params: Record<string, string>, timeoutMs?: number): Promise<boolean> => {
    try {
      const r = await deps.executor.executeScript(deps.prepare(script, { PROJECT_FILE_PATH: args.libPath, ...params }, HELPERS), timeoutMs);
      const ok = r.success && r.output.includes('SCRIPT_SUCCESS');
      const code = ok ? null : extractErrorCode(r.output);
      steps.push({ name, ok, code, detail: ok ? summary(name, args.version) : (r.output || r.error || '').slice(-600) });
      return ok;
    } catch (err) {
      steps.push({ name, ok: false, code: null, detail: err instanceof Error ? err.message : String(err) });
      return false;
    }
  };
  const failCode = () => steps[steps.length - 1]?.code ?? 'ERR_UNKNOWN';

  if (!(await script('precheck', 'library_release_precheck', { VERSION: args.version }))) return done(failCode());

  if (deps.snapshot) await deps.snapshot(args.libPath);
  if (!(await script('set_version', 'set_project_info',
    { VERSION: args.version, TITLE: '', AUTHOR: '', COMPANY: '', DESCRIPTION: '', RELEASED: 'false' }))) return done(failCode());
  if (!(await script('rebuild_library', 'rebuild_library', { REGENERATE_ARTIFACTS: 'true' }, 180_000))) return done(failCode());
  if (!(await script('mark_released', 'set_project_info',
    { VERSION: '', TITLE: '', AUTHOR: '', COMPANY: '', DESCRIPTION: '', RELEASED: 'true' }))) return done(failCode());
  if (!(await script('install_library_to_repository', 'install_library_to_repository', { REPOSITORY_NAME: '' }))) return done(failCode());

  if (args.distFolder) {
    try {
      const baseName = path.basename(args.libPath, path.extname(args.libPath));
      const targetDir = path.join(args.distFolder, `v${args.version}`);
      fs.mkdirSync(targetDir, { recursive: true });
      const targetFile = path.join(targetDir, `${baseName}-v${args.version}.library`);
      fs.copyFileSync(args.libPath, targetFile);
      steps.push({ name: 'copy_to_dist', ok: true, detail: `copied to ${targetFile}` });
    } catch (err) {
      steps.push({ name: 'copy_to_dist', ok: false, detail: err instanceof Error ? err.message : String(err) });
    }
  }

  if (args.gitTag && deps.run) {
    const repoDir = path.dirname(args.libPath);
    try {
      deps.run(`git tag v${args.version}`, repoDir, 10_000);
      steps.push({ name: 'git_tag', ok: true, detail: `tagged v${args.version}` });
      if (args.ghRelease) {
        try {
          deps.run(`gh release create v${args.version} --generate-notes`, repoDir, 30_000);
          steps.push({ name: 'gh_release', ok: true, detail: `release v${args.version} created` });
        } catch (err) {
          steps.push({ name: 'gh_release', ok: false, detail: err instanceof Error ? err.message : String(err) });
        }
      }
    } catch (err) {
      steps.push({ name: 'git_tag', ok: false, detail: err instanceof Error ? err.message : String(err) });
    }
  }

  return done(null);
}

function summary(step: string, version: string): string {
  switch (step) {
    case 'precheck': return `${version} is not installed yet`;
    case 'set_version': return `version set to ${version}, Released cleared for the edit`;
    case 'rebuild_library': return 'rebuild done';
    case 'mark_released': return 'marked Released';
    case 'install_library_to_repository': return 'installed and verified';
    default: return 'ok';
  }
}

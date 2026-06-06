/**
 * MCP Server — registers tools and resources for CODESYS automation.
 * Supports persistent (watcher-based) and headless (spawn-per-command) modes.
 */

import * as path from 'path';
import * as fs from 'fs';
import { McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { ServerConfig, IpcResult, ScriptExecutor, ExecutionMode } from './types';
import { CodesysLauncher } from './launcher';
import { HeadlessExecutor } from './headless';
import { ScriptManager } from './script-manager';
import { ExecutorProxy, ResilientExecutor } from './executor-proxy';
import { BackupManager } from './backup-manager';
import { diffLibraryFiles } from './library-diff';
import { parseProjectOffline, searchProjectOffline } from './offline-reader';
import { parseResultJson } from './result-parser';
import { serverLog, setLogLevel } from './logger';

/** Resolve a file path to an absolute normalized path */
function resolvePath(filePath: string, workspaceDir: string): string {
  return path.normalize(
    path.isAbsolute(filePath) ? filePath : path.join(workspaceDir, filePath)
  );
}

/** Sanitize a POU path (forward slashes, no leading/trailing slashes) */
function sanitizePouPath(pouPath: string): string {
  return pouPath.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
}

/**
 * Pluck an MCPErrorCode marker from a script's stdout if present. Scripts
 * emit lines of the form
 *     SCRIPT_ERROR_CODE: ERR_<X>
 * to surface a structured error code in addition to the human-readable
 * SCRIPT_ERROR line. Returns null when no marker is present (uncoded error).
 */
function extractErrorCode(output: string): string | null {
  const marker = 'SCRIPT_ERROR_CODE:';
  const idx = output.lastIndexOf(marker);
  if (idx === -1) return null;
  // Take the rest of that line (until \n or end) and trim.
  const rest = output.slice(idx + marker.length);
  const nl = rest.indexOf('\n');
  const code = (nl === -1 ? rest : rest.slice(0, nl)).trim();
  return code || null;
}

/** Format an IpcResult into an MCP tool response */
function formatToolResponse(
  result: IpcResult,
  successMessage: string
): { content: Array<{ type: 'text'; text: string }>; isError: boolean } {
  const success = result.success && result.output.includes('SCRIPT_SUCCESS');
  if (success) {
    return {
      content: [{ type: 'text' as const, text: successMessage }],
      isError: false,
    };
  }
  // Failure path: surface error code if present so the agent can switch on
  // it without parsing prose.
  const code = extractErrorCode(result.output);
  const codePrefix = code ? `[${code}] ` : '';
  return {
    content: [
      {
        type: 'text' as const,
        text: `${codePrefix}Operation failed. Output:\n${result.output}${result.error ? '\nError: ' + result.error : ''}`,
      },
    ],
    isError: true,
  };
}

/**
 * Format an IpcResult that emits a structured JSON payload via emit_result()
 * into an MCP tool response. On success, parses the `### RESULT_JSON ###`
 * block and returns the pretty-printed JSON so callers (LLM or scripts) can
 * actually consume the data instead of just a "done" message.
 *
 * On failure or missing JSON block, falls back to formatToolResponse so the
 * error path is consistent across tools. summaryPrefix (optional) is
 * prepended to the JSON block, useful when the tool also wants to surface
 * a one-line summary (e.g. "3 libraries enumerated:") above the data.
 */
function formatStructuredResponse(
  result: IpcResult,
  fallbackSuccessMessage: string,
  summaryPrefix?: string
): { content: Array<{ type: 'text'; text: string }>; isError: boolean } {
  const success = result.success && result.output.includes('SCRIPT_SUCCESS');
  if (!success) {
    return formatToolResponse(result, fallbackSuccessMessage);
  }
  const parsed = parseResultJson(result.output);
  if (!parsed.ok) {
    // Script ran successfully but emitted no JSON. Fall back to the
    // text-only success message so the caller at least sees something.
    return formatToolResponse(result, fallbackSuccessMessage);
  }
  const jsonText = JSON.stringify(parsed.data, null, 2);
  return {
    content: [
      {
        type: 'text' as const,
        text: summaryPrefix ? `${summaryPrefix}\n${jsonText}` : jsonText,
      },
    ],
    isError: false,
  };
}

/** Check if a file exists (async) */
async function fileExists(filePath: string): Promise<boolean> {
  try {
    fs.statSync(filePath);
    return true;
  } catch {
    return false;
  }
}

/**
 * List of named patches applied in the babos1908/ab-mcp-toolkit fork relative
 * to the luke-harriman/Codesys-MCP upstream. Surfaced via get_mcp_version so
 * agents (and the agent-side skill) can verify which fixes are active in
 * this build before assuming a workaround is needed for a known-fixed bug.
 *
 * Keep this list in sync with the actual commits in this repo. Order is
 * roughly chronological. Each entry maps a short stable ID to a description.
 */
const MCP_PATCHES: Array<{ id: string; description: string }> = [
  { id: 'path-resolution-uniform', description: 'find_object_by_path_robust gains a leaf-name recursive fallback: when strict folder-by-folder traversal fails (e.g. a library POU at "MyLib/Function Blocks/FB_X" whose folders are not direct children of the root), it retries an unambiguous recursive find of the last segment from project + Application roots. Makes full-from-root, folder/leaf, and bare-leaf path forms resolve uniformly across ALL tools. delete_object no longer blanket-refuses bare names -- only exact system paths + known system leaves. Tool descriptions document the accepted path forms. NEXO feedback 2026-06-06 #1.' },
  { id: 'project-info-version-decode-fix', description: 'get_project_info no longer returns "ERR: Version object has no attribute decode": _to_unicode() coerces non-str objects (e.g. the .NET Version proxy) via unicode() instead of calling .decode() on them. NEXO feedback 2026-06-06 #2.' },
  { id: 'create-method-name-alias', description: 'create_method accepts `name` as an alias of `methodName` (matches create_pou), so the param-name inconsistency no longer causes a first-call InputValidationError. NEXO feedback 2026-06-06 #3.' },
  { id: 'keep-alive-decouple-ab-lifetime', description: 'AB lifetime decoupled from MCP server process. With --keep-alive, signal-driven shutdown (SIGTERM/SIGINT from client recycle / compact / reconnect) now detachKeepAlive() instead of taskkill -- the detached AB survives. On next startup adoptExisting() re-binds to the still-running watcher (newest session with fresh heartbeat + PID-alive from ready.signal), skipping the ~2min cold start and avoiding a second AB. Explicit shutdown_codesys + force_reset_watcher still terminate AB. Fixes the recurring "AB closed itself again" on routine session events.' },
  { id: 'soft-probe-before-forcereset', description: 'ResilientExecutor soft-probes the watcher heartbeat before hard-resetting on 2 consecutive timeouts. A fresh heartbeat = "busy, not dead" (classic case: an interactive ONLINE session on a real PLC monopolizes AB primary thread so MCP commands time out) -> re-throw the timeout instead of killing AB under the user. Only a STALE heartbeat triggers the kill+coldstart path.' },
  { id: 'watcher-prompt-handling-guard', description: 'watcher sets se.system.prompt_handling=ProcessScriptPrompts per command exec (restored after) so a modal dialog cannot deadlock the primary thread. Fixes the #1 field blocker: close_project/open_project while an interactive ONLINE session is logged in to a PLC would pop a "Logout from device?" modal that the headless host could never answer -> heartbeat stale -> force_reset + 2min cold start. Proxy-verified 2026-06-01: SARIF-export modal went from >200s deadlock to <1s return. Also fixes orphan-command queue starvation: a .command.json whose scriptPath is missing is now removed instead of re-read every worker loop forever.' },
  { id: 'online-ops-error-message-corrected', description: 'ensure_online_connection ERR_ONLINE_STACK_EMPTY message no longer tells the user to "click Online->Login, the MCP will reuse your session" -- that reuse path does NOT exist on AB 2.9 SP19 (Standard or Premium); the message now states the confirmed limitation and points to AB UI / out-of-band protocols.' },
  { id: 'create-boot-application', description: 'create_boot_application tool (Premium-confirmed): ScriptApplication.create_boot_application(path) after generate_code() -> deployable .app + .crc artifact, offline (no PLC). Verified 2026-05-31 on AB 2.9 SP19 (215KB .app + .crc). NOTE: SA config store/load + Standard Metrics export remain UI-only — their commands open modal Save-As dialogs that deadlock the headless watcher.' },
  { id: 'run-static-analysis', description: 'run_static_analysis tool (Premium): executes the "Run Static Analysis" ScriptCommand (guid AE97B6F4) and reads findings from message category "Additional code checks" (guid 220493A1). Reuses parseCompileMessages. Avoids SARIF export (modal dialog deadlocks the watcher). Confirmed scriptable 2026-05-30 on AB 2.9 SP19 Premium.' },
  { id: 'attach-mode-pid-guard', description: 'attach_codesys no longer flips healthy attached sessions to error: skip the PID-liveness health check when attached (pid is null by design in attach mode; liveness governed by watcher heartbeat). Confirmed 2026-05-30 on Premium that online ops still raise Stack empty from the GUI scripting context — edition-independent SP19 limit.' },
  { id: 'ready-timeout-ms-configurable', description: 'CLI --ready-timeout-ms flag wired to LauncherConfig (cold-start ~120s on AB)' },
  { id: 'command-timeout-wired', description: 'CLI --timeout wired to IpcClient.commandTimeoutMs (previously ignored)' },
  { id: 'attach-codesys-tool', description: 'attach_codesys tool for Premium edition (Tools > Scripting > Execute Script File flow)' },
  { id: 'create-pou-function-return-type', description: 'create_pou for type=Function accepts returnType parameter' },
  { id: 'create-pou-interface', description: 'create_pou supports type=Interface via parent.create_interface()' },
  { id: 'create-pou-parameter-list', description: 'create_pou type=ParameterList probes 7 candidate method names + enum fallback' },
  { id: 'compile-project-categories', description: 'compile_project / get_compile_messages force-merge Build / Precompile / Additional code checks category GUIDs + re-enumerate post-build' },
  { id: 'compile-project-library', description: 'compile_project supports .library projects via check_all_pool_objects path' },
  { id: 'close-project-tool', description: 'close_project tool for switching between projects without shutdown+launch' },
  { id: 'install-library-to-repository', description: 'install_library_to_repository with 3-arg signature (path, repo, overwrite=True)' },
  { id: 'set-project-info', description: 'set_project_info / get_project_info tools (Project Information node read/write)' },
  { id: 'task-configuration', description: 'get_task_configuration / set_task_parameter (TaskConfiguration node name normalization)' },
  { id: 'gateway-guid-resolution', description: 'connect_to_device resolves gateway display name to GUID via communication_manager' },
  { id: 'watcher-heartbeat', description: 'watcher writes heartbeat.signal every ~5s + stale-file cleanup at startup' },
  { id: 'stalled-state', description: 'CodesysState=stalled when heartbeat stale; executeScript rejects fast with guiding error' },
  { id: 'force-reset-watcher', description: 'force_reset_watcher tool for fast lock recovery (kill+cleanup+relaunch)' },
  { id: 'diagnose-mcp-state', description: 'diagnose_mcp_state read-only diagnostic dump with interpretation' },
  { id: 'auto-recovery', description: 'ResilientExecutor auto-triggers forceReset on 2 consecutive timeouts and retries' },
  { id: 'structured-json-responses', description: 'get_project_info / get_task_configuration return parsed JSON payload via formatStructuredResponse' },
  { id: 'mcp-error-codes', description: 'MCPErrorCode enum + SCRIPT_ERROR_CODE: marker in script outputs' },
  // ─── Round 3 phase B: library repository visibility ──────────────
  { id: 'list-library-repository', description: 'list_library_repository / uninstall_library_from_repository tools (per-repo enumeration + name extraction fallback)' },
  { id: 'library-parameters', description: 'get_library_parameters / set_library_parameter / reset_library_parameter (probe-driven; gracefully reports API-not-exposed)' },
  { id: 'library-parameters-export-import', description: 'export_library_parameters / import_library_parameters round-trip via JSON' },
  { id: 'rebuild-library', description: 'rebuild_library with compiled-artifact regen attempt (soft warning on ERR_API_NOT_EXPOSED Standard)' },
  { id: 'diff-library-versions', description: 'diff_library_versions tool (pure-Node parser, no AB needed) for PLCopen XML inputs' },
  // ─── Round 3 phase C: workflow tools ─────────────────────────────
  { id: 'clean-project', description: 'clean_project tool: target_app.clean() + .precompilecache / .compileinfo / .bootinfo eviction' },
  { id: 'set-library-reference-version', description: 'set_library_reference_version tool (pin/update lib ref version with backup)' },
  { id: 'release-library-version', description: 'release_library_version composite: set_project_info + rebuild + install + copy-to-dist + optional git tag / gh release' },
  { id: 'inspect-project-tree', description: 'inspect_project_tree unified JSON dump (devices/libraries/pous/gvls/duts/folders/tasks + counts + countsHint)' },
  { id: 'create-ac500-project', description: 'create_ac500_project bootstrap (copy AC500 V3 template + addLibraries)' },
  // ─── Round 3 phase D-E: online priming + offline parsing ─────────
  { id: 'online-application-reuse-probe', description: 'ensure_online_connection probes 4 hosts x 6 attrs for target_app.online_application reuse (Premium-only path)' },
  { id: 'get-pou-dependency-graph', description: 'get_pou_dependency_graph: directed call graph + dead-code detection from rootPOU' },
  { id: 'offline-parsing', description: 'get_all_pou_code_offline / search_code_offline pure-Node parsers (PLCopen XML inputs, no AB required)' },
  // ─── Round 3 export workflow ─────────────────────────────────────
  { id: 'export-project-to-plcopen-xml', description: 'export_project_to_plcopen_xml standalone tool wrapping project.export_plcopenxml()' },
  { id: 'diff-libraries-via-export', description: 'diff_libraries_via_export composite: open libA + export + close x2 + diff_library_versions (solves .library binary format)' },
  // ─── Round 3 follow-up fixes (empirical from NEXO PLC testing) ───
  { id: 'ensure-project-open-skip-when-primary', description: 'ensure_project_open returns primary unchanged when path matches (unlocks runtime ops after UI Online Login takes the .lock)' },
  { id: 'list-library-repository-diagnostic', description: 'list_library_repository diagnostic dump (first-entry type + hasattr probe) when API enumeration yields 0 surfaced libraries' },
  { id: 'inspect-tree-kind-normalization', description: 'inspect_project_tree: normalize node-name match (LibraryManager / TaskConfiguration) by stripping spaces+underscores both sides; extended countsHint to gvls/duts/tasks' },
  { id: 'gateway-resolver-none-on-unavailable', description: 'connect_to_device gateway resolver returns None when communication_manager unavailable (skips set_gateway_and_address instead of passing the friendly name and getting a cryptic GUID error)' },
  { id: 'pep263-encoding-injection', description: 'ScriptManager defensively prepends `# -*- coding: utf-8 -*-` to every generated script (idempotent) so a stray non-ASCII comment cannot break IronPython parsing' },
  { id: 'safe-online-login', description: 'safe_online_login() helper probes login() signature variants (change_option / force=True/False / no-args) — fixes SP19 `login() takes 2 arguments (0 given)` regression' },
  { id: 'set-library-reference-version-better-error', description: 'set_library_reference_version distinguishes 0-children (Standard limit -> AB UI fallback hint) from name-typo (shows enumerated names) in ERR_LIB_NOT_FOUND' },
  { id: 'unicode-text-decode', description: 'to_codesys_text() helper decodes bytes->unicode before assigning to .NET String properties (textual_declaration / textual_implementation / project_info / library_parameter / device_parameter). Prevents silent Unicode->NUL corruption (U+2500 box-drawing, U+2014 em-dash, etc.) that broke compile downstream when struct fields followed the corrupted comment line' },
];

/** Read the MCP package.json version. Cached after first call. */
let _cachedPackageVersion: string | null = null;
function getPackageVersion(): string {
  if (_cachedPackageVersion !== null) return _cachedPackageVersion;
  try {
    // dist/server.js sits next to dist/, while package.json is at dist/../
    // Resolve relative to this file's directory.
    const pkgPath = path.join(__dirname, '..', 'package.json');
    const raw = fs.readFileSync(pkgPath, 'utf-8');
    const pkg = JSON.parse(raw);
    _cachedPackageVersion = String(pkg.version ?? 'unknown');
  } catch {
    _cachedPackageVersion = 'unknown';
  }
  return _cachedPackageVersion;
}

/**
 * Resolve the current git commit SHA for the installed MCP code. Best-effort:
 * if the repo isn't a git checkout (e.g. installed via npm tarball), returns
 * 'unknown'. Run synchronously since this is a cold-path tool call.
 */
function getBuildSha(): string {
  try {
    const { execSync } = require('child_process');
    // Run in the package root (dist's parent).
    const repoRoot = path.join(__dirname, '..');
    const sha = execSync('git rev-parse HEAD', {
      cwd: repoRoot,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 3_000,
    });
    return String(sha).trim();
  } catch {
    return 'unknown';
  }
}

export async function startMcpServer(config: ServerConfig): Promise<void> {
  // Set log level
  if (config.debug) setLogLevel('debug');
  else if (config.verbose) setLogLevel('info');

  serverLog.info(`Starting CODESYS Persistent MCP Server v0.1.0`);
  serverLog.info(`Mode: ${config.mode}`);
  serverLog.info(`CODESYS Path: ${config.codesysPath}`);
  serverLog.info(`Profile: ${config.profileName}`);
  serverLog.info(`Workspace: ${config.workspaceDir}`);

  // Validate CODESYS path
  if (!fs.existsSync(config.codesysPath)) {
    throw new Error(`CODESYS executable not found: ${config.codesysPath}`);
  }

  // Initialize executor based on mode.
  //
  // IMPORTANT: We do NOT await launcher.launch() here. CODESYS persistent startup
  // takes ~30s, but the MCP `initialize` handshake from Claude Code times out long
  // before that — making the server look "Failed to connect" while a zombie CODESYS
  // process stays running. Instead we register tools, connect the stdio transport
  // immediately (so the handshake answers in milliseconds), then kick the launch
  // off in the background and swap the executor reference once it's ready.
  // Tool handlers below capture `executor` as a `let` binding, so reassignment
  // propagates without further changes.
  // Stable proxy reference. Tool handlers capture `executor` once (it's a
  // const) and never see the inner swap directly - the proxy gates every
  // executeScript on a readiness promise that's atomically updated whenever
  // the inner executor changes (see executor-proxy.ts for the contract).
  let launcher: CodesysLauncher | null = null;
  // resilientLauncher wraps `launcher` with auto-recovery on consecutive
  // timeouts. We swap THIS into the executor proxy (not the raw launcher),
  // so command timeouts trigger forceReset() + retry transparently when
  // the watcher silently goes catatonic. Created together with the launcher
  // so handlers that pass `launcher` to `executor.swap*` get the resilient
  // wrapper instead.
  let resilientLauncher: ResilientExecutor | null = null;
  let executionMode: ExecutionMode = config.mode;
  const initialExecutor: ScriptExecutor = new HeadlessExecutor(config);
  const executor = new ExecutorProxy(initialExecutor);

  // BackupManager: snapshots .project/.library files before destructive
  // tool handlers run. Created once and shared across all handlers.
  // Opt-out via config.autoBackup = false (CLI: --no-auto-backup).
  const backupManager = new BackupManager({ autoBackup: config.autoBackup });

  if (config.mode === 'persistent') {
    launcher = new CodesysLauncher(config);
    resilientLauncher = new ResilientExecutor(launcher);
    // Start in headless mode; we'll swap to the persistent launcher once it's
    // ready (see "Background auto-launch" block below).
    executionMode = 'headless';
  }

  const scriptManager = new ScriptManager();
  const workspaceDir = config.workspaceDir;

  // Create MCP server
  const server = new McpServer(
    {
      name: 'CODESYS Persistent MCP Server',
      version: '0.1.0',
    },
    {
      capabilities: {
        resources: { listChanged: true },
        tools: { listChanged: true },
      },
    }
  );

  // Note: using 'as any' cast on server for tool() calls to work around
  // TS2589 deep type instantiation with MCP SDK generics + Zod.
  const s = server as any;

  // ─── Management Tools ────────────────────────────────────────────────

  s.tool(
    'launch_codesys',
    'Manually launch CODESYS with UI. Use when --no-auto-launch was set. If a still-running AB from a previous keep-alive session is detected, this adopts it (no cold start) instead of spawning a second instance.',
    async () => {
      if (!launcher) {
        return {
          content: [{ type: 'text' as const, text: 'Persistent mode not configured. Use --mode persistent.' }],
          isError: true,
        };
      }
      try {
        // Prefer adopting a still-running AB (left alive by --keep-alive across
        // a server recycle) over a fresh ~2min cold start. This is the path the
        // typical "--no-auto-launch + manual launch_codesys" setup hits after a
        // client reconnect, so adoption must live HERE too, not only in the
        // background auto-launch block.
        let adopted = false;
        try {
          adopted = await launcher.adoptExisting();
        } catch (adoptErr) {
          const m = adoptErr instanceof Error ? adoptErr.message : String(adoptErr);
          serverLog.warn(`launch_codesys: adoptExisting() raised (ignored, will cold-launch): ${m}`);
        }
        if (!adopted) {
          await launcher.launch();
        }
        // Swap in the RESILIENT wrapper, not the raw launcher, so command
        // timeouts trigger auto-recovery via forceReset().
        executor.swapNow(resilientLauncher!);
        executionMode = 'persistent';
        return {
          content: [{ type: 'text' as const, text: adopted
            ? 'Adopted the already-running CODESYS instance (no cold start). Persistent mode active.'
            : 'CODESYS launched successfully in persistent mode.' }],
          isError: false,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          content: [{ type: 'text' as const, text: `Launch failed: ${msg}` }],
          isError: true,
        };
      }
    }
  );

  s.tool(
    'attach_codesys',
    'Attach to an ALREADY-RUNNING CODESYS / Automation Builder. Two-step flow that puts the user in control of the GUI lifecycle (no auto-spawn, no lock conflicts). Step 1: call without confirm — returns a watcher.py path. The user opens that file in CODESYS via "Tools → Scripting → Execute Script File..." (CODESYS must already be running; open the project there if needed). Step 2: call again with confirm=true — the server polls for the watcher\'s ready signal and switches to persistent mode. Use this instead of launch_codesys when the user wants to drive the GUI themselves.',
    {
      confirm: z.boolean().describe('Pass false (or omit) on the first call to prepare the watcher. Pass true on the second call after the user has started the watcher script inside CODESYS.').optional(),
    },
    async (args: { confirm?: boolean }) => {
      if (!launcher) {
        return {
          content: [{ type: 'text' as const, text: 'Persistent mode not configured. Start the server with --mode persistent.' }],
          isError: true,
        };
      }
      const confirm = args.confirm === true;
      try {
        if (!confirm) {
          const { watcherPath, sessionId } = await launcher.prepareAttach();
          const text = [
            'Watcher prepared. The MCP server is NOT spawning CODESYS — please do these two things in your already-running CODESYS / Automation Builder GUI:',
            '',
            '  1. (Optional) Open the project you want to work on.',
            `  2. Tools → Scripting → Execute Script File... → select:\n     ${watcherPath}`,
            '',
            'Then call attach_codesys again with confirm=true. The server will poll the IPC channel until the watcher signals ready (timeout follows --ready-timeout-ms).',
            '',
            `Session: ${sessionId}`,
          ].join('\n');
          return { content: [{ type: 'text' as const, text }], isError: false };
        }

        // confirm=true → finalise attach: poll ready.signal, swap executor.
        await launcher.completeAttach();
        executor.swapNow(resilientLauncher!);
        executionMode = 'persistent';
        return {
          content: [{ type: 'text' as const, text: 'Attached. Persistent mode active — subsequent tool calls run inside the user\'s CODESYS GUI session.' }],
          isError: false,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          content: [{ type: 'text' as const, text: `attach_codesys failed: ${msg}` }],
          isError: true,
        };
      }
    }
  );

  s.tool(
    'shutdown_codesys',
    'Shut down the persistent CODESYS instance.',
    async () => {
      if (!launcher) {
        return {
          content: [{ type: 'text' as const, text: 'No persistent CODESYS instance to shut down.' }],
          isError: true,
        };
      }
      // Swap the executor BEFORE awaiting shutdown - if shutdown throws
      // mid-flight, we don't want the proxy still pointing at a dead launcher.
      executor.swapNow(new HeadlessExecutor(config));
      executionMode = 'headless';
      try {
        await launcher.shutdown();
        return {
          content: [{ type: 'text' as const, text: 'CODESYS shut down successfully.' }],
          isError: false,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          content: [{ type: 'text' as const, text: `Shutdown failed: ${msg}` }],
          isError: true,
        };
      }
    }
  );

  s.tool(
    'get_codesys_status',
    "Get the current status of the CODESYS instance: lifecycle state, PID, mode, and watcher heartbeat age. State='stalled' means the watcher heartbeat has gone stale (worker thread dead or primary UI thread deadlocked) and force_reset_watcher should be called to recover.",
    async () => {
      const status = launcher ? await launcher.getStatusAsync() : {
        state: 'stopped',
        pid: null,
        sessionId: null,
        ipcDir: null,
        startedAt: null,
        lastError: null,
        heartbeatAgeSeconds: null,
      };
      const text = [
        `State: ${status.state}`,
        `Mode: ${executionMode}`,
        `PID: ${status.pid ?? 'N/A'}`,
        `Session: ${status.sessionId ?? 'N/A'}`,
        `Started: ${status.startedAt ? new Date(status.startedAt).toISOString() : 'N/A'}`,
        status.heartbeatAgeSeconds !== null && status.heartbeatAgeSeconds !== undefined
          ? `Heartbeat: ${status.heartbeatAgeSeconds.toFixed(1)}s ago`
          : `Heartbeat: never (no heartbeat.signal yet)`,
        status.lastError ? `Last Error: ${status.lastError}` : null,
      ].filter(Boolean).join('\n');
      return {
        content: [{ type: 'text' as const, text }],
        isError: false,
      };
    }
  );

  s.tool(
    'get_mcp_version',
    "Returns the MCP server's package version, the git commit SHA of the running build, and the list of named patches applied in this fork. Use to verify which fixes are active before assuming a workaround is needed for a known-fixed bug.",
    async () => {
      const payload = {
        mcpVersion: getPackageVersion(),
        buildSha: getBuildSha(),
        codesysPath: config.codesysPath,
        codesysProfile: config.profileName,
        mode: executionMode,
        patches: MCP_PATCHES,
      };
      return {
        content: [
          { type: 'text' as const, text: JSON.stringify(payload, null, 2) },
        ],
        isError: false,
      };
    }
  );

  s.tool(
    'force_reset_watcher',
    "Recovery tool for when the CODESYS MCP appears 'locked' (commands time out / state is 'stalled' / agent suspects watcher is dead). Kills the CODESYS process, cleans up the IPC directory, and re-launches CODESYS with a fresh watcher in a single operation. Equivalent to shutdown_codesys + launch_codesys but faster (~10-30s) and with stale-file cleanup in between. Does NOT save any open project (the project state is unknown when the watcher is stalled). Use after diagnose_mcp_state confirms a stall.",
    async () => {
      if (!launcher) {
        return {
          content: [{ type: 'text' as const, text: 'No launcher instance available (server is in headless mode). force_reset_watcher only applies to persistent mode.' }],
          isError: true,
        };
      }
      try {
        await launcher.forceReset();
        const status = await launcher.getStatusAsync();
        return {
          content: [{ type: 'text' as const, text: `force_reset_watcher complete. New state: ${status.state}. PID: ${status.pid ?? 'N/A'}.` }],
          isError: false,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          content: [{ type: 'text' as const, text: `force_reset_watcher failed: ${msg}` }],
          isError: true,
        };
      }
    }
  );

  s.tool(
    'diagnose_mcp_state',
    "Read-only diagnostic dump for when something feels off with the MCP. Returns: launcher lifecycle state, process liveness, watcher heartbeat age, pending command queue depth, orphan result file count, last watcher_error.txt contents, plus a human-readable interpretation telling you whether the state is healthy / stalled / process-died / recovering. Use this BEFORE force_reset_watcher so you know whether the reset is actually needed (vs. e.g. a long-running command in flight).",
    async () => {
      if (!launcher) {
        return {
          content: [{ type: 'text' as const, text: 'No launcher instance available (server is in headless mode).' }],
          isError: false,
        };
      }
      const d = await launcher.diagnose();
      const lines: string[] = [];
      lines.push(`=== MCP DIAGNOSTIC STATE ===`);
      lines.push(`Launcher state: ${d.status.state}`);
      lines.push(`Process alive: ${d.isProcessAlive ? 'yes' : 'no'} (PID ${d.status.pid ?? 'N/A'})`);
      lines.push(`Started: ${d.status.startedAt ? new Date(d.status.startedAt).toISOString() : 'N/A'}`);
      if (d.status.heartbeatAgeSeconds === null || d.status.heartbeatAgeSeconds === undefined) {
        lines.push(`Heartbeat: never (no heartbeat.signal exists)`);
      } else {
        lines.push(`Heartbeat: ${d.status.heartbeatAgeSeconds.toFixed(1)}s old`);
      }
      if (d.queueDepth) {
        lines.push(`Pending commands: ${d.queueDepth.pendingCommands}`);
        lines.push(`Orphan results: ${d.queueDepth.orphanResults}`);
      }
      if (d.status.lastError) {
        lines.push(`Last error: ${d.status.lastError}`);
      }
      if (d.watcherErrorLog) {
        lines.push(`--- watcher_error.txt ---`);
        const trimmed = d.watcherErrorLog.length > 2000
          ? '...(truncated)...\n' + d.watcherErrorLog.slice(-2000)
          : d.watcherErrorLog;
        lines.push(trimmed);
        lines.push(`--- end watcher_error.txt ---`);
      }
      lines.push(`Interpretation: ${d.interpretation}`);
      return {
        content: [{ type: 'text' as const, text: lines.join('\n') }],
        isError: false,
      };
    }
  );

  // ─── Project Tools ───────────────────────────────────────────────────

  s.tool(
    'open_project',
    'Opens an existing CODESYS project file.',
    {
      filePath: z.string().describe("Path to the project file (e.g., 'C:/Projects/MyPLC.project')."),
    },
    async (args: { filePath: string }) => {
      const escaped = resolvePath(args.filePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'open_project', { PROJECT_FILE_PATH: escaped }, ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(result, `Project opened: ${args.filePath}`);
    }
  );

  s.tool(
    'create_project',
    'Creates a new CODESYS project from the standard template.',
    {
      filePath: z.string().describe("Path where the new project file should be created."),
    },
    async (args: { filePath: string }) => {
      const absPath = path.normalize(
        path.isAbsolute(args.filePath) ? args.filePath : path.join(workspaceDir, args.filePath)
      );

      // Find template project
      let templatePath = '';
      try {
        const baseDir = path.dirname(path.dirname(config.codesysPath));
        templatePath = path.normalize(path.join(baseDir, 'Templates', 'Standard.project'));
        if (!(await fileExists(templatePath))) {
          const programData = process.env.ALLUSERSPROFILE || process.env.ProgramData || 'C:\\ProgramData';
          const pd1 = path.normalize(path.join(programData, 'CODESYS', 'CODESYS', config.profileName, 'Templates', 'Standard.project'));
          if (await fileExists(pd1)) {
            templatePath = pd1;
          } else {
            const pd2 = path.normalize(path.join(programData, 'CODESYS', 'Templates', 'Standard.project'));
            if (await fileExists(pd2)) {
              templatePath = pd2;
            } else {
              throw new Error('Standard template project file not found.');
            }
          }
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        return {
          content: [{ type: 'text' as const, text: `Template Error: ${msg}` }],
          isError: true,
        };
      }

      const script = scriptManager.prepareScript('create_project', {
        PROJECT_FILE_PATH: absPath,
        TEMPLATE_PROJECT_PATH: templatePath,
      });
      const result = await executor.executeScript(script);
      return formatToolResponse(result, `Project created from template: ${absPath}`);
    }
  );

  s.tool(
    'save_project',
    'Saves the currently open CODESYS project.',
    {
      projectFilePath: z.string().describe("Path to the project file to ensure is open before saving."),
    },
    async (args: { projectFilePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'save_project', { PROJECT_FILE_PATH: escaped }, ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(result, `Project saved: ${args.projectFilePath}`);
    }
  );

  s.tool(
    'set_project_info',
    "Updates the Project Information node (Title / Version / Author / Company / Description). Mirrors the AB UI menu 'Project > Project Information'. Pass only the fields you want to change; omitted fields are left untouched. Saves the project after applying changes. Useful for automated version bumps in CI/CD pipelines that maintain a library's auto-generated GetVersion() POU.",
    {
      projectFilePath: z.string().describe("Path to the project file."),
      version: z.string().describe("Project version. Format: 'MAJOR.MINOR.SERVICEPACK[.BUILD]', e.g. '1.0.5' or '1.0.5.42'.").optional(),
      title: z.string().describe("Project title.").optional(),
      author: z.string().describe("Project author.").optional(),
      company: z.string().describe("Project company.").optional(),
      description: z.string().describe("Project description (multi-line allowed).").optional(),
    },
    async (args: { projectFilePath: string; version?: string; title?: string; author?: string; company?: string; description?: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const provided = [
        args.version !== undefined ? 'version' : '',
        args.title !== undefined ? 'title' : '',
        args.author !== undefined ? 'author' : '',
        args.company !== undefined ? 'company' : '',
        args.description !== undefined ? 'description' : '',
      ].filter(Boolean);
      if (provided.length === 0) {
        return {
          content: [{ type: 'text' as const, text: 'Error: at least one of version/title/author/company/description must be provided.' }],
          isError: true,
        };
      }
      const script = scriptManager.prepareScriptWithHelpers(
        'set_project_info',
        {
          PROJECT_FILE_PATH: escaped,
          VERSION: args.version ?? '',
          TITLE: args.title ?? '',
          AUTHOR: args.author ?? '',
          COMPANY: args.company ?? '',
          DESCRIPTION: args.description ?? '',
        },
        ['_text_utils', 'ensure_project_open']
      );
      await backupManager.snapshot(escaped);
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Project Information updated (fields: ${provided.join(', ')}) on ${args.projectFilePath}.`
      );
    }
  );

  s.tool(
    'get_project_info',
    "Reads the Project Information node fields (version, title, author, company, description). Returns a JSON object with the present fields. Mirrors what is shown in the AB UI menu 'Project > Project Information'.",
    {
      projectFilePath: z.string().describe("Path to the project file."),
    },
    async (args: { projectFilePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'get_project_info',
        { PROJECT_FILE_PATH: escaped },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      // Return the structured JSON payload emitted by emit_result() so callers
      // (LLM or scripts) can actually consume the version/title/author fields.
      // Previously formatToolResponse stripped the JSON and returned only the
      // success summary string, making the tool useless for chained tooling.
      return formatStructuredResponse(
        result,
        `Project Information read for ${args.projectFilePath}.`
      );
    }
  );

  s.tool(
    'close_project',
    "Closes the currently open primary CODESYS project so that another project can be opened. Saves first unless 'force' is true. No-op if no project is currently open. Use this when switching between a library project and a consumer project to avoid the ~30-60s shutdown_codesys/launch_codesys cycle.",
    {
      projectFilePath: z.string().describe("Path to the project file expected to be open (used only for diagnostics; the tool closes whichever project is the current primary)."),
      force: z.boolean().describe("If true, skip saving and discard unsaved changes. Default false (saves first).").optional(),
    },
    async (args: { projectFilePath: string; force?: boolean }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScript('close_project', {
        PROJECT_FILE_PATH: escaped,
        FORCE: args.force ? 'true' : 'false',
      });
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        args.force
          ? `Project closed (force=true, unsaved changes discarded): ${args.projectFilePath}`
          : `Project saved and closed: ${args.projectFilePath}`
      );
    }
  );

  // ─── POU Tools ───────────────────────────────────────────────────────

  s.tool(
    'create_pou',
    'Creates a new Program, Function Block, Function, Interface, or Parameter List POU within the specified CODESYS project.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      name: z.string().min(1).describe("Name for the new POU (must be a valid IEC identifier)."),
      type: z.enum(['Program', 'FunctionBlock', 'Function', 'Interface', 'ParameterList']).describe("Type of POU. 'Interface' creates an abstract OOP contract with no implementation; add methods to it via the create_method tool. 'ParameterList' creates a CODESYS Parameter List (library consumer-overridable VAR_GLOBAL CONSTANT block surfaced under the Library Manager 'Parameters' tab); populate it with set_pou_code on the declaration section. NOTE: ParameterList creation is empirically not supported by the IronPython ScriptEngine on AB 2.9 Standard edition (PouType.ParameterList enum member is absent and no create_parameterlist* method is exposed on parent objects). If the call fails with a diagnostic RuntimeError, fall back to creating the POU manually in the AB UI (Add Object -> Parameter List) and then use set_pou_code to populate its declaration. May work on AB 2.9 Premium or future CODESYS V3.5 SPxx builds that expose the API."),
      language: z.enum(['ST', 'LD', 'FBD', 'SFC', 'IL', 'CFC']).describe("Implementation language. Ignored for Interface and ParameterList POUs (no implementation section)."),
      parentPath: z.string().min(1).describe("Relative path under project root or application (e.g., 'Application')."),
      returnType: z.string().describe("Return type for Function POUs (e.g., 'BOOL', 'STRING', 'INT', 'REAL'). Required when type is 'Function'; ignored for 'Program', 'FunctionBlock', 'Interface', and 'ParameterList'.").optional(),
    },
    async (args: { projectFilePath: string; name: string; type: 'Program' | 'FunctionBlock' | 'Function' | 'Interface' | 'ParameterList'; language: 'ST' | 'LD' | 'FBD' | 'SFC' | 'IL' | 'CFC'; parentPath: string; returnType?: string }) => {
      // Function POUs require a return_type per CODESYS scripting API.
      if (args.type === 'Function' && (!args.returnType || !args.returnType.trim())) {
        return {
          content: [{ type: 'text' as const, text: `Error: Function POUs require a 'returnType' parameter (e.g. 'BOOL', 'STRING', 'INT'). Pass returnType when type is 'Function'.` }],
          isError: true,
        };
      }
      const escProjPath = resolvePath(args.projectFilePath, workspaceDir);
      const sanParentPath = sanitizePouPath(args.parentPath);
      const script = scriptManager.prepareScriptWithHelpers(
        'create_pou',
        {
          PROJECT_FILE_PATH: escProjPath,
          POU_NAME: args.name.trim(),
          POU_TYPE_STR: args.type,
          IMPL_LANGUAGE_STR: args.language,
          PARENT_PATH: sanParentPath,
          RETURN_TYPE: (args.returnType ?? '').trim(),
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `POU '${args.name}' created in '${sanParentPath}' of ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'set_pou_code',
    'Sets the declaration and/or implementation code for a specific POU, Method, or Property. Omit (or pass empty string for) a section to leave it unchanged.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      pouPath: z.string().min(1).describe("Path to the target POU/Method/Property. Accepted forms (any of): full-from-root 'Application/MyPOU' or library 'MyLib/Function Blocks/FB_X[/Method]'; an unambiguous bare leaf name 'FB_X' or even a nested method 'VerifyInput' (resolved by recursive search). Ambiguous bare names error cleanly."),
      declarationCode: z.string().optional().describe("Code for the declaration part (VAR...END_VAR). If omitted or empty, not changed."),
      implementationCode: z.string().optional().describe("Code for the implementation logic. If omitted or empty, not changed."),
    },
    async (args: { projectFilePath: string; pouPath: string; declarationCode?: string; implementationCode?: string }) => {
      // Treat empty string the same as omitted - the previous code silently
      // overwrote the section with an empty string, which was surprising and
      // caused data loss. To explicitly clear a section, pass a single-line
      // placeholder like a comment.
      const declProvided = args.declarationCode !== undefined && args.declarationCode !== '';
      const implProvided = args.implementationCode !== undefined && args.implementationCode !== '';
      if (!declProvided && !implProvided) {
        return {
          content: [{ type: 'text' as const, text: 'Error: At least one of declarationCode or implementationCode must be provided (and non-empty).' }],
          isError: true,
        };
      }
      const escProjPath = resolvePath(args.projectFilePath, workspaceDir);
      const sanPouPath = sanitizePouPath(args.pouPath);
      const script = scriptManager.prepareScriptWithHelpers(
        'set_pou_code',
        {
          PROJECT_FILE_PATH: escProjPath,
          POU_FULL_PATH: sanPouPath,
          DECLARATION_CONTENT: args.declarationCode ?? '',
          IMPLEMENTATION_CONTENT: args.implementationCode ?? '',
          UPDATE_DECL: declProvided ? '1' : '0',
          UPDATE_IMPL: implProvided ? '1' : '0',
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      // Snapshot before destructive op (no-op when autoBackup=false).
      await backupManager.snapshot(escProjPath);
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Code set for '${sanPouPath}' in ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'create_property',
    'Creates a new Property within a specific Function Block POU.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      parentPouPath: z.string().describe("Relative path to the parent Function Block POU (e.g., 'Application/MyFB')."),
      propertyName: z.string().describe("Name for the new property (must be a valid IEC identifier)."),
      propertyType: z.string().describe("Data type of the property (e.g., 'BOOL', 'INT', 'MyDUT')."),
    },
    async (args: { projectFilePath: string; parentPouPath: string; propertyName: string; propertyType: string }) => {
      const escProjPath = resolvePath(args.projectFilePath, workspaceDir);
      const sanParentPath = sanitizePouPath(args.parentPouPath);
      const script = scriptManager.prepareScriptWithHelpers(
        'create_property',
        {
          PROJECT_FILE_PATH: escProjPath,
          PARENT_POU_FULL_PATH: sanParentPath,
          PROPERTY_NAME: args.propertyName.trim(),
          PROPERTY_TYPE: args.propertyType.trim(),
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Property '${args.propertyName}' created under '${sanParentPath}' in ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'create_method',
    'Creates a new Method within a specific Function Block POU.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      parentPouPath: z.string().describe("Relative path to the parent Function Block POU (e.g., 'Application/MyFB')."),
      // Accept BOTH `name` (matches create_pou) and `methodName` (legacy) so a
      // first call doesn't fail with InputValidationError over the param-name
      // inconsistency (NEXO feedback 2026-06-06). At least one must be present.
      methodName: z.string().optional().describe("Name of the new method (must be a valid IEC identifier). Alias of `name`."),
      name: z.string().optional().describe("Name of the new method (alias of `methodName`, matches create_pou's param)."),
      returnType: z.string().optional().describe("Return type (e.g., 'BOOL', 'INT'). Leave empty or omit for no return value."),
    },
    async (args: { projectFilePath: string; parentPouPath: string; methodName?: string; name?: string; returnType?: string }) => {
      const methodName = (args.methodName ?? args.name ?? '').trim();
      if (!methodName) {
        return {
          content: [{ type: 'text' as const, text: 'Error: provide the method name via `name` (or `methodName`).' }],
          isError: true,
        };
      }
      const escProjPath = resolvePath(args.projectFilePath, workspaceDir);
      const sanParentPath = sanitizePouPath(args.parentPouPath);
      const script = scriptManager.prepareScriptWithHelpers(
        'create_method',
        {
          PROJECT_FILE_PATH: escProjPath,
          PARENT_POU_FULL_PATH: sanParentPath,
          METHOD_NAME: methodName,
          RETURN_TYPE: (args.returnType ?? '').trim(),
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Method '${methodName}' created under '${sanParentPath}' in ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'compile_project',
    'Compiles (Builds) the primary application within a CODESYS project. Returns structured compiler messages (errors, warnings) when available.',
    {
      projectFilePath: z.string().describe("Path to the project file containing the application to compile."),
    },
    async (args: { projectFilePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'compile_project', { PROJECT_FILE_PATH: escaped }, ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script, 120_000); // 120s timeout for compile

      const success = result.success && result.output.includes('SCRIPT_SUCCESS');

      // Parse structured compile messages if present
      let compileMessages: Array<{ severity: string; text: string; object?: string; line?: number }> = [];
      const msgStartMarker = '### COMPILE_MESSAGES_START ###';
      const msgEndMarker = '### COMPILE_MESSAGES_END ###';
      const msgStartIdx = result.output.indexOf(msgStartMarker);
      const msgEndIdx = result.output.indexOf(msgEndMarker);
      if (msgStartIdx !== -1 && msgEndIdx !== -1 && msgStartIdx < msgEndIdx) {
        try {
          const jsonStr = result.output.substring(msgStartIdx + msgStartMarker.length, msgEndIdx).trim();
          compileMessages = JSON.parse(jsonStr);
        } catch {
          // JSON parse failed, ignore
        }
      }

      // Build response message
      let message: string;
      let isError = !success;

      if (!success) {
        message = `Failed initiating compilation for ${args.projectFilePath}. Output:\n${result.output}`;
      } else if (compileMessages.length > 0) {
        // Treat 'fatal' as an error too. The Python script emits 'fatal'
        // for Severity.FatalError; without this filter, fatals are
        // silently dropped from the formatted output.
        const errors = compileMessages.filter(
          (m) => m.severity === 'error' || m.severity === 'fatal'
        );
        const warnings = compileMessages.filter((m) => m.severity === 'warning');
        const formatMsg = (m: { severity: string; text: string; object?: string; line?: number }) => {
          const loc = m.object ? (m.line != null ? ` [${m.object}:${m.line}]` : ` [${m.object}]`) : '';
          return `${m.severity.toUpperCase()}: ${m.text}${loc}`;
        };

        message = `Compilation complete for ${args.projectFilePath}.\n`;
        message += `${errors.length} error(s), ${warnings.length} warning(s).\n`;
        if (errors.length > 0) {
          message += '\nErrors:\n' + errors.map(formatMsg).join('\n');
          isError = true;
        }
        if (warnings.length > 0) {
          message += '\nWarnings:\n' + warnings.map(formatMsg).join('\n');
        }
      } else {
        // No structured messages available — fall back to old behavior
        message = `Compilation initiated for ${args.projectFilePath}.`;
        const hasCompileErrors =
          result.output.includes('Compile complete --') &&
          !/ 0 error\(s\),/.test(result.output);
        if (hasCompileErrors) {
          message += ' WARNING: Build command reported errors. Use get_compile_messages for details.';
          isError = true;
        }
      }

      // Surface the Python script's DEBUG / WARN lines so the caller can
      // see which categories were scanned, what severity histogram each
      // produced, and why a given error was or was not caught. Without
      // this, those print() lines were swallowed by the success path. The
      // full trace is also mirrored to %TEMP%/codesys-mcp-compile-debug.txt
      // by the Python script for post-mortem inspection.
      try {
        const debugLines = result.output
          .split(/\r?\n/)
          .filter((line) => /^(DEBUG:|WARN:)/.test(line));
        if (debugLines.length > 0) {
          message += '\n\n[script diagnostics]:\n' + debugLines.join('\n');
        }
      } catch {
        // best-effort surfacing; ignore failures
      }

      return { content: [{ type: 'text' as const, text: message }], isError };
    }
  );

  s.tool(
    'rebuild_library',
    "Force a full rebuild of a .library project. Runs target_app.clean() (cache invalidation) + check_all_pool_objects() (source-level semantic check) and, when regenerateCompiledArtifacts=true (default), attempts to regenerate the compiled-library artifacts embedded in the .library project file -- mirrors the AB UI 'Build > Generate Library'. The compiled-artifact regeneration is best-effort: not all CODESYS builds expose generate_compiled_library() and the tool surfaces ERR_API_NOT_EXPOSED with a SOFT warning (source rebuild still succeeded) when not available.",
    {
      libraryProjectFilePath: z.string().describe("Path to the .library project file to rebuild."),
      regenerateCompiledArtifacts: z.boolean().describe("If true (default), also attempt to regenerate compiled-library artifacts inside the .library file.").optional(),
    },
    async (args: { libraryProjectFilePath: string; regenerateCompiledArtifacts?: boolean }) => {
      const escaped = resolvePath(args.libraryProjectFilePath, workspaceDir);
      const regen = args.regenerateCompiledArtifacts !== false;
      const script = scriptManager.prepareScriptWithHelpers(
        'rebuild_library',
        {
          PROJECT_FILE_PATH: escaped,
          REGENERATE_ARTIFACTS: regen ? 'true' : 'false',
        },
        ['_text_utils', 'ensure_project_open']
      );
      await backupManager.snapshot(escaped);
      const result = await executor.executeScript(script, 180_000); // 3 min for big libs
      return formatStructuredResponse(
        result,
        `Library rebuild requested for ${args.libraryProjectFilePath}.`
      );
    }
  );

  s.tool(
    'get_pou_dependency_graph',
    "Build a directed call graph of POUs/FBs/Methods in the project: for each pair (caller, callee) the script detects whether the callee's name appears word-boundary-matched in the caller's body. Optionally compute reachability from a root POU (typically 'PLC_PRG') to flag dead-code POUs not reachable from the application's entry point. Useful for architecture review, refactoring impact analysis, and understanding why a typo in an unreferenced POU did NOT show up in compile (CODESYS doesn't analyze unreachable code).",
    {
      projectFilePath: z.string().describe("Path to the project file."),
      rootPOU: z.string().describe("Optional root POU name (e.g. 'PLC_PRG'). When provided, the graph is annotated with isDeadCode=true for POUs unreachable from this root.").optional(),
    },
    async (args: { projectFilePath: string; rootPOU?: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'get_pou_dependency_graph',
        {
          PROJECT_FILE_PATH: escaped,
          ROOT_POU: (args.rootPOU ?? '').trim(),
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script, 120_000);
      return formatStructuredResponse(result, 'POU dependency graph built.');
    }
  );

  s.tool(
    'create_ac500_project',
    "Create a new AC500 V3 .project file by copying an existing clean AC500 template and optionally adding initial libraries. AB Standard does NOT ship with an AC500-specific stock template that the scripting API can use directly, so the caller provides a known-good AC500 project to use as the base (typically a vanilla NexoPlcExample.project with no user code). The template's device tree (PM5650-2ETH / PM5032 / etc) is preserved exactly. To use a different PLC model, point the templateProjectPath at a project that already targets that model.",
    {
      newProjectPath: z.string().min(1).describe("Path where the new .project file should be created (parent directory is auto-created)."),
      templateProjectPath: z.string().min(1).describe("Path to an existing AC500 V3 .project file to use as the template (its device tree is preserved)."),
      addLibraries: z.string().describe("Optional SEMICOLON-separated list of fully-qualified libraries to add (e.g. 'Standard, * (System); MQTT Client SL, 4.1.0.0 (3S - Smart Software Solutions GmbH)'). Use semicolons to avoid colliding with the commas inside library names.").optional(),
      overwrite: z.boolean().describe("If true (default), overwrite newProjectPath if it exists.").optional(),
    },
    async (args: { newProjectPath: string; templateProjectPath: string; addLibraries?: string; overwrite?: boolean }) => {
      const newPath = resolvePath(args.newProjectPath, workspaceDir);
      const tmplPath = resolvePath(args.templateProjectPath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'create_ac500_project',
        {
          PROJECT_FILE_PATH: tmplPath, // ensure_project_open helper sees template
          NEW_PROJECT_PATH: newPath,
          TEMPLATE_PROJECT_PATH: tmplPath,
          ADD_LIBRARIES_CSV: args.addLibraries ?? '',
          OVERWRITE: args.overwrite === false ? 'false' : 'true',
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      return formatStructuredResponse(result, `AC500 project created: ${args.newProjectPath}.`);
    }
  );

  s.tool(
    'inspect_project_tree',
    "Return a structured JSON dump of the project tree: devices, library references (with version), POUs, GVLs, DUTs, folders, tasks. Categorization is best-effort (CODESYS scripting does not expose a stable type enum, so we infer from probed attributes). Optionally include the first 200 chars of each POU/GVL/DUT declaration for quick orientation. Replaces ad-hoc DFS walks the agent might do via get_all_pou_code+list_project_libraries+get_task_configuration in 3 separate round trips.",
    {
      projectFilePath: z.string().describe("Path to the project file."),
      includeSymbols: z.boolean().describe("If true, embed first 200 chars of each POU/GVL/DUT declaration. Default false (compact dump).").optional(),
    },
    async (args: { projectFilePath: string; includeSymbols?: boolean }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'inspect_project_tree',
        {
          PROJECT_FILE_PATH: escaped,
          INCLUDE_SYMBOLS: args.includeSymbols ? 'true' : 'false',
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      return formatStructuredResponse(result, `Project tree inspected for ${args.projectFilePath}.`);
    }
  );

  s.tool(
    'release_library_version',
    "Orchestrate a library release in a single tool call: (1) set_project_info with the new version, (2) rebuild_library, (3) install_library_to_repository, (4) copy the .library file to distFolder/v{version}/{name}-v{version}.library, and optionally (5) `git tag` + `gh release create` against the repo. Each step is conditional and failures surface step-by-step in the returned JSON. Safer than scripting these calls manually because the steps run in the right order with shared error context.",
    {
      libraryProjectFilePath: z.string().describe("Path to the .library project file to release."),
      version: z.string().min(1).describe("New version string (e.g. '1.0.11'). Format: MAJOR.MINOR.PATCH[.BUILD]."),
      distFolder: z.string().describe("Optional path to a dist folder. The .library file is copied to {distFolder}/v{version}/{name}-v{version}.library after install.").optional(),
      gitTag: z.boolean().describe("If true, run 'git tag v{version}' in the library's repo directory after install. Off by default.").optional(),
      ghRelease: z.boolean().describe("If true and gitTag is also true, run 'gh release create v{version} --generate-notes' after the tag. Off by default.").optional(),
    },
    async (args: { libraryProjectFilePath: string; version: string; distFolder?: string; gitTag?: boolean; ghRelease?: boolean }) => {
      const steps: Array<{ name: string; ok: boolean; detail: string }> = [];
      const recordStep = (name: string, ok: boolean, detail: string): void => {
        steps.push({ name, ok, detail });
      };

      const libPath = resolvePath(args.libraryProjectFilePath, workspaceDir);

      // STEP 1: set_project_info(version)
      try {
        const script = scriptManager.prepareScriptWithHelpers(
          'set_project_info',
          { PROJECT_FILE_PATH: libPath, VERSION: args.version, TITLE: '', AUTHOR: '', COMPANY: '', DESCRIPTION: '' },
          ['_text_utils', 'ensure_project_open']
        );
        await backupManager.snapshot(libPath);
        const r = await executor.executeScript(script);
        const ok = r.success && r.output.includes('SCRIPT_SUCCESS');
        recordStep('set_project_info', ok, ok ? `version set to ${args.version}` : r.output.slice(-500));
        if (!ok) {
          return {
            content: [{ type: 'text' as const, text: JSON.stringify({ released: false, steps }, null, 2) }],
            isError: true,
          };
        }
      } catch (err) {
        recordStep('set_project_info', false, err instanceof Error ? err.message : String(err));
        return {
          content: [{ type: 'text' as const, text: JSON.stringify({ released: false, steps }, null, 2) }],
          isError: true,
        };
      }

      // STEP 2: rebuild_library
      try {
        const script = scriptManager.prepareScriptWithHelpers(
          'rebuild_library',
          { PROJECT_FILE_PATH: libPath, REGENERATE_ARTIFACTS: 'true' },
          ['_text_utils', 'ensure_project_open']
        );
        const r = await executor.executeScript(script, 180_000);
        const ok = r.success && r.output.includes('SCRIPT_SUCCESS');
        recordStep('rebuild_library', ok, ok ? 'rebuild done' : r.output.slice(-500));
        if (!ok) {
          return {
            content: [{ type: 'text' as const, text: JSON.stringify({ released: false, steps }, null, 2) }],
            isError: true,
          };
        }
      } catch (err) {
        recordStep('rebuild_library', false, err instanceof Error ? err.message : String(err));
      }

      // STEP 3: install_library_to_repository
      try {
        const script = scriptManager.prepareScriptWithHelpers(
          'install_library_to_repository',
          { PROJECT_FILE_PATH: libPath, REPOSITORY_NAME: '' },
          ['_text_utils', 'ensure_project_open']
        );
        const r = await executor.executeScript(script);
        const ok = r.success && r.output.includes('SCRIPT_SUCCESS');
        recordStep('install_library_to_repository', ok, ok ? 'installed' : r.output.slice(-500));
        if (!ok) {
          return {
            content: [{ type: 'text' as const, text: JSON.stringify({ released: false, steps }, null, 2) }],
            isError: true,
          };
        }
      } catch (err) {
        recordStep('install_library_to_repository', false, err instanceof Error ? err.message : String(err));
        return {
          content: [{ type: 'text' as const, text: JSON.stringify({ released: false, steps }, null, 2) }],
          isError: true,
        };
      }

      // STEP 4: copy to distFolder
      if (args.distFolder) {
        try {
          const distDir = resolvePath(args.distFolder, workspaceDir);
          const baseName = path.basename(libPath, path.extname(libPath));
          const targetDir = path.join(distDir, `v${args.version}`);
          fs.mkdirSync(targetDir, { recursive: true });
          const targetFile = path.join(targetDir, `${baseName}-v${args.version}.library`);
          fs.copyFileSync(libPath, targetFile);
          recordStep('copy_to_dist', true, `copied to ${targetFile}`);
        } catch (err) {
          recordStep('copy_to_dist', false, err instanceof Error ? err.message : String(err));
        }
      }

      // STEP 5: git tag + gh release (optional)
      if (args.gitTag) {
        try {
          const { execSync } = require('child_process');
          const repoDir = path.dirname(libPath);
          execSync(`git tag v${args.version}`, { cwd: repoDir, timeout: 10_000, stdio: 'pipe' });
          recordStep('git_tag', true, `tagged v${args.version}`);
          if (args.ghRelease) {
            try {
              execSync(`gh release create v${args.version} --generate-notes`, {
                cwd: repoDir,
                timeout: 30_000,
                stdio: 'pipe',
              });
              recordStep('gh_release', true, `release v${args.version} created`);
            } catch (gerr) {
              recordStep('gh_release', false, gerr instanceof Error ? gerr.message : String(gerr));
            }
          }
        } catch (err) {
          recordStep('git_tag', false, err instanceof Error ? err.message : String(err));
        }
      }

      const released = steps.every((s) => s.ok);
      return {
        content: [{ type: 'text' as const, text: JSON.stringify({ released, version: args.version, steps }, null, 2) }],
        isError: !released,
      };
    }
  );

  s.tool(
    'set_library_reference_version',
    "Change the version pin of a library reference in the consumer project's Library Manager (e.g. switch 'NexoMqttLib, * (NEXO)' to 'NexoMqttLib, 1.0.10'). Triggers re-resolution on next compile. Cascades through set_version() / version=property / remove+add fallback paths. WARNING: the remove+add fallback drops any consumer-side parameter overrides on that library -- save/export them first if needed (export_library_parameters).",
    {
      projectFilePath: z.string().describe("Path to the consumer .project file."),
      libraryName: z.string().min(1).describe("Library name in Library Manager."),
      version: z.string().min(1).describe("Target version (e.g. '1.0.10') or '*' for latest available."),
    },
    async (args: { projectFilePath: string; libraryName: string; version: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'set_library_reference_version',
        {
          PROJECT_FILE_PATH: escaped,
          LIBRARY_NAME: args.libraryName.trim(),
          NEW_VERSION: args.version.trim(),
        },
        ['_text_utils', 'ensure_project_open']
      );
      await backupManager.snapshot(escaped);
      const result = await executor.executeScript(script);
      return formatStructuredResponse(
        result,
        `Library reference version updated: ${args.libraryName} -> ${args.version}.`
      );
    }
  );

  s.tool(
    'clean_project',
    "Force a clean rebuild state. Runs target_app.clean() (or project.clean() for library projects) and -- when alsoEvictPrecompileCache=true (default) -- also deletes the .precompilecache / .compileinfo / .bootinfo cache files next to the source. Use when compile_project results don't reflect recent edits (cache lying) or before measuring a true cold-compile time.",
    {
      projectFilePath: z.string().describe("Path to the project file."),
      alsoEvictPrecompileCache: z.boolean().describe("If true (default), also delete <project>.precompilecache / .compileinfo / .bootinfo files from disk.").optional(),
    },
    async (args: { projectFilePath: string; alsoEvictPrecompileCache?: boolean }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const evict = args.alsoEvictPrecompileCache !== false;
      const script = scriptManager.prepareScriptWithHelpers(
        'clean_project',
        {
          PROJECT_FILE_PATH: escaped,
          EVICT_PRECOMPILE_CACHE: evict ? 'true' : 'false',
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      return formatStructuredResponse(result, `Project cleaned: ${args.projectFilePath}.`);
    }
  );

  s.tool(
    'export_project_to_plcopen_xml',
    "Export the project's POUs/DUTs/GVLs to a PLCopen XML file via project.export_plcopenxml(). Equivalent to AB UI 'File > Export PLCopen XML...'. Use as a precursor to the offline / diff tools that need XML input (.project files are binary). Probes export_plcopenxml signature variants since the .NET binding accepts varying numbers of args across CODESYS V3.5 SPxx builds.",
    {
      projectFilePath: z.string().describe("Path to the .project or .library file to export."),
      outputXmlPath: z.string().min(1).describe("Path where the .xml file will be written. Parent directory is auto-created."),
      applicationOnly: z.boolean().describe("If true, export only the active application's tree (smaller, recommended). If false, project-level export including non-application objects.").optional(),
      includeLibraries: z.boolean().describe("If true, recurse into referenced libraries and include their content (heavy; rarely needed). Default false.").optional(),
    },
    async (args: { projectFilePath: string; outputXmlPath: string; applicationOnly?: boolean; includeLibraries?: boolean }) => {
      const escapedProj = resolvePath(args.projectFilePath, workspaceDir);
      const escapedOut = resolvePath(args.outputXmlPath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'export_project_to_plcopen_xml',
        {
          PROJECT_FILE_PATH: escapedProj,
          OUTPUT_XML_PATH: escapedOut,
          APPLICATION_ONLY: args.applicationOnly !== false ? 'true' : 'false',
          INCLUDE_LIBRARIES: args.includeLibraries === true ? 'true' : 'false',
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script, 180_000); // big projects can take a while
      return formatStructuredResponse(result, `PLCopen XML exported to ${args.outputXmlPath}.`);
    }
  );

  s.tool(
    'create_boot_application',
    "Generate a deployable boot application (.app + .crc) from the project's active application via ScriptApplication.create_boot_application(). Equivalent to AB UI 'Online > Create Boot Application' but offline (no PLC connection needed). Runs generate_code() first so the image is current. Premium-confirmed. Returns the output path and byte size; the .crc sibling is written automatically next to the .app.",
    {
      projectFilePath: z.string().describe("Path to the .project file."),
      outputAppPath: z.string().min(1).describe("Path where the .app file will be written (e.g. C:/out/MyApp.app). Parent directory is auto-created; a sibling .crc is written alongside."),
      writeVisuFiles: z.boolean().describe("If true, also write visualization files (uses the 3-arg create_boot_application overload). Default false.").optional(),
    },
    async (args: { projectFilePath: string; outputAppPath: string; writeVisuFiles?: boolean }) => {
      const escapedProj = resolvePath(args.projectFilePath, workspaceDir);
      const escapedOut = resolvePath(args.outputAppPath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'create_boot_application',
        {
          PROJECT_FILE_PATH: escapedProj,
          OUTPUT_APP_PATH: escapedOut,
          WRITE_VISU_FILES: args.writeVisuFiles === true ? 'true' : 'false',
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script, 180_000); // codegen + boot image can be slow
      return formatStructuredResponse(result, `Boot application created at ${args.outputAppPath}.`);
    }
  );

  s.tool(
    'diff_libraries_via_export',
    "Compose-tool: opens libraryA, exports PLCopen XML, closes; opens libraryB, exports XML, closes; runs the structured diff on the two XML files. Solves the binary-format limitation of diff_library_versions in one tool call. SLOW (~30-90s) because it round-trips through CODESYS for both exports. xmlOutputDir (optional) keeps the intermediate XML files for inspection; omit to use %TEMP%.",
    {
      sourceLibraryPath: z.string().min(1).describe("Path to the OLDER .library file."),
      targetLibraryPath: z.string().min(1).describe("Path to the NEWER .library file."),
      xmlOutputDir: z.string().describe("Optional directory to keep the intermediate XML exports. Defaults to %TEMP%.").optional(),
      keepXml: z.boolean().describe("If true, keep the intermediate XML files after diffing (default true when xmlOutputDir is set, false otherwise).").optional(),
    },
    async (args: { sourceLibraryPath: string; targetLibraryPath: string; xmlOutputDir?: string; keepXml?: boolean }) => {
      const srcLib = resolvePath(args.sourceLibraryPath, workspaceDir);
      const tgtLib = resolvePath(args.targetLibraryPath, workspaceDir);
      const xmlDir = args.xmlOutputDir
        ? resolvePath(args.xmlOutputDir, workspaceDir)
        : require('os').tmpdir();
      const keep = args.keepXml ?? !!args.xmlOutputDir;
      const ts = new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 15);
      const srcXml = path.join(xmlDir, `diff-source-${ts}.xml`);
      const tgtXml = path.join(xmlDir, `diff-target-${ts}.xml`);

      const steps: Array<{ step: string; ok: boolean; detail: string }> = [];

      const runExport = async (libPath: string, xmlPath: string, label: string): Promise<boolean> => {
        try {
          // Open / ensure the library is current.
          const openScript = scriptManager.prepareScriptWithHelpers(
            'open_project', { PROJECT_FILE_PATH: libPath }, ['_text_utils', 'ensure_project_open']
          );
          await executor.executeScript(openScript);
          // Export.
          const expScript = scriptManager.prepareScriptWithHelpers(
            'export_project_to_plcopen_xml',
            {
              PROJECT_FILE_PATH: libPath,
              OUTPUT_XML_PATH: xmlPath,
              APPLICATION_ONLY: 'false',
              INCLUDE_LIBRARIES: 'false',
            },
            ['_text_utils', 'ensure_project_open']
          );
          const r = await executor.executeScript(expScript, 180_000);
          const ok = r.success && r.output.includes('SCRIPT_SUCCESS');
          steps.push({ step: `export_${label}`, ok, detail: ok ? `exported to ${xmlPath}` : r.output.slice(-400) });
          if (!ok) return false;
          // Close (force=true so we don't accidentally save anything).
          const closeScript = scriptManager.prepareScript('close_project', { PROJECT_FILE_PATH: libPath, FORCE: 'true' });
          try { await executor.executeScript(closeScript); } catch { /* ignore close errors */ }
          return true;
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          steps.push({ step: `export_${label}`, ok: false, detail: msg });
          return false;
        }
      };

      const srcOk = await runExport(srcLib, srcXml, 'source');
      if (!srcOk) {
        return {
          content: [{ type: 'text' as const, text: JSON.stringify({ diffed: false, steps }, null, 2) }],
          isError: true,
        };
      }
      const tgtOk = await runExport(tgtLib, tgtXml, 'target');
      if (!tgtOk) {
        return {
          content: [{ type: 'text' as const, text: JSON.stringify({ diffed: false, steps }, null, 2) }],
          isError: true,
        };
      }

      // Run the XML diff.
      let diff;
      try {
        diff = diffLibraryFiles(srcXml, tgtXml);
        steps.push({ step: 'diff', ok: true, detail: `diff produced` });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        steps.push({ step: 'diff', ok: false, detail: msg });
        return {
          content: [{ type: 'text' as const, text: JSON.stringify({ diffed: false, steps }, null, 2) }],
          isError: true,
        };
      }

      // Cleanup XML files if not requested to keep.
      if (!keep) {
        try { fs.unlinkSync(srcXml); } catch { /* ignore */ }
        try { fs.unlinkSync(tgtXml); } catch { /* ignore */ }
      }

      const payload: { diffed: boolean; diff: typeof diff; intermediateXml?: { source: string; target: string }; steps: typeof steps } = {
        diffed: true,
        diff,
        steps,
      };
      if (keep) {
        payload.intermediateXml = { source: srcXml, target: tgtXml };
      }

      return {
        content: [{ type: 'text' as const, text: JSON.stringify(payload, null, 2) }],
        isError: false,
      };
    }
  );

  s.tool(
    'diff_library_versions',
    "Compare two PLCopen XML exports of a library (or two snapshots across versions) and return a structured diff: POUs/GVLs/DUTs added/removed/modified, library references added/removed/version-changed, Project Information field changes. **IMPORTANT**: Native CODESYS .library files are binary and unsupported. First export PLCopen XML from each version's library (File > Export PLCopen XML... in AB), then diff the XML files. Useful for release notes auto-generation, pre-install validation, and 'what changed' investigations across versions.",
    {
      sourceLibraryPath: z.string().min(1).describe("Path to the OLDER .library file (the 'from' side)."),
      targetLibraryPath: z.string().min(1).describe("Path to the NEWER .library file (the 'to' side)."),
    },
    async (args: { sourceLibraryPath: string; targetLibraryPath: string }) => {
      try {
        const a = resolvePath(args.sourceLibraryPath, workspaceDir);
        const b = resolvePath(args.targetLibraryPath, workspaceDir);
        const diff = diffLibraryFiles(a, b);
        return {
          content: [{ type: 'text' as const, text: JSON.stringify(diff, null, 2) }],
          isError: false,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          content: [{ type: 'text' as const, text: `diff_library_versions failed: ${msg}` }],
          isError: true,
        };
      }
    }
  );

  s.tool(
    'get_all_pou_code_offline',
    "Read POU/GVL/DUT declaration + implementation bodies from a PLCopen XML export by parsing the file directly -- NO CODESYS instance required. **IMPORTANT**: Native CODESYS .project / .library files on AB 2.9 are in a proprietary BINARY container format and CANNOT be parsed by this tool (it will throw with a guiding error). To use this tool, first run File > Export PLCopen XML... in AB on the project of interest to produce an XML file, then point this tool at the .xml. Useful for concurrent reads while user has the (binary) project open in AB UI -- the export XML is a static snapshot and can be re-parsed at any time.",
    {
      projectFilePath: z.string().describe("Path to the .project / .library file."),
    },
    async (args: { projectFilePath: string }) => {
      try {
        const abs = resolvePath(args.projectFilePath, workspaceDir);
        const snap = parseProjectOffline(abs);
        return {
          content: [{ type: 'text' as const, text: JSON.stringify(snap, null, 2) }],
          isError: false,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          content: [{ type: 'text' as const, text: `get_all_pou_code_offline failed: ${msg}` }],
          isError: true,
        };
      }
    }
  );

  s.tool(
    'search_code_offline',
    "Search POU/GVL/DUT bodies in a PLCopen XML export by parsing the file directly. **IMPORTANT**: Native CODESYS .project / .library files are binary and unsupported (throws with guiding error). Export PLCopen XML from AB first, then point this tool at the .xml. Use for fast searches when AB is busy / locked / would be slow to launch.",
    {
      projectFilePath: z.string().describe("Path to the .project / .library file."),
      pattern: z.string().min(1).describe("Search pattern. Literal substring by default; pass regex=true to interpret as regex."),
      regex: z.boolean().describe("If true, interpret pattern as a regex. Default false (literal substring).").optional(),
      caseSensitive: z.boolean().describe("If true, case-sensitive match. Default false.").optional(),
      maxHits: z.number().int().positive().describe("Maximum hits to return. Default 500.").optional(),
    },
    async (args: { projectFilePath: string; pattern: string; regex?: boolean; caseSensitive?: boolean; maxHits?: number }) => {
      try {
        const abs = resolvePath(args.projectFilePath, workspaceDir);
        const hits = searchProjectOffline(abs, args.pattern, {
          regex: args.regex,
          caseSensitive: args.caseSensitive,
          maxHits: args.maxHits,
        });
        return {
          content: [{ type: 'text' as const, text: JSON.stringify({ pattern: args.pattern, hits }, null, 2) }],
          isError: false,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          content: [{ type: 'text' as const, text: `search_code_offline failed: ${msg}` }],
          isError: true,
        };
      }
    }
  );

  s.tool(
    'get_compile_messages',
    "Retrieves the last compiler messages (errors, warnings) without triggering a new build. Note: returns the cached results from the last compile_project run; if you've edited code since, run compile_project to refresh.",
    {
      projectFilePath: z.string().describe("Path to the project file."),
    },
    async (args: { projectFilePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'get_compile_messages', { PROJECT_FILE_PATH: escaped }, ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);

      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) {
        return formatToolResponse(result, '');
      }

      // Parse structured messages
      let compileMessages: Array<{ severity: string; text: string; object?: string; line?: number }> = [];
      const msgStartMarker = '### COMPILE_MESSAGES_START ###';
      const msgEndMarker = '### COMPILE_MESSAGES_END ###';
      const msgStartIdx = result.output.indexOf(msgStartMarker);
      const msgEndIdx = result.output.indexOf(msgEndMarker);
      if (msgStartIdx !== -1 && msgEndIdx !== -1 && msgStartIdx < msgEndIdx) {
        try {
          const jsonStr = result.output.substring(msgStartIdx + msgStartMarker.length, msgEndIdx).trim();
          compileMessages = JSON.parse(jsonStr);
        } catch {
          // JSON parse failed
        }
      }

      if (compileMessages.length === 0) {
        return {
          content: [{ type: 'text' as const, text: `No compile messages found. The message API may not be available in this CODESYS version.` }],
          isError: false,
        };
      }

      const errors = compileMessages.filter((m) => m.severity === 'error');
      const warnings = compileMessages.filter((m) => m.severity === 'warning');
      const formatMsg = (m: { severity: string; text: string; object?: string; line?: number }) => {
        const loc = m.object ? (m.line != null ? ` [${m.object}:${m.line}]` : ` [${m.object}]`) : '';
        return `${m.severity.toUpperCase()}: ${m.text}${loc}`;
      };

      let message = `${errors.length} error(s), ${warnings.length} warning(s), ${compileMessages.length} total message(s).\n`;
      if (errors.length > 0) {
        message += '\nErrors:\n' + errors.map(formatMsg).join('\n');
      }
      if (warnings.length > 0) {
        message += '\nWarnings:\n' + warnings.map(formatMsg).join('\n');
      }
      const others = compileMessages.filter((m) => m.severity !== 'error' && m.severity !== 'warning');
      if (others.length > 0) {
        message += '\nOther:\n' + others.map(formatMsg).join('\n');
      }

      return {
        content: [{ type: 'text' as const, text: message }],
        isError: errors.length > 0,
      };
    }
  );

  // ─── Project Structure Tools ──────────────────────────────────────────

  s.tool(
    'create_dut',
    'Creates a new Data Unit Type (DUT) - structure, enumeration, union, or alias - within the specified CODESYS project.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      name: z.string().min(1).describe("Name for the new DUT (must be a valid IEC identifier)."),
      dutType: z.enum(['Structure', 'Enumeration', 'Union', 'Alias']).describe("Type of DUT."),
      parentPath: z.string().min(1).describe("Relative path under project root or application (e.g., 'Application')."),
    },
    async (args: { projectFilePath: string; name: string; dutType: 'Structure' | 'Enumeration' | 'Union' | 'Alias'; parentPath: string }) => {
      const escProjPath = resolvePath(args.projectFilePath, workspaceDir);
      const sanParentPath = sanitizePouPath(args.parentPath);
      const script = scriptManager.prepareScriptWithHelpers(
        'create_dut',
        {
          PROJECT_FILE_PATH: escProjPath,
          DUT_NAME: args.name.trim(),
          DUT_TYPE_STR: args.dutType,
          PARENT_PATH: sanParentPath,
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `DUT '${args.name}' (${args.dutType}) created in '${sanParentPath}' of ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'create_gvl',
    'Creates a new Global Variable List (GVL) within the specified CODESYS project.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      name: z.string().describe("Name for the new GVL (must be a valid IEC identifier)."),
      parentPath: z.string().describe("Relative path under project root or application (e.g., 'Application')."),
      declarationCode: z.string().optional().describe("Optional initial declaration code for the GVL (VAR_GLOBAL...END_VAR)."),
    },
    async (args: { projectFilePath: string; name: string; parentPath: string; declarationCode?: string }) => {
      const escProjPath = resolvePath(args.projectFilePath, workspaceDir);
      const sanParentPath = sanitizePouPath(args.parentPath);
      const script = scriptManager.prepareScriptWithHelpers(
        'create_gvl',
        {
          PROJECT_FILE_PATH: escProjPath,
          GVL_NAME: args.name.trim(),
          PARENT_PATH: sanParentPath,
          DECLARATION_CONTENT: args.declarationCode ?? '',
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `GVL '${args.name}' created in '${sanParentPath}' of ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'create_folder',
    'Creates an organizational folder within the CODESYS project tree.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      folderName: z.string().describe("Name for the new folder."),
      parentPath: z.string().describe("Relative path under project root or application (e.g., 'Application')."),
    },
    async (args: { projectFilePath: string; folderName: string; parentPath: string }) => {
      const escProjPath = resolvePath(args.projectFilePath, workspaceDir);
      const sanParentPath = sanitizePouPath(args.parentPath);
      const script = scriptManager.prepareScriptWithHelpers(
        'create_folder',
        {
          PROJECT_FILE_PATH: escProjPath,
          FOLDER_NAME: args.folderName.trim(),
          PARENT_PATH: sanParentPath,
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Folder '${args.folderName}' created in '${sanParentPath}' of ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'delete_object',
    'Deletes a project object (POU, DUT, GVL, folder, etc.) from the CODESYS project. WARNING: This is destructive and cannot be undone. System nodes (Application, Device, Plc Logic, Library Manager, Project Settings, Task Configuration, etc.) are refused.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      objectPath: z.string().describe("Path to the object to delete. Accepted forms (any of): full-from-root 'Application/MyPOU' or library 'MyLib/Function Blocks/FB_X[/Method]'; an unambiguous bare leaf name 'FB_X'. System/top-level nodes (Application, Device, Library Manager, Task Configuration, etc.) are refused."),
    },
    async (args: { projectFilePath: string; objectPath: string }) => {
      const escProjPath = resolvePath(args.projectFilePath, workspaceDir);
      const sanObjPath = sanitizePouPath(args.objectPath);
      // Refuse to delete system nodes by EXACT PATH MATCH - the previous
      // last-segment-only check produced false positives (a user folder
      // named `MainTask` under `Application/SomeFolder/MainTask` was wrongly
      // refused). Match the exact canonical paths instead, plus reject any
      // top-level path (no `/`).
      const SYSTEM_PATHS = new Set([
        'Application',
        'Device',
        'Project Settings',
        '__VisualizationStyle',
        'Device/Plc Logic',
        'Device/Plc Logic/Application',
        'Application/Library Manager',
        'Device/Plc Logic/Application/Library Manager',
        'Application/Task Configuration',
        'Device/Plc Logic/Application/Task Configuration',
        'Application/Task Configuration/MainTask',
        'Device/Plc Logic/Application/Task Configuration/MainTask',
        'Device/Communication',
        'Device/Communication/Ethernet',
        'Device/SoftMotion General Axis Pool',
      ]);
      // Known system node LEAF names. On a LIBRARY project a user POU lives at
      // the root (e.g. bare 'FB_X' or 'NexoMqttLib/Function Blocks/FB_X'), so a
      // blanket "must contain /" rule wrongly refused legitimate bare library
      // POUs (NEXO feedback 2026-06-06). Instead: refuse exact system paths AND
      // bare names that are known system leaves; allow other bare names through
      // -- the Python layer's resolver + (system-node refusal) handles the rest.
      const SYSTEM_LEAVES = new Set([
        'Application', 'Device', 'Plc Logic', 'Project Settings',
        'Library Manager', 'Task Configuration', '__VisualizationStyle',
      ]);
      const isBare = !sanObjPath.includes('/');
      const refused =
        sanObjPath === '' ||
        SYSTEM_PATHS.has(sanObjPath) ||
        (isBare && SYSTEM_LEAVES.has(sanObjPath));
      if (refused) {
        return {
          content: [{
            type: 'text' as const,
            text: `Refused: '${sanObjPath || '(empty)'}' is a system node or top-level object. delete_object only operates on user objects (e.g. 'Application/MyPOU', a full library path like 'MyLib/Function Blocks/FB_X', or an unambiguous bare leaf name).`,
          }],
          isError: true,
        };
      }
      const script = scriptManager.prepareScriptWithHelpers(
        'delete_object',
        {
          PROJECT_FILE_PATH: escProjPath,
          OBJECT_PATH: sanObjPath,
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      await backupManager.snapshot(escProjPath);
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Object '${sanObjPath}' deleted from ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'rename_object',
    'Renames a project object (POU, DUT, GVL, folder, etc.) in the CODESYS project.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      objectPath: z.string().describe("Full relative path to the object to rename (e.g., 'Application/MyPOU')."),
      newName: z.string().describe("New name for the object (must be a valid IEC identifier)."),
    },
    async (args: { projectFilePath: string; objectPath: string; newName: string }) => {
      const escProjPath = resolvePath(args.projectFilePath, workspaceDir);
      const sanObjPath = sanitizePouPath(args.objectPath);
      const script = scriptManager.prepareScriptWithHelpers(
        'rename_object',
        {
          PROJECT_FILE_PATH: escProjPath,
          OBJECT_PATH: sanObjPath,
          NEW_NAME: args.newName.trim(),
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Object '${sanObjPath}' renamed to '${args.newName}' in ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'get_all_pou_code',
    'Reads the declaration and implementation code of every POU/DUT/GVL in the project. Returns all code in a single response for bulk review.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
    },
    async (args: { projectFilePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'get_all_pou_code', { PROJECT_FILE_PATH: escaped }, ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script, 120_000); // 120s for large projects

      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) {
        return formatToolResponse(result, '');
      }

      // Parse the JSON output
      const codeStartMarker = '### ALL_POU_CODE_START ###';
      const codeEndMarker = '### ALL_POU_CODE_END ###';
      const startIdx = result.output.indexOf(codeStartMarker);
      const endIdx = result.output.indexOf(codeEndMarker);

      if (startIdx === -1 || endIdx === -1 || startIdx >= endIdx) {
        return {
          content: [{ type: 'text' as const, text: 'Could not parse POU code output.' }],
          isError: true,
        };
      }

      try {
        const jsonStr = result.output.substring(startIdx + codeStartMarker.length, endIdx).trim();
        const allCode: Array<{ path: string; type: string; declaration?: string; implementation?: string }> = JSON.parse(jsonStr);

        if (allCode.length === 0) {
          return {
            content: [{ type: 'text' as const, text: 'No POUs with code found in the project.' }],
            isError: false,
          };
        }

        // Format output
        const sections = allCode.map((item) => {
          let section = `\n=== ${item.path} (${item.type}) ===`;
          if (item.declaration) {
            section += `\n// ----- Declaration -----\n${item.declaration}`;
          }
          if (item.implementation) {
            section += `\n// ----- Implementation -----\n${item.implementation}`;
          }
          return section;
        });

        return {
          content: [{ type: 'text' as const, text: `${allCode.length} object(s) with code:\n${sections.join('\n')}` }],
          isError: false,
        };
      } catch {
        return {
          content: [{ type: 'text' as const, text: 'Failed to parse POU code JSON.' }],
          isError: true,
        };
      }
    }
  );

  s.tool(
    'search_code',
    'Regex (or literal substring) search across every POU/Method/Property/DUT/GVL textual body. Returns file:line:col hits. Graphical bodies with no textual_implementation are skipped.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      pattern: z.string().min(1).describe("Pattern to search for. Treated as a regex unless regex=false."),
      regex: z.boolean().optional().describe("If true (default), pattern is a regex. If false, pattern is a literal substring."),
      caseSensitive: z.boolean().optional().describe("If true (default), matching is case-sensitive."),
      includeDeclaration: z.boolean().optional().describe("If true (default), search declaration sections."),
      includeImplementation: z.boolean().optional().describe("If true (default), search implementation sections."),
      maxHits: z.number().int().positive().optional().describe("Cap the number of returned hits (default 1000)."),
    },
    async (args: {
      projectFilePath: string;
      pattern: string;
      regex?: boolean;
      caseSensitive?: boolean;
      includeDeclaration?: boolean;
      includeImplementation?: boolean;
      maxHits?: number;
    }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'search_code',
        {
          PROJECT_FILE_PATH: escaped,
          PATTERN: args.pattern,
          USE_REGEX: (args.regex ?? true) ? '1' : '0',
          CASE_SENSITIVE: (args.caseSensitive ?? true) ? '1' : '0',
          INCLUDE_DECL: (args.includeDeclaration ?? true) ? '1' : '0',
          INCLUDE_IMPL: (args.includeImplementation ?? true) ? '1' : '0',
          MAX_HITS: String(args.maxHits ?? 1000),
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script, 120_000);
      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) return formatToolResponse(result, '');
      const parsed = parseResultJson<{
        hits: Array<{ path: string; section: string; line: number; col: number; text: string; match: string }>;
        count: number;
        truncated: boolean;
        pattern: string;
      }>(result.output);
      if (!parsed.ok) return formatToolResponse(result, '');
      const { hits, count, truncated } = parsed.data;
      if (count === 0) {
        return {
          content: [{ type: 'text' as const, text: `No matches for /${args.pattern}/ in project.` }],
          isError: false,
        };
      }
      const lines = hits.map(h =>
        `${h.path}:${h.line}:${h.col} (${h.section}) ${h.text.trim()}`
      );
      const header = `${count} match(es)${truncated ? ' (truncated to maxHits)' : ''}:`;
      return {
        content: [{ type: 'text' as const, text: `${header}\n${lines.join('\n')}` }],
        isError: false,
      };
    }
  );

  // ─── Online/Runtime Tools ─────────────────────────────────────────────

  s.tool(
    'connect_to_device',
    'Connects (logs in) to the PLC runtime for the active application. If ipAddress is provided, set_gateway_and_address is called on the device first; otherwise the device must already have a configured gateway/address (or be in simulation mode via set_simulation_mode).',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      ipAddress: z.string().optional().describe("Optional PLC IP address. Sets the device gateway/address before login. Leave unset to use whatever is configured on the device, or to use simulation mode."),
      gatewayName: z.string().optional().describe("Optional gateway name (defaults to 'Gateway-1', the CODESYS install default). Only used if ipAddress is also provided."),
    },
    async (args: { projectFilePath: string; ipAddress?: string; gatewayName?: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'connect_to_device',
        {
          PROJECT_FILE_PATH: escaped,
          IP_ADDRESS: (args.ipAddress || '').trim(),
          GATEWAY_NAME: (args.gatewayName || '').trim(),
        },
        ['ensure_project_open', 'ensure_online_connection']
      );
      const result = await executor.executeScript(script, 60_000);
      return formatToolResponse(result, `Connected to device for ${args.projectFilePath}.`);
    }
  );

  s.tool(
    'set_credentials',
    'Set default username/password used for subsequent PLC logins. Use this once per session before connect_to_device when the runtime requires authentication. Both fields must be non-empty: CODESYS rejects empty username strings. If your runtime has no auth, do not call this tool.',
    {
      username: z.string().min(1).describe("Username (must be non-empty; CODESYS rejects empty strings)."),
      password: z.string().describe("Password."),
    },
    async (args: { username: string; password: string }) => {
      const script = scriptManager.prepareScript(
        'set_credentials',
        { USERNAME: args.username, PASSWORD: args.password }
      );
      const result = await executor.executeScript(script, 10_000);
      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) return formatToolResponse(result, '');
      return {
        content: [{ type: 'text' as const, text: `Default credentials set (user='${args.username}').` }],
        isError: false,
      };
    }
  );

  s.tool(
    'set_simulation_mode',
    'Toggle PLC simulation mode on/off for the project Device. Run before connect_to_device when no physical PLC is available; CODESYS will then simulate execution without a runtime gateway.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      enable: z.boolean().describe("True to enable simulation mode, false to disable."),
      verbose: z.boolean().optional().describe("If true, return the full script output (device list, verification, etc.). Default false returns a terse summary."),
    },
    async (args: { projectFilePath: string; enable: boolean; verbose?: boolean }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'set_simulation_mode',
        { PROJECT_FILE_PATH: escaped, ENABLE: args.enable ? 'true' : 'false' },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script, 30_000);
      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) return formatToolResponse(result, '');
      if (args.verbose === true) {
        return { content: [{ type: 'text' as const, text: result.output }], isError: false };
      }
      const afterMatch = result.output.match(/Simulation After:\s*(.+)/);
      const after = afterMatch ? afterMatch[1].trim() : 'unknown';
      return {
        content: [{ type: 'text' as const, text: `Simulation mode ${args.enable ? 'enabled' : 'disabled'} on device. Current state: ${after}` }],
        isError: false,
      };
    }
  );

  s.tool(
    'disconnect_from_device',
    'Disconnects (logs out) from the PLC runtime. No-op (success) if not connected.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
    },
    async (args: { projectFilePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'disconnect_from_device', { PROJECT_FILE_PATH: escaped },
        ['ensure_project_open']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(result, `Disconnected from device for ${args.projectFilePath}.`);
    }
  );

  s.tool(
    'get_application_state',
    'Gets the current state of the PLC application (running, stopped, exception, etc.).',
    {
      projectFilePath: z.string().describe("Path to the project file."),
    },
    async (args: { projectFilePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'get_application_state', { PROJECT_FILE_PATH: escaped },
        ['ensure_project_open', 'ensure_online_connection']
      );
      const result = await executor.executeScript(script);

      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) {
        return formatToolResponse(result, '');
      }

      // Parse state from output
      const stateMatch = result.output.match(/State:\s*(.+)/);
      const loggedInMatch = result.output.match(/Logged In:\s*(.+)/);
      const appMatch = result.output.match(/Application:\s*(.+)/);

      const text = [
        `Application: ${appMatch ? appMatch[1].trim() : 'Unknown'}`,
        `State: ${stateMatch ? stateMatch[1].trim() : 'Unknown'}`,
        `Logged In: ${loggedInMatch ? loggedInMatch[1].trim() : 'Unknown'}`,
      ].join('\n');

      return {
        content: [{ type: 'text' as const, text }],
        isError: false,
      };
    }
  );

  s.tool(
    'read_variable',
    'Reads the current value of a variable from the running PLC application. Must be connected first.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      variablePath: z.string().describe("Variable path (e.g., 'PLC_PRG.bMotorRunning', 'GVL.nCounter')."),
    },
    async (args: { projectFilePath: string; variablePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'read_variable',
        {
          PROJECT_FILE_PATH: escaped,
          VARIABLE_PATH: args.variablePath.trim(),
        },
        ['_text_utils', 'ensure_project_open', 'ensure_online_connection']
      );
      const result = await executor.executeScript(script);

      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) {
        return formatToolResponse(result, '');
      }

      // Parse the structured RESULT_JSON block; multi-line struct values
      // survive intact via this channel (the previous regex Value: capture
      // truncated at the first newline).
      const parsed = parseResultJson<{ variable: string; value: string | null; type: string | null; raw: string | null; application: string }>(result.output);
      if (!parsed.ok) {
        return formatToolResponse(result, '');
      }
      const text = `${parsed.data.variable} = ${parsed.data.value ?? 'N/A'} (${parsed.data.type ?? 'unknown'})`;
      return {
        content: [{ type: 'text' as const, text }],
        isError: false,
      };
    }
  );

  s.tool(
    'write_variable',
    'Writes a value to a variable in the running PLC application. Must be connected first.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      variablePath: z.string().describe("Variable path (e.g., 'PLC_PRG.bMotorRunning')."),
      value: z.string().describe("Value to write (e.g., 'TRUE', '42', '3.14')."),
    },
    async (args: { projectFilePath: string; variablePath: string; value: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'write_variable',
        {
          PROJECT_FILE_PATH: escaped,
          VARIABLE_PATH: args.variablePath.trim(),
          VARIABLE_VALUE: args.value,
        },
        ['ensure_project_open', 'ensure_online_connection']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Variable '${args.variablePath}' set to '${args.value}'.`
      );
    }
  );

  s.tool(
    'download_to_device',
    "Downloads the compiled application to the PLC device. mode controls strategy: 'auto' (default) tries online change then falls back to full; 'online_change' fails if online change is rejected; 'full' always does a full download.",
    {
      projectFilePath: z.string().describe("Path to the project file."),
      mode: z.enum(['auto', 'online_change', 'full']).optional().describe("Download strategy. Default 'auto'."),
    },
    async (args: { projectFilePath: string; mode?: 'auto' | 'online_change' | 'full' }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const mode = args.mode || 'auto';
      const script = scriptManager.prepareScriptWithHelpers(
        'download_to_device',
        { PROJECT_FILE_PATH: escaped, MODE: mode },
        ['ensure_project_open', 'ensure_online_connection']
      );
      const result = await executor.executeScript(script, 120_000);
      return formatToolResponse(result, `Application downloaded to device for ${args.projectFilePath} (mode=${mode}).`);
    }
  );

  s.tool(
    'start_stop_application',
    'Starts or stops the PLC application on the connected device.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      action: z.enum(['start', 'stop']).describe("Action to perform."),
    },
    async (args: { projectFilePath: string; action: 'start' | 'stop' }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'start_stop_application',
        {
          PROJECT_FILE_PATH: escaped,
          APP_ACTION: args.action,
        },
        ['ensure_project_open', 'ensure_online_connection']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Application ${args.action} executed for ${args.projectFilePath}.`
      );
    }
  );

  // ─── Library Management Tools ─────────────────────────────────────────

  s.tool(
    'list_project_libraries',
    'Lists all libraries currently referenced in the CODESYS project.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
    },
    async (args: { projectFilePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'list_project_libraries', { PROJECT_FILE_PATH: escaped }, ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);

      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) {
        return formatToolResponse(result, '');
      }

      // Parse libraries JSON
      const libStartMarker = '### LIBRARIES_START ###';
      const libEndMarker = '### LIBRARIES_END ###';
      const startIdx = result.output.indexOf(libStartMarker);
      const endIdx = result.output.indexOf(libEndMarker);

      if (startIdx === -1 || endIdx === -1 || startIdx >= endIdx) {
        return {
          content: [{ type: 'text' as const, text: 'Could not parse libraries output.' }],
          isError: true,
        };
      }

      try {
        const jsonStr = result.output.substring(startIdx + libStartMarker.length, endIdx).trim();
        const libraries: Array<{ name: string; version?: string; company?: string }> = JSON.parse(jsonStr);

        if (libraries.length === 0) {
          return {
            content: [{ type: 'text' as const, text: 'No libraries found in the project (or Library Manager not found).' }],
            isError: false,
          };
        }

        const lines = libraries.map((lib) => {
          let line = `- ${lib.name}`;
          if (lib.version) line += ` (v${lib.version})`;
          if (lib.company) line += ` [${lib.company}]`;
          return line;
        });

        return {
          content: [{ type: 'text' as const, text: `${libraries.length} library/libraries:\n${lines.join('\n')}` }],
          isError: false,
        };
      } catch {
        return {
          content: [{ type: 'text' as const, text: 'Failed to parse libraries JSON.' }],
          isError: true,
        };
      }
    }
  );

  s.tool(
    'list_device_repository',
    "Enumerate device descriptors from the local CODESYS Device Repository. Returns {name, vendor, device_type, device_id, version, description, category} per entry. Use to discover canonical ids for add_device.",
    {
      vendor: z.string().optional().describe("Optional case-insensitive vendor substring filter (e.g. '3S', 'ifm', 'Beckhoff')."),
      nameContains: z.string().optional().describe("Optional case-insensitive substring filter on the device name."),
      maxResults: z.number().int().positive().optional().describe("Cap on returned entries (default 500)."),
    },
    async (args: { vendor?: string; nameContains?: string; maxResults?: number }) => {
      // No project context needed - this hits the GLOBAL repository on the
      // CODESYS instance. The script doesn't include ensure_project_open or
      // require_project_open in its helper chain.
      const script = scriptManager.prepareScriptWithHelpers(
        'list_device_repository',
        {
          VENDOR_FILTER: args.vendor ?? '',
          NAME_FILTER: args.nameContains ?? '',
          MAX_RESULTS: String(args.maxResults ?? 500),
        },
        ['_text_utils']
      );
      const result = await executor.executeScript(script, 60_000);
      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) return formatToolResponse(result, '');
      const parsed = parseResultJson<{
        devices: Array<{ name: string | null; vendor: string | null; device_type: number | null; device_id: number | null; version: string | null; category: string | null; description: string | null }>;
        count: number;
        truncated: boolean;
        total_in_repo: number;
      }>(result.output);
      if (!parsed.ok) return formatToolResponse(result, '');
      return {
        content: [{ type: 'text' as const, text: JSON.stringify(parsed.data, null, 2) }],
        isError: false,
      };
    }
  );

  s.tool(
    'map_io_channel',
    "Bind (or clear) a fieldbus I/O channel to a global variable symbol. Use inspect_device_node first to discover the channel layout.",
    {
      projectFilePath: z.string().describe("Path to the project file."),
      devicePath: z.string().min(1).describe("Path to the device node (e.g. 'Device/Ethernet/EIP_Adapter')."),
      channelPath: z.string().min(1).describe("Channel address relative to the device. Either a name path ('Inputs/Byte 0/Bit 3') or numeric indices ('0/3')."),
      variableName: z.string().optional().describe("Global variable to bind (e.g. 'GVL.bSensor', 'PLC_PRG.xMotor'). Required unless clearBinding is true."),
      clearBinding: z.boolean().optional().describe("If true, remove the existing binding instead of setting one. variableName is ignored."),
    },
    async (args: {
      projectFilePath: string;
      devicePath: string;
      channelPath: string;
      variableName?: string;
      clearBinding?: boolean;
    }) => {
      const escProj = resolvePath(args.projectFilePath, workspaceDir);
      const sanDev = sanitizePouPath(args.devicePath);
      const script = scriptManager.prepareScriptWithHelpers(
        'map_io_channel',
        {
          PROJECT_FILE_PATH: escProj,
          DEVICE_PATH: sanDev,
          CHANNEL_PATH: args.channelPath,
          VARIABLE_NAME: args.variableName ?? '',
          CLEAR_BINDING: args.clearBinding ? '1' : '0',
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script, 30_000);
      return formatToolResponse(
        result,
        args.clearBinding
          ? `Cleared I/O channel binding at '${sanDev}/${args.channelPath}'. Project saved.`
          : `Bound '${sanDev}/${args.channelPath}' -> ${args.variableName}. Project saved.`
      );
    }
  );

  s.tool(
    'inspect_device_node',
    'Read-only introspection of a device node: descriptor metadata, parameter list with current values, child sub-devices. Pair with set_device_parameter to discover writable IDs.',
    {
      projectFilePath: z.string().describe("Path to the project file (must be the currently-open project)."),
      devicePath: z.string().min(1).describe("Path to the device node, e.g. 'Device' for the PLC root, 'Device/Ethernet/EIP_Adapter' for a fieldbus adapter."),
    },
    async (args: { projectFilePath: string; devicePath: string }) => {
      const escProj = resolvePath(args.projectFilePath, workspaceDir);
      const sanDev = sanitizePouPath(args.devicePath);
      const script = scriptManager.prepareScriptWithHelpers(
        'inspect_device_node',
        { PROJECT_FILE_PATH: escProj, DEVICE_PATH: sanDev },
        ['_text_utils', 'require_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script, 30_000);
      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) return formatToolResponse(result, '');
      const parsed = parseResultJson(result.output);
      if (!parsed.ok) return formatToolResponse(result, '');
      return {
        content: [{ type: 'text' as const, text: JSON.stringify(parsed.data, null, 2) }],
        isError: false,
      };
    }
  );

  s.tool(
    'add_device',
    'Add a device under an existing parent device. Use list_device_repository to source canonical deviceType/deviceId/version. Wrong ids produce a wrong-but-syntactically-valid node that fails at compile time.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      parentDevicePath: z.string().min(1).describe("Path to the parent device in the project tree, e.g. 'Device' for the root PLC, 'Device/Ethernet' for a fieldbus master."),
      deviceName: z.string().min(1).describe("Name for the new device node (must be a valid CODESYS object name)."),
      deviceType: z.number().int().describe("CODESYS device type id (numeric, from the device repository)."),
      deviceId: z.number().int().optional().describe("CODESYS device id (numeric). Some add_device signatures don't require this."),
      version: z.string().optional().describe("Version string for the device (e.g. '3.5.16.0')."),
    },
    async (args: {
      projectFilePath: string;
      parentDevicePath: string;
      deviceName: string;
      deviceType: number;
      deviceId?: number;
      version?: string;
    }) => {
      const escProj = resolvePath(args.projectFilePath, workspaceDir);
      const sanParent = sanitizePouPath(args.parentDevicePath);
      const script = scriptManager.prepareScriptWithHelpers(
        'add_device',
        {
          PROJECT_FILE_PATH: escProj,
          PARENT_DEVICE_PATH: sanParent,
          DEVICE_NAME: args.deviceName.trim(),
          DEVICE_TYPE: String(args.deviceType),
          DEVICE_ID: args.deviceId !== undefined ? String(args.deviceId) : '',
          DEVICE_VERSION: args.version ?? '',
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script, 60_000);
      return formatToolResponse(
        result,
        `Device '${args.deviceName}' added under '${sanParent}' in ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'set_device_parameter',
    'EXPERIMENTAL. Set a parameter value on a device. Use inspect_device_node first to find writable IDs. Many fieldbus parameters are GUI-only; this tool returns a clear error in that case.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      devicePath: z.string().min(1).describe("Path to the device in the project tree, e.g. 'Device/Ethernet/EIP_Adapter_X'."),
      parameterId: z.union([z.number().int(), z.string().min(1)]).describe("Parameter id (numeric for most CODESYS device descriptors; string accepted as a fallback)."),
      value: z.string().describe("Value to write. Use the type-appropriate textual representation (e.g. '192.168.1.10' for IP, 'TRUE' for BOOL, '42' for INT)."),
    },
    async (args: {
      projectFilePath: string;
      devicePath: string;
      parameterId: number | string;
      value: string;
    }) => {
      const escProj = resolvePath(args.projectFilePath, workspaceDir);
      const sanDev = sanitizePouPath(args.devicePath);
      const script = scriptManager.prepareScriptWithHelpers(
        'set_device_parameter',
        {
          PROJECT_FILE_PATH: escProj,
          DEVICE_PATH: sanDev,
          PARAMETER_ID: String(args.parameterId),
          VALUE: args.value,
        },
        ['_text_utils', 'ensure_project_open', 'find_object_by_path']
      );
      const result = await executor.executeScript(script, 30_000);
      return formatToolResponse(
        result,
        `Parameter ${args.parameterId} on '${sanDev}' set to '${args.value}'. Project saved.`
      );
    }
  );

  s.tool(
    'get_task_configuration',
    "Lists every Task Configuration node in the project with its child tasks and their current properties (cycle time, priority, watchdog, stack size where exposed). Library projects have no Task Configuration -- this tool is for application/consumer projects (typically PLC_AC500_V3 / Plc Logic / Application / Task Configuration).",
    {
      projectFilePath: z.string().describe("Path to the project file."),
    },
    async (args: { projectFilePath: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'get_task_configuration',
        { PROJECT_FILE_PATH: escaped },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      // Surface the structured task_configurations payload (same fix as
      // get_project_info -- formatToolResponse was stripping the JSON block).
      return formatStructuredResponse(
        result,
        `Task configuration read for ${args.projectFilePath}.`
      );
    }
  );

  s.tool(
    'set_task_parameter',
    "Updates one or more properties of a Task (cycle time, priority, watchdog time, stack size). Pass only the knobs you want to change; others are left untouched. Saves the project after applying. For AC500 V3 stack size: when set at task level fails, the script walks up to ancestor nodes; AC500 may store PLC stack config via Device parameter dict instead -- in that case use set_device_parameter once the parameter id is known (set_device_parameter does NOT auto-discover it; consult AB UI Device > PLC Settings).",
    {
      projectFilePath: z.string().describe("Path to the project file."),
      taskName: z.string().min(1).describe("Exact name of the task as shown under Task Configuration (e.g. 'MainTask'). Use get_task_configuration to discover."),
      cycleTimeMs: z.number().int().positive().describe("Cycle time / interval in milliseconds.").optional(),
      watchdogTimeMs: z.number().int().positive().describe("Watchdog timeout in milliseconds. Setting it also enables the watchdog if a toggle is exposed.").optional(),
      priority: z.number().int().min(0).max(31).describe("Task priority (0 = highest, 31 = lowest on AC500 V3).").optional(),
      stackSizeBytes: z.number().int().positive().describe("Stack size in bytes. Required when a library has large STRING(N) buffers that overflow the default ~128KB stack; common bump is 262144 (256KB).").optional(),
    },
    async (args: {
      projectFilePath: string;
      taskName: string;
      cycleTimeMs?: number;
      watchdogTimeMs?: number;
      priority?: number;
      stackSizeBytes?: number;
    }) => {
      const provided = [
        args.cycleTimeMs !== undefined ? 'cycleTimeMs' : '',
        args.watchdogTimeMs !== undefined ? 'watchdogTimeMs' : '',
        args.priority !== undefined ? 'priority' : '',
        args.stackSizeBytes !== undefined ? 'stackSizeBytes' : '',
      ].filter(Boolean);
      if (provided.length === 0) {
        return {
          content: [{ type: 'text' as const, text: 'Error: at least one of cycleTimeMs / watchdogTimeMs / priority / stackSizeBytes must be provided.' }],
          isError: true,
        };
      }
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'set_task_parameter',
        {
          PROJECT_FILE_PATH: escaped,
          TASK_NAME: args.taskName.trim(),
          CYCLE_TIME_MS: args.cycleTimeMs !== undefined ? String(args.cycleTimeMs) : '',
          WATCHDOG_TIME_MS: args.watchdogTimeMs !== undefined ? String(args.watchdogTimeMs) : '',
          PRIORITY: args.priority !== undefined ? String(args.priority) : '',
          STACK_SIZE_BYTES: args.stackSizeBytes !== undefined ? String(args.stackSizeBytes) : '',
        },
        ['_text_utils', 'ensure_project_open']
      );
      await backupManager.snapshot(escaped);
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Task '${args.taskName}' updated (${provided.join(', ')}) in ${args.projectFilePath}.`
      );
    }
  );

  s.tool(
    'find_references',
    'Find every word-boundary reference to a symbol (\\bsymbol\\b) across textual POU/Method/Property/DUT/GVL bodies. Wraps search_code. Comments and string literals are not excluded.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      symbol: z.string().min(1).describe("Identifier to find references to (e.g. 'GVL_Cameras', 'fbParser1')."),
      caseSensitive: z.boolean().optional().describe("If true (default), match case-sensitively per IEC 61131-3 conventions."),
      maxHits: z.number().int().positive().optional().describe("Cap on returned hits (default 1000)."),
    },
    async (args: {
      projectFilePath: string;
      symbol: string;
      caseSensitive?: boolean;
      maxHits?: number;
    }) => {
      // Word-boundary regex - escape any regex metacharacters that might
      // appear in the symbol (defensive: IEC identifiers can't contain them,
      // but a malformed input shouldn't blow up the search).
      const escaped = args.symbol.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const pattern = `\\b${escaped}\\b`;
      const escProj = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'search_code',
        {
          PROJECT_FILE_PATH: escProj,
          PATTERN: pattern,
          USE_REGEX: '1',
          CASE_SENSITIVE: (args.caseSensitive ?? true) ? '1' : '0',
          INCLUDE_DECL: '1',
          INCLUDE_IMPL: '1',
          MAX_HITS: String(args.maxHits ?? 1000),
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script, 120_000);
      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) return formatToolResponse(result, '');
      const parsed = parseResultJson<{
        hits: Array<{ path: string; section: string; line: number; col: number; text: string }>;
        count: number;
        truncated: boolean;
      }>(result.output);
      if (!parsed.ok) return formatToolResponse(result, '');
      const { hits, count, truncated } = parsed.data;
      if (count === 0) {
        return {
          content: [{ type: 'text' as const, text: `No references to '${args.symbol}' found.` }],
          isError: false,
        };
      }
      const lines = hits.map(h => `${h.path}:${h.line}:${h.col} (${h.section}) ${h.text.trim()}`);
      const header = `${count} reference(s) to '${args.symbol}'${truncated ? ' (truncated)' : ''}:`;
      return {
        content: [{ type: 'text' as const, text: `${header}\n${lines.join('\n')}` }],
        isError: false,
      };
    }
  );

  s.tool(
    'rename_symbol',
    'Best-effort word-boundary textual rename across textual POU/Method/Property/DUT/GVL bodies. Defaults to dryRun=true. Does not rename the project object node (use rename_object) or graphical bodies.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      oldName: z.string().min(1).describe("Existing symbol name."),
      newName: z.string().min(1).describe("Replacement name."),
      dryRun: z.boolean().optional().describe("If true (default), report matches without writing. Set false to apply."),
      includeDeclaration: z.boolean().optional().describe("If true (default), rewrite declaration sections."),
      includeImplementation: z.boolean().optional().describe("If true (default), rewrite implementation sections."),
    },
    async (args: {
      projectFilePath: string;
      oldName: string;
      newName: string;
      dryRun?: boolean;
      includeDeclaration?: boolean;
      includeImplementation?: boolean;
    }) => {
      const escProj = resolvePath(args.projectFilePath, workspaceDir);
      const dry = args.dryRun ?? true;
      const script = scriptManager.prepareScriptWithHelpers(
        'rename_symbol',
        {
          PROJECT_FILE_PATH: escProj,
          OLD_NAME: args.oldName,
          NEW_NAME: args.newName,
          DRY_RUN: dry ? '1' : '0',
          INCLUDE_DECL: (args.includeDeclaration ?? true) ? '1' : '0',
          INCLUDE_IMPL: (args.includeImplementation ?? true) ? '1' : '0',
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script, 120_000);
      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) return formatToolResponse(result, '');
      const parsed = parseResultJson<{
        old_name: string;
        new_name: string;
        dry_run: boolean;
        changes: Array<{ path: string; section: string; match_count: number; applied: boolean }>;
        total_matches: number;
        applied_count: number;
      }>(result.output);
      if (!parsed.ok) return formatToolResponse(result, '');
      const { dry_run, total_matches, applied_count, changes } = parsed.data;
      if (total_matches === 0) {
        return {
          content: [{ type: 'text' as const, text: `No matches for '${args.oldName}'; nothing renamed.` }],
          isError: false,
        };
      }
      const summary = changes.map(c =>
        `${c.path} [${c.section}]: ${c.match_count} match(es)${dry_run ? '' : c.applied ? ' (applied)' : ' (NOT applied)'}`
      );
      const header = dry_run
        ? `DRY RUN: ${total_matches} match(es) of '${args.oldName}' -> '${args.newName}' across ${changes.length} section(s). Re-run with dryRun=false to apply.`
        : `Applied ${total_matches} replacement(s) of '${args.oldName}' -> '${args.newName}' across ${applied_count} section(s). Project saved.`;
      return {
        content: [{ type: 'text' as const, text: `${header}\n${summary.join('\n')}` }],
        isError: false,
      };
    }
  );

  s.tool(
    'monitor_variables',
    "Sample one or more PLC variables at a fixed interval over a bounded duration; returns the timeseries. Blocks the CODESYS UI thread (capped at 60s).",
    {
      projectFilePath: z.string().describe("Path to the project file."),
      variablePaths: z.array(z.string().min(1)).min(1).describe("List of variable paths to sample (e.g. ['PLC_PRG.x', 'GVL.nCounter'])."),
      durationMs: z.number().int().positive().describe("Total sampling duration in ms. Capped at 60000."),
      intervalMs: z.number().int().positive().describe("Sample interval in ms. Floor 10ms."),
    },
    async (args: {
      projectFilePath: string;
      variablePaths: string[];
      durationMs: number;
      intervalMs: number;
    }) => {
      // Clamp here so TS-side timeouts and the script-side cap stay consistent
      // (the script also clamps to 60000 defensively, but a caller asking for
      // 120000 deserves a fast fail-and-warn rather than silent truncation).
      const clampedDuration = Math.min(args.durationMs, 60_000);
      const clampedInterval = Math.max(args.intervalMs, 10);
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'monitor_variables',
        {
          PROJECT_FILE_PATH: escaped,
          VARIABLES_JSON: JSON.stringify(args.variablePaths),
          DURATION_MS: String(clampedDuration),
          INTERVAL_MS: String(clampedInterval),
        },
        ['_text_utils', 'ensure_project_open', 'ensure_online_connection']
      );
      // Per-call timeout = clamped duration + 30s headroom for connect/return.
      const callTimeoutMs = clampedDuration + 30_000;
      const result = await executor.executeScript(script, callTimeoutMs);
      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) return formatToolResponse(result, '');
      const parsed = parseResultJson<{
        variables: string[];
        sample_count: number;
        duration_ms_requested: number;
        duration_ms_actual: number;
        interval_ms: number;
        application: string;
        samples: Array<{ t_ms: number; values: Record<string, string | null> }>;
      }>(result.output);
      if (!parsed.ok) return formatToolResponse(result, '');
      // Caller wants the full timeseries - return it as JSON in the message
      // body (not summarised) so plotting tools downstream can parse it.
      return {
        content: [{
          type: 'text' as const,
          text: JSON.stringify(parsed.data, null, 2),
        }],
        isError: false,
      };
    }
  );

  s.tool(
    'create_project_archive',
    'Saves the currently-open project as a .projectarchive. Read-only with respect to the project itself - the project must already be open (this tool will not switch projects). Output path may be absolute or relative to the workspace.',
    {
      projectFilePath: z.string().describe("Path to the project file (must be the currently-open project)."),
      outputPath: z.string().min(1).describe("Output .projectarchive path (absolute or workspace-relative)."),
      comment: z.string().optional().describe("Optional comment embedded in the archive metadata."),
      includeLibraries: z.boolean().optional().describe("If true (default), include referenced library sources in the archive."),
      includeCompiledLibraries: z.boolean().optional().describe("If true (default), include compiled library binaries. Set false to keep archives small for plain-text version control."),
    },
    async (args: {
      projectFilePath: string;
      outputPath: string;
      comment?: string;
      includeLibraries?: boolean;
      includeCompiledLibraries?: boolean;
    }) => {
      const escProj = resolvePath(args.projectFilePath, workspaceDir);
      const escOut = resolvePath(args.outputPath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'create_project_archive',
        {
          PROJECT_FILE_PATH: escProj,
          ARCHIVE_PATH: escOut,
          COMMENT: args.comment ?? '',
          INCLUDE_LIBRARIES: (args.includeLibraries ?? true) ? '1' : '0',
          INCLUDE_COMPILED: (args.includeCompiledLibraries ?? true) ? '1' : '0',
        },
        ['_text_utils', 'require_project_open']
      );
      const result = await executor.executeScript(script, 120_000);
      const success = result.success && result.output.includes('SCRIPT_SUCCESS');
      if (!success) return formatToolResponse(result, '');
      const parsed = parseResultJson<{ archive_path: string; size_bytes: number; comment: string | null }>(result.output);
      const sizeKb = parsed.ok ? Math.round(parsed.data.size_bytes / 1024) : 0;
      return {
        content: [{
          type: 'text' as const,
          text: parsed.ok
            ? `Archive saved to ${parsed.data.archive_path} (${sizeKb} KB).${parsed.data.comment ? ` Comment: "${parsed.data.comment}".` : ''}`
            : `Archive saved (output details unavailable).`,
        }],
        isError: false,
      };
    }
  );

  s.tool(
    'add_library',
    'Adds a library reference to the CODESYS project. The library must be installed in the CODESYS library repository.',
    {
      projectFilePath: z.string().describe("Path to the project file."),
      libraryName: z.string().describe("Name of the library to add (e.g., 'Standard', 'Util', 'CAA Memory')."),
    },
    async (args: { projectFilePath: string; libraryName: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'add_library',
        {
          PROJECT_FILE_PATH: escaped,
          LIBRARY_NAME: args.libraryName.trim(),
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Library '${args.libraryName}' added to ${args.projectFilePath}. Project saved.`
      );
    }
  );

  s.tool(
    'install_library_to_repository',
    "Installs the currently open .library project into the CODESYS Library Repository, equivalent to the UI menu 'File > Save Project and Install into Library Repository'. Required after editing a library project so consumer projects (referencing it via Library Manager) pick up the new version. If a library with the same name+version already exists in the repository, it is overwritten; different versions are installed alongside.",
    {
      libraryProjectFilePath: z.string().describe("Path to the .library project file to install."),
      repositoryName: z.string().describe("Optional name of the target repository (e.g. 'User', 'Default'). If omitted, the script picks the User repository if available, otherwise the first repository.").optional(),
    },
    async (args: { libraryProjectFilePath: string; repositoryName?: string }) => {
      const escaped = resolvePath(args.libraryProjectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'install_library_to_repository',
        {
          PROJECT_FILE_PATH: escaped,
          REPOSITORY_NAME: (args.repositoryName ?? '').trim(),
        },
        ['_text_utils', 'ensure_project_open']
      );
      // Snapshot the .library before pushing it into the repo (the install
      // re-saves the project as part of the flow).
      await backupManager.snapshot(escaped);
      const result = await executor.executeScript(script);
      return formatToolResponse(
        result,
        `Library installed to repository: ${args.libraryProjectFilePath}` +
        (args.repositoryName ? ` (target: ${args.repositoryName})` : '')
      );
    }
  );

  s.tool(
    'list_library_repository',
    "Enumerate libraries installed in the CODESYS Library Repository (the System / User / Default repos). Returns one JSON entry per repository containing its libraries with name, version, company, location. Use to verify which versions are installed before/after install_library_to_repository or uninstall_library_from_repository -- saves the round-trip to 'Tools > Library Repository' in the AB UI.",
    {
      nameFilter: z.string().describe("Optional case-insensitive substring filter on library name (e.g. 'Nexo' returns only libs whose name contains 'Nexo').").optional(),
    },
    async (args: { nameFilter?: string }) => {
      const script = scriptManager.prepareScriptWithHelpers(
        'list_library_repository',
        { NAME_FILTER: (args.nameFilter ?? '').trim() },
        ['_text_utils']
      );
      const result = await executor.executeScript(script);
      return formatStructuredResponse(result, 'Library repository enumerated.');
    }
  );

  s.tool(
    'get_library_parameters',
    "Returns the Library Parameters (consumer-overridable VAR_GLOBAL CONSTANT values from Parameter List POUs) exposed by each library reference in the project's Library Manager. For each parameter: name, current effective value, library default value, isOverridden flag, type, comment. Use to diagnose 'consumer override vs lib default' confusion: if isOverridden=true but the override is stale relative to the new library default, call reset_library_parameter. Returns a diagnostic dump if the CODESYS scripting API on this build does not expose parameter access (worth forwarding to maintainers).",
    {
      projectFilePath: z.string().describe("Path to the consumer .project file."),
      libraryName: z.string().describe("Optional library name filter (e.g. 'NexoMqttLib'). Case-insensitive substring match.").optional(),
    },
    async (args: { projectFilePath: string; libraryName?: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'get_library_parameters',
        {
          PROJECT_FILE_PATH: escaped,
          LIBRARY_NAME: (args.libraryName ?? '').trim(),
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      return formatStructuredResponse(result, 'Library parameters enumerated.');
    }
  );

  s.tool(
    'set_library_parameter',
    "Set a consumer-side override for a Library Parameter (overrides the library's default VAR_GLOBAL CONSTANT value). Persists in the consumer .project file. Use to pin a value the library default doesn't match (e.g. raise GC_MAX_TAG_DEFINITIONS). For the canonical value declared by the library itself, edit the Parameter List POU in the library source instead.",
    {
      projectFilePath: z.string().describe("Path to the consumer .project file."),
      libraryName: z.string().min(1).describe("Library name (must match a Library Manager reference)."),
      parameterName: z.string().min(1).describe("Parameter name (e.g. 'GC_MAX_TAG_DEFINITIONS')."),
      value: z.string().describe("New value as a string (e.g. '1024', 'TRUE', \"'foo'\"). Use the IEC literal form the parameter expects."),
    },
    async (args: { projectFilePath: string; libraryName: string; parameterName: string; value: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'set_library_parameter',
        {
          PROJECT_FILE_PATH: escaped,
          LIBRARY_NAME: args.libraryName.trim(),
          PARAMETER_NAME: args.parameterName.trim(),
          PARAMETER_VALUE: args.value,
        },
        ['_text_utils', 'ensure_project_open']
      );
      await backupManager.snapshot(escaped);
      const result = await executor.executeScript(script);
      return formatStructuredResponse(
        result,
        `Library parameter override set: ${args.libraryName}.${args.parameterName} = ${args.value}.`
      );
    }
  );

  s.tool(
    'reset_library_parameter',
    "Remove the consumer-side override for a Library Parameter, falling back to the library's default value. Use when a stale override from an old library version is silently masking a default change (the canonical cause of 'why is my consumer still seeing the old value' debugging spirals).",
    {
      projectFilePath: z.string().describe("Path to the consumer .project file."),
      libraryName: z.string().min(1).describe("Library name."),
      parameterName: z.string().min(1).describe("Parameter name to reset."),
    },
    async (args: { projectFilePath: string; libraryName: string; parameterName: string }) => {
      const escaped = resolvePath(args.projectFilePath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'reset_library_parameter',
        {
          PROJECT_FILE_PATH: escaped,
          LIBRARY_NAME: args.libraryName.trim(),
          PARAMETER_NAME: args.parameterName.trim(),
        },
        ['_text_utils', 'ensure_project_open']
      );
      await backupManager.snapshot(escaped);
      const result = await executor.executeScript(script);
      return formatStructuredResponse(
        result,
        `Library parameter override reset: ${args.libraryName}.${args.parameterName}.`
      );
    }
  );

  s.tool(
    'export_library_parameters',
    "Export the consumer-side Library Parameter values to a JSON file. Useful for replicating a consumer's parameter config across projects or stashing a baseline before mass-editing. By default exports ALL parameters with their current value + isOverridden flag; pair with import_library_parameters to restore.",
    {
      projectFilePath: z.string().describe("Path to the source consumer .project file."),
      outputPath: z.string().min(1).describe("Path where the JSON export will be written. Overwritten if exists."),
      libraryName: z.string().describe("Optional library name filter (case-insensitive substring).").optional(),
    },
    async (args: { projectFilePath: string; outputPath: string; libraryName?: string }) => {
      const escapedProj = resolvePath(args.projectFilePath, workspaceDir);
      const escapedOut = resolvePath(args.outputPath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'export_library_parameters',
        {
          PROJECT_FILE_PATH: escapedProj,
          OUTPUT_PATH: escapedOut,
          LIBRARY_NAME: (args.libraryName ?? '').trim(),
        },
        ['_text_utils', 'ensure_project_open']
      );
      const result = await executor.executeScript(script);
      return formatStructuredResponse(result, `Library parameters exported to ${args.outputPath}.`);
    }
  );

  s.tool(
    'import_library_parameters',
    "Import Library Parameter values from a JSON file (produced by export_library_parameters) into a consumer project. By default applies only entries that were marked isOverridden=true in the export (skipping defaults that the library already provides); set skipDefaults=false to import every entry blindly. Returns per-parameter applied/skipped/failed lists for review.",
    {
      projectFilePath: z.string().describe("Path to the target consumer .project file."),
      inputPath: z.string().min(1).describe("Path to the JSON export to import."),
      skipDefaults: z.boolean().describe("If true (default), skip entries whose isOverridden was false in the export.").optional(),
    },
    async (args: { projectFilePath: string; inputPath: string; skipDefaults?: boolean }) => {
      const escapedProj = resolvePath(args.projectFilePath, workspaceDir);
      const escapedIn = resolvePath(args.inputPath, workspaceDir);
      const script = scriptManager.prepareScriptWithHelpers(
        'import_library_parameters',
        {
          PROJECT_FILE_PATH: escapedProj,
          INPUT_PATH: escapedIn,
          SKIP_DEFAULTS: args.skipDefaults === false ? 'false' : 'true',
        },
        ['_text_utils', 'ensure_project_open']
      );
      await backupManager.snapshot(escapedProj);
      const result = await executor.executeScript(script);
      return formatStructuredResponse(result, `Library parameters imported from ${args.inputPath}.`);
    }
  );

  s.tool(
    'uninstall_library_from_repository',
    "Remove a library version from the CODESYS Library Repository. Pass '*' as version to remove ALL versions of the named library. Use after release iteration to clean up superseded versions (e.g. uninstall v1.0.5 once v1.0.10 is installed and validated). Returns ERR_LIB_NOT_FOUND if no matching entry; safe to call on already-uninstalled libraries.",
    {
      libraryName: z.string().min(1).describe("Library name (e.g. 'NexoMqttLib'). Case-insensitive."),
      version: z.string().min(1).describe("Version string to uninstall (e.g. '1.0.10') or '*' for all versions."),
      repositoryName: z.string().describe("Optional repository name (e.g. 'System', 'User'). If omitted, matches across all repositories.").optional(),
    },
    async (args: { libraryName: string; version: string; repositoryName?: string }) => {
      const script = scriptManager.prepareScriptWithHelpers(
        'uninstall_library_from_repository',
        {
          LIBRARY_NAME: args.libraryName.trim(),
          LIBRARY_VERSION: args.version.trim(),
          REPOSITORY_NAME: (args.repositoryName ?? '').trim(),
        },
        ['_text_utils']
      );
      const result = await executor.executeScript(script);
      return formatStructuredResponse(
        result,
        `Library uninstall request processed for ${args.libraryName} ${args.version}.`
      );
    }
  );

  // ─── Resources ───────────────────────────────────────────────────────

  server.resource(
    'project-status',
    'codesys://project/status',
    async (uri) => {
      try {
        const script = scriptManager.loadTemplate('check_status');
        const result = await executor.executeScript(script);

        const outputLines = result.output.split(/[\r\n]+/).filter((l) => l.trim());
        const statusData: Record<string, string> = {};
        outputLines.forEach((line) => {
          const match = line.match(/^([^:]+):\s*(.*)$/);
          if (match) statusData[match[1].trim()] = match[2].trim();
        });

        const statusText = [
          'CODESYS Status:',
          ` - Scripting OK: ${statusData['Scripting OK'] ?? 'Unknown'}`,
          ` - Project Open: ${statusData['Project Open'] ?? 'Unknown'}`,
          ` - Project Name: ${statusData['Project Name'] ?? 'Unknown'}`,
          ` - Project Path: ${statusData['Project Path'] ?? 'N/A'}`,
        ].join('\n');

        const isError =
          !result.success ||
          statusData['Scripting OK']?.toLowerCase() !== 'true';

        return {
          contents: [{ uri: uri.href, text: statusText, contentType: 'text/plain' }],
          isError,
        };
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        return {
          contents: [{ uri: uri.href, text: `Failed status check: ${msg}`, contentType: 'text/plain' }],
          isError: true,
        };
      }
    }
  );

  const projectStructureTemplate = new ResourceTemplate(
    'codesys://project/{+project_path}/structure',
    { list: undefined }
  );

  server.resource(
    'project-structure',
    projectStructureTemplate,
    async (uri, params) => {
      const projectPath = params.project_path as string;
      if (!projectPath) {
        return {
          contents: [{ uri: uri.href, text: 'Error: Project path missing.', contentType: 'text/plain' }],
          isError: true,
        };
      }
      try {
        const escaped = resolvePath(projectPath, workspaceDir);
        // Resource handler - require_project_open refuses to switch projects.
        const script = scriptManager.prepareScriptWithHelpers(
          'get_project_structure', { PROJECT_FILE_PATH: escaped }, ['_text_utils', 'require_project_open']
        );
        const result = await executor.executeScript(script);

        let structureText = `Error retrieving structure.\n\n${result.output}`;
        let isError = !result.success;

        if (result.success && result.output.includes('SCRIPT_SUCCESS')) {
          const startMarker = '--- PROJECT STRUCTURE START ---';
          const endMarker = '--- PROJECT STRUCTURE END ---';
          const startIdx = result.output.indexOf(startMarker);
          const endIdx = result.output.indexOf(endMarker);
          if (startIdx !== -1 && endIdx !== -1 && startIdx < endIdx) {
            structureText = result.output
              .substring(startIdx + startMarker.length, endIdx)
              .replace(/\\n/g, '\n')
              .trim();
          } else {
            structureText = `Could not parse structure markers.\n\nOutput:\n${result.output}`;
            isError = true;
          }
        }

        return {
          contents: [{ uri: uri.href, text: structureText, contentType: 'text/plain' }],
          isError,
        };
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        return {
          contents: [{ uri: uri.href, text: `Failed: ${msg}`, contentType: 'text/plain' }],
          isError: true,
        };
      }
    }
  );

  const pouCodeTemplate = new ResourceTemplate(
    'codesys://project/{+project_path}/pou/{+pou_path}/code',
    { list: undefined }
  );

  server.resource(
    'pou-code',
    pouCodeTemplate,
    async (uri, params) => {
      const projectPath = params.project_path as string;
      const pouPath = params.pou_path as string;
      if (!projectPath || !pouPath) {
        return {
          contents: [{ uri: uri.href, text: 'Error: Project or POU path missing.', contentType: 'text/plain' }],
          isError: true,
        };
      }
      try {
        const escProjPath = resolvePath(projectPath, workspaceDir);
        const sanPouPath = sanitizePouPath(pouPath);
        // Resource handler - require_project_open refuses to switch projects.
        const script = scriptManager.prepareScriptWithHelpers(
          'get_pou_code',
          { PROJECT_FILE_PATH: escProjPath, POU_FULL_PATH: sanPouPath },
          ['_text_utils', 'require_project_open', 'find_object_by_path']
        );
        const result = await executor.executeScript(script);

        let codeText = `Error retrieving code.\n\n${result.output}`;
        let isError = !result.success;

        if (result.success && result.output.includes('SCRIPT_SUCCESS')) {
          const declStart = '### POU DECLARATION START ###';
          const declEnd = '### POU DECLARATION END ###';
          const implStart = '### POU IMPLEMENTATION START ###';
          const implEnd = '### POU IMPLEMENTATION END ###';

          let declaration = '/* Declaration not found */';
          let implementation = '/* Implementation not found */';

          const ds = result.output.indexOf(declStart);
          const de = result.output.indexOf(declEnd);
          if (ds !== -1 && de !== -1 && ds < de) {
            declaration = result.output.substring(ds + declStart.length, de).replace(/\\n/g, '\n').trim();
          }

          const is_ = result.output.indexOf(implStart);
          const ie = result.output.indexOf(implEnd);
          if (is_ !== -1 && ie !== -1 && is_ < ie) {
            implementation = result.output.substring(is_ + implStart.length, ie).replace(/\\n/g, '\n').trim();
          }

          codeText = `// ----- Declaration -----\n${declaration}\n\n// ----- Implementation -----\n${implementation}`;
        }

        return {
          contents: [{ uri: uri.href, text: codeText, contentType: 'text/plain' }],
          isError,
        };
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        return {
          contents: [{ uri: uri.href, text: `Failed: ${msg}`, contentType: 'text/plain' }],
          isError: true,
        };
      }
    }
  );

  // ─── Connect ─────────────────────────────────────────────────────────
  // Connect transport BEFORE auto-launching CODESYS so the MCP `initialize`
  // handshake answers immediately (Claude Code's probe times out fast).

  const transport = new StdioServerTransport();
  serverLog.info('Connecting MCP server via stdio...');
  await server.connect(transport);
  serverLog.info('MCP Server connected and listening.');

  // ─── Background auto-launch (do not await) ───────────────────────────

  if (launcher && config.autoLaunch) {
    const persistentLauncher = launcher;
    const persistentResilient = resilientLauncher!;
    serverLog.info('Auto-launching CODESYS in the background...');
    // Hand the proxy a readiness promise so tool calls during the launch
    // window block on it before delegating - no race between swap and
    // mid-flight executeScript calls.
    // Try to ADOPT a still-running AB from a previous keep-alive server before
    // cold-launching. If --keep-alive left an AB alive across this server
    // recycle, adoptExisting() re-binds to its live watcher (no ~2min cold
    // start, no second AB). Only fall through to launch() when no live,
    // PID-alive, fresh-heartbeat session is found.
    const launchOrAdopt = (async () => {
      try {
        if (await persistentLauncher.adoptExisting()) {
          serverLog.info('Adopted an existing live AB watcher; skipped cold launch.');
          return;
        }
      } catch (adoptErr) {
        const m = adoptErr instanceof Error ? adoptErr.message : String(adoptErr);
        serverLog.warn(`adoptExisting() raised (ignored, will cold-launch): ${m}`);
      }
      return persistentLauncher.launch();
    })();
    const launchReady = launchOrAdopt.then(
      () => {
        executionMode = 'persistent';
        serverLog.info('CODESYS persistent instance ready; executor switched.');
      },
      (err) => {
        const errMsg = err instanceof Error ? err.message : String(err);
        serverLog.error(`Persistent launch failed: ${errMsg}`);
        if (config.fallbackHeadless) {
          serverLog.warn('Continuing in headless mode (fallback).');
        } else {
          serverLog.error(
            'No fallback configured; tool calls will keep using headless executor.'
          );
        }
        // Re-throw so the proxy keeps the headless executor.
        throw err;
      }
    );
    // Pass the resilient wrapper, not the raw launcher, so command timeouts
    // trigger auto-recovery via forceReset() transparently.
    executor.swap(persistentResilient, launchReady);
  }

  // ─── Graceful Shutdown ───────────────────────────────────────────────

  const shutdown = async () => {
    serverLog.info('Shutdown signal received');
    if (launcher) {
      try {
        if (config.keepAlive) {
          // Decouple AB's lifetime from the MCP server process. The client
          // (Claude Code) recycles this server on routine events -- reconnect,
          // /compact, config reload, client restart -- each delivering SIGTERM.
          // Without keepAlive the handler would taskkill AB (it was spawned
          // detached precisely so it wouldn't have to), forcing a ~2min cold
          // start every time. With keepAlive we detach cleanly: AB keeps
          // running, its watcher keeps heart-beating, and the NEXT server
          // instance adopts it on startup (see adoptExisting). The explicit
          // shutdown_codesys tool and force_reset_watcher still terminate AB.
          await launcher.detachKeepAlive();
        } else {
          await launcher.shutdown();
        }
      } catch {
        serverLog.warn('Launcher shutdown failed during signal handler');
      }
    }
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
  process.on('unhandledRejection', (reason) => {
    serverLog.error(`Unhandled rejection: ${reason}`);
  });
}

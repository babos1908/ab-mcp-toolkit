/**
 * Shared TypeScript types for codesys-mcp-persistent
 */

export type RequestId = string;
export type SessionId = string;

/**
 * Standardized error codes surfaced by MCP tool failures. Goals:
 *
 *  - Replace fragile regex string matching (e.g. /timed out after \d+ms/) in
 *    ResilientExecutor and the agent-side skill with explicit identifiers.
 *  - Let scripts emit a structured marker `SCRIPT_ERROR_CODE: ERR_<X>` that
 *    server.ts can pluck out and surface as the tool's error code, in
 *    addition to the human-readable message.
 *  - Document the error taxonomy in one place so new tools nascano with
 *    aligned codes instead of inventing prose.
 *
 * Convention: ALL_CAPS_SNAKE prefixed with ERR_. Add new codes here AND in
 * the matching script-side marker (search src/scripts for SCRIPT_ERROR_CODE).
 */
export enum MCPErrorCode {
  // ─── IPC / lifecycle ──────────────────────────────────────────────
  /** Command did not return within commandTimeoutMs. */
  ERR_TIMEOUT = 'ERR_TIMEOUT',
  /** Watcher heartbeat is stale; primary thread or worker thread stuck. */
  ERR_STALL = 'ERR_STALL',
  /** Launcher state prohibits the operation (e.g. tool called while stopped). */
  ERR_STATE = 'ERR_STATE',
  /** CODESYS process died while waiting for a result. */
  ERR_PROCESS_DEAD = 'ERR_PROCESS_DEAD',

  // ─── Project / file ───────────────────────────────────────────────
  /** Project file not found at the given path. */
  ERR_PROJECT_NOT_FOUND = 'ERR_PROJECT_NOT_FOUND',
  /** Project is locked by another process; .lock file present. */
  ERR_PROJECT_LOCKED = 'ERR_PROJECT_LOCKED',
  /** Project file is corrupt or unreadable by AB. */
  ERR_PROJECT_CORRUPT = 'ERR_PROJECT_CORRUPT',
  /** A POU / object lookup failed (path not in tree). */
  ERR_OBJECT_NOT_FOUND = 'ERR_OBJECT_NOT_FOUND',

  // ─── Library ──────────────────────────────────────────────────────
  /** Library is not installed in any repository. */
  ERR_LIB_NOT_FOUND = 'ERR_LIB_NOT_FOUND',
  /** Same name+version is already installed (re-install without overwrite). */
  ERR_LIB_EXISTS = 'ERR_LIB_EXISTS',
  /** Library parameter name not exposed by the referenced library. */
  ERR_LIB_PARAM_NOT_FOUND = 'ERR_LIB_PARAM_NOT_FOUND',

  // ─── Online / device ──────────────────────────────────────────────
  /** Online application failed with "Stack empty" -- IDE context missing. */
  ERR_ONLINE_STACK_EMPTY = 'ERR_ONLINE_STACK_EMPTY',
  /** No PLC reachable at the configured gateway/address. */
  ERR_DEVICE_UNREACHABLE = 'ERR_DEVICE_UNREACHABLE',
  /** Gateway name could not be resolved to a GUID. */
  ERR_GATEWAY_UNKNOWN = 'ERR_GATEWAY_UNKNOWN',
  /** Application not running on PLC (read_variable / write_variable). */
  ERR_APP_NOT_RUNNING = 'ERR_APP_NOT_RUNNING',

  // ─── Build / compile ──────────────────────────────────────────────
  /** Compile finished with errors. */
  ERR_COMPILE_ERROR = 'ERR_COMPILE_ERROR',

  // ─── Scripting API limits ─────────────────────────────────────────
  /** The CODESYS scripting API on this build does not expose what's needed. */
  ERR_API_NOT_EXPOSED = 'ERR_API_NOT_EXPOSED',
  /** Operation is restricted to AB Premium edition. */
  ERR_PREMIUM_ONLY = 'ERR_PREMIUM_ONLY',

  // ─── Input validation ─────────────────────────────────────────────
  /** Tool parameter validation failed (missing/invalid). */
  ERR_BAD_INPUT = 'ERR_BAD_INPUT',

  // ─── Catch-all ────────────────────────────────────────────────────
  /** Unknown / uncategorized failure. */
  ERR_UNKNOWN = 'ERR_UNKNOWN',
}

/**
 * Marker emitted by Python scripts to surface a structured error code via
 * stdout. server.ts parses this from result.output. Format:
 *
 *     SCRIPT_ERROR_CODE: ERR_PROJECT_LOCKED
 *
 * Scripts SHOULD emit this in addition to the existing `SCRIPT_ERROR: ...`
 * line, NOT instead of -- the human-readable message is still useful.
 */
export const SCRIPT_ERROR_CODE_MARKER = 'SCRIPT_ERROR_CODE:';

/** Command file written by Node.js to commands/ directory */
export interface IpcCommand {
  requestId: RequestId;
  scriptPath: string;
  timestamp: number;
}

/** Result file written by watcher to results/ directory */
export interface IpcResult {
  requestId: RequestId;
  success: boolean;
  output: string;
  error: string;
  timestamp: number;
}

/**
 * CODESYS process lifecycle state.
 *
 * 'stalled' is a sub-state of 'ready' from the OS perspective (the CODESYS
 * process is still alive) but the watcher hasn't refreshed heartbeat.signal
 * recently, indicating either the worker thread died or the primary UI
 * thread is deadlocked. The only recovery is force_reset_watcher (kill +
 * relaunch). This state is surfaced so the agent knows to call reset
 * instead of waiting for commands to time out.
 */
export type CodesysState = 'stopped' | 'launching' | 'ready' | 'stalled' | 'stopping' | 'error';

/** Configuration for launching CODESYS */
export interface LauncherConfig {
  codesysPath: string;
  profileName: string;
  workspaceDir: string;
  /**
   * If true, runs `taskkill /F /T /IM CODESYS.exe` before spawning a new
   * instance. Useful in dev when MCP server restarts leave orphaned CODESYS
   * processes holding project locks. Off by default — never kill an external
   * CODESYS instance the user might be using.
   */
  killExistingCodesys?: boolean;
  /**
   * Maximum time to wait (ms) for the watcher to write ready.signal after
   * spawning CODESYS. Defaults to 60000. Heavyweight CODESYS distributions
   * (e.g. ABB Automation Builder) can take ~2 minutes to cold-boot the
   * scripting engine; bump this to 180000+ in those cases.
   */
  readyTimeoutMs?: number;
  /**
   * Per-command IPC timeout (ms) — how long the server waits for the watcher
   * to return a result before giving up. Defaults to 60000. First-time
   * project opens / large compiles on heavyweight distributions can exceed
   * this; bump to 300000+ to match the slowest expected operation.
   */
  commandTimeoutMs?: number;
}

/** Runtime status of the CODESYS launcher */
export interface LauncherStatus {
  state: CodesysState;
  pid: number | null;
  sessionId: SessionId | null;
  ipcDir: string | null;
  startedAt: number | null;
  lastError: string | null;
  /**
   * Age (in seconds) of the watcher's heartbeat.signal file at the time
   * getStatus() was called. null if no heartbeat file exists yet (cold
   * launch in progress) or if the launcher has no IPC client.
   *
   * A heartbeat age above ~30s while state is 'ready' usually indicates
   * the worker thread or primary UI thread is stuck. The launcher's health
   * monitor flips state to 'stalled' when this happens.
   */
  heartbeatAgeSeconds?: number | null;
}

/** IPC transport configuration */
export interface IpcConfig {
  baseDir: string;
  commandTimeoutMs: number;
  pollIntervalMs: number;
  maxPollIntervalMs: number;
  deleteResultAfterRead: boolean;
}

/** Full server configuration */
export interface ServerConfig extends LauncherConfig {
  autoLaunch: boolean;
  keepAlive: boolean;
  timeoutMs: number;
  fallbackHeadless: boolean;
  verbose: boolean;
  debug: boolean;
  mode: ExecutionMode;
  /**
   * When true (default), destructive tools (set_pou_code, delete_object,
   * set_project_info, set_task_parameter, install_library_to_repository,
   * etc.) take a filesystem snapshot of the .project/.library file before
   * running the underlying IronPython script. Backup files are stored next
   * to the source as `<path>.backup-YYYYMMDDTHHMMSSZ`. Opt out via CLI
   * --no-auto-backup. Disk-space management is out of scope -- the user
   * owns cleanup of accumulated .backup-* files.
   */
  autoBackup: boolean;
}

/** Script template parameters */
export type ScriptParams = Record<string, string>;

/** Execution mode */
export type ExecutionMode = 'persistent' | 'headless';

/** Interface for script executors (both persistent and headless) */
export interface ScriptExecutor {
  executeScript(content: string, timeoutMs?: number): Promise<IpcResult>;
}

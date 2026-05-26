/**
 * Shared TypeScript types for codesys-mcp-persistent
 */

export type RequestId = string;
export type SessionId = string;

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
}

/** Script template parameters */
export type ScriptParams = Record<string, string>;

/** Execution mode */
export type ExecutionMode = 'persistent' | 'headless';

/** Interface for script executors (both persistent and headless) */
export interface ScriptExecutor {
  executeScript(content: string, timeoutMs?: number): Promise<IpcResult>;
}

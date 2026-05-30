/**
 * CODESYS launcher — spawns CODESYS with UI and watcher script,
 * tracks process lifecycle, delegates to IPC for command execution.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { spawn, ChildProcess } from 'child_process';
import { v4 as uuidv4 } from 'uuid';
import { LauncherConfig, LauncherStatus, CodesysState, IpcResult, ScriptExecutor } from './types';
import { IpcClient, DEFAULT_IPC_CONFIG } from './ipc';
import { ScriptManager } from './script-manager';
import { sweepStaleLocks } from './lock-file';
import { launcherLog } from './logger';

const SESSION_DIR_PREFIX = 'codesys-mcp-persistent';
const DEFAULT_READY_TIMEOUT_MS = 60_000;
const READY_POLL_MS = 500;
const SHUTDOWN_WAIT_MS = 5_000;
const HEALTH_CHECK_INTERVAL_MS = 5_000;
/**
 * Heartbeat age (seconds) above which the launcher transitions to 'stalled'.
 * The watcher writes heartbeat.signal every ~5s when the worker thread is
 * alive. 30s gives plenty of slack for a long-running command on the primary
 * thread (which suspends heartbeat refresh) without false positives, but is
 * still much faster than the 60-600s command timeout.
 */
const HEARTBEAT_STALL_THRESHOLD_S = 30;

export class CodesysLauncher implements ScriptExecutor {
  private config: LauncherConfig;
  private state: CodesysState = 'stopped';
  private pid: number | null = null;
  private sessionId: string | null = null;
  private ipcDir: string | null = null;
  private ipcClient: IpcClient | null = null;
  private process: ChildProcess | null = null;
  private startedAt: number | null = null;
  private lastError: string | null = null;
  private healthInterval: ReturnType<typeof setInterval> | null = null;
  private stateChangeCallbacks: Array<(state: CodesysState) => void> = [];
  /**
   * True when we attached to a user-owned GUI (prepareAttach/completeAttach)
   * instead of spawning the process ourselves. In attach mode `pid` is null
   * by design, so the PID-based liveness check (isRunning()) must NOT be used
   * to decide the process died -- liveness is governed purely by the watcher
   * heartbeat. Without this guard the health monitor flips an otherwise
   * healthy attach session to 'error' within one interval. Reset on every
   * launch()/shutdown()/forceReset().
   */
  private attached = false;

  constructor(config: LauncherConfig) {
    this.config = config;
  }

  /** Launch CODESYS with UI and watcher script */
  async launch(): Promise<void> {
    if (this.state === 'ready' || this.state === 'launching') {
      launcherLog.warn(`Cannot launch: state is ${this.state}`);
      return;
    }

    // Validate CODESYS exe exists
    if (!fs.existsSync(this.config.codesysPath)) {
      const err = `CODESYS executable not found: ${this.config.codesysPath}`;
      this.setState('error');
      this.lastError = err;
      throw new Error(err);
    }

    // Optional: kill any pre-existing CODESYS.exe before launching. This is
    // only useful in dev to clean up after an MCP server restart that left
    // the old CODESYS detached and holding a project lock. It is OFF by
    // default because killing an unrelated CODESYS instance the user is
    // working in would lose unsaved work. Opt in with --kill-existing-codesys.
    if (this.config.killExistingCodesys === true && process.platform === 'win32') {
      try {
        const { execSync } = require('child_process');
        const exeBase = path.basename(this.config.codesysPath);
        try {
          execSync(`taskkill /F /T /IM "${exeBase}"`, { timeout: 10_000, stdio: 'ignore' });
          launcherLog.info(`Killed pre-existing ${exeBase} processes (opted-in via --kill-existing-codesys).`);
          await this.sleep(2_000);
        } catch {
          // Most common failure: no process found. That's the normal case.
        }
      } catch (killErr) {
        launcherLog.warn(`Pre-launch kill skipped: ${killErr}`);
      }
    }

    this.setState('launching');
    this.attached = false; // we are spawning, not attaching
    this.sessionId = uuidv4();
    this.ipcDir = path.join(os.tmpdir(), SESSION_DIR_PREFIX, this.sessionId);

    launcherLog.info(`Session ${this.sessionId} — IPC dir: ${this.ipcDir}`);

    // Stale lock-file sweep BEFORE launching. After a crash or
    // force_reset_watcher, .lock files next to .project/.library files can
    // survive and trigger "selected project is currently in use by 'X' on
    // 'Y'" on the next open_project. We sweep the configured workspaceDir
    // first; if the user opens a project from elsewhere, the lock-aware
    // retry in ensure_project_open handles the per-file case.
    try {
      if (this.config.workspaceDir) {
        sweepStaleLocks(this.config.workspaceDir);
      }
    } catch (sweepErr) {
      launcherLog.warn(`Stale lock sweep raised (ignored): ${sweepErr}`);
    }

    // Create IPC client and directories. commandTimeoutMs from LauncherConfig
    // overrides the default so heavy operations (cold project open, large
    // compiles on Automation Builder, etc.) are not killed by the 60s default.
    this.ipcClient = new IpcClient({
      baseDir: this.ipcDir,
      ...DEFAULT_IPC_CONFIG,
      ...(this.config.commandTimeoutMs ? { commandTimeoutMs: this.config.commandTimeoutMs } : {}),
    });
    await this.ipcClient.ensureDirectories();

    // Prepare watcher script with interpolated IPC path. ScriptManager.
    // interpolate() now Python-escapes the value, so no manual pre-escape.
    const scriptManager = new ScriptManager();
    const watcherTemplate = scriptManager.loadTemplate('watcher');
    const watcherContent = scriptManager.interpolate(watcherTemplate, {
      IPC_BASE_DIR: this.ipcDir,
    });

    // Write interpolated watcher to IPC directory
    const watcherPath = path.join(this.ipcDir, 'watcher.py');
    fs.writeFileSync(watcherPath, watcherContent, 'utf-8');

    // Build CODESYS args. Pass argv directly (no shell) so this.process.pid
    // is the real CODESYS PID rather than a wrapping cmd.exe shell PID.
    // Node will quote args containing spaces correctly when shell is off.
    const codesysArgs = [
      `--profile=${this.config.profileName}`,
      `--runscript=${watcherPath}`,
    ];
    const codesysDir = path.dirname(this.config.codesysPath);

    launcherLog.info(`Spawning: ${this.config.codesysPath} ${codesysArgs.join(' ')}`);

    // Spawn CODESYS detached with UI visible
    this.process = spawn(this.config.codesysPath, codesysArgs, {
      detached: true,
      shell: false,
      windowsHide: false,
      stdio: 'ignore',
      cwd: codesysDir,
    });

    this.pid = this.process.pid ?? null;
    this.process.unref();

    launcherLog.info(`CODESYS spawned with PID ${this.pid}`);

    // Handle process exit
    this.process.on('exit', (code) => {
      launcherLog.warn(`CODESYS process exited with code ${code}`);
      if (this.state !== 'stopping') {
        this.lastError = `CODESYS exited unexpectedly (code ${code})`;
        this.setState('error');
      }
      this.pid = null;
      this.process = null;
    });

    // Poll for ready.signal. Bumped past the default for heavy distributions
    // (ABB Automation Builder needs ~2 minutes for the scripting engine to
    // come up on cold start) by passing readyTimeoutMs in LauncherConfig.
    const readyTimeout = this.config.readyTimeoutMs ?? DEFAULT_READY_TIMEOUT_MS;
    const readyStart = Date.now();
    while (Date.now() - readyStart < readyTimeout) {
      if (await this.ipcClient.isReady()) {
        this.setState('ready');
        this.startedAt = Date.now();
        launcherLog.info(`CODESYS watcher is ready (after ${Date.now() - readyStart}ms)`);
        this.startHealthMonitor();
        return;
      }
      await this.sleep(READY_POLL_MS);
    }

    // Timeout — watcher never signaled ready
    this.lastError = `Watcher did not signal ready within ${readyTimeout}ms`;
    this.setState('error');
    throw new Error(this.lastError);
  }

  /** Graceful shutdown */
  async shutdown(): Promise<void> {
    if (this.state === 'stopped' || this.state === 'stopping') return;

    this.setState('stopping');
    this.stopHealthMonitor();

    // Try to close projects and quit CODESYS gracefully via script
    if (this.ipcClient && this.state !== 'error') {
      try {
        launcherLog.info('Sending quit script to close projects and exit CODESYS...');
        await this.ipcClient.sendCommand(`
import sys
try:
    import scriptengine as se
    # Close all open projects without saving (save should be done before shutdown)
    for p in list(se.projects):
        try:
            p.close()
        except:
            pass
    print("Projects closed")
except:
    pass
# Request CODESYS to quit
try:
    import scriptengine as se
    se.system.exit()
except:
    pass
print("SCRIPT_SUCCESS")
sys.exit(0)
`, 10_000);
      } catch {
        launcherLog.debug('Quit script timed out or failed (expected if CODESYS exits)');
      }
    }

    // Send terminate signal to watcher
    if (this.ipcClient) {
      try {
        await this.ipcClient.sendTerminate();
      } catch {
        launcherLog.warn('Failed to send terminate signal');
      }
    }

    // Wait for process exit
    if (this.pid !== null) {
      const waitStart = Date.now();
      while (Date.now() - waitStart < SHUTDOWN_WAIT_MS) {
        if (!this.isRunning()) break;
        await this.sleep(500);
      }

      // Force kill if still alive
      if (this.isRunning() && this.pid !== null) {
        launcherLog.warn('Force-killing CODESYS process');
        try {
          // On Windows, use taskkill for reliable process termination
          if (process.platform === 'win32') {
            const { execSync } = require('child_process');
            try {
              // First try graceful close (WM_CLOSE)
              execSync(`taskkill /PID ${this.pid}`, { timeout: 5000, stdio: 'ignore' });
              await this.sleep(3_000);
            } catch { /* ignore */ }
            if (this.isRunning()) {
              // Force kill
              try {
                execSync(`taskkill /F /PID ${this.pid}`, { timeout: 5000, stdio: 'ignore' });
              } catch { /* ignore */ }
            }
          } else if (this.process) {
            this.process.kill('SIGTERM');
            await this.sleep(2_000);
            if (this.isRunning() && this.process) {
              this.process.kill('SIGKILL');
            }
          }
        } catch {
          launcherLog.warn('Failed to kill CODESYS process');
        }
      }
    }

    // Clean up IPC directory
    if (this.ipcClient) {
      await this.ipcClient.cleanup();
    }

    this.pid = null;
    this.process = null;
    this.ipcClient = null;
    this.attached = false;
    this.setState('stopped');
    launcherLog.info('Shutdown complete');
  }

  /** Execute a script through the IPC channel */
  async executeScript(content: string, timeoutMs?: number): Promise<IpcResult> {
    if (!this.ipcClient) {
      throw new Error(`Cannot execute script: launcher state is '${this.state}'`);
    }
    if (this.state === 'stalled') {
      throw new Error(
        `Cannot execute script: launcher state is 'stalled' (watcher heartbeat stale). ` +
        `Call force_reset_watcher to recover, then retry.`
      );
    }
    if (this.state !== 'ready') {
      throw new Error(`Cannot execute script: launcher state is '${this.state}'`);
    }
    return this.ipcClient.sendCommand(content, timeoutMs);
  }

  /**
   * "Attach to existing CODESYS" — step 1. Prepares an IPC session and writes
   * a watcher.py the user runs themselves from inside an already-running
   * CODESYS / Automation Builder GUI (Tools → Scripting → Execute Script
   * File...). Returns the absolute path of the watcher.py.
   *
   * Does NOT spawn CODESYS. Pair with completeAttach() once the user has
   * started the script. The combination is functionally equivalent to
   * launch() but lets the user own the GUI lifecycle (lock conflicts disappear
   * because there is only one CODESYS instance, the user's own).
   */
  async prepareAttach(): Promise<{ watcherPath: string; sessionId: string }> {
    if (this.state !== 'stopped' && this.state !== 'error') {
      throw new Error(`Cannot prepare attach: state is '${this.state}'`);
    }

    this.setState('launching');
    this.attached = true; // user owns the GUI; pid will stay null
    this.sessionId = uuidv4();
    this.ipcDir = path.join(os.tmpdir(), SESSION_DIR_PREFIX, this.sessionId);
    launcherLog.info(`Attach session ${this.sessionId} — IPC dir: ${this.ipcDir}`);

    this.ipcClient = new IpcClient({
      baseDir: this.ipcDir,
      ...DEFAULT_IPC_CONFIG,
    });
    await this.ipcClient.ensureDirectories();

    const scriptManager = new ScriptManager();
    const watcherTemplate = scriptManager.loadTemplate('watcher');
    const watcherContent = scriptManager.interpolate(watcherTemplate, {
      IPC_BASE_DIR: this.ipcDir,
    });
    const watcherPath = path.join(this.ipcDir, 'watcher.py');
    fs.writeFileSync(watcherPath, watcherContent, 'utf-8');

    launcherLog.info(`Watcher prepared at ${watcherPath} (waiting for user to run it)`);
    return { watcherPath, sessionId: this.sessionId };
  }

  /**
   * "Attach to existing CODESYS" — step 2. Polls ready.signal until it
   * appears, then transitions to ready state. Call this AFTER the user has
   * started the prepared watcher script inside their CODESYS GUI.
   *
   * The pid is left null because we did not spawn — health monitoring still
   * works because the IPC channel will go silent if the user closes CODESYS.
   */
  async completeAttach(): Promise<void> {
    if (this.state !== 'launching' || !this.ipcClient) {
      throw new Error(`Cannot complete attach: state is '${this.state}'. Call prepareAttach() first.`);
    }

    const readyTimeout = this.config.readyTimeoutMs ?? DEFAULT_READY_TIMEOUT_MS;
    const readyStart = Date.now();
    while (Date.now() - readyStart < readyTimeout) {
      if (await this.ipcClient.isReady()) {
        this.setState('ready');
        this.startedAt = Date.now();
        launcherLog.info(`Attached to existing CODESYS watcher (after ${Date.now() - readyStart}ms)`);
        this.startHealthMonitor();
        return;
      }
      await this.sleep(READY_POLL_MS);
    }

    this.lastError = `Watcher did not signal ready within ${readyTimeout}ms after attach. Did you run the watcher script in CODESYS Tools → Scripting → Execute Script File...?`;
    this.setState('error');
    throw new Error(this.lastError);
  }

  /** Get current launcher status */
  getStatus(): LauncherStatus {
    return {
      state: this.state,
      pid: this.pid,
      sessionId: this.sessionId,
      ipcDir: this.ipcDir,
      startedAt: this.startedAt,
      lastError: this.lastError,
      // heartbeatAgeSeconds is filled by getStatusAsync(); the sync version
      // omits it to keep getStatus() side-effect-free.
    };
  }

  /**
   * Async variant of getStatus() that also reads the heartbeat file age.
   * Used by diagnose_mcp_state and get_codesys_status to surface watcher
   * liveness independent of the cached state field.
   */
  async getStatusAsync(): Promise<LauncherStatus> {
    const base = this.getStatus();
    if (this.ipcClient) {
      try {
        base.heartbeatAgeSeconds = await this.ipcClient.getHeartbeatAgeSeconds();
      } catch {
        base.heartbeatAgeSeconds = null;
      }
    } else {
      base.heartbeatAgeSeconds = null;
    }
    return base;
  }

  /**
   * Diagnostic dump for diagnose_mcp_state tool. Returns runtime state +
   * filesystem evidence about what the watcher is/isn't doing. Read-only;
   * does not modify any state.
   */
  async diagnose(): Promise<{
    status: LauncherStatus;
    queueDepth: { pendingCommands: number; orphanResults: number } | null;
    watcherErrorLog: string | null;
    isProcessAlive: boolean;
    interpretation: string;
  }> {
    const status = await this.getStatusAsync();
    const isProcessAlive = this.isRunning();
    let queueDepth: { pendingCommands: number; orphanResults: number } | null = null;
    let watcherErrorLog: string | null = null;
    if (this.ipcClient) {
      try { queueDepth = await this.ipcClient.getQueueDepth(); } catch { /* ignore */ }
      try { watcherErrorLog = await this.ipcClient.readWatcherErrorLog(); } catch { /* ignore */ }
    }

    // Build a human-readable interpretation so the agent can decide whether
    // to call force_reset_watcher without parsing the raw numbers.
    let interpretation: string;
    if (!isProcessAlive && status.state !== 'stopped' && status.state !== 'launching') {
      interpretation = 'CODESYS process is dead but launcher state is not stopped -- call launch_codesys to recover.';
    } else if (status.state === 'stalled') {
      interpretation = `Watcher heartbeat stale (age=${status.heartbeatAgeSeconds?.toFixed(1)}s). Worker thread died or primary UI thread is deadlocked. Call force_reset_watcher to recover.`;
    } else if (status.state === 'ready' && status.heartbeatAgeSeconds !== null && status.heartbeatAgeSeconds !== undefined && status.heartbeatAgeSeconds > HEARTBEAT_STALL_THRESHOLD_S) {
      interpretation = `Watcher heartbeat appears stale (age=${status.heartbeatAgeSeconds.toFixed(1)}s) but state is still 'ready' -- health monitor will flip to stalled shortly. Either wait or call force_reset_watcher.`;
    } else if (status.state === 'ready' && queueDepth && queueDepth.pendingCommands > 5) {
      interpretation = `Commands are backing up (${queueDepth.pendingCommands} pending) -- watcher may be slow or recovering from a stall. If a single command takes >2 min something is wrong; call force_reset_watcher.`;
    } else if (status.state === 'ready') {
      interpretation = 'Healthy.';
    } else {
      interpretation = `Launcher state is '${status.state}'. See lastError for details.`;
    }

    return { status, queueDepth, watcherErrorLog, isProcessAlive, interpretation };
  }

  /** Check if the CODESYS process is still alive */
  isRunning(): boolean {
    if (this.pid === null) return false;
    try {
      process.kill(this.pid, 0); // Signal 0 = test if process exists
      return true;
    } catch {
      return false;
    }
  }

  /** Register callback for state changes */
  onStateChange(callback: (state: CodesysState) => void): void {
    this.stateChangeCallbacks.push(callback);
  }

  private setState(state: CodesysState): void {
    const prev = this.state;
    this.state = state;
    if (prev !== state) {
      launcherLog.info(`State: ${prev} -> ${state}`);
      for (const cb of this.stateChangeCallbacks) {
        try { cb(state); } catch { /* ignore callback errors */ }
      }
    }
  }

  private startHealthMonitor(): void {
    this.healthInterval = setInterval(async () => {
      // Pre-existing check: did the CODESYS process die outright?
      // Skip in attach mode: pid is null by design (we did not spawn), so
      // isRunning() would always report "dead" and falsely flip a healthy
      // attached session to 'error'. In attach mode liveness is governed
      // entirely by the heartbeat staleness check below -- if the user closes
      // their GUI, heartbeat.signal stops updating and we flip to 'stalled'.
      if (!this.attached && (this.state === 'ready' || this.state === 'stalled') && !this.isRunning()) {
        launcherLog.error('Health check: CODESYS process died');
        this.lastError = 'CODESYS process died unexpectedly';
        this.pid = null;
        this.process = null;
        this.setState('error');
        this.stopHealthMonitor();
        return;
      }
      // New: watcher heartbeat staleness check. The process is alive but
      // the worker thread isn't refreshing heartbeat.signal -- typical
      // symptoms are primary-thread deadlock (long script hang) or worker
      // thread crash. We surface this as 'stalled' so callers know to
      // force_reset_watcher; we do NOT auto-reset here because the user
      // may have a long manual operation in progress they don't want killed.
      if (this.state === 'ready' && this.ipcClient) {
        try {
          const ageS = await this.ipcClient.getHeartbeatAgeSeconds();
          if (ageS !== null && ageS > HEARTBEAT_STALL_THRESHOLD_S) {
            launcherLog.warn(
              `Health check: watcher heartbeat is ${ageS.toFixed(1)}s old ` +
              `(threshold ${HEARTBEAT_STALL_THRESHOLD_S}s) -- flipping state to stalled.`
            );
            this.lastError =
              `Watcher heartbeat stale: ${ageS.toFixed(1)}s old. ` +
              `Worker thread died or primary UI thread is deadlocked. ` +
              `Call force_reset_watcher to recover.`;
            this.setState('stalled');
          }
        } catch (err) {
          launcherLog.debug(`Heartbeat check failed (ignored): ${err}`);
        }
      }
      // Recovery direction: if state was 'stalled' and heartbeat is now
      // fresh again, flip back to 'ready'. This handles the rare case
      // where a long-running command completes and the worker resumes
      // heartbeat updates.
      if (this.state === 'stalled' && this.ipcClient) {
        try {
          const ageS = await this.ipcClient.getHeartbeatAgeSeconds();
          if (ageS !== null && ageS <= HEARTBEAT_STALL_THRESHOLD_S) {
            launcherLog.info(
              `Health check: heartbeat recovered (age=${ageS.toFixed(1)}s) -- flipping back to ready.`
            );
            this.lastError = null;
            this.setState('ready');
          }
        } catch { /* ignore */ }
      }
    }, HEALTH_CHECK_INTERVAL_MS);
  }

  /**
   * Force-reset: kill the CODESYS process, clean up the IPC directory,
   * then re-launch. Equivalent to shutdown_codesys() + launch_codesys()
   * but in a single call with stale-file cleanup in between.
   *
   * Recovery path for: silent watcher death, primary-thread deadlock,
   * or any other state where commands stop returning. Does NOT save
   * any open project (the project is already in an unknown state if the
   * watcher hit a deadlock; we'd risk corrupting it by trying to save).
   */
  async forceReset(): Promise<void> {
    launcherLog.warn(`forceReset() called -- killing process and re-launching. State was: ${this.state}`);

    // Best-effort: send terminate so a non-stalled watcher exits cleanly.
    // We give it a short window because if it WAS stalled the signal will
    // never be read.
    if (this.ipcClient) {
      try { await this.ipcClient.sendTerminate(); } catch { /* ignore */ }
    }

    // Stop health monitor so it doesn't fight the state transitions below.
    this.stopHealthMonitor();
    this.setState('stopping');

    // Kill the process. Skip the graceful "quit script" attempt that
    // shutdown() does -- the whole point of forceReset() is "process is
    // not responding, kill it hard". We still try /F /T (force tree)
    // first via taskkill on Windows.
    if (this.pid !== null) {
      if (process.platform === 'win32') {
        const { execSync } = require('child_process');
        try {
          execSync(`taskkill /F /T /PID ${this.pid}`, { timeout: 10_000, stdio: 'ignore' });
        } catch { /* process may already be gone */ }
      } else if (this.process) {
        try { this.process.kill('SIGKILL'); } catch { /* ignore */ }
      }
      // Wait briefly for the OS to reap the PID.
      const waitStart = Date.now();
      while (Date.now() - waitStart < 5_000 && this.isRunning()) {
        await this.sleep(200);
      }
    }

    // Clean up the IPC dir for the dead session.
    if (this.ipcClient) {
      try { await this.ipcClient.cleanup(); } catch { /* ignore */ }
    }
    this.pid = null;
    this.process = null;
    this.ipcClient = null;
    this.startedAt = null;
    this.attached = false;
    this.setState('stopped');
    this.lastError = null;

    launcherLog.info('forceReset(): killed previous session, now re-launching');

    // Re-launch. This goes through the normal launch() path and will
    // create a fresh session dir, watcher.py, and ready.signal cycle.
    await this.launch();
  }

  private stopHealthMonitor(): void {
    if (this.healthInterval) {
      clearInterval(this.healthInterval);
      this.healthInterval = null;
    }
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

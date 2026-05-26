/**
 * File-based IPC transport layer.
 * Writes command files, polls for result files, with command serialization.
 */

import * as fs from 'fs';
import * as path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { IpcConfig, IpcResult, IpcCommand, RequestId } from './types';
import { ipcLog } from './logger';

/** Default IPC configuration */
export const DEFAULT_IPC_CONFIG: Omit<IpcConfig, 'baseDir'> = {
  commandTimeoutMs: 60_000,
  pollIntervalMs: 100,
  maxPollIntervalMs: 1_000,
  deleteResultAfterRead: true,
};

/**
 * Async mutex for serializing commands.
 * Ensures only one command is in-flight at a time.
 */
class AsyncMutex {
  private _queue: Array<() => void> = [];
  private _locked = false;

  async acquire(): Promise<void> {
    if (!this._locked) {
      this._locked = true;
      return;
    }
    return new Promise<void>((resolve) => {
      this._queue.push(resolve);
    });
  }

  release(): void {
    if (this._queue.length > 0) {
      const next = this._queue.shift()!;
      next();
    } else {
      this._locked = false;
    }
  }
}

/**
 * Atomic file write: write to .tmp then rename.
 * Uses fsync to ensure data is flushed to disk before rename.
 */
async function atomicWrite(filePath: string, content: string): Promise<void> {
  const tmpPath = filePath + '.tmp';
  const fd = fs.openSync(tmpPath, 'w');
  try {
    fs.writeSync(fd, content, undefined, 'utf-8');
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(tmpPath, filePath);
}

export class IpcClient {
  private config: IpcConfig;
  private mutex = new AsyncMutex();
  private commandsDir: string;
  private resultsDir: string;

  constructor(config: IpcConfig) {
    this.config = config;
    this.commandsDir = path.join(config.baseDir, 'commands');
    this.resultsDir = path.join(config.baseDir, 'results');
  }

  /** Create commands/ and results/ directories */
  async ensureDirectories(): Promise<void> {
    fs.mkdirSync(this.commandsDir, { recursive: true });
    fs.mkdirSync(this.resultsDir, { recursive: true });
    ipcLog.debug(`IPC directories created at ${this.config.baseDir}`);
  }

  /** Check if the watcher has written ready.signal */
  async isReady(): Promise<boolean> {
    const signalPath = path.join(this.config.baseDir, 'ready.signal');
    return fs.existsSync(signalPath);
  }

  /**
   * Get the age (seconds) of the watcher's heartbeat.signal file. Returns
   * null if the file does not exist (e.g. watcher hasn't run a single loop
   * iteration yet, or it never wrote one). A stale age (typically > 30s)
   * means the watcher's worker thread died OR the primary UI thread is
   * deadlocked -- both unrecoverable without a process restart.
   */
  async getHeartbeatAgeSeconds(): Promise<number | null> {
    const heartbeatPath = path.join(this.config.baseDir, 'heartbeat.signal');
    try {
      const stat = fs.statSync(heartbeatPath);
      const ageMs = Date.now() - stat.mtimeMs;
      return ageMs / 1000;
    } catch {
      return null;
    }
  }

  /**
   * Read the contents of watcher_error.txt (the watcher's fatal error log,
   * written before any other logging is set up). Returns null if the file
   * does not exist. Useful for diagnose_mcp_state to surface why a watcher
   * never started.
   */
  async readWatcherErrorLog(): Promise<string | null> {
    const errorPath = path.join(this.config.baseDir, 'watcher_error.txt');
    try {
      if (!fs.existsSync(errorPath)) return null;
      return fs.readFileSync(errorPath, 'utf-8');
    } catch {
      return null;
    }
  }

  /**
   * Count files in commands/ and results/ for diagnose_mcp_state. A high
   * pending command count means commands are backing up (watcher slow or
   * deadlocked); a high orphan result count means results are accumulating
   * without being consumed (Node-side cleanup broken).
   */
  async getQueueDepth(): Promise<{ pendingCommands: number; orphanResults: number }> {
    let pending = 0;
    let orphan = 0;
    try {
      const cmdFiles = fs.readdirSync(this.commandsDir);
      pending = cmdFiles.filter((f) => f.endsWith('.command.json')).length;
    } catch { /* ignore */ }
    try {
      const resFiles = fs.readdirSync(this.resultsDir);
      orphan = resFiles.filter((f) => f.endsWith('.result.json')).length;
    } catch { /* ignore */ }
    return { pendingCommands: pending, orphanResults: orphan };
  }

  /**
   * Remove orphan files in commands/ and results/ older than a threshold.
   * Called at launcher startup AND by force_reset_watcher to clean up state
   * from a previous (crashed/stalled) session before re-launching.
   */
  async cleanupStaleFiles(maxAgeSeconds: number = 3600): Promise<{ removed: number }> {
    const nowMs = Date.now();
    const cutoffMs = maxAgeSeconds * 1000;
    let removed = 0;
    for (const dir of [this.commandsDir, this.resultsDir]) {
      try {
        for (const fn of fs.readdirSync(dir)) {
          const fp = path.join(dir, fn);
          try {
            const stat = fs.statSync(fp);
            if (nowMs - stat.mtimeMs > cutoffMs) {
              fs.unlinkSync(fp);
              removed++;
            }
          } catch { /* skip files that can't be stat'd */ }
        }
      } catch { /* dir doesn't exist yet */ }
    }
    if (removed > 0) {
      ipcLog.info(`cleanupStaleFiles removed ${removed} stale file(s)`);
    }
    return { removed };
  }

  /** Write terminate.signal to request watcher shutdown */
  async sendTerminate(): Promise<void> {
    const signalPath = path.join(this.config.baseDir, 'terminate.signal');
    await atomicWrite(signalPath, JSON.stringify({ timestamp: Date.now() }));
    ipcLog.info('Terminate signal sent');
  }

  /**
   * Send a command to the watcher and wait for result.
   * Serialized via async mutex — only one command in-flight at a time.
   */
  async sendCommand(scriptContent: string, timeoutMs?: number): Promise<IpcResult> {
    await this.mutex.acquire();
    try {
      return await this._sendCommandInternal(scriptContent, timeoutMs);
    } finally {
      this.mutex.release();
    }
  }

  private async _sendCommandInternal(
    scriptContent: string,
    timeoutMs?: number
  ): Promise<IpcResult> {
    const requestId: RequestId = uuidv4();
    const timeout = timeoutMs ?? this.config.commandTimeoutMs;
    const scriptFileName = `${requestId}.py`;
    const commandFileName = `${requestId}.command.json`;
    const resultFileName = `${requestId}.result.json`;

    const scriptPath = path.join(this.commandsDir, scriptFileName);
    const commandPath = path.join(this.commandsDir, commandFileName);
    const resultPath = path.join(this.resultsDir, resultFileName);

    ipcLog.debug(`Sending command ${requestId}`);

    // Step 1: Write .py script file with fsync
    await atomicWrite(scriptPath, scriptContent);

    // Step 2: Write .command.json (triggers watcher)
    const command: IpcCommand = {
      requestId,
      scriptPath: scriptPath,
      timestamp: Date.now(),
    };
    await atomicWrite(commandPath, JSON.stringify(command));

    ipcLog.debug(`Command ${requestId} written, polling for result...`);

    // Step 3: Poll for result with progressive backoff
    const startTime = Date.now();
    let pollInterval = this.config.pollIntervalMs;

    while (Date.now() - startTime < timeout) {
      if (fs.existsSync(resultPath)) {
        // Try to read result with retry for partial writes
        const result = await this._readResultWithRetry(resultPath, requestId);
        if (result) {
          // Clean up result file if configured
          if (this.config.deleteResultAfterRead) {
            try {
              fs.unlinkSync(resultPath);
            } catch {
              // Ignore cleanup errors
            }
          }
          ipcLog.debug(
            `Command ${requestId} completed: success=${result.success}`
          );
          return result;
        }
      }

      // Progressive backoff: double interval, cap at max
      await this._sleep(pollInterval);
      pollInterval = Math.min(pollInterval * 2, this.config.maxPollIntervalMs);
    }

    // Timeout — clean up command files
    this._cleanupCommandFiles(requestId);

    throw new Error(
      `Command ${requestId} timed out after ${timeout}ms waiting for result`
    );
  }

  /**
   * Read result file with retry for corrupted/partial JSON.
   * Up to 3 attempts with 100ms delay between.
   */
  private async _readResultWithRetry(
    resultPath: string,
    requestId: string
  ): Promise<IpcResult | null> {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const content = fs.readFileSync(resultPath, 'utf-8');
        const result: IpcResult = JSON.parse(content);
        if (result.requestId === requestId) {
          return result;
        }
        ipcLog.warn(
          `Result file requestId mismatch: expected ${requestId}, got ${result.requestId}`
        );
        return null;
      } catch (err) {
        if (attempt < 2) {
          ipcLog.debug(
            `Result read attempt ${attempt + 1} failed, retrying in 100ms...`
          );
          await this._sleep(100);
        } else {
          ipcLog.warn(
            `Failed to read result after 3 attempts for ${requestId}: ${err}`
          );
          return null;
        }
      }
    }
    return null;
  }

  /** Clean up command files for a given request */
  private _cleanupCommandFiles(requestId: string): void {
    const scriptPath = path.join(this.commandsDir, `${requestId}.py`);
    const commandPath = path.join(
      this.commandsDir,
      `${requestId}.command.json`
    );
    try {
      if (fs.existsSync(scriptPath)) fs.unlinkSync(scriptPath);
    } catch { /* ignore */ }
    try {
      if (fs.existsSync(commandPath)) fs.unlinkSync(commandPath);
    } catch { /* ignore */ }
  }

  /** Remove the entire session directory */
  async cleanup(): Promise<void> {
    try {
      fs.rmSync(this.config.baseDir, { recursive: true, force: true });
      ipcLog.info(`Session directory cleaned up: ${this.config.baseDir}`);
    } catch (err) {
      ipcLog.warn(`Failed to clean up session directory: ${err}`);
    }
  }

  private _sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

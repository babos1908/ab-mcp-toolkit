/**
 * Structured stderr logging with levels.
 * MCP uses stdout for protocol, so all logs go to stderr.
 *
 * Optional file sink: under Claude Code CLI, a stdio server's stderr is not
 * persisted to a file the user can find, so lifecycle markers
 * (detachKeepAlive / Force-killing / soft-probe) are invisible after a
 * recurrence. setLogFile(path) mirrors every emitted line to a file using
 * SYNCHRONOUS appends -- intentionally, so the last lines survive an abrupt
 * process teardown (e.g. an OS job-object kill-on-close) that would lose a
 * buffered stream. Low log volume makes the sync cost negligible.
 */
import * as fs from 'fs';
import * as path from 'path';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

let currentLevel: LogLevel = 'info';
let logFilePath: string | null = null;

export function setLogLevel(level: LogLevel): void {
  currentLevel = level;
}

export function getLogLevel(): LogLevel {
  return currentLevel;
}

/**
 * Enable mirroring of all log lines to a file (in addition to stderr). Creates
 * the parent directory if needed. Best-effort: a file that can't be opened is
 * reported once to stderr and then ignored (stderr logging continues).
 */
export function setLogFile(filePath: string | null): void {
  if (!filePath) {
    logFilePath = null;
    return;
  }
  try {
    const dir = path.dirname(filePath);
    fs.mkdirSync(dir, { recursive: true });
    // Touch with a session-start marker so the file always exists and the user
    // can confirm the path is live even before the first real event.
    fs.appendFileSync(filePath, `${new Date().toISOString()} [LOGGER] INFO: log file opened\n`);
    logFilePath = filePath;
  } catch (err) {
    process.stderr.write(`[LOGGER] could not open log file '${filePath}': ${err}\n`);
    logFilePath = null;
  }
}

export function getLogFile(): string | null {
  return logFilePath;
}

function shouldLog(level: LogLevel): boolean {
  return LOG_LEVELS[level] >= LOG_LEVELS[currentLevel];
}

function formatMessage(prefix: string, level: LogLevel, message: string): string {
  const timestamp = new Date().toISOString();
  return `${timestamp} [${prefix}] ${level.toUpperCase()}: ${message}`;
}

function emit(line: string): void {
  process.stderr.write(line + '\n');
  if (logFilePath) {
    try {
      fs.appendFileSync(logFilePath, line + '\n');
    } catch {
      // Don't let a file-sink failure break logging; stderr already got it.
    }
  }
}

function createLogger(prefix: string) {
  return {
    debug(message: string): void {
      if (shouldLog('debug')) emit(formatMessage(prefix, 'debug', message));
    },
    info(message: string): void {
      if (shouldLog('info')) emit(formatMessage(prefix, 'info', message));
    },
    warn(message: string): void {
      if (shouldLog('warn')) emit(formatMessage(prefix, 'warn', message));
    },
    error(message: string): void {
      if (shouldLog('error')) emit(formatMessage(prefix, 'error', message));
    },
  };
}

export const ipcLog = createLogger('IPC');
export const launcherLog = createLogger('LAUNCHER');
export const serverLog = createLogger('SERVER');
export const watcherLog = createLogger('WATCHER');
export const headlessLog = createLogger('HEADLESS');

/**
 * ExecutorProxy - stable reference that forwards executeScript calls to a
 * swappable inner executor, gated on a readiness promise.
 *
 * Solves the launcher-swap race: when persistent-mode auto-launch resolves
 * mid-call and the tool handler had already captured a `let executor`
 * binding, the rest of the in-flight call would either still use the old
 * executor (closure-binding semantics in JS reads lazily, but the result is
 * the same: no atomic swap point), or two parallel calls that arrive within
 * the swap window would land on different executors and race on the same
 * project file.
 *
 * The proxy reference is stable (`const`), and every executeScript awaits
 * the readyPromise first. swap() updates the readyPromise; new calls block
 * on the new promise until it resolves, then run on the new inner executor.
 * Calls that started before swap() finish on whichever inner they snapshotted.
 */
import { IpcResult, ScriptExecutor } from './types';
import { launcherLog } from './logger';

/**
 * Interface for executors that support a force-reset recovery operation.
 * The CODESYS launcher implements this; HeadlessExecutor does not (each
 * headless call spawns its own CODESYS instance, so there is no persistent
 * state to reset).
 */
export interface ResettableExecutor extends ScriptExecutor {
  forceReset(): Promise<void>;
}

/**
 * Wraps a ResettableExecutor with auto-recovery on watcher lockups.
 *
 * Failure mode this exists for: the watcher inside CODESYS goes silent for
 * reasons we cannot detect from the script side -- background worker thread
 * dies, primary UI thread hits a CLR deadlock, GC stall, etc. The user
 * symptom is "MCP locked, I have to restart AB". The 30s heartbeat staleness
 * check in the launcher catches most of these, but the timeout path
 * (command never returns) is the canonical signal.
 *
 * Recovery policy:
 *   - On the first command timeout: assume it's a long-running operation,
 *     re-throw immediately so the caller sees the timeout error.
 *   - On a second consecutive timeout: assume watcher is genuinely stuck,
 *     call forceReset() (kill CODESYS, clean IPC, relaunch) and retry the
 *     command ONCE on the fresh watcher.
 *   - Successful calls reset the consecutive-timeout counter.
 *
 * We do NOT auto-reset on the first timeout because legitimate slow
 * operations (cold project open, big compile) can exceed the configured
 * commandTimeoutMs. The "two strikes" policy avoids fighting the user when
 * the timeout is just too tight.
 */
export class ResilientExecutor implements ResettableExecutor {
  private consecutiveTimeouts = 0;
  // While a reset is in flight, do not start another one. New calls wait
  // for this promise to settle (or proceed normally if null).
  private resetInFlight: Promise<void> | null = null;

  constructor(private inner: ResettableExecutor) {}

  async executeScript(content: string, timeoutMs?: number): Promise<IpcResult> {
    // If a reset is currently in progress, wait for it to finish before
    // sending a new command. The new command runs against the fresh watcher.
    if (this.resetInFlight) {
      try { await this.resetInFlight; } catch { /* reset failed; surface via next call */ }
    }
    try {
      const result = await this.inner.executeScript(content, timeoutMs);
      // Command returned (success or in-script error) -- the watcher is alive,
      // reset the consecutive-timeout counter.
      this.consecutiveTimeouts = 0;
      return result;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const isTimeout = /timed out after \d+ms/i.test(msg);
      if (!isTimeout) {
        // Not a timeout -- propagate without touching the counter.
        throw err;
      }

      this.consecutiveTimeouts++;
      launcherLog.warn(
        `ResilientExecutor: command timed out (consecutive=${this.consecutiveTimeouts})`
      );

      if (this.consecutiveTimeouts < 2) {
        // First timeout -- could be a legitimate slow operation. Re-throw
        // and let the caller decide whether to retry.
        throw err;
      }

      // Two timeouts in a row -- assume watcher is locked. Reset and retry once.
      // Guard against concurrent resets if multiple in-flight calls all time out.
      if (!this.resetInFlight) {
        launcherLog.warn(
          `ResilientExecutor: 2 consecutive timeouts -- triggering forceReset() and retrying.`
        );
        this.resetInFlight = this.inner.forceReset()
          .then(() => {
            // Reset succeeded. Clear counter so retries don't immediately
            // trigger another reset on transient slowness post-recovery.
            this.consecutiveTimeouts = 0;
          })
          .finally(() => {
            this.resetInFlight = null;
          });
      }
      try {
        await this.resetInFlight;
      } catch (resetErr) {
        const rmsg = resetErr instanceof Error ? resetErr.message : String(resetErr);
        throw new Error(
          `Watcher appeared locked (2 consecutive timeouts). Auto-recovery via ` +
          `forceReset() also failed: ${rmsg}. Original timeout: ${msg}.`
        );
      }
      // Retry the command on the fresh watcher.
      launcherLog.info(`ResilientExecutor: retrying command after successful reset.`);
      return this.inner.executeScript(content, timeoutMs);
    }
  }

  /** Pass-through reset for callers that have a ResettableExecutor reference. */
  async forceReset(): Promise<void> {
    if (this.resetInFlight) {
      return this.resetInFlight;
    }
    this.resetInFlight = this.inner.forceReset()
      .finally(() => { this.resetInFlight = null; });
    return this.resetInFlight;
  }
}

export class ExecutorProxy implements ScriptExecutor {
  private inner: ScriptExecutor;
  private readyPromise: Promise<void> = Promise.resolve();
  // Monotonic version stamp - each swap call increments it, and pending
  // chains compare against the live version before applying their inner.
  // Stops a slow-resolving background swap from later overwriting a faster
  // explicit swapNow (e.g. user calls launch_codesys while the auto-launch
  // is still resolving).
  private swapVersion: number = 0;

  constructor(initial: ScriptExecutor) {
    this.inner = initial;
  }

  /** Replace the inner executor once `newReady` resolves.
   *
   * Calls to executeScript that arrive AFTER this returns will block on
   * newReady before delegating to the new inner. If newReady rejects, the
   * old inner stays in place and subsequent calls run on it.
   */
  swap(newInner: ScriptExecutor, newReady: Promise<void>): void {
    const myVersion = ++this.swapVersion;
    // Chain the new readiness onto whatever was previously pending so callers
    // never see the inner change without a corresponding readyPromise resolve.
    const chained = this.readyPromise.then(() => newReady);
    this.readyPromise = chained;
    chained
      .then(() => {
        if (myVersion === this.swapVersion) {
          this.inner = newInner;
        }
        // else: a later swap superseded us; do nothing.
      })
      .catch(() => {
        if (myVersion === this.swapVersion) {
          // Keep the old inner. Reset readyPromise so future calls don't block.
          this.readyPromise = Promise.resolve();
        }
      });
  }

  /** Synchronously swap the inner executor with no readiness gate. Use only
   *  for explicit tool-driven transitions (launch_codesys, shutdown_codesys)
   *  where the caller has already awaited the underlying readiness.
   *  Bumps swapVersion so any pending background swap won't overwrite us. */
  swapNow(newInner: ScriptExecutor): void {
    this.swapVersion++;
    this.inner = newInner;
    this.readyPromise = Promise.resolve();
  }

  /** Snapshot the current inner reference - useful for status reporting. */
  current(): ScriptExecutor {
    return this.inner;
  }

  async executeScript(content: string, timeoutMs?: number): Promise<IpcResult> {
    await this.readyPromise;
    return this.inner.executeScript(content, timeoutMs);
  }
}

import sys
import scriptengine as script_engine
import os
import time
import re
import traceback

# --- Function to ensure the correct project is open ---
MAX_RETRIES = 3
RETRY_DELAY = 2.0

# Pattern indicating a .lock file conflict from CODESYS. The exact wording
# varies per AB version but always includes "in use" and host or user info.
_LOCK_ERROR_PATTERNS = (
    'is currently in use',
    'project is locked',
    'in use by',
)

def clean_path(path_str):
    return path_str.strip('"\'')

def _find_lock_file(project_path):
    """Return the path of the .lock file next to the project, or None."""
    base, ext = os.path.splitext(project_path)
    candidates = (base + '.lock', project_path + '.lock')
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def _pid_alive(pid):
    """Return True if PID is alive on this Windows machine, False if not,
    None if we can't tell. We avoid spawning tasklist for every check; the
    Win32 OpenProcess API would be ideal but is awkward from IronPython.
    Best-effort heuristic: assume "unknown" when in doubt -- the caller
    will fall back to "leave the lock alone"."""
    try:
        import subprocess
        # tasklist /FI "PID eq <pid>" /NH outputs a line if the process exists.
        out = subprocess.check_output(
            ['tasklist', '/FI', 'PID eq %d' % pid, '/NH'],
            stderr=subprocess.STDOUT
        )
        return b'No tasks' not in out and bool(out.strip())
    except Exception:
        return None

def _try_clean_stale_lock(project_path):
    """If a .lock file exists and the PID inside is dead, remove the lock.
    Returns True if a stale lock was cleaned (caller should retry the open).
    """
    lock_path = _find_lock_file(project_path)
    if not lock_path:
        return False
    try:
        with open(lock_path, 'r') as f:
            content = f.read()
    except Exception:
        content = ''
    m = re.search(r'\bpid\s*[:=]\s*(\d+)', content, re.IGNORECASE)
    if m:
        pid = int(m.group(1))
        alive = _pid_alive(pid)
        if alive is False:
            try:
                os.remove(lock_path)
                print("DEBUG: ensure_project_open removed stale lock for dead pid %d: %s" % (pid, lock_path))
                return True
            except Exception as rm_err:
                print("WARN: could not remove stale lock %s: %s" % (lock_path, rm_err))
                return False
        print("DEBUG: lock file %s held by alive pid %d; not removing." % (lock_path, pid))
        return False
    # No PID we can resolve -> safer to leave it alone.
    print("DEBUG: lock file %s has no parseable PID; not removing." % lock_path)
    return False

def _is_lock_error(err):
    msg = str(err).lower()
    return any(p in msg for p in _LOCK_ERROR_PATTERNS)

def ensure_project_open(target_project_path):
    path_to_use = clean_path(target_project_path)
    normalized_target_path = os.path.normcase(os.path.abspath(path_to_use))

    # Track the most recent open() error so the final RuntimeError can include
    # the actual root cause (locked project, missing file, version mismatch,
    # etc.) instead of a generic "after 3 attempts" message.
    last_open_error = None

    for attempt in range(MAX_RETRIES):
        primary_project = None
        try:
            primary_project = script_engine.projects.primary
        except Exception as primary_err:
             print("WARN: Error getting primary project: %s. Assuming none." % primary_err)
             primary_project = None

        current_project_path = ""
        project_ok = False

        if primary_project:
            try:
                current_project_path = os.path.normcase(os.path.abspath(primary_project.path))
                if current_project_path == normalized_target_path:
                    # Right project is primary; sanity-check accessibility before returning.
                    try:
                         _ = len(primary_project.get_children(False))
                         project_ok = True
                         return primary_project
                    except Exception as access_err:
                         print("WARN: Primary project access check failed for '%s': %s. Will attempt reopen." % (current_project_path, access_err))
                         primary_project = None
                else:
                     primary_project = None
            except Exception as path_err:
                 print("WARN: Could not get path of current primary project: %s. Assuming not the target." % path_err)
                 primary_project = None

        if not project_ok:
            try:
                update_mode = script_engine.VersionUpdateFlags.NoUpdates | script_engine.VersionUpdateFlags.SilentMode

                try:
                     opened_project = script_engine.projects.open(target_project_path, update_flags=update_mode)

                     if not opened_project:
                         print("ERROR: projects.open returned None for %s on attempt %d" % (target_project_path, attempt + 1))
                     else:
                         time.sleep(RETRY_DELAY)
                         recheck_primary = None
                         try:
                             recheck_primary = script_engine.projects.primary
                         except Exception as recheck_primary_err:
                             print("WARN: Error getting primary project after reopen: %s" % recheck_primary_err)
                             traceback.print_exc()

                         if recheck_primary:
                              recheck_path = ""
                              try:
                                  recheck_path = os.path.normcase(os.path.abspath(recheck_primary.path))
                              except Exception as recheck_path_err:
                                  print("WARN: Failed to get path after reopen: %s" % recheck_path_err)

                              if recheck_path == normalized_target_path:
                                   try:
                                       _ = len(recheck_primary.get_children(False))
                                       return recheck_primary
                                   except Exception as access_err_reopen:
                                        print("WARN: Reopened project (%s) basic access check failed: %s." % (normalized_target_path, access_err_reopen))
                              else:
                                   print("WARN: Different project is primary after reopening! Expected '%s', got '%s'." % (normalized_target_path, recheck_path))
                         else:
                               print("WARN: No primary project found after reopening attempt %d!" % (attempt+1))

                except Exception as open_err:
                     print("ERROR: Exception during projects.open call on attempt %d: %s" % (attempt + 1, open_err))
                     traceback.print_exc()
                     last_open_error = open_err
                     # If the open failed with a lock-conflict error, try to
                     # clean a stale lock and retry immediately (no sleep).
                     # The lock file may belong to a dead PID from a previous
                     # AB crash that didn't clean up properly.
                     if _is_lock_error(open_err):
                        cleaned = _try_clean_stale_lock(target_project_path)
                        if cleaned:
                            print("DEBUG: stale lock cleaned -- retrying open immediately on attempt %d." % (attempt + 1))
                            # Loop body will continue and try open again in
                            # next iteration; reset error so we don't surface
                            # a stale message on success.
                            last_open_error = None
                            continue

            except Exception as outer_open_err:
                 print("ERROR: Unexpected error during open setup/logic attempt %d: %s" % (attempt + 1, outer_open_err))
                 traceback.print_exc()

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)
        else:
             print("ERROR: Failed all ensure_project_open attempts for %s." % normalized_target_path)

    # If all retries fail, include the most recent open() error so callers can
    # distinguish "file locked", "file missing", "version mismatch", etc.
    # Emit a SCRIPT_ERROR_CODE marker so server.ts can surface a structured
    # code to the agent (ERR_PROJECT_LOCKED for lock issues, ERR_PROJECT_NOT_FOUND
    # otherwise).
    if last_open_error is not None:
        if _is_lock_error(last_open_error):
            print("SCRIPT_ERROR_CODE: ERR_PROJECT_LOCKED")
            lock_path = _find_lock_file(target_project_path)
            extra = ""
            if lock_path:
                extra = " Lock file: %s (still present; another AB instance may have it open)." % lock_path
            raise RuntimeError(
                "Failed to open project '%s' after %d attempts: lock conflict. %s Last error: %s: %s" %
                (target_project_path, MAX_RETRIES, extra, type(last_open_error).__name__, last_open_error)
            )
        if not os.path.exists(target_project_path):
            print("SCRIPT_ERROR_CODE: ERR_PROJECT_NOT_FOUND")
        raise RuntimeError(
            "Failed to ensure project '%s' is open and accessible after %d attempts. Last error: %s: %s" %
            (target_project_path, MAX_RETRIES, type(last_open_error).__name__, last_open_error)
        )
    raise RuntimeError(
        "Failed to ensure project '%s' is open and accessible after %d attempts." %
        (target_project_path, MAX_RETRIES)
    )
# --- End of function ---

# Placeholder for the project file path (must be set in scripts using this snippet)
PROJECT_FILE_PATH = "{PROJECT_FILE_PATH}"

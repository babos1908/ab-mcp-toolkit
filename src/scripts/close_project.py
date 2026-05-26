import sys, scriptengine as script_engine, os, traceback

# Path of the project the caller expects to close. Used only for diagnostics --
# the script closes whichever project is the current primary, regardless of
# whether its path matches. We define PROJECT_FILE_PATH directly here (instead
# of relying on the ensure_project_open helper) because close_project must NOT
# open a project as a side-effect of running.
PROJECT_FILE_PATH = "{PROJECT_FILE_PATH}"

# Whether to discard unsaved changes. 'true' / 'false' (case-insensitive).
FORCE_STR = "{FORCE}"

try:
    print("DEBUG: close_project script: Project='%s' Force='%s'" % (PROJECT_FILE_PATH, FORCE_STR))

    force = FORCE_STR.strip().lower() in ('true', '1', 'yes', 'on')

    # Locate the currently open primary project. Unlike most tools we do NOT
    # call ensure_project_open(): if nothing is open, this should be a no-op
    # rather than an error, and if a DIFFERENT project is open we still
    # close it (the caller's intent is "close whatever is current so I can
    # switch projects").
    pp = None
    try:
        pp = script_engine.projects.primary
    except Exception as primary_err:
        print("DEBUG: projects.primary access raised: %s" % primary_err)

    if pp is None:
        # Fallback to context manager / current selection if exposed
        for attr in ('current_project', 'active_project'):
            try:
                cand = getattr(script_engine.projects, attr, None)
                if cand:
                    pp = cand
                    print("DEBUG: Using projects.%s as the open project." % attr)
                    break
            except Exception:
                pass

    if pp is None:
        print("No project is currently open -- nothing to close.")
        print("SCRIPT_SUCCESS: close_project no-op (no primary project).")
        sys.exit(0)

    open_path = None
    try:
        if hasattr(pp, 'path'):
            open_path = pp.path
        elif hasattr(pp, 'get_path'):
            open_path = pp.get_path()
    except Exception:
        pass
    print("DEBUG: Currently-open primary project path: %s" % open_path)

    # Save unless caller passed force=true.
    if not force:
        try:
            if hasattr(pp, 'dirty') and not pp.dirty:
                print("DEBUG: Project is clean -- save skipped.")
            else:
                pp.save()
                print("DEBUG: Project saved before close.")
        except Exception as save_err:
            # Surface as a real error: silent save-failure could lose work.
            raise RuntimeError(
                "Failed to save project before close: %s. "
                "Pass force=true to discard unsaved changes." % save_err
            )
    else:
        print("DEBUG: force=true -- skipping save, unsaved changes will be discarded.")

    # Close. CODESYS V3 exposes ScriptObject.close() on the project object.
    if not hasattr(pp, 'close'):
        raise TypeError("Primary project object does not support close().")
    pp.close()
    print("DEBUG: pp.close() returned.")

    # Verify the runtime no longer reports an open primary.
    still_open = None
    try:
        still_open = script_engine.projects.primary
    except Exception:
        pass
    if still_open is not None:
        # Some builds keep a stale handle visible; not necessarily a failure,
        # but worth reporting so the caller can shutdown_codesys if needed.
        print("WARN: projects.primary still returns a project handle after close(): %s" % still_open)

    print("Project closed: %s" % (open_path or "(unknown path)"))
    print("SCRIPT_SUCCESS: Primary project closed.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error closing project '%s': %s\n%s" % (PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

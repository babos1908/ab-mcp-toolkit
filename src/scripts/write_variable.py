import sys, scriptengine as script_engine, os, traceback

VARIABLE_PATH = "{VARIABLE_PATH}"
VARIABLE_VALUE = "{VARIABLE_VALUE}"

try:
    print("DEBUG: write_variable script: Variable='%s', Value='%s', Project='%s'" % (VARIABLE_PATH, VARIABLE_VALUE, PROJECT_FILE_PATH))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not VARIABLE_PATH: print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT"); raise ValueError("Variable path empty.")

    online_app, target_app = ensure_online_connection(primary_project)
    app_name = getattr(target_app, 'get_name', lambda: "Unknown")()

    # UNVERIFIED on this build (2026-06-29, ported from upstream a063aad):
    # CODESYS V3 IScriptOnlineApplication (SP14+) does NOT expose a direct
    # write_value/write method -- variables are written by staging a value
    # with set_prepared_value(name, value_str) then committing with
    # force_prepared_values(). After commit the variable is FORCED at the
    # new value (held there until unforced) -- fine for BOOL/INT control
    # flags, but a variable the PLC program also writes (counters, FB
    # outputs) will freeze until set_unforce_value or a runtime restart.
    # Both calls routed through with_executor: they can hit "Stack empty"
    # from a pure IPC script the same way create_online_application does.
    # Falls back to the older write_value/write path for CODESYS builds
    # that expose neither prepared-value method (pre-SP14, unconfirmed).
    if hasattr(online_app, 'set_prepared_value') and hasattr(online_app, 'force_prepared_values'):
        try:
            with_executor(online_app.set_prepared_value, VARIABLE_PATH, VARIABLE_VALUE)
            with_executor(online_app.force_prepared_values)
            print("DEBUG: set_prepared_value + force_prepared_values succeeded.")
        except Exception as e:
            print("DEBUG: set_prepared_value/force_prepared_values failed: %s" % e)
            print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
            raise

    elif hasattr(online_app, 'write_value'):
        try:
            with_executor(online_app.write_value, VARIABLE_PATH, VARIABLE_VALUE)
            print("DEBUG: write_value succeeded (legacy path).")
        except Exception as e:
            print("DEBUG: write_value failed: %s" % e)
            print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
            raise

    elif hasattr(online_app, 'write'):
        try:
            with_executor(online_app.write, VARIABLE_PATH, VARIABLE_VALUE)
            print("DEBUG: write succeeded (legacy path).")
        except Exception as e:
            print("DEBUG: write failed: %s" % e)
            print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
            raise

    else:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise TypeError(
            "Online application has neither set_prepared_value/"
            "force_prepared_values nor write_value/write.")

    print("Variable: %s" % VARIABLE_PATH)
    print("Value Written: %s" % VARIABLE_VALUE)
    print("Application: %s" % app_name)
    print("SCRIPT_SUCCESS: Variable written successfully.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error writing variable '%s' in project %s: %s\n%s" % (VARIABLE_PATH, PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

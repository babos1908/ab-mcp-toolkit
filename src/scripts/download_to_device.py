import sys, scriptengine as script_engine, os, traceback

# MODE controls download strategy:
#   'auto' (default) - try online change, fall back to full download.
#   'online_change'  - online change only; raise if rejected (no fallback).
#   'full'           - skip online change, always full download.
MODE = "{MODE}"


def _login(online_app, mode):
    # All login() calls below route through safe_online_login() from
    # _text_utils.py to handle the V3.5 SP19 arity requirement
    # (login(bForceLogin: bool) vs legacy login() no-args). See its
    # docstring for the empirical history.
    if not hasattr(online_app, 'login'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise TypeError("Online application does not support login().")

    # All login attempts routed through with_executor (UNVERIFIED on this
    # build, see ensure_online_connection.py module docstring): login can
    # hit "Stack empty" from a pure IPC script the same way
    # create_online_application does.
    if mode == 'full':
        # Plain login - no online change attempt.
        with_executor(safe_online_login, online_app, None)
        print("DEBUG: Logged in (full download mode).")
        return

    # 'online_change' or 'auto' - both want TryOnlineChange first.
    if not hasattr(script_engine, 'OnlineChangeOption'):
        if mode == 'online_change':
            print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
            raise RuntimeError(
                "OnlineChangeOption not available in this CODESYS version; "
                "use mode='full' instead."
            )
        # 'auto': no OCO available, plain login is the only path.
        with_executor(safe_online_login, online_app, None)
        print("DEBUG: Logged in (no OnlineChangeOption available).")
        return

    try:
        with_executor(safe_online_login, online_app, script_engine.OnlineChangeOption.TryOnlineChange)
        print("DEBUG: Logged in with TryOnlineChange.")
    except Exception as e:
        if mode == 'online_change':
            print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
            raise RuntimeError(
                "Online change rejected: %s. The change is structural; "
                "use mode='full' or mode='auto' to allow a full download." % e
            )
        # 'auto': fall back to plain login.
        print("DEBUG: TryOnlineChange failed, falling back to full login: %s" % e)
        with_executor(safe_online_login, online_app, None)


try:
    print("DEBUG: download_to_device: Project='%s' Mode='%s'" % (PROJECT_FILE_PATH, MODE))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    online_app, target_app = ensure_online_connection(primary_project)
    app_name = getattr(target_app, 'get_name', lambda: "Unknown")()

    _login(online_app, MODE)

    print("DEBUG: Calling download()...")
    if hasattr(online_app, 'download'):
        with_executor(online_app.download)
        print("DEBUG: Download complete.")
    elif hasattr(online_app, 'create_boot_application'):
        with_executor(online_app.create_boot_application)
        print("DEBUG: Boot application created.")
    else:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise TypeError("Online application does not support download().")

    print("Downloaded to device for application: %s" % app_name)
    print("SCRIPT_SUCCESS: Application downloaded to device successfully.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error downloading to device for project %s: %s\n%s" % (
        PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

import traceback


def ensure_online_connection(primary_project):
    """Returns (online_application, target_app). Raises with an actionable
    message if create_online_application fails.

    Pre-conditions handled by the caller, NOT by this helper:
      * For a real PLC, the device must have a gateway/address configured
        (or the caller must pass ipAddress/gatewayName to connect_to_device,
        which sets it before this helper runs).
      * For simulator mode, the caller must invoke set_simulation_mode
        (enable=True) on the project first.

    Known limitation: the CODESYS scripting API can raise "Stack empty" from
    create_online_application even with simulation engaged, because the
    internal context stack is populated by IDE selection. If this happens,
    the user must click Online -> Login once in the IDE for the session
    (the project-level simulation state then sticks).
    """
    print("DEBUG: ensure_online_connection")

    target_app = primary_project.active_application
    if not target_app:
        for child in primary_project.get_children(True):
            if hasattr(child, 'is_application') and child.is_application:
                target_app = child
                break
    if not target_app:
        raise RuntimeError(
            "No active application found. Open the project in the IDE and "
            "right-click the Application node -> Set Active Application."
        )

    app_name = getattr(target_app, 'get_name', lambda: '?')()
    print("DEBUG: target_app: '%s'" % app_name)

    import scriptengine as se

    # Strategy 1: try the EXISTING online session reachable via the
    # application's online_application property. This avoids the
    # "Stack empty" issue on Standard edition entirely if the user has
    # already done a UI Login -- we reuse their session instead of
    # spawning a parallel one.
    for attr in ('online_application', 'current_online_application'):
        if hasattr(target_app, attr):
            try:
                existing = getattr(target_app, attr)
                if existing is not None:
                    print("DEBUG: reused existing online session via target_app.%s" % attr)
                    return existing, target_app
            except Exception as ge:
                print("DEBUG: target_app.%s raised: %s" % (attr, ge))

    # Strategy 2: standard create_online_application path.
    try:
        oa = se.online.create_online_application(target_app)
        if oa is not None:
            print("DEBUG: create_online_application OK")
            return oa, target_app
    except Exception as e:
        # Differentiate stack-empty from other failures so the agent can
        # decide whether the workaround applies.
        err_text = str(e)
        if 'stack' in err_text.lower() and 'empty' in err_text.lower():
            print("SCRIPT_ERROR_CODE: ERR_ONLINE_STACK_EMPTY")
        msg = (
            "create_online_application failed for '%s': %s. "
            "For simulation, call set_simulation_mode(enable=True) first; "
            "for a real PLC, ensure the gateway/address is set on the "
            "device (or pass ipAddress/gatewayName to connect_to_device). "
            "If simulation is engaged but this still raises 'Stack empty', "
            "click Online -> Login once in the IDE for this session (the "
            "MCP will then reuse your session via target_app.online_application "
            "on subsequent calls)."
        ) % (app_name, e)
        raise RuntimeError(msg)

    raise RuntimeError(
        "create_online_application returned None for '%s'." % app_name
    )

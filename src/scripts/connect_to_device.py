import sys, scriptengine as script_engine, os, traceback

IP_ADDRESS = "{IP_ADDRESS}"
GATEWAY_NAME = "{GATEWAY_NAME}"


def _resolve_gateway_guid(name):
    """Resolve a gateway display name (e.g. 'Gateway-1') to its GUID string.

    The scripting API exposes the Communication Manager under one of several
    names depending on AB version. Probe in order; raise with the candidates
    seen if no match.

    AB 2.9 / CODESYS V3.5 SP19 was observed (2026-05-26 by Stefano) to reject
    set_gateway_and_address('Gateway-1', ...) with
        Guid should contain 32 digits with 4 dashes
    because the underlying API expects a GUID, not the display name. This
    helper performs the lookup so callers can pass the friendly name.
    """
    target = (name or 'Gateway-1').strip()

    gateway_manager = None
    for path_chain in (
        ('communication_manager',),
        ('gateway_manager',),
        ('communicationmanager',),
    ):
        obj = script_engine
        ok = True
        for attr in path_chain:
            if not hasattr(obj, attr):
                ok = False
                break
            obj = getattr(obj, attr)
        if ok and obj is not None:
            gateway_manager = obj
            print("DEBUG: gateway manager: script_engine.%s" % '.'.join(path_chain))
            break

    if gateway_manager is None:
        # If no manager is present we have nothing to resolve. Return the
        # input verbatim so set_gateway_and_address can still be tried.
        print("WARN: No communication_manager / gateway_manager on script_engine; "
              "passing gateway name through unchanged.")
        return target

    candidates_seen = []
    gateways = None
    for attr in ('gateways', 'all_gateways'):
        if hasattr(gateway_manager, attr):
            try:
                gateways = getattr(gateway_manager, attr)
                if callable(gateways):
                    gateways = gateways()
                break
            except Exception as ge:
                print("DEBUG: %s.%s raised: %s" % (gateway_manager, attr, ge))

    if gateways is None:
        print("WARN: gateway manager exposes neither .gateways nor .all_gateways.")
        return target

    for gw in gateways:
        gw_name = None
        gw_guid = None
        for nattr in ('get_name', 'name'):
            if hasattr(gw, nattr):
                try:
                    val = getattr(gw, nattr)
                    gw_name = val() if callable(val) else val
                except Exception:
                    pass
                break
        for gattr in ('guid', 'id', 'gateway_guid'):
            if hasattr(gw, gattr):
                try:
                    gw_guid = getattr(gw, gattr)
                except Exception:
                    pass
                break
        candidates_seen.append({'name': str(gw_name), 'guid': str(gw_guid)})
        if gw_name is not None and str(gw_name).strip().lower() == target.lower():
            print("DEBUG: gateway '%s' resolved to GUID %s" % (target, gw_guid))
            return str(gw_guid) if gw_guid else target

    # No match. Return the original name; the caller will get a clearer error
    # from set_gateway_and_address if the runtime rejects it.
    print("WARN: gateway '%s' not in repository. Candidates: %s" % (target, candidates_seen))
    return target


def _prime_online_session(target_app=None):
    """Populate the IronPython online-context stack BEFORE
    create_online_application is called.

    AB 2.9 Standard surfaces a 'Stack empty' error from
    se.online.create_online_application when the IDE context stack hasn't
    been touched in this scripting session. Empirically clicking
    'Online > Login' once in the UI fixes it. This helper tries three
    strategies in order, each best-effort:

      1. target_app.online_application (proprietà che ritorna la sessione
         online corrente se presente). If this returns a non-null object,
         we already have the priming we need -- the caller can re-use it.
         Returns the object if found.
      2. system.commands.find_commands('Online.*') -- mere PRESENCE check
         (not execute) of read-only Online commands may populate the
         context on some builds.
      3. system.commands.find_commands('Online.OnlineConfigMode') +
         execute() -- last resort, attempts to drive the menu command
         that would normally come from a UI click. May fail silently
         on Standard (the command may exist but be gated).

    Returns the online_application handle if strategy 1 found one;
    otherwise None. The caller then proceeds to
    create_online_application(target_app) as normal.
    """
    # Strategy 1: target_app.online_application
    if target_app is not None:
        for attr in ('online_application', 'current_online_application'):
            if hasattr(target_app, attr):
                try:
                    v = getattr(target_app, attr)
                    if v is not None:
                        print("DEBUG: prime: target_app.%s returned an existing online session." % attr)
                        return v
                except Exception as ge:
                    print("DEBUG: prime: target_app.%s access raised: %s" % (attr, ge))

    cmd_mgr = getattr(getattr(script_engine, 'system', None), 'commands', None)
    if cmd_mgr is None:
        print("DEBUG: system.commands not exposed; skipping further priming.")
        return None

    find_fn = None
    for attr in ('find_commands', 'find', 'get_commands'):
        if hasattr(cmd_mgr, attr):
            find_fn = getattr(cmd_mgr, attr)
            break
    if find_fn is None:
        print("DEBUG: command manager has no find_commands-style accessor.")
        return None

    # Strategy 2: presence check (some builds populate context from this alone)
    for cmd_name in ('Online.OnlineConfigMode', 'Online.OnlineSelected', 'View.OnlineActions'):
        try:
            cmds = find_fn(cmd_name)
            if cmds:
                print("DEBUG: prime: '%s' presence detected (count=%d)." % (cmd_name, len(cmds)))
        except Exception as ce:
            print("DEBUG: prime: find_fn('%s') raised: %s" % (cmd_name, ce))

    # Strategy 3: try actually executing a Read-only Online command
    # (OnlineConfigMode is typically a TOGGLE check, not a destructive op).
    # On Premium / dev builds this works; on Standard it may be gated.
    try:
        cmds = find_fn('Online.OnlineConfigMode')
        if cmds:
            try:
                cmd = cmds[0]
                if hasattr(cmd, 'execute'):
                    cmd.execute()
                    print("DEBUG: prime: Online.OnlineConfigMode.execute() invoked.")
            except Exception as exec_err:
                print("DEBUG: prime: OnlineConfigMode.execute() failed (expected on some builds): %s" % exec_err)
    except Exception:
        pass
    return None


try:
    print("DEBUG: connect_to_device: Project='%s' IP='%s' Gateway='%s'" % (
        PROJECT_FILE_PATH, IP_ADDRESS, GATEWAY_NAME))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    # If the caller passed an IP, set gateway+address on the device before
    # creating the online application. set_gateway_and_address rejects an
    # empty address string, so only invoke it when an IP was provided.
    if IP_ADDRESS:
        gw_input = GATEWAY_NAME or "Gateway-1"
        # Resolve display name -> GUID (Gap 8). If resolution fails, fall back
        # to passing the name unchanged; the error surfaced will be more
        # actionable than the generic "Guid should contain..." message.
        gw_guid_or_name = _resolve_gateway_guid(gw_input)
        device = None
        for child in primary_project.get_children(True):
            if hasattr(child, 'set_gateway_and_address'):
                device = child
                break
        if device is None:
            raise RuntimeError(
                "No device in the project supports set_gateway_and_address."
            )
        dev_name = getattr(device, 'get_name', lambda: '?')()
        print("DEBUG: Setting gateway='%s' (resolved='%s') address='%s' on device '%s'" % (
            gw_input, gw_guid_or_name, IP_ADDRESS, dev_name))
        try:
            device.set_gateway_and_address(gw_guid_or_name, IP_ADDRESS)
        except Exception as sga_err:
            # If we resolved to a GUID, this should work; if it failed with
            # the GUID-format error, retry with the original name as a fallback
            # (some builds want the friendly name).
            err_text = str(sga_err)
            if 'Guid' in err_text and gw_guid_or_name != gw_input:
                print("DEBUG: set_gateway_and_address(GUID) raised %s; retrying with name '%s'" % (err_text, gw_input))
                device.set_gateway_and_address(gw_input, IP_ADDRESS)
            else:
                raise

    # Gap 9: try to prime the online-context stack BEFORE the first call to
    # create_online_application. Best-effort; if priming fails, the existing
    # ensure_online_connection error message still guides the user to click
    # Online -> Login once.
    try:
        _prime_online_session()
    except Exception as prime_err:
        print("DEBUG: prime_online_session raised (ignored): %s" % prime_err)

    online_app, target_app = ensure_online_connection(primary_project)
    app_name = getattr(target_app, 'get_name', lambda: "Unknown")()

    print("DEBUG: Calling login() on online application...")
    if hasattr(online_app, 'login'):
        if hasattr(script_engine, 'OnlineChangeOption'):
            try:
                online_app.login(script_engine.OnlineChangeOption.TryOnlineChange)
                print("DEBUG: Logged in with TryOnlineChange option.")
            except Exception as e:
                print("DEBUG: TryOnlineChange failed, trying plain login: %s" % e)
                online_app.login()
        else:
            online_app.login()
        print("DEBUG: Login successful.")
    else:
        raise TypeError("Online application does not support login().")

    state = "connected"
    if hasattr(online_app, 'application_state'):
        try:
            state = str(online_app.application_state)
        except Exception:
            pass

    print("Connected to device for application: %s" % app_name)
    print("Application State: %s" % state)
    print("SCRIPT_SUCCESS: Connected to device successfully.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error connecting to device for project %s: %s\n%s" % (
        PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

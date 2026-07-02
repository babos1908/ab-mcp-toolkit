import traceback

# ensure_online_connection.py
# ----------------------------
# Shared helper for every online (logged-in) CODESYS V3 operation. Exports:
#
#   - ensure_online_connection(primary_project) -> (online_application, target_app)
#   - with_executor(fn, *args) -> fn's return value
#   - resolve_device_address(primary_project) -> resolved node-address string or None
#
# UNVERIFIED ON AB 2.9 / CODESYS V3.5 SP19 (2026-06-29): the ExecuteSource
# fallback + with_executor mechanism below is PORTED from
# luke-harriman/Codesys-MCP commit a063aad (fix(online): unblock real-PLC
# online tools on V3 SP14+), verified there against CODESYS V3 SP16 Patch 5
# on an ifm AE3100 IIoT Controller -- a different vendor and service pack
# than ours. Their root-cause diagnosis matches ours independently (both
# projects separately traced "Stack empty" to the same IDE-internal
# _executionStack / Executing-event gap), which is why this is worth
# integrating -- but it has NOT been exercised end-to-end against a real
# AB 2.9 AC500 PLC yet. Needs an on-PLC test before the "online is dead"
# framing in the skill/docs is revised. Until verified, treat any success
# from the ExecuteSource path as provisional and any failure as expected.

# Stable diagnostic history (kept from the pre-2026-06-29 version):
#   - AB 2.9 SP19, Standard AND Premium, edition-independent: direct
#     create_online_application() raises "Stack empty" from ANY scripting
#     context (--runscript or attach mode). Clicking Online->Login in the
#     IDE does NOT make the session reusable from script (no
#     online_application accessor exists on target_app/project/device/
#     se.online -- probed exhaustively 2026-05-27/05-30).


def _get_online_executor():
    """Resolve scriptengine.online._executor via .NET reflection.

    Returns the executor object (exposes ExecuteSource) or None if
    reflection fails (field absent/renamed on this CODESYS build, or the
    clr/System.Reflection imports aren't available). Safe to call
    repeatedly.
    """
    try:
        import scriptengine as se
        import clr
        from System.Reflection import BindingFlags
        if not hasattr(se, 'online'):
            return None
        flags = (BindingFlags.Public
                 | BindingFlags.NonPublic
                 | BindingFlags.Instance)
        field = clr.GetClrType(type(se.online)).GetField('_executor', flags)
        if field is None:
            return None
        executor = field.GetValue(se.online)
        if not hasattr(executor, 'ExecuteSource'):
            return None
        return executor
    except Exception:
        return None


def with_executor(fn, *args):
    """Invoke fn(*args) inside a CODESYS scripting executor frame.

    Wrap every call into `scriptengine.online` or an OnlineApplication
    returned by ensure_online_connection with this:

        with_executor(online_app.start)
        value = with_executor(online_app.read_value, 'GVL.x')
        with_executor(safe_online_login, online_app, change_option)

    The executor's ExecuteSource fires the Executing/Executed lifecycle
    events that populate the IDE-internal _executionStack, which a plain
    IPC-driven call bypasses (that gap is the entire "Stack empty" bug).
    If reflection into _executor is unavailable on this CODESYS build,
    falls back to calling fn(*args) directly -- same behavior as before
    this helper existed.

    Positional args ONLY (no kwargs) -- the inner exec frame marshals
    fn/args through module globals, which only supports a plain tuple.
    Re-raises whatever exception the wrapped call raised.
    """
    executor = _get_online_executor()
    if executor is None:
        return fn(*args)

    import __builtin__ as _b
    _b._mcp_online_fn = fn
    _b._mcp_online_args = args
    _b._mcp_online_result = None
    _b._mcp_online_exc = None
    try:
        inner = (
            "import __builtin__ as _b\n"
            "try:\n"
            "    _b._mcp_online_result = _b._mcp_online_fn(*_b._mcp_online_args)\n"
            "except BaseException as _e:\n"
            "    _b._mcp_online_exc = _e\n"
        )
        executor.ExecuteSource(inner)
        if _b._mcp_online_exc is not None:
            raise _b._mcp_online_exc
        return _b._mcp_online_result
    finally:
        for _n in ('_mcp_online_fn', '_mcp_online_args',
                   '_mcp_online_result', '_mcp_online_exc'):
            try:
                delattr(_b, _n)
            except Exception:
                pass


def resolve_device_address(primary_project):
    """Re-set the project device's gateway address from the raw IP form to
    the gateway-scan node form CODESYS V3 actually routes logins by (e.g.
    '0301.B0F7'). Complements (does not replace) connect_to_device.py's own
    _resolve_gateway_guid, which resolves the GATEWAY NAME to a GUID before
    set_gateway_and_address is called; this runs AFTER that, converting the
    ADDRESS itself. Best-effort -- returns the resolved address on success,
    or None if any step is unavailable (no device, no gateway, scan
    failed/empty). On None the device address is left as the caller set it,
    so this is safe to call speculatively.
    """
    import scriptengine as se

    device = None
    for child in primary_project.get_children(True):
        if (hasattr(child, 'set_gateway_and_address')
                and hasattr(child, 'get_gateway')):
            device = child
            break
    if device is None:
        return None

    try:
        gw_guid = device.get_gateway()
    except Exception as e:
        print("DEBUG: resolve_device_address: get_gateway raised: %s" % e)
        return None
    if gw_guid is None:
        return None

    if not hasattr(se, 'online'):
        return None
    target_gw = None
    try:
        for g in se.online.gateways:
            try:
                if g.guid == gw_guid:
                    target_gw = g
                    break
            except Exception:
                continue
    except Exception as e:
        print("DEBUG: resolve_device_address: gateway iteration raised: %s" % e)
        return None
    if target_gw is None:
        return None

    try:
        nodes = list(target_gw.perform_network_scan())
    except Exception as e:
        print("DEBUG: resolve_device_address: scan failed: %s" % e)
        return None
    if not nodes:
        print("DEBUG: resolve_device_address: scan returned 0 nodes")
        return None

    target = None
    if len(nodes) == 1:
        target = nodes[0]
    else:
        type_hint = ''
        for attr in ('get_device_identification', 'get_device_id'):
            if hasattr(device, attr):
                try:
                    info = getattr(device, attr)()
                    type_hint = str(info).lower()
                    break
                except Exception:
                    continue
        if type_hint:
            for n in nodes:
                dn = (getattr(n, 'device_name', '') or '').lower()
                if dn and dn in type_hint:
                    target = n
                    break
        if target is None:
            target = nodes[0]
            print("DEBUG: resolve_device_address: %d nodes; no name match, "
                  "using first ('%s')" % (len(nodes), getattr(target, 'device_name', '?')))

    addr = getattr(target, 'address', None)
    if not addr:
        return None

    try:
        device.set_gateway_and_address(target_gw.name, addr)
        print("DEBUG: resolve_device_address: '%s' -> node '%s'" % (
            getattr(target, 'device_name', '?'), addr))
        return addr
    except Exception as e:
        print("DEBUG: resolve_device_address: set_gateway_and_address failed: %s" % e)
        return None


def ensure_online_connection(primary_project):
    """Returns (online_application, target_app). Raises with an actionable
    message if create_online_application fails via every strategy tried.

    Strategy order:
      1. Reuse an existing online session already exposed somewhere on the
         project tree (target_app/project/device ancestors, se.online
         collections). Cheap, and sidesteps Stack empty entirely if a UI
         Login session is somehow reachable. Empirically 2026-05-27/05-30:
         this has never found an accessor on AB 2.9 SP19 -- kept because it
         is free and harmless, not because it is expected to hit.
      2. Direct se.online.create_online_application(target_app) call.
      3. UNVERIFIED (2026-06-29): ExecuteSource fallback via with_executor
         when strategy 2 raises "Stack empty". Ported from
         luke-harriman/Codesys-MCP a063aad; verified there on V3 SP16 (ifm),
         not on our SP19 (ABB AC500). If reflection into scriptengine.
         online._executor fails on this build, this strategy is skipped and
         the original actionable error is raised.
    """
    print("DEBUG: ensure_online_connection")

    target_app = primary_project.active_application
    if not target_app:
        for child in primary_project.get_children(True):
            if hasattr(child, 'is_application') and child.is_application:
                target_app = child
                break
    if not target_app:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError(
            "No active application found. Open the project in the IDE and "
            "right-click the Application node -> Set Active Application."
        )

    app_name = getattr(target_app, 'get_name', lambda: '?')()
    print("DEBUG: target_app: '%s'" % app_name)

    # Make active_application authoritative. Some "Stack empty" paths trace
    # back to project/active-app disagreement; idempotent when already right.
    try:
        primary_project.active_application = target_app
    except Exception as aa_err:
        print("DEBUG: could not set active_application (ignored): %s" % aa_err)

    import scriptengine as se

    # --- Strategy 1: reuse an existing online session -----------------
    reuse_attempts = []
    candidate_hosts = [('target_app', target_app), ('primary_project', primary_project)]
    cur = target_app
    for _ in range(4):
        parent = None
        for pattr in ('parent', 'parent_object'):
            if hasattr(cur, pattr):
                try:
                    p = getattr(cur, pattr)
                    if p is not None:
                        parent = p
                        break
                except Exception:
                    pass
        if parent is None:
            break
        candidate_hosts.append(('ancestor_%s' % getattr(parent, 'get_name', lambda: type(parent).__name__)(), parent))
        cur = parent

    online_attrs = ('online_application', 'current_online_application', 'active_online_application',
                    'online', 'current_online', 'active_online')

    for host_label, host in candidate_hosts:
        for attr in online_attrs:
            if not hasattr(host, attr):
                continue
            try:
                existing = getattr(host, attr)
            except Exception as ge:
                reuse_attempts.append('%s.%s raised: %s' % (host_label, attr, ge))
                continue
            if existing is None:
                reuse_attempts.append('%s.%s = None' % (host_label, attr))
                continue
            picked = existing
            try:
                if hasattr(existing, '__iter__') and not hasattr(existing, 'login'):
                    for cand in existing:
                        if cand is not None:
                            picked = cand
                            break
            except Exception:
                pass
            if picked is not None and (hasattr(picked, 'login') or hasattr(picked, 'application_state')):
                print("DEBUG: reused existing online session via %s.%s" % (host_label, attr))
                return picked, target_app
            reuse_attempts.append('%s.%s = %r (no login/state attr)' % (host_label, attr, type(picked).__name__))

    if hasattr(se, 'online'):
        for attr in ('online_applications', 'all_online_applications', 'current'):
            if hasattr(se.online, attr):
                try:
                    coll = getattr(se.online, attr)
                    if callable(coll):
                        coll = coll()
                    if coll is not None:
                        try:
                            for cand in coll:
                                if cand is not None and (hasattr(cand, 'login') or hasattr(cand, 'application_state')):
                                    print("DEBUG: reused existing online session via se.online.%s" % attr)
                                    return cand, target_app
                        except TypeError:
                            if hasattr(coll, 'login') or hasattr(coll, 'application_state'):
                                print("DEBUG: reused existing online session via se.online.%s (singleton)" % attr)
                                return coll, target_app
                except Exception as ge:
                    reuse_attempts.append('se.online.%s raised: %s' % (attr, ge))

    if reuse_attempts:
        print("DEBUG: online_application reuse attempts (none yielded a session):")
        for a in reuse_attempts:
            print("DEBUG:   - %s" % a)
    else:
        host_attrs_dump = []
        for host_label, host in candidate_hosts:
            probe = [a for a in online_attrs if hasattr(host, a)]
            host_attrs_dump.append('%s present=%s' % (host_label, probe))
        print("DEBUG: no online_application accessor exposed on any host. Probed: %s" % '; '.join(host_attrs_dump))

    # --- Strategy 2: direct create_online_application ------------------
    stack_empty_err = None
    try:
        oa = se.online.create_online_application(target_app)
        if oa is not None:
            print("DEBUG: create_online_application OK (direct)")
            return oa, target_app
    except Exception as direct_err:
        err_text = str(direct_err)
        if 'stack' not in err_text.lower() or 'empty' not in err_text.lower():
            # Genuine error (auth/network/version/...), not the Stack-empty
            # bug -- surface as-is, no point trying the executor fallback.
            print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
            raise RuntimeError(
                "create_online_application failed for '%s': %s. For "
                "simulation, call set_simulation_mode(enable=True) first; "
                "for a real PLC, ensure the gateway/address is set on the "
                "device." % (app_name, direct_err))
        stack_empty_err = direct_err
        print("DEBUG: Stack empty on direct call; trying ExecuteSource fallback "
              "(UNVERIFIED on this CODESYS build -- see module docstring)")

    # --- Strategy 3: ExecuteSource fallback (UNVERIFIED on SP19) -------
    executor = _get_online_executor()
    if executor is None:
        print("SCRIPT_ERROR_CODE: ERR_ONLINE_STACK_EMPTY")
        raise RuntimeError(
            "create_online_application failed for '%s': %s. "
            "scriptengine.online._executor could not be resolved via "
            "reflection on this CODESYS build (field absent/renamed), so "
            "the ExecuteSource fallback is unavailable. There is no further "
            "scripting workaround known for this build: drive online ops "
            "(Login/Download/Watch/read/write) from the AB UI, or "
            "out-of-band via the PLC's own protocol (MQTT/OPC UA/HTTP)."
            % (app_name, stack_empty_err))

    try:
        oa = with_executor(se.online.create_online_application, target_app)
    except Exception as fallback_err:
        print("SCRIPT_ERROR_CODE: ERR_ONLINE_STACK_EMPTY")
        raise RuntimeError(
            "create_online_application failed for '%s' both directly (%s) "
            "and via the ExecuteSource fallback (%s). Manual workaround: "
            "click Online -> Login once in the IDE for this session, or "
            "drive online ops out-of-band via the PLC's own protocol "
            "(MQTT/OPC UA/HTTP)." % (app_name, stack_empty_err, fallback_err))

    if oa is None:
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        raise RuntimeError(
            "create_online_application returned None for '%s' even via the "
            "ExecuteSource fallback." % app_name)

    print("DEBUG: create_online_application OK (via ExecuteSource fallback -- "
          "UNVERIFIED path, please report success/failure)")
    return oa, target_app

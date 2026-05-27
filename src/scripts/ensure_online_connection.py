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

    # Strategy 1: try the EXISTING online session reachable via a property
    # exposed somewhere on the project tree. This avoids the "Stack empty"
    # issue on Standard edition entirely if the user has already done a UI
    # Login -- we reuse their session instead of spawning a parallel one.
    #
    # Empirical 2026-05-27 (NEXO feedback): target_app.online_application
    # is NOT exposed on AB 2.9 SP19 -- hasattr(target_app, 'online_application')
    # returns False, so the loop silently skipped to create_online_application
    # and hit ERR_ONLINE_STACK_EMPTY. The live online_application is plausibly
    # owned by the Device node or by a global se.online collection. Probe
    # several candidate accessors before giving up.
    reuse_attempts = []  # diagnostic: which paths we tried and what they returned
    candidate_hosts = []
    candidate_hosts.append(('target_app', target_app))
    candidate_hosts.append(('primary_project', primary_project))
    # The Application node's parent is typically a Plc Logic node whose
    # parent is the Device. Walk up and add each ancestor.
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
            # If the accessor returns a collection (multiple online apps in
            # a multi-PLC project), pick the first non-None.
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

    # Also try the global se.online collection if exposed
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
                            # single object, not iterable
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
        # No accessor matched on any host -- dump the surfaces we probed
        # so the next iteration knows where to look.
        host_attrs_dump = []
        for host_label, host in candidate_hosts:
            probe = [a for a in online_attrs if hasattr(host, a)]
            host_attrs_dump.append('%s present=%s' % (host_label, probe))
        print("DEBUG: no online_application accessor exposed on any host. Probed: %s" % '; '.join(host_attrs_dump))

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

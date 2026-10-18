import sys, scriptengine as script_engine, os, traceback

TASK_NAME = "{TASK_NAME}"
# Empty string sentinel = do not touch this knob. Numeric values are passed
# as their decimal string representation; we parse here.
CYCLE_TIME_MS_STR       = "{CYCLE_TIME_MS}"
WATCHDOG_TIME_MS_STR    = "{WATCHDOG_TIME_MS}"
WATCHDOG_ENABLED_STR    = "{WATCHDOG_ENABLED}"
WATCHDOG_SENSITIVITY_STR = "{WATCHDOG_SENSITIVITY}"
PRIORITY_STR            = "{PRIORITY}"
STACK_SIZE_BYTES_STR    = "{STACK_SIZE_BYTES}"
# create_task mode (all through opt_placeholder: an older server leaves the
# literal placeholders, which must read as "not provided" = old behaviour).
CREATE_TASK_STR         = "{CREATE_TASK}"   # 'true' = create the task; fail if it exists
TASK_KIND_STR           = "{TASK_KIND}"     # cyclic | freewheeling | event | status | externalevent
ADD_POUS_STR            = "{ADD_POUS}"      # newline/comma separated programs to call

def _maybe_int(s):
    s = opt_placeholder(s)
    if s is None or s == "":
        return None
    try:
        return int(s)
    except Exception:
        return None

def _maybe_bool(s):
    """Strict: only recognised boolean tokens count. Anything unrecognised is
    'not provided' (None), never a silent False -- for a knob that arms or
    disarms a watchdog, guessing toward 'disabled' is the dangerous direction.
    opt_placeholder additionally catches an unsubstituted "{NAME}" arriving
    from an older tool handler."""
    s = opt_placeholder(s)
    if s is None or s == "":
        return None
    txt = unicode(s).strip().lower()
    if txt in (u'true', u'1', u'yes', u'on'):
        return True
    if txt in (u'false', u'0', u'no', u'off'):
        return False
    return None

def _ms_to_timespan(ms):
    """Construct a System.TimeSpan from milliseconds. IronPython gives us .NET
    types via the CLR; we use TimeSpan.FromMilliseconds when available."""
    try:
        import System
        return System.TimeSpan.FromMilliseconds(float(ms))
    except Exception:
        # If System is not available, return the raw float -- CODESYS may
        # accept the implicit conversion, or fail with a helpful error.
        return float(ms)

# IEC TIME parsing (iec_time_literal_to_ms / time_value_to_ms) lives in
# _text_utils, shared with get_task_configuration.

def _time_value_for(obj, attr, ms):
    """Pick the representation a time-valued attribute actually wants.

    Empirical on AC500 V3 (2026-06-12, PIOPO brief): `task.interval` is a
    PLAIN STRING holding an IEC TIME literal ('t#10ms'), with a sibling
    `interval_unit` ('ms'). Assigning a System.TimeSpan there 'succeeds'
    (the string property accepts the coerced ToString) but the task keeps
    its old value -- a silent no-op. So: if the current value is a string,
    write an IEC literal; otherwise use the TimeSpan path for builds whose
    attribute is a real TimeSpan.

    2026-10-12: the watchdog time has the same shape and was still on the
    unconditional-TimeSpan path, so watchdogTimeMs was a silent no-op that
    reported success -- a bench program ran with a 20ms watchdog and the PLC
    threw an exception on the first blocking call. Hence this helper is now
    shared by every time-valued write in this script.
    """
    try:
        cur = getattr(obj, attr)
    except Exception:
        cur = None
    if isinstance(cur, (str, unicode)):
        return u't#%dms' % int(ms)
    return _ms_to_timespan(ms)

def _write_time_verified(get_owner, attr, ms, field_label):
    """Write a time value and PROVE it stuck.

    `get_owner` is a callable returning the object holding `attr`; it is
    re-invoked for the read-back so a stale proxy cannot mask a failed write
    (some CODESYS wrappers hand out a fresh object per property access).

    Comparison is done in milliseconds, so it holds whether the attribute is
    a TimeSpan, an IEC literal or a numeric. An unreadable read-back counts
    as a FAILURE: if the value cannot be proven, success must not be claimed.

    Returns (ok, detail_dict).
    """
    owner = get_owner()
    if owner is None:
        return False, {'field': field_label, 'reason': 'owner_not_found'}
    try:
        new_val = _time_value_for(owner, attr, ms)
        setattr(owner, attr, new_val)
    except Exception as e:
        return False, {'field': field_label, 'attribute': attr, 'error': str(e)}

    owner2 = get_owner()
    readback = None
    try:
        readback = getattr(owner2, attr) if owner2 is not None else None
    except Exception:
        pass
    rb_ms = time_value_to_ms(readback)
    try:
        rb_str = unicode(readback) if readback is not None else None
    except Exception:
        rb_str = None

    if rb_ms is None:
        return False, {'field': field_label, 'attribute': attr,
                       'error': 'write could not be verified: read back %r '
                                '(unparseable as a time value)' % rb_str}
    if abs(rb_ms - float(ms)) > 0.5:
        return False, {'field': field_label, 'attribute': attr,
                       'error': 'write did not stick: wrote %s, read back %s '
                                '(%.0f ms)' % (unicode(new_val), rb_str, rb_ms)}
    return True, {'field': field_label, 'attribute': attr, 'value': ms,
                  'written': unicode(new_val), 'readback_ms': rb_ms}

def _write_scalar_verified(get_owner, attr, value, field_label, coerce):
    """Write a non-time scalar (bool/int) and read it back. Same contract as
    _write_time_verified: unverifiable means failed.

    Live 2026-10-17 (AB 2.9 SP19, AC500 V3): task.priority and
    watchdog.sensitivity are STRING properties ('14', '1'); assigning an int
    raises "TypeError: expected str, got int", so priority/sensitivity writes
    always failed. An int that is refused with a TypeError is retried as its
    decimal string; the read-back still compares through `coerce`."""
    owner = get_owner()
    if owner is None:
        return False, {'field': field_label, 'reason': 'owner_not_found'}
    try:
        setattr(owner, attr, value)
    except TypeError as te:
        if isinstance(value, bool) or not isinstance(value, (int, long)):
            return False, {'field': field_label, 'attribute': attr, 'error': str(te)}
        try:
            setattr(owner, attr, unicode(value))
        except Exception as e:
            return False, {'field': field_label, 'attribute': attr, 'error': str(e)}
    except Exception as e:
        return False, {'field': field_label, 'attribute': attr, 'error': str(e)}
    owner2 = get_owner()
    readback = None
    try:
        readback = getattr(owner2, attr) if owner2 is not None else None
    except Exception:
        pass
    try:
        rb = coerce(readback)
    except Exception:
        rb = None
    if rb is None or rb != value:
        return False, {'field': field_label, 'attribute': attr,
                       'error': 'write did not stick: wrote %r, read back %r'
                                % (value, readback)}
    return True, {'field': field_label, 'attribute': attr, 'value': value}

try:
    print("DEBUG: set_task_parameter: Project='%s' Task='%s' "
          "cycleMs=%s watchdogMs=%s watchdogEnabled=%s watchdogSens=%s "
          "priority=%s stackBytes=%s" % (
        PROJECT_FILE_PATH, TASK_NAME,
        CYCLE_TIME_MS_STR, WATCHDOG_TIME_MS_STR, WATCHDOG_ENABLED_STR,
        WATCHDOG_SENSITIVITY_STR, PRIORITY_STR, STACK_SIZE_BYTES_STR))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not TASK_NAME:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("Task name empty.")

    cycle_ms    = _maybe_int(CYCLE_TIME_MS_STR)
    watchdog_ms = _maybe_int(WATCHDOG_TIME_MS_STR)
    watchdog_on = _maybe_bool(WATCHDOG_ENABLED_STR)
    watchdog_sens = _maybe_int(WATCHDOG_SENSITIVITY_STR)
    priority    = _maybe_int(PRIORITY_STR)
    stack_bytes = _maybe_int(STACK_SIZE_BYTES_STR)
    create_task = _maybe_bool(CREATE_TASK_STR) is True
    task_kind = (_to_unicode(opt_placeholder(TASK_KIND_STR, 'TASK_KIND')) or u'').strip().lower()
    add_pous = []
    for part in _to_unicode(opt_placeholder(ADD_POUS_STR, 'ADD_POUS') or u'').replace(u',', u'\n').split(u'\n'):
        if part.strip() and part.strip() not in add_pous:
            add_pous.append(part.strip())

    _KINDS = {u'cyclic': 'Cyclic', u'freewheeling': 'Freewheeling', u'event': 'Event',
              u'status': 'Status', u'externalevent': 'ExternalEvent'}
    if task_kind and task_kind not in _KINDS:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("Unknown task kind '%s' (use: %s)." % (task_kind, ', '.join(sorted(_KINDS))))

    if (cycle_ms is None and watchdog_ms is None and watchdog_on is None
            and watchdog_sens is None and priority is None and stack_bytes is None
            and not create_task and not task_kind and not add_pous):
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError(
            "At least one of cycleTimeMs / watchdogTimeMs / watchdogEnabled / "
            "watchdogSensitivity / priority / stackSizeBytes / kind / addPous must be provided.")

    # Locate the named Task. Walk every Task Configuration node, then look for
    # a child matching TASK_NAME (case-insensitive). Same normalization as
    # get_task_configuration: the internal node name is "TaskConfiguration"
    # (one word, no space) while the AB UI displays it with a space.
    def _is_task_config_name(name):
        if not name:
            return False
        norm = name.strip().lower().replace(' ', '').replace('_', '')
        return norm == 'taskconfiguration'

    task_obj = None
    task_configs = []

    def _walk_for_tc(node, depth, max_depth=10):
        if depth > max_depth:
            return
        try:
            children = node.get_children(False)
        except Exception:
            return
        for child in children:
            cname = getattr(child, 'get_name', lambda: '')()
            if _is_task_config_name(cname):
                task_configs.append(child)
            _walk_for_tc(child, depth + 1, max_depth)

    try:
        _walk_for_tc(primary_project, 0)
    except Exception:
        pass

    if not task_configs:
        for probe_name in ('TaskConfiguration', 'Task Configuration'):
            try:
                found = primary_project.find(probe_name, True)
                if found:
                    for f in found:
                        if _is_task_config_name(getattr(f, 'get_name', lambda: '')()):
                            task_configs.append(f)
                    if task_configs:
                        break
            except Exception:
                pass

    for tc in task_configs:
        try:
            for child in tc.get_children(False):
                cn = getattr(child, 'get_name', lambda: '')()
                if cn and cn.lower() == TASK_NAME.strip().lower():
                    task_obj = child
                    break
        except Exception:
            pass
        if task_obj is not None:
            break

    created_in = None
    if create_task:
        if task_obj is not None:
            print("SCRIPT_ERROR_CODE: ERR_OBJECT_EXISTS")
            raise RuntimeError(
                "Task '%s' already exists; use set_task_parameter to change it." % TASK_NAME)
        # Task Configuration of the ACTIVE application first (a project can
        # hold several applications); create one if the application has none.
        target_tc = None
        active_app = None
        try:
            active_app = primary_project.active_application
        except Exception:
            active_app = None
        if active_app is not None:
            try:
                for c in active_app.get_children(False):
                    if getattr(c, 'is_task_configuration', False) or _is_task_config_name(
                            getattr(c, 'get_name', lambda: '')()):
                        target_tc = c
                        break
            except Exception:
                pass
            if target_tc is None and hasattr(active_app, 'create_task_configuration'):
                target_tc = active_app.create_task_configuration()
                print("DEBUG: created a Task Configuration under the active application.")
        if target_tc is None and len(task_configs) == 1:
            target_tc = task_configs[0]
        if target_tc is None:
            print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
            raise RuntimeError(
                "No Task Configuration to create '%s' in (%d found, none under the "
                "active application)." % (TASK_NAME, len(task_configs)))
        if not hasattr(target_tc, 'create_task'):
            print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
            raise RuntimeError("Task Configuration exposes no create_task() on this build.")
        task_obj = target_tc.create_task(TASK_NAME)
        if task_obj is None:
            print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
            raise RuntimeError("create_task('%s') returned nothing." % TASK_NAME)
        created_in = _to_unicode(getattr(target_tc, 'get_name', lambda: '?')())
        print("DEBUG: task '%s' created in '%s'." % (TASK_NAME, created_in))

    if task_obj is None:
        # Last resort: project.find(TASK_NAME, True)
        try:
            cand = primary_project.find(TASK_NAME, True)
            if cand:
                for c in cand:
                    if hasattr(c, 'cycle_time') or hasattr(c, 'priority') or hasattr(c, 'watchdog'):
                        task_obj = c
                        break
        except Exception:
            pass

    if task_obj is None:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError(
            "Task '%s' not found in any Task Configuration node. Inspect via "
            "get_task_configuration to confirm the exact name." % TASK_NAME)

    applied = []
    skipped = []

    # kind (before the interval: AB requires Cyclic for an interval to apply)
    if task_kind:
        want_kind = _KINDS[task_kind]
        kinds = getattr(script_engine, 'KindOfTask', None)
        if kinds is None or not hasattr(kinds, want_kind) or not hasattr(task_obj, 'kind_of_task'):
            skipped.append({'field': 'kind', 'reason': 'KindOfTask / kind_of_task not exposed'})
        else:
            try:
                task_obj.kind_of_task = getattr(kinds, want_kind)
                rb = _to_unicode(task_obj.kind_of_task)
                if rb.split(u'.')[-1].lower() == want_kind.lower():
                    applied.append({'field': 'kind', 'attribute': 'kind_of_task', 'value': want_kind})
                else:
                    skipped.append({'field': 'kind', 'error': 'write did not stick: read back %s' % rb})
            except Exception as e:
                skipped.append({'field': 'kind', 'error': str(e)})

    # cycle time
    if cycle_ms is not None:
        target_attr = None
        for a in ('cycle_time', 'interval', 'time'):
            if hasattr(task_obj, a):
                target_attr = a
                break
        if target_attr is None:
            skipped.append({'field': 'cycle_time_ms', 'reason': 'attribute_not_found'})
        else:
            # Verification is now in ms, so it covers the TimeSpan path too --
            # previously only a string write was checked and a TimeSpan write
            # was taken on trust.
            ok, detail = _write_time_verified(
                lambda: task_obj, target_attr, cycle_ms, 'cycle_time_ms')
            (applied if ok else skipped).append(detail)

    # priority -- a STRING property on AC500 V3 (see _write_scalar_verified);
    # now read back like every other knob (it used to be taken on trust).
    if priority is not None:
        if hasattr(task_obj, 'priority'):
            ok, detail = _write_scalar_verified(
                lambda: task_obj, 'priority', priority, 'priority', int)
            (applied if ok else skipped).append(detail)
        else:
            skipped.append({'field': 'priority', 'reason': 'attribute_not_found'})

    # watchdog (time / enabled / sensitivity)
    #
    # Re-fetch task_obj.watchdog for every access instead of caching it: if the
    # wrapper hands back a fresh object per property read, writing to a cached
    # one would be discarded and a cached read-back would still show the value
    # we just wrote. _get_wd is passed as the owner-getter so the verification
    # genuinely round-trips through the project.
    def _get_wd():
        try:
            return getattr(task_obj, 'watchdog', None)
        except Exception:
            return None

    if watchdog_ms is not None or watchdog_on is not None or watchdog_sens is not None:
        wd_probe = _get_wd()
        if wd_probe is None:
            for f in ('watchdog_time_ms', 'watchdog_enabled', 'watchdog_sensitivity'):
                skipped.append({'field': f, 'reason': 'watchdog_object_not_found'})
        else:
            # Order matters: set the time BEFORE toggling enable, so a task is
            # never briefly armed with the old (possibly far too short) timeout.
            if watchdog_ms is not None:
                wd_target = None
                for a in ('time', 'watchdog_time'):
                    if hasattr(wd_probe, a):
                        wd_target = a
                        break
                if wd_target is None:
                    skipped.append({'field': 'watchdog_time_ms',
                                    'reason': 'attribute_not_found_on_watchdog'})
                else:
                    ok, detail = _write_time_verified(
                        _get_wd, wd_target, watchdog_ms, 'watchdog_time_ms')
                    detail['attribute'] = 'watchdog.' + detail.get('attribute', wd_target)
                    (applied if ok else skipped).append(detail)

            if watchdog_sens is not None:
                sens_attr = None
                for a in ('sensitivity', 'watchdog_sensitivity'):
                    if hasattr(wd_probe, a):
                        sens_attr = a
                        break
                if sens_attr is None:
                    skipped.append({'field': 'watchdog_sensitivity',
                                    'reason': 'attribute_not_found_on_watchdog'})
                else:
                    ok, detail = _write_scalar_verified(
                        _get_wd, sens_attr, watchdog_sens, 'watchdog_sensitivity', int)
                    detail['attribute'] = 'watchdog.' + detail.get('attribute', sens_attr)
                    (applied if ok else skipped).append(detail)

            # An explicit watchdogEnabled always wins. Otherwise setting a time
            # implies arming the watchdog -- the long-standing behaviour, kept
            # so existing callers do not silently change meaning.
            want_enabled = watchdog_on
            implicit = False
            if want_enabled is None and watchdog_ms is not None:
                want_enabled = True
                implicit = True
            if want_enabled is not None:
                en_attr = None
                for a in ('enable', 'enabled'):
                    if hasattr(wd_probe, a):
                        en_attr = a
                        break
                if en_attr is None:
                    # Only a problem if the caller asked for it explicitly.
                    if not implicit:
                        skipped.append({'field': 'watchdog_enabled',
                                        'reason': 'attribute_not_found_on_watchdog'})
                else:
                    ok, detail = _write_scalar_verified(
                        _get_wd, en_attr, bool(want_enabled), 'watchdog_enabled', bool)
                    detail['attribute'] = 'watchdog.' + detail.get('attribute', en_attr)
                    if implicit:
                        detail['implicit'] = 'enabled because watchdogTimeMs was set'
                    if ok or not implicit:
                        (applied if ok else skipped).append(detail)

    # stack size: try the task first (rare), then walk up to the Device parent.
    if stack_bytes is not None:
        applied_stack = False
        for a in ('stack_size', 'stack_size_bytes'):
            if hasattr(task_obj, a):
                try:
                    setattr(task_obj, a, stack_bytes)
                    applied.append({'field': 'stack_size_bytes', 'attribute': a, 'value': stack_bytes, 'where': 'task'})
                    applied_stack = True
                    break
                except Exception as e:
                    skipped.append({'field': 'stack_size_bytes', 'where': 'task', 'attribute': a, 'error': str(e)})
        if not applied_stack:
            # Walk up the device tree to find a Device with set_stack_size
            # or similar. This is best-effort -- AC500 V3 may expose stack
            # config via Device.parameter[<param_id>] rather than a named
            # attribute, in which case the user must use set_device_parameter.
            cur = task_obj
            for _ in range(8):  # sanity bound
                try:
                    cur = getattr(cur, 'parent', None) or getattr(cur, 'parent_object', None)
                except Exception:
                    cur = None
                if cur is None:
                    break
                for a in ('stack_size', 'stack_size_bytes', 'set_stack_size'):
                    if hasattr(cur, a):
                        try:
                            attr_val = getattr(cur, a)
                            if callable(attr_val):
                                attr_val(stack_bytes)
                            else:
                                setattr(cur, a, stack_bytes)
                            applied.append({'field': 'stack_size_bytes', 'attribute': a, 'value': stack_bytes, 'where': 'ancestor'})
                            applied_stack = True
                            break
                        except Exception as e:
                            skipped.append({'field': 'stack_size_bytes', 'where': 'ancestor', 'attribute': a, 'error': str(e)})
                if applied_stack:
                    break
        if not applied_stack:
            skipped.append({
                'field': 'stack_size_bytes',
                'reason': 'no_stack_attribute_found_on_task_or_ancestors',
                'hint': "AC500 V3 typically stores PLC stack config under the Device node's parameter dict (parameter ID varies by firmware). Use set_device_parameter once the parameter ID is known. The UI path is Device > PLC Settings."
            })

    # POU calls (live 2026-10-17): ITERATING task.pous yields the program
    # names, while task.pous[i] returns a (name, comment) tuple; pous.add()
    # appends. add() does not check the POU exists, so a name the project tree
    # does not know is reported as a warning -- the compile is the real check
    # (a library program can be legitimate).
    pou_warnings = []

    def _task_pou_names():
        out = []
        try:
            for item in task_obj.pous:
                if isinstance(item, (tuple, list)):
                    item = item[0] if item else u''
                out.append(_to_unicode(item))
        except Exception:
            pass
        return out

    if add_pous:
        if not hasattr(task_obj, 'pous'):
            for p in add_pous:
                skipped.append({'field': 'pou:' + p, 'reason': 'task exposes no pous collection'})
        else:
            for p in add_pous:
                present = [n.lower() for n in _task_pou_names()]
                if p.lower() in present:
                    applied.append({'field': 'pou:' + p, 'value': p, 'note': 'already called by the task'})
                    continue
                try:
                    task_obj.pous.add(p)
                except Exception as e:
                    skipped.append({'field': 'pou:' + p, 'error': str(e)})
                    continue
                if p.lower() in [n.lower() for n in _task_pou_names()]:
                    applied.append({'field': 'pou:' + p, 'value': p})
                else:
                    skipped.append({'field': 'pou:' + p, 'error': 'pous.add() returned but the call is not listed'})
                    continue
                try:
                    found = primary_project.find(p.split(u'.')[-1], True)
                except Exception:
                    found = None
                if not found:
                    pou_warnings.append(
                        u"'%s' is not in the project tree (fine for a library program; "
                        u"otherwise compile_project will report it)" % p)

    # Persist (a Released project is read-only: clear error instead of ERR_UNKNOWN)
    try:
        save_project_checked(primary_project, "the task change")
        print("DEBUG: Project saved after task parameter update.")
    except Exception as save_err:
        if 'READ-ONLY' in str(save_err):
            raise
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        raise RuntimeError("Failed to save project after task update: %s" % save_err)

    def _snapshot():
        snap = {u'name': _to_unicode(TASK_NAME), u'pous': _task_pou_names()}
        for a in ('kind_of_task', 'interval', 'interval_unit', 'priority'):
            try:
                snap[_to_unicode(a)] = _to_unicode(getattr(task_obj, a))
            except Exception:
                pass
        wd = _get_wd()
        if wd is not None:
            for a in ('enabled', 'time', 'sensitivity'):
                try:
                    v = getattr(wd, a)
                    snap[u'watchdog_' + _to_unicode(a)] = v if isinstance(v, bool) else _to_unicode(v)
                except Exception:
                    pass
        return snap

    emit_result({
        u'task': _to_unicode(TASK_NAME),
        u'created': created_in is not None,
        u'taskConfiguration': created_in,
        u'applied': applied,
        u'failed': skipped,
        u'warnings': pou_warnings,
        u'state': _snapshot(),
    })

    print("Task: %s" % TASK_NAME)
    print("Applied: %d field(s)" % len(applied))
    for a in applied:
        print("  - %s" % a)
    if skipped:
        print("Skipped/failed: %d field(s)" % len(skipped))
        for s in skipped:
            print("  - %s" % s)

    # A requested knob that did not take must FAIL the call. Reporting success
    # with the failure buried in a 'skipped' line is how a 20ms watchdog
    # reached a PLC while the tool said "Task updated (cycleTimeMs,
    # watchdogTimeMs)" (2026-10-12). Fields that DID apply are already saved
    # above -- the error says which, so the caller knows the real state.
    if skipped:
        # In create mode the task already exists and is saved at this point.
        # Say so: otherwise the natural retry, create_task again, fails with a
        # baffling ERR_OBJECT_EXISTS. Deleting the half-configured task here
        # was rejected on purpose -- a destructive step inside a failure path
        # is a worse surprise than a task that needs one more field.
        created_note = ""
        if created_in is not None:
            created_note = (
                " The task WAS created in '%s' and saved -- do not call "
                "create_task again (it would fail with ERR_OBJECT_EXISTS); fix "
                "the remaining field(s) with set_task_parameter or in the AB "
                "task editor, or delete the task to start over." % created_in)
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "Task '%s': %d field(s) applied and saved (%s), but %d requested "
            "field(s) did NOT take: %s. The project reflects only the applied "
            "fields -- re-read with get_task_configuration and set the rest in "
            "the AB task editor if the attribute is not scriptable on this build.%s"
            % (TASK_NAME,
               len(applied), ', '.join(a.get('field', '?') for a in applied) or 'none',
               len(skipped), '; '.join(
                   '%s (%s)' % (s.get('field', '?'),
                                s.get('error') or s.get('reason') or 'unknown')
                   for s in skipped),
               created_note))

    print("SCRIPT_SUCCESS: Task parameters updated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error setting task parameter on '%s' (task='%s'): %s\n%s" % (
        PROJECT_FILE_PATH, TASK_NAME, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

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

def _maybe_int(s):
    if s is None or s == "":
        return None
    try:
        return int(s)
    except Exception:
        return None

def _maybe_bool(s):
    if s is None or s == "":
        return None
    return unicode(s).strip().lower() in (u'true', u'1', u'yes', u'on')

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

def _iec_time_to_ms(s):
    """Parse an IEC 61131-3 TIME literal ('t#10ms', 'T#1m30s') to ms.
    Returns None if it does not parse. Mirrors the parser in
    get_task_configuration.py -- keep the two in step."""
    import re as _re
    try:
        txt = unicode(s).strip().lower()
    except Exception:
        return None
    if txt.startswith('time#'):
        txt = txt[5:]
    elif txt.startswith('t#'):
        txt = txt[2:]
    else:
        return None
    txt = txt.replace('_', '')
    # Order matters: 'ms'/'us'/'ns' must match before 'm'/'s'.
    factors = {'ms': 1.0, 'us': 0.001, 'ns': 0.000001,
               'd': 86400000.0, 'h': 3600000.0, 'm': 60000.0, 's': 1000.0}
    total = 0.0
    matched = False
    pos = 0
    for m in _re.finditer(r'(\d+(?:\.\d+)?)(ms|us|ns|d|h|m|s)', txt):
        total += float(m.group(1)) * factors[m.group(2)]
        matched = True
        pos = m.end()
    if not matched or pos != len(txt):
        return None
    return total

def _any_time_to_ms(v):
    """Coerce whatever a time-valued attribute holds (.NET TimeSpan, IEC TIME
    literal string, plain numeric) into milliseconds. None if unreadable."""
    if v is None:
        return None
    for attr in ('TotalMilliseconds', 'total_milliseconds', 'total_ms'):
        if hasattr(v, attr):
            try:
                return float(getattr(v, attr))
            except Exception:
                pass
    iec = _iec_time_to_ms(v)
    if iec is not None:
        return iec
    try:
        return float(v)
    except Exception:
        return None

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
    rb_ms = _any_time_to_ms(readback)
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
    _write_time_verified: unverifiable means failed."""
    owner = get_owner()
    if owner is None:
        return False, {'field': field_label, 'reason': 'owner_not_found'}
    try:
        setattr(owner, attr, value)
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

    if (cycle_ms is None and watchdog_ms is None and watchdog_on is None
            and watchdog_sens is None and priority is None and stack_bytes is None):
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError(
            "At least one of cycleTimeMs / watchdogTimeMs / watchdogEnabled / "
            "watchdogSensitivity / priority / stackSizeBytes must be provided.")

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

    # priority
    if priority is not None:
        if hasattr(task_obj, 'priority'):
            try:
                task_obj.priority = priority
                applied.append({'field': 'priority', 'attribute': 'priority', 'value': priority})
            except Exception as e:
                skipped.append({'field': 'priority', 'error': str(e)})
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

    # Persist
    try:
        primary_project.save()
        print("DEBUG: Project saved after task parameter update.")
    except Exception as save_err:
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        raise RuntimeError("Failed to save project after task update: %s" % save_err)

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
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "Task '%s': %d field(s) applied and saved (%s), but %d requested "
            "field(s) did NOT take: %s. The project reflects only the applied "
            "fields -- re-read with get_task_configuration and set the rest in "
            "the AB task editor if the attribute is not scriptable on this build."
            % (TASK_NAME,
               len(applied), ', '.join(a.get('field', '?') for a in applied) or 'none',
               len(skipped), '; '.join(
                   '%s (%s)' % (s.get('field', '?'),
                                s.get('error') or s.get('reason') or 'unknown')
                   for s in skipped)))

    print("SCRIPT_SUCCESS: Task parameters updated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error setting task parameter on '%s' (task='%s'): %s\n%s" % (
        PROJECT_FILE_PATH, TASK_NAME, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

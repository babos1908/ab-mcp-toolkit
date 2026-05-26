import sys, scriptengine as script_engine, os, traceback

TASK_NAME = "{TASK_NAME}"
# Empty string sentinel = do not touch this knob. Numeric values are passed
# as their decimal string representation; we parse here.
CYCLE_TIME_MS_STR     = "{CYCLE_TIME_MS}"
WATCHDOG_TIME_MS_STR  = "{WATCHDOG_TIME_MS}"
PRIORITY_STR          = "{PRIORITY}"
STACK_SIZE_BYTES_STR  = "{STACK_SIZE_BYTES}"

def _maybe_int(s):
    if s is None or s == "":
        return None
    try:
        return int(s)
    except Exception:
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

try:
    print("DEBUG: set_task_parameter: Project='%s' Task='%s' "
          "cycleMs=%s watchdogMs=%s priority=%s stackBytes=%s" % (
        PROJECT_FILE_PATH, TASK_NAME,
        CYCLE_TIME_MS_STR, WATCHDOG_TIME_MS_STR, PRIORITY_STR, STACK_SIZE_BYTES_STR))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not TASK_NAME:
        raise ValueError("Task name empty.")

    cycle_ms    = _maybe_int(CYCLE_TIME_MS_STR)
    watchdog_ms = _maybe_int(WATCHDOG_TIME_MS_STR)
    priority    = _maybe_int(PRIORITY_STR)
    stack_bytes = _maybe_int(STACK_SIZE_BYTES_STR)

    if cycle_ms is None and watchdog_ms is None and priority is None and stack_bytes is None:
        raise ValueError(
            "At least one of cycleTimeMs / watchdogTimeMs / priority / "
            "stackSizeBytes must be provided.")

    # Locate the named Task. Walk every Task Configuration node, then look for
    # a child matching TASK_NAME (case-insensitive).
    task_obj = None
    task_configs = []
    try:
        for child in primary_project.get_children(True):
            cname = getattr(child, 'get_name', lambda: '')()
            if cname and 'task configuration' in cname.lower():
                task_configs.append(child)
    except Exception:
        pass

    if not task_configs:
        try:
            found = primary_project.find("Task Configuration", True)
            if found:
                task_configs = list(found)
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
            try:
                setattr(task_obj, target_attr, _ms_to_timespan(cycle_ms))
                applied.append({'field': 'cycle_time_ms', 'attribute': target_attr, 'value': cycle_ms})
            except Exception as e:
                skipped.append({'field': 'cycle_time_ms', 'attribute': target_attr, 'error': str(e)})

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

    # watchdog
    if watchdog_ms is not None:
        wd = None
        for a in ('watchdog',):
            if hasattr(task_obj, a):
                try:
                    wd = getattr(task_obj, a)
                    break
                except Exception:
                    pass
        if wd is None:
            skipped.append({'field': 'watchdog_time_ms', 'reason': 'watchdog_object_not_found'})
        else:
            wd_target = None
            for a in ('time', 'watchdog_time'):
                if hasattr(wd, a):
                    wd_target = a
                    break
            if wd_target is None:
                skipped.append({'field': 'watchdog_time_ms', 'reason': 'attribute_not_found_on_watchdog'})
            else:
                try:
                    setattr(wd, wd_target, _ms_to_timespan(watchdog_ms))
                    # Also enable the watchdog if there's an explicit toggle.
                    for ea in ('enable', 'enabled'):
                        if hasattr(wd, ea):
                            try:
                                setattr(wd, ea, True)
                            except Exception:
                                pass
                            break
                    applied.append({'field': 'watchdog_time_ms', 'attribute': 'watchdog.' + wd_target, 'value': watchdog_ms})
                except Exception as e:
                    skipped.append({'field': 'watchdog_time_ms', 'error': str(e)})

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
        raise RuntimeError("Failed to save project after task update: %s" % save_err)

    print("Task: %s" % TASK_NAME)
    print("Applied: %d field(s)" % len(applied))
    for a in applied:
        print("  - %s" % a)
    if skipped:
        print("Skipped/failed: %d field(s)" % len(skipped))
        for s in skipped:
            print("  - %s" % s)
    print("SCRIPT_SUCCESS: Task parameters updated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error setting task parameter on '%s' (task='%s'): %s\n%s" % (
        PROJECT_FILE_PATH, TASK_NAME, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

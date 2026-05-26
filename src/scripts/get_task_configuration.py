import sys, scriptengine as script_engine, os, traceback

try:
    print("DEBUG: get_task_configuration: Project='%s'" % PROJECT_FILE_PATH)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    # Find Task Configuration node(s) anywhere in the device/application tree.
    # On an AC500 V3 standard project the path is roughly:
    #   PLC_AC500_V3 / Plc Logic / Application / Task Configuration / <Task>
    # On Standard editions get_children(True) does NOT descend into the
    # device sub-tree -- empirical 2026-05-26 on NexoPlcExample.project,
    # the recursive flag returned only top-level project items (project
    # settings, libraries, the device node itself) but stopped at the
    # device boundary. So we walk via explicit DFS calling get_children(False)
    # on each node, with a sanity-bounded depth.

    # Empirical 2026-05-26 on NexoPlcExample.project: the internal node
    # name is 'TaskConfiguration' (one word, no space), while the AB UI
    # displays it as 'Task Configuration'. Match on both spellings to
    # cover any vendor/version variation. Same case-folded normalization
    # is applied so we catch 'taskconfig' / 'Task_Configuration' too if
    # they ever appear.
    def _is_task_config_name(name):
        if not name:
            return False
        norm = name.strip().lower().replace(' ', '').replace('_', '')
        return norm == 'taskconfiguration'

    task_configs = []
    visited_names = []

    def _walk(node, depth, max_depth=10):
        if depth > max_depth:
            return
        try:
            children = node.get_children(False)
        except Exception:
            return
        for child in children:
            cname = getattr(child, 'get_name', lambda: '')()
            visited_names.append((depth, cname, type(child).__name__))
            if _is_task_config_name(cname):
                task_configs.append(child)
                # Don't return -- multiple Task Configuration nodes possible
                # (e.g. multi-PLC projects).
            _walk(child, depth + 1, max_depth)

    try:
        _walk(primary_project, 0)
    except Exception as e:
        print("DEBUG: DFS walk failed: %s" % e)

    if not task_configs:
        # Fallback: project.find with both name spellings.
        for probe_name in ('TaskConfiguration', 'Task Configuration'):
            try:
                found = primary_project.find(probe_name, True)
                if found:
                    for f in found:
                        if _is_task_config_name(getattr(f, 'get_name', lambda: '')()):
                            task_configs.append(f)
                    if task_configs:
                        break
            except Exception as ferr:
                print("DEBUG: find('%s') failed: %s" % (probe_name, ferr))

    if not task_configs:
        # Last resort: try the active application's children directly.
        # Task Configuration is always a direct child of an Application node.
        try:
            target_app = primary_project.active_application
            if target_app is not None:
                for ac in target_app.get_children(False):
                    cn = getattr(ac, 'get_name', lambda: '')()
                    if _is_task_config_name(cn):
                        task_configs.append(ac)
        except Exception as aerr:
            print("DEBUG: active_application probe failed: %s" % aerr)

    if not task_configs:
        # Dump what we DID see so the failure is diagnosable upstream.
        print("DEBUG: DFS visited %d node(s). First 80:" % len(visited_names))
        for d, n, t in visited_names[:80]:
            print("DEBUG:   %s[%s] %s (%s)" % ("  " * d, d, n, t))

    if not task_configs:
        raise RuntimeError(
            "No Task Configuration node found in the project. Library projects "
            "typically have none -- Task Configuration is on consumer projects "
            "(application + device)."
        )

    def _ts_to_ms(ts):
        """Convert a System.TimeSpan-like value to milliseconds (float)."""
        if ts is None:
            return None
        # .NET TimeSpan exposes .TotalMilliseconds. IronPython gets it via attr access.
        for attr in ('TotalMilliseconds', 'total_milliseconds', 'total_ms'):
            if hasattr(ts, attr):
                try:
                    return float(getattr(ts, attr))
                except Exception:
                    pass
        # Fallback: assume integer microseconds or string -- skip.
        try:
            return float(ts)
        except Exception:
            return None

    def _bytes(v):
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    def _str(v):
        if v is None:
            return None
        try:
            return _to_unicode(unicode(v))
        except Exception:
            try:
                return _to_unicode(repr(v))
            except Exception:
                return None

    def _probe_task(task_obj):
        """Extract a dict of known properties from a Task object."""
        tname = getattr(task_obj, 'get_name', lambda: '?')()
        rec = {u'name': _to_unicode(tname)}

        # cycle time / interval
        for attr in ('cycle_time', 'interval', 'time'):
            if hasattr(task_obj, attr):
                try:
                    val = getattr(task_obj, attr)
                    rec[u'cycle_time_ms'] = _ts_to_ms(val)
                    rec[u'_cycle_time_attr'] = attr
                    break
                except Exception:
                    pass

        # priority
        for attr in ('priority',):
            if hasattr(task_obj, attr):
                try:
                    rec[u'priority'] = int(getattr(task_obj, attr))
                    break
                except Exception:
                    pass

        # watchdog (often a nested object)
        wd = None
        for attr in ('watchdog',):
            if hasattr(task_obj, attr):
                try:
                    wd = getattr(task_obj, attr)
                    break
                except Exception:
                    pass
        if wd is not None:
            wd_rec = {}
            for ta in ('time', 'watchdog_time'):
                if hasattr(wd, ta):
                    try:
                        wd_rec[u'time_ms'] = _ts_to_ms(getattr(wd, ta))
                        break
                    except Exception:
                        pass
            for sa in ('sensitivity', 'watchdog_sensitivity'):
                if hasattr(wd, sa):
                    try:
                        wd_rec[u'sensitivity'] = int(getattr(wd, sa))
                        break
                    except Exception:
                        pass
            for ea in ('enable', 'enabled'):
                if hasattr(wd, ea):
                    try:
                        wd_rec[u'enabled'] = bool(getattr(wd, ea))
                        break
                    except Exception:
                        pass
            if wd_rec:
                rec[u'watchdog'] = wd_rec

        # task type / event (best-effort)
        for attr in ('task_type', 'type', 'event_name', 'event'):
            if hasattr(task_obj, attr):
                try:
                    rec[u'_' + attr] = _str(getattr(task_obj, attr))
                except Exception:
                    pass

        # Stack size is usually on the Device, not the Task -- but probe anyway
        # for builds that expose it here.
        for attr in ('stack_size', 'stack_size_bytes'):
            if hasattr(task_obj, attr):
                try:
                    rec[u'stack_size_bytes'] = _bytes(getattr(task_obj, attr))
                    break
                except Exception:
                    pass

        return rec

    output = []
    for tc in task_configs:
        tc_name = getattr(tc, 'get_name', lambda: '?')()
        rec = {u'task_configuration_name': _to_unicode(tc_name), u'tasks': []}
        try:
            for child in tc.get_children(False):
                rec[u'tasks'].append(_probe_task(child))
        except Exception as cerr:
            rec[u'enumeration_error'] = _to_unicode(str(cerr))
        output.append(rec)

    emit_result({u'task_configurations': output})
    print("Found %d Task Configuration node(s)." % len(task_configs))
    print("SCRIPT_SUCCESS: Task configuration read.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error reading task configuration for '%s': %s\n%s" % (
        PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

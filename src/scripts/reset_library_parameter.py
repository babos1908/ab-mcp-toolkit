import sys, scriptengine as script_engine, traceback

LIBRARY_NAME = "{LIBRARY_NAME}"
PARAMETER_NAME = "{PARAMETER_NAME}"

try:
    print("DEBUG: reset_library_parameter: Lib='%s' Param='%s'" % (LIBRARY_NAME, PARAMETER_NAME))

    if not LIBRARY_NAME or not PARAMETER_NAME:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("libraryName and parameterName are required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    # Same Library Manager + reference lookup as set_library_parameter.
    lib_manager_node = None
    try:
        found = primary_project.find("Library Manager", True)
        if found:
            lib_manager_node = found[0]
    except Exception:
        pass
    if lib_manager_node is None:
        for child in primary_project.get_children(True):
            cname = getattr(child, 'get_name', lambda: '')()
            if cname and 'library manager' in cname.lower():
                lib_manager_node = child
                break
    if lib_manager_node is None:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError("Library Manager node not found in project.")

    target_ref = None
    for ref in lib_manager_node.get_children(False):
        ref_name = getattr(ref, 'get_name', lambda: '')()
        if ref_name and ref_name.strip().lower() == LIBRARY_NAME.strip().lower():
            target_ref = ref
            break
    if target_ref is None:
        print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_FOUND")
        raise RuntimeError("Library reference '%s' not found." % LIBRARY_NAME)

    probe_attrs = (
        'parameters', 'parameter', 'get_parameters', 'get_all_parameters',
        'overridden_parameters', 'placeholders',
    )
    params_collection = None
    for attr in probe_attrs:
        if hasattr(target_ref, attr):
            try:
                v = getattr(target_ref, attr)
                cand = v() if callable(v) else v
                if cand is not None:
                    params_collection = cand
                    break
            except Exception:
                pass
    if params_collection is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError("No library-parameter accessor on this build.")

    # Find the slot and try a reset/clear/remove operation.
    target_slot = None
    target_key = None
    try:
        if hasattr(params_collection, '__getitem__'):
            try:
                target_slot = params_collection[PARAMETER_NAME]
                target_key = PARAMETER_NAME
            except Exception:
                pass
    except Exception:
        pass
    if target_slot is None:
        keys = []
        try:
            keys = list(params_collection.keys())
        except Exception:
            try:
                keys = list(iter(params_collection))
            except Exception:
                keys = []
        for k in keys:
            slot = k
            if hasattr(params_collection, '__getitem__'):
                try:
                    slot = params_collection[k]
                except Exception:
                    pass
            slot_name = None
            for nattr in ('name', 'get_name', 'identifier'):
                if hasattr(slot, nattr):
                    try:
                        v = getattr(slot, nattr)
                        slot_name = v() if callable(v) else v
                    except Exception:
                        pass
                    break
            if slot_name is None and isinstance(k, (str, unicode)):
                slot_name = k
            if slot_name and str(slot_name).strip() == PARAMETER_NAME.strip():
                target_slot = slot
                target_key = k
                break
    if target_slot is None:
        print("SCRIPT_ERROR_CODE: ERR_LIB_PARAM_NOT_FOUND")
        raise RuntimeError("Parameter '%s' not exposed by library '%s'." % (PARAMETER_NAME, LIBRARY_NAME))

    # Pre-record the default value so we can confirm reset took effect.
    default_value = None
    for dattr in ('default_value', 'default', 'get_default'):
        if hasattr(target_slot, dattr):
            try:
                v = getattr(target_slot, dattr)
                default_value = v() if callable(v) else v
            except Exception:
                pass
            break

    # Cascade of reset operations:
    # 1. slot.reset() / slot.clear() / slot.reset_to_default()
    # 2. delete params_collection[key]
    # 3. slot.value = default_value (last resort -- may still show "overridden" flag)
    reset_via = None
    last_err = None
    for mname in ('reset_to_default', 'reset', 'clear', 'remove_override'):
        if hasattr(target_slot, mname):
            try:
                getattr(target_slot, mname)()
                reset_via = "slot.%s()" % mname
                break
            except Exception as e:
                last_err = "%s: %s" % (mname, e)
    if reset_via is None and hasattr(params_collection, '__delitem__'):
        try:
            del params_collection[target_key]
            reset_via = "del collection[key]"
        except Exception as e:
            last_err = (last_err or '') + " | del: %s" % e
    if reset_via is None and default_value is not None and hasattr(target_slot, 'value'):
        try:
            target_slot.value = default_value
            reset_via = "slot.value=default (soft reset)"
        except Exception as e:
            last_err = (last_err or '') + " | value=default: %s" % e

    if reset_via is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Could not reset parameter '%s'. Tried slot.reset/clear/remove_override, "
            "del collection[key], slot.value=default. Last error: %s" % (
                PARAMETER_NAME, last_err))

    try:
        primary_project.save()
    except Exception as se:
        print("WARN: project.save() raised: %s" % se)

    emit_result({
        u'library': _to_unicode(LIBRARY_NAME),
        u'parameter': _to_unicode(PARAMETER_NAME),
        u'defaultValueRecorded': _to_unicode(unicode(default_value)) if default_value is not None else None,
        u'resetVia': _to_unicode(reset_via),
    })
    print("SCRIPT_SUCCESS: Library parameter override reset.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error resetting library parameter: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

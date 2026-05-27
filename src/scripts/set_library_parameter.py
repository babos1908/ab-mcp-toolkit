import sys, scriptengine as script_engine, traceback

LIBRARY_NAME = "{LIBRARY_NAME}"
PARAMETER_NAME = "{PARAMETER_NAME}"
PARAMETER_VALUE = """{PARAMETER_VALUE}"""

try:
    print("DEBUG: set_library_parameter: Lib='%s' Param='%s' Value=%r" % (
        LIBRARY_NAME, PARAMETER_NAME, PARAMETER_VALUE))

    if not LIBRARY_NAME or not PARAMETER_NAME:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("libraryName and parameterName are required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    # Find Library Manager + the named library reference
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
        raise RuntimeError(
            "Library reference '%s' not found under Library Manager. Use "
            "list_project_libraries to confirm the exact name." % LIBRARY_NAME)

    # Probe parameter accessor on the reference. Same cascade as get_.
    probe_attrs = (
        'parameters', 'parameter', 'get_parameters', 'get_all_parameters',
        'overridden_parameters', 'placeholders',
    )
    params_collection = None
    accessor_used = None
    for attr in probe_attrs:
        if hasattr(target_ref, attr):
            try:
                v = getattr(target_ref, attr)
                cand = v() if callable(v) else v
                if cand is not None:
                    params_collection = cand
                    accessor_used = attr
                    break
            except Exception:
                pass

    if params_collection is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "No library-parameter accessor on this build. Run "
            "get_library_parameters and forward the diagnostic dump."
        )

    # Locate the target parameter slot by name.
    target_slot = None
    target_key = None
    # Try dict-style by-name access first.
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
        # Iterate.
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
        raise RuntimeError(
            "Parameter '%s' not exposed by library '%s'." % (PARAMETER_NAME, LIBRARY_NAME))

    # Write the value. Try multiple set/property patterns.
    written = False
    last_err = None
    # 1. slot.value = X
    if not written and hasattr(target_slot, 'value'):
        try:
            target_slot.value = PARAMETER_VALUE
            written = True
        except Exception as e:
            last_err = "slot.value=...: %s: %s" % (type(e).__name__, e)
    # 2. slot.set_value(X)
    if not written and hasattr(target_slot, 'set_value'):
        try:
            target_slot.set_value(PARAMETER_VALUE)
            written = True
        except Exception as e:
            last_err = (last_err or '') + " | slot.set_value(): %s: %s" % (type(e).__name__, e)
    # 3. collection[name] = X (dict-style overwrite)
    if not written and hasattr(params_collection, '__setitem__'):
        try:
            params_collection[target_key] = PARAMETER_VALUE
            written = True
        except Exception as e:
            last_err = (last_err or '') + " | collection[k]=...: %s: %s" % (type(e).__name__, e)

    if not written:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Could not write parameter '%s'. Tried slot.value, slot.set_value, "
            "collection[key]. Last error: %s" % (PARAMETER_NAME, last_err))

    # Save so the override persists.
    try:
        primary_project.save()
    except Exception as se:
        print("WARN: project.save() raised: %s" % se)

    emit_result({
        u'library': _to_unicode(LIBRARY_NAME),
        u'parameter': _to_unicode(PARAMETER_NAME),
        u'newValue': _to_unicode(PARAMETER_VALUE),
        u'accessorUsed': _to_unicode(accessor_used),
    })
    print("SCRIPT_SUCCESS: Library parameter override set.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error setting library parameter: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

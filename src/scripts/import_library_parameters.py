import sys, scriptengine as script_engine, os, traceback, json

INPUT_PATH = "{INPUT_PATH}"
# Optional: only apply parameters whose isOverridden was true at export time.
# Default true -- importing default-only values back is a no-op since they
# match the library default anyway and the override is redundant.
SKIP_DEFAULTS = "{SKIP_DEFAULTS}"

try:
    print("DEBUG: import_library_parameters: Input='%s' SkipDefaults='%s'" % (INPUT_PATH, SKIP_DEFAULTS))
    if not INPUT_PATH:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("inputPath is required.")
    skip_defaults = SKIP_DEFAULTS.strip().lower() in ('true', '1', 'yes', 'on')

    if not os.path.exists(INPUT_PATH):
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise RuntimeError("Input file does not exist: %s" % INPUT_PATH)

    with open(INPUT_PATH, 'rb') as f:
        raw = f.read()
    try:
        data = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
    except Exception as je:
        raise RuntimeError("Failed to parse JSON: %s" % je)

    libs_to_apply = data.get(u'libraries', [])
    if not isinstance(libs_to_apply, list):
        raise RuntimeError("'libraries' key in input is not a list.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)
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
        raise RuntimeError("Library Manager node not found in target project.")

    # Build a lookup of library references in the target project by name.
    refs_by_name = {}
    for ref in lib_manager_node.get_children(False):
        rn = getattr(ref, 'get_name', lambda: '')()
        if rn:
            refs_by_name[str(rn).strip().lower()] = ref

    applied = []
    skipped = []
    failures = []

    for lib_entry in libs_to_apply:
        lib_name = lib_entry.get(u'libraryName')
        if not lib_name:
            continue
        ref = refs_by_name.get(str(lib_name).strip().lower())
        if ref is None:
            skipped.append({'library': lib_name, 'reason': 'not_in_target_library_manager'})
            continue

        # Resolve parameter accessor.
        params_collection = None
        for attr in ('parameters', 'parameter', 'get_parameters', 'get_all_parameters'):
            if hasattr(ref, attr):
                try:
                    v = getattr(ref, attr)
                    cand = v() if callable(v) else v
                    if cand is not None:
                        params_collection = cand
                        break
                except Exception:
                    pass
        if params_collection is None:
            skipped.append({'library': lib_name, 'reason': 'no_parameter_accessor'})
            continue

        for p in lib_entry.get(u'parameters', []):
            p_name = p.get(u'name')
            p_value = p.get(u'value')
            p_overridden = p.get(u'isOverridden')
            if not p_name or p_value is None:
                skipped.append({'library': lib_name, 'parameter': p_name, 'reason': 'missing_name_or_value'})
                continue
            if skip_defaults and not p_overridden:
                skipped.append({'library': lib_name, 'parameter': p_name, 'reason': 'not_overridden_in_export'})
                continue

            # Find the slot.
            target_slot = None
            target_key = None
            try:
                if hasattr(params_collection, '__getitem__'):
                    try:
                        target_slot = params_collection[p_name]
                        target_key = p_name
                    except Exception:
                        pass
            except Exception:
                pass
            if target_slot is None:
                # iterate
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
                    for nattr in ('name', 'get_name'):
                        if hasattr(slot, nattr):
                            try:
                                v = getattr(slot, nattr)
                                slot_name = v() if callable(v) else v
                            except Exception:
                                pass
                            break
                    if slot_name is None and isinstance(k, (str, unicode)):
                        slot_name = k
                    if slot_name and str(slot_name).strip() == str(p_name).strip():
                        target_slot = slot
                        target_key = k
                        break
            if target_slot is None:
                failures.append({'library': lib_name, 'parameter': p_name, 'error': 'slot_not_found'})
                continue

            written = False
            last_err = None
            if hasattr(target_slot, 'value'):
                try:
                    target_slot.value = p_value
                    written = True
                except Exception as e:
                    last_err = "value=: %s" % e
            if not written and hasattr(target_slot, 'set_value'):
                try:
                    target_slot.set_value(p_value)
                    written = True
                except Exception as e:
                    last_err = (last_err or '') + " | set_value(): %s" % e
            if not written and hasattr(params_collection, '__setitem__'):
                try:
                    params_collection[target_key] = p_value
                    written = True
                except Exception as e:
                    last_err = (last_err or '') + " | collection[k]=: %s" % e
            if written:
                applied.append({'library': lib_name, 'parameter': p_name, 'value': p_value})
            else:
                failures.append({'library': lib_name, 'parameter': p_name, 'error': last_err})

    try:
        primary_project.save()
    except Exception as se:
        print("WARN: project.save() raised: %s" % se)

    emit_result({
        u'applied': applied,
        u'skipped': skipped,
        u'failures': failures,
    })
    print("Applied: %d. Skipped: %d. Failures: %d." % (len(applied), len(skipped), len(failures)))
    print("SCRIPT_SUCCESS: Library parameters imported.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error importing library parameters: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

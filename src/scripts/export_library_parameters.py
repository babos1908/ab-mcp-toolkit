import sys, scriptengine as script_engine, os, traceback, json

OUTPUT_PATH = "{OUTPUT_PATH}"
LIBRARY_NAME = "{LIBRARY_NAME}"

try:
    print("DEBUG: export_library_parameters: Output='%s' LibFilter='%s'" % (OUTPUT_PATH, LIBRARY_NAME))
    if not OUTPUT_PATH:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("outputPath is required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    # Reuse the same enumeration logic from get_library_parameters but build
    # a focused export payload (no diagnostics, just the data needed for
    # round-trip via import_library_parameters).
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

    name_filter_lower = LIBRARY_NAME.strip().lower() if LIBRARY_NAME else ''
    export_libs = []
    for ref in lib_manager_node.get_children(False):
        ref_name = getattr(ref, 'get_name', lambda: '')()
        if not ref_name:
            continue
        if name_filter_lower and name_filter_lower not in str(ref_name).lower():
            continue

        ref_version = None
        for vattr in ('version', 'resolved_version'):
            if hasattr(ref, vattr):
                try:
                    v = getattr(ref, vattr)
                    ref_version = v() if callable(v) else v
                except Exception:
                    pass
                break

        params_collection = None
        for attr in ('parameters', 'parameter', 'get_parameters', 'get_all_parameters', 'overridden_parameters'):
            if hasattr(ref, attr):
                try:
                    v = getattr(ref, attr)
                    cand = v() if callable(v) else v
                    if cand is not None:
                        params_collection = cand
                        break
                except Exception:
                    pass

        params_out = []
        if params_collection is not None:
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
                p_name = None
                for nattr in ('name', 'get_name'):
                    if hasattr(slot, nattr):
                        try:
                            v = getattr(slot, nattr)
                            p_name = v() if callable(v) else v
                        except Exception:
                            pass
                        break
                if p_name is None and isinstance(k, (str, unicode)):
                    p_name = k
                if p_name is None:
                    continue
                p_value = None
                for vattr in ('value', 'get_value'):
                    if hasattr(slot, vattr):
                        try:
                            v = getattr(slot, vattr)
                            p_value = v() if callable(v) else v
                        except Exception:
                            pass
                        break
                p_overridden = None
                for oattr in ('is_overridden', 'overridden', 'has_override'):
                    if hasattr(slot, oattr):
                        try:
                            v = getattr(slot, oattr)
                            p_overridden = bool(v() if callable(v) else v)
                        except Exception:
                            pass
                        break
                params_out.append({
                    u'name': _to_unicode(p_name),
                    u'value': _to_unicode(unicode(p_value)) if p_value is not None else None,
                    u'isOverridden': p_overridden,
                })
        export_libs.append({
            u'libraryName': _to_unicode(ref_name),
            u'resolvedVersion': _to_unicode(unicode(ref_version)) if ref_version else None,
            u'parameters': params_out,
        })

    out = {
        u'sourceProject': _to_unicode(PROJECT_FILE_PATH),
        u'exportedAt': time.time() if False else None,  # IronPython lacks reliable time precision here; keep null
        u'libraries': export_libs,
    }

    try:
        import io
        with open(OUTPUT_PATH, 'wb') as f:
            payload = json.dumps(out, indent=2, ensure_ascii=False)
            if isinstance(payload, unicode):
                payload = payload.encode('utf-8')
            f.write(payload)
    except Exception as we:
        raise RuntimeError("Failed to write export file: %s" % we)

    emit_result({u'outputPath': _to_unicode(OUTPUT_PATH), u'librariesExported': len(export_libs)})
    print("Exported %d library/libraries to %s" % (len(export_libs), OUTPUT_PATH))
    print("SCRIPT_SUCCESS: Library parameters exported.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error exporting library parameters: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

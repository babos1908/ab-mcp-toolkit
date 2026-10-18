import sys, scriptengine as script_engine, os, traceback, json

INPUT_PATH = "{INPUT_PATH}"
# Optional: only apply parameters whose isOverridden was true at export time.
# Default true -- importing default-only values back is a no-op since they
# match the library default anyway and the override is redundant.
SKIP_DEFAULTS = "{SKIP_DEFAULTS}"

# Writes overrides through ref.parameters[name] = expr with a read-back per
# value, resolving each libraryName with the shared lm.references lookup in
# _text_utils (the old get_children() walk matched nothing on AB 2.9, so every
# entry was skipped as 'not_in_target_library_manager').

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
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise RuntimeError("Failed to parse JSON: %s" % je)

    libs_to_apply = data.get(u'libraries', [])
    if not isinstance(libs_to_apply, list):
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise RuntimeError("'libraries' key in input is not a list.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    entries = library_reference_entries(primary_project)
    if not entries and not library_managers(primary_project):
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError("Library Manager node not found in target project.")

    applied = []
    skipped = []
    failures = []

    for lib_entry in libs_to_apply:
        lib_name = lib_entry.get(u'libraryName')
        if not lib_name:
            continue
        entry, err = resolve_library_reference(entries, lib_name)
        if entry is None:
            skipped.append({'library': lib_name, 'reason': 'not_in_target_library_manager', 'detail': err})
            continue
        ref = entry['_ref']
        if ref is None or library_parameter_names(ref) is None:
            skipped.append({'library': lib_name, 'reason': 'no_parameter_accessor'})
            continue

        for p in lib_entry.get(u'parameters', []):
            p_name = p.get(u'name')
            p_value = p.get(u'value')
            p_overridden = p.get(u'isOverridden')
            if not p_name or p_value is None or not _to_unicode(p_value).strip():
                skipped.append({'library': lib_name, 'parameter': p_name, 'reason': 'missing_name_or_value'})
                continue
            if skip_defaults and not p_overridden:
                skipped.append({'library': lib_name, 'parameter': p_name, 'reason': 'not_overridden_in_export'})
                continue
            val = to_codesys_text(p_value).strip()
            try:
                ref.parameters[p_name] = val
                rb = library_parameter_value(entry['_lm'].references[entry['display']], p_name)
            except Exception as we:
                failures.append({'library': lib_name, 'parameter': p_name, 'error': str(we)})
                continue
            if rb is None or rb.strip() != val:
                failures.append({'library': lib_name, 'parameter': p_name,
                                 'error': 'write did not stick: wrote %r, read back %r' % (val, rb)})
                continue
            applied.append({'library': entry['display'], 'parameter': p_name, 'value': val})

    if applied:
        save_project_checked(primary_project, "the imported library parameters")

    emit_result({
        u'applied': applied,
        u'skipped': skipped,
        u'failures': failures,
    })
    print("Applied: %d. Skipped: %d. Failures: %d." % (len(applied), len(skipped), len(failures)))
    if failures:
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError("%d parameter(s) failed to import (applied ones were saved): %s" % (
            len(failures), failures))
    print("SCRIPT_SUCCESS: Library parameters imported.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error importing library parameters: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

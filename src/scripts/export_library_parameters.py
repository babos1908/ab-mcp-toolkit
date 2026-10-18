import sys, scriptengine as script_engine, os, traceback, json

OUTPUT_PATH = "{OUTPUT_PATH}"
LIBRARY_NAME = "{LIBRARY_NAME}"

# Exports the consumer-side overrides (the only values ref.parameters exposes
# on AB 2.9, live 2026-10-17) of every reference -- or of the references
# matching LIBRARY_NAME -- for a later import_library_parameters. Uses the
# shared lm.references lookup in _text_utils (the old get_children() walk
# exported nothing on AB 2.9).

try:
    print("DEBUG: export_library_parameters: Output='%s' LibFilter='%s'" % (OUTPUT_PATH, LIBRARY_NAME))
    if not OUTPUT_PATH:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("outputPath is required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    entries = library_reference_entries(primary_project)
    if not entries and not library_managers(primary_project):
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError("Library Manager node not found in project.")

    q = _norm_lib_query(LIBRARY_NAME) if LIBRARY_NAME.strip() else u''
    export_libs = []
    for e in entries:
        if q and not (q in (e['display'] or u'').lower() or q in (e['resolution'] or u'').lower()):
            continue
        if e['_ref'] is None:
            continue
        overrides = library_parameter_overrides(e['_ref'])
        if not overrides:
            continue
        export_libs.append({
            u'libraryName': e['display'],
            u'resolvedVersion': e['version'],
            u'parameters': [{u'name': k, u'value': v, u'isOverridden': True}
                            for k, v in sorted(overrides.items())],
        })

    out = {
        u'sourceProject': _to_unicode(PROJECT_FILE_PATH),
        u'note': u'Only consumer-side overrides are exported (library defaults stay in the library).',
        u'libraries': export_libs,
    }
    try:
        with open(OUTPUT_PATH, 'wb') as f:
            payload = json.dumps(out, indent=2, ensure_ascii=False)
            if isinstance(payload, unicode):
                payload = payload.encode('utf-8')
            f.write(payload)
    except Exception as we:
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        raise RuntimeError("Failed to write export file: %s" % we)

    emit_result({u'outputPath': _to_unicode(OUTPUT_PATH), u'librariesExported': len(export_libs),
                 u'parametersExported': sum(len(l[u'parameters']) for l in export_libs)})
    print("Exported %d library/libraries to %s" % (len(export_libs), OUTPUT_PATH))
    print("SCRIPT_SUCCESS: Library parameters exported.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error exporting library parameters: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

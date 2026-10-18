import sys, scriptengine as script_engine, os, traceback, json

try:
    print("DEBUG: list_project_libraries script: Project='%s'" % PROJECT_FILE_PATH)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    libraries = []

    # Primary path: lm.references / get_libraries() on EVERY Library Manager
    # (see _text_utils.library_reference_entries). Works on AB 2.9 where the
    # references are not child objects. Each entry says whether it is a
    # placeholder ('#'-prefixed display name) and -- separately -- whether it
    # is a SYSTEM reference added implicitly by the device or a plug-in; the
    # two are different things (2026-10-17: '#LogiQ' is a user placeholder).
    for e in library_reference_entries(primary_project):
        entry = {
            'name': e['base'],
            'displayName': e['display'],
            'placeholder': e['isPlaceholder'],
            'system': e['isSystem'],
            'manager': e['manager'],
        }
        if e['isPlaceholder']:
            entry['hidden'] = True  # kept for older handlers
        if e['version']:
            entry['version'] = e['version']
        if e['company']:
            entry['company'] = e['company']
        if e['resolution']:
            entry['resolution'] = e['resolution']
        libraries.append(entry)
    print("DEBUG: %d references across all Library Managers." % len(libraries))

    if not libraries:
        # Fallback: legacy children enumeration (older builds where references
        # ARE child objects).
        for lm, lm_path in library_managers(primary_project):
            try:
                for lib_child in lm.get_children(False):
                    lib_name = getattr(lib_child, 'get_name', lambda: '?')()
                    lib_entry = {'name': lib_name, 'manager': lm_path}
                    for vattr in ('version', 'get_version'):
                        if hasattr(lib_child, vattr):
                            try:
                                v = getattr(lib_child, vattr)
                                lib_entry['version'] = str(v() if callable(v) else v)
                            except Exception:
                                pass
                    if hasattr(lib_child, 'company'):
                        try:
                            lib_entry['company'] = str(lib_child.company)
                        except Exception:
                            pass
                    libraries.append(lib_entry)
            except Exception as e:
                print("WARN: Error enumerating libraries of %s: %s" % (lm_path, e))
        if not libraries and not library_managers(primary_project):
            print("WARN: Library Manager not found in project.")

    for entry in libraries:
        for k in ('name', 'version', 'company', 'displayName', 'resolution', 'manager'):
            if k in entry and entry[k] is not None:
                entry[k] = _to_unicode(entry[k])
    libs_json = json.dumps(libraries, ensure_ascii=False)
    if isinstance(libs_json, unicode):
        libs_json_bytes = libs_json.encode('utf-8')
    else:
        libs_json_bytes = libs_json
    sys.stdout.write("### LIBRARIES_START ###\n")
    sys.stdout.write(libs_json_bytes)
    sys.stdout.write("\n### LIBRARIES_END ###\n")
    sys.stdout.flush()
    print("Library Count: %d" % len(libraries))
    print("SCRIPT_SUCCESS: Project libraries listed.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error listing libraries for project %s: %s\n%s" % (PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

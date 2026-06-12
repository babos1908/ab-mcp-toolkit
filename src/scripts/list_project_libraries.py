import sys, scriptengine as script_engine, os, traceback, json

try:
    print("DEBUG: list_project_libraries script: Project='%s'" % PROJECT_FILE_PATH)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    project_name = os.path.basename(PROJECT_FILE_PATH)

    libraries = []
    lib_manager = None

    # Find Library Manager object
    # Pattern 1: Search for it by name in project tree
    try:
        found_list = primary_project.find("Library Manager", True)
        if found_list:
            lib_manager = found_list[0]
            print("DEBUG: Found Library Manager via find('Library Manager')")
    except Exception as e:
        print("DEBUG: find('Library Manager') failed: %s" % e)

    # Pattern 2: Search all children
    if not lib_manager:
        try:
            all_children = primary_project.get_children(True)
            for child in all_children:
                child_name = getattr(child, 'get_name', lambda: '')()
                if 'library' in child_name.lower() and 'manager' in child_name.lower():
                    lib_manager = child
                    print("DEBUG: Found Library Manager by name search: %s" % child_name)
                    break
        except Exception as e:
            print("DEBUG: Children search for Library Manager failed: %s" % e)

    if lib_manager:
        print("DEBUG: Library Manager found: %s" % getattr(lib_manager, 'get_name', lambda: '?')())

        # Primary path: ScriptLibManObject.get_libraries(recursive) -- works on
        # AB 2.9 even when the Library Manager has 0 enumerable children (the
        # references are NOT child objects on these builds; empirical
        # 2026-06-12 on an AC500 V3 consumer: children=0 but get_libraries()
        # returned all 15 references). Names come back as the display string
        # ('MyLib, * (Vendor)'); system/hidden references are '#'-prefixed.
        if hasattr(lib_manager, 'get_libraries'):
            try:
                for raw in lib_manager.get_libraries(False):
                    disp = _to_unicode(raw)
                    entry = {'name': disp}
                    if disp.startswith('#'):
                        entry['name'] = disp[1:]
                        entry['hidden'] = True
                    # split 'Name, version (Vendor)' when present
                    if ',' in entry['name']:
                        base, rest = entry['name'].split(',', 1)
                        entry['name'] = base.strip()
                        rest = rest.strip()
                        if rest.endswith(')') and '(' in rest:
                            ver, vendor = rest.rsplit('(', 1)
                            entry['version'] = ver.strip()
                            entry['company'] = vendor[:-1].strip()
                        else:
                            entry['version'] = rest
                    entry['displayName'] = disp
                    libraries.append(entry)
                print("DEBUG: get_libraries() returned %d references." % len(libraries))
            except Exception as gl_err:
                print("WARN: get_libraries() failed (%s); falling back to children walk." % gl_err)

    if lib_manager and not libraries:
        # Fallback: legacy children enumeration (older builds where references
        # ARE child objects).
        try:
            lib_children = lib_manager.get_children(False)
            for lib_child in lib_children:
                lib_name = getattr(lib_child, 'get_name', lambda: '?')()
                lib_entry = {'name': lib_name}

                # Try to get version info
                if hasattr(lib_child, 'version'):
                    try:
                        lib_entry['version'] = str(lib_child.version)
                    except Exception:
                        pass
                if hasattr(lib_child, 'get_version'):
                    try:
                        lib_entry['version'] = str(lib_child.get_version())
                    except Exception:
                        pass

                # Try to get company/vendor
                if hasattr(lib_child, 'company'):
                    try:
                        lib_entry['company'] = str(lib_child.company)
                    except Exception:
                        pass

                libraries.append(lib_entry)
                print("DEBUG: Found library: %s" % lib_name)
        except Exception as e:
            print("WARN: Error enumerating libraries: %s" % e)
    else:
        print("WARN: Library Manager not found in project.")

    for entry in libraries:
        for k in ('name', 'version', 'company', 'displayName'):
            if k in entry:
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

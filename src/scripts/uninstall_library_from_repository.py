import sys, scriptengine as script_engine, traceback

# Required: name of the library to uninstall (e.g. 'NexoMqttLib').
LIBRARY_NAME = "{LIBRARY_NAME}"
# Required: version string to uninstall (e.g. '1.0.10'). Use '*' to uninstall
# ALL versions of the library (caller must confirm intent).
LIBRARY_VERSION = "{LIBRARY_VERSION}"
# Optional: target repository name. If empty, uninstall from any repository.
REPOSITORY_NAME = "{REPOSITORY_NAME}"

try:
    print("DEBUG: uninstall_library_from_repository: Name='%s' Version='%s' Repo='%s'" % (
        LIBRARY_NAME, LIBRARY_VERSION, REPOSITORY_NAME))

    if not LIBRARY_NAME:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("library name is required.")
    if not LIBRARY_VERSION:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("version is required (use '*' for all).")

    # Locate library manager
    lib_mgr = None
    for attr in ('librarymanager', 'library_manager'):
        if hasattr(script_engine, attr):
            try:
                cand = getattr(script_engine, attr)
                if cand is not None:
                    lib_mgr = cand
                    break
            except Exception:
                pass
    if lib_mgr is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Could not locate library manager on script_engine."
        )

    # Enumerate installed libraries and find matching handle(s).
    if not hasattr(lib_mgr, 'get_all_libraries'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "lib_mgr.get_all_libraries() not exposed by this CODESYS build."
        )

    targets = []  # list of (lib_handle, repo_handle_or_None, lib_name_str, lib_ver_str, repo_name_str)
    for entry in lib_mgr.get_all_libraries():
        lib_handle = entry
        repo_handle = None
        if isinstance(entry, (tuple, list)):
            if len(entry) >= 1:
                lib_handle = entry[0]
            if len(entry) >= 2:
                repo_handle = entry[1]

        name = None
        for nattr in ('get_name', 'name'):
            if hasattr(lib_handle, nattr):
                try:
                    v = getattr(lib_handle, nattr)
                    name = v() if callable(v) else v
                except Exception:
                    pass
                break
        if name is None or str(name).strip().lower() != LIBRARY_NAME.strip().lower():
            continue

        version = None
        for vattr in ('version', 'get_version'):
            if hasattr(lib_handle, vattr):
                try:
                    v = getattr(lib_handle, vattr)
                    version = v() if callable(v) else v
                except Exception:
                    pass
                break
        ver_str = str(version) if version is not None else ''
        if LIBRARY_VERSION != '*' and ver_str != LIBRARY_VERSION:
            continue

        # Resolve repository if we don't have it from the tuple.
        if repo_handle is None and hasattr(lib_handle, 'repository'):
            try:
                repo_handle = lib_handle.repository
            except Exception:
                pass

        repo_name = None
        if repo_handle is not None:
            for nattr in ('get_name', 'name'):
                if hasattr(repo_handle, nattr):
                    try:
                        v = getattr(repo_handle, nattr)
                        repo_name = v() if callable(v) else v
                    except Exception:
                        pass
                    break

        if REPOSITORY_NAME and (repo_name is None or str(repo_name).strip().lower() != REPOSITORY_NAME.strip().lower()):
            continue

        targets.append({
            'lib_handle': lib_handle,
            'repo_handle': repo_handle,
            'name': str(name),
            'version': ver_str,
            'repo': str(repo_name) if repo_name else '?',
        })

    if not targets:
        print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_FOUND")
        raise RuntimeError(
            "No library matching name='%s' version='%s' repo='%s' is installed." % (
                LIBRARY_NAME, LIBRARY_VERSION, REPOSITORY_NAME or '(any)')
        )

    if not hasattr(lib_mgr, 'uninstall_library'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "lib_mgr.uninstall_library() not exposed by this CODESYS build."
        )

    # Attempt uninstall on each match. Signature is loosely
    # uninstall_library(lib_handle, repo_handle?) -- probe.
    uninstalled = []
    failures = []
    for t in targets:
        ok = False
        last_err = None
        # Signature variants to try, ordered by what seems most likely on
        # the .NET side (mirrors install_library: 3-arg path/repo/force or 2).
        candidates = [
            (t['lib_handle'], t['repo_handle']),
            (t['lib_handle'],),
            (t['lib_handle'], t['repo_handle'], True),  # in case there's a force flag
        ]
        for args in candidates:
            try:
                lib_mgr.uninstall_library(*args)
                ok = True
                break
            except Exception as ue:
                last_err = "%s%r: %s: %s" % ('uninstall_library', args, type(ue).__name__, ue)
        if ok:
            uninstalled.append({'name': t['name'], 'version': t['version'], 'repo': t['repo']})
            print("DEBUG: uninstalled %s %s from %s" % (t['name'], t['version'], t['repo']))
        else:
            failures.append({'name': t['name'], 'version': t['version'], 'repo': t['repo'], 'error': last_err})

    emit_result({
        u'uninstalled': uninstalled,
        u'failures': failures,
        u'requestedName': _to_unicode(LIBRARY_NAME),
        u'requestedVersion': _to_unicode(LIBRARY_VERSION),
    })
    if failures and not uninstalled:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError("All uninstall attempts failed: %s" % failures)
    print("Uninstalled %d library entry/entries; %d failure(s)." % (len(uninstalled), len(failures)))
    print("SCRIPT_SUCCESS: Library uninstall complete.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error uninstalling library: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

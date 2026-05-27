import sys, scriptengine as script_engine, traceback

# Optional filter: only list libraries whose name contains this substring
# (case-insensitive). Empty = no filter.
NAME_FILTER = "{NAME_FILTER}"

try:
    print("DEBUG: list_library_repository: NameFilter='%s'" % NAME_FILTER)

    # The library manager is available globally on script_engine. Probe both
    # known attribute names (some builds expose librarymanager, some
    # library_manager).
    lib_mgr = None
    for attr in ('librarymanager', 'library_manager'):
        if hasattr(script_engine, attr):
            try:
                cand = getattr(script_engine, attr)
                if cand is not None:
                    lib_mgr = cand
                    print("DEBUG: lib_mgr via script_engine.%s" % attr)
                    break
            except Exception:
                pass

    if lib_mgr is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Could not locate library manager on script_engine (tried "
            "librarymanager, library_manager). This CODESYS build may not "
            "expose library repository operations."
        )

    # Method shape: lib_mgr.get_all_libraries() returns a sequence of
    # library handles. Each handle exposes name / version / company /
    # location / repository fields (probed via hasattr -- COM proxies hide
    # explicit-interface members from dir()).
    if not hasattr(lib_mgr, 'get_all_libraries'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "lib_mgr.get_all_libraries() not exposed by this CODESYS build."
        )

    # Enumerate repositories first so we can group results sensibly.
    repos_by_name = {}
    if hasattr(lib_mgr, 'repositories'):
        try:
            repos = lib_mgr.repositories
            if callable(repos):
                repos = repos()
            if repos is not None:
                for r in repos:
                    rname = None
                    for nattr in ('get_name', 'name'):
                        if hasattr(r, nattr):
                            try:
                                v = getattr(r, nattr)
                                rname = v() if callable(v) else v
                            except Exception:
                                pass
                            break
                    rloc = None
                    for lattr in ('get_location', 'location', 'path'):
                        if hasattr(r, lattr):
                            try:
                                v = getattr(r, lattr)
                                rloc = v() if callable(v) else v
                            except Exception:
                                pass
                            break
                    key = str(rname) if rname is not None else '?'
                    repos_by_name[key] = {
                        u'name': _to_unicode(key),
                        u'location': _to_unicode(rloc) if rloc else None,
                        u'libraries': [],
                    }
        except Exception as repos_err:
            print("WARN: could not enumerate repositories: %s" % repos_err)

    # If no repositories enumerated, use a single 'default' bucket so the
    # output shape is still consistent.
    if not repos_by_name:
        repos_by_name['(default)'] = {
            u'name': u'(default)',
            u'location': None,
            u'libraries': [],
        }

    name_filter_lower = NAME_FILTER.strip().lower() if NAME_FILTER else ''

    # Iterate libraries. The shape returned by get_all_libraries() varies:
    # may return library handles, or (library, repo) tuples. Probe.
    all_libs = lib_mgr.get_all_libraries()
    total_seen = 0
    total_kept = 0
    for entry in all_libs:
        total_seen += 1
        # Unpack possible shapes
        lib_handle = entry
        owning_repo_name = None
        if isinstance(entry, (tuple, list)):
            if len(entry) >= 1:
                lib_handle = entry[0]
            if len(entry) >= 2:
                second = entry[1]
                for nattr in ('get_name', 'name'):
                    if hasattr(second, nattr):
                        try:
                            v = getattr(second, nattr)
                            owning_repo_name = v() if callable(v) else v
                        except Exception:
                            pass
                        break

        # Extract library metadata
        name = None
        for nattr in ('get_name', 'name'):
            if hasattr(lib_handle, nattr):
                try:
                    v = getattr(lib_handle, nattr)
                    name = v() if callable(v) else v
                except Exception:
                    pass
                break
        if name is None:
            continue

        if name_filter_lower and name_filter_lower not in str(name).lower():
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

        company = None
        for cattr in ('company', 'get_company', 'vendor'):
            if hasattr(lib_handle, cattr):
                try:
                    v = getattr(lib_handle, cattr)
                    company = v() if callable(v) else v
                except Exception:
                    pass
                break

        location = None
        for lattr in ('location', 'path', 'get_path', 'file_path'):
            if hasattr(lib_handle, lattr):
                try:
                    v = getattr(lib_handle, lattr)
                    location = v() if callable(v) else v
                except Exception:
                    pass
                break

        # Resolve owning repo: prefer the value from the tuple, else
        # look at the lib_handle.repository attribute, else default bucket.
        if owning_repo_name is None and hasattr(lib_handle, 'repository'):
            try:
                rh = lib_handle.repository
                for nattr in ('get_name', 'name'):
                    if hasattr(rh, nattr):
                        try:
                            v = getattr(rh, nattr)
                            owning_repo_name = v() if callable(v) else v
                        except Exception:
                            pass
                        break
            except Exception:
                pass
        if owning_repo_name is None:
            owning_repo_name = list(repos_by_name.keys())[0]

        # Ensure the repo bucket exists (handles get_all_libraries returning
        # a repo we didn't enumerate above).
        bucket = repos_by_name.get(str(owning_repo_name))
        if bucket is None:
            bucket = {
                u'name': _to_unicode(owning_repo_name),
                u'location': None,
                u'libraries': [],
            }
            repos_by_name[str(owning_repo_name)] = bucket

        bucket[u'libraries'].append({
            u'name': _to_unicode(name),
            u'version': _to_unicode(str(version)) if version is not None else None,
            u'company': _to_unicode(company) if company else None,
            u'location': _to_unicode(location) if location else None,
        })
        total_kept += 1

    # Build output: list of repos with their libraries.
    output = []
    for k, v in repos_by_name.items():
        output.append(v)

    emit_result({u'repositories': output, u'totalLibraries': total_kept, u'totalScanned': total_seen})
    print("Repositories: %d. Libraries kept: %d / scanned: %d (filter=%r)" % (
        len(repos_by_name), total_kept, total_seen, name_filter_lower))
    print("SCRIPT_SUCCESS: Library repository enumerated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error listing library repository: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

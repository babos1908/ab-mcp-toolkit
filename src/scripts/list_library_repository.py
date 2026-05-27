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

    # Build the iteration pool. PRIMARY path: per-repo enumeration via
    # repository.get_libraries() -- empirically more reliable than
    # lib_mgr.get_all_libraries() which on AB 2.9 SP19 returned 355 entries
    # of an opaque CategoryHandle / GUID type that had neither .name nor
    # .get_name and produced 0 kept libraries downstream (2026-05-27).
    #
    # The pool is a list of (lib_handle, owning_repo_name) tuples. We try
    # per-repo first; if that yields nothing, fall back to the legacy
    # global enumeration.
    pool = []
    repo_methods_seen = []
    if hasattr(lib_mgr, 'repositories'):
        try:
            repos_iter = lib_mgr.repositories
            if callable(repos_iter):
                repos_iter = repos_iter()
            for r in repos_iter or []:
                rname = None
                for nattr in ('get_name', 'name'):
                    if hasattr(r, nattr):
                        try:
                            v = getattr(r, nattr)
                            rname = v() if callable(v) else v
                        except Exception:
                            pass
                        break
                rname_str = str(rname) if rname is not None else '(unknown repo)'
                # Probe each repo for a libraries accessor.
                got_from_this_repo = 0
                for laccess in ('get_libraries', 'libraries', 'get_all_libraries'):
                    if not hasattr(r, laccess):
                        continue
                    repo_methods_seen.append('%s.%s' % (rname_str, laccess))
                    try:
                        v = getattr(r, laccess)
                        libs_iter = v() if callable(v) else v
                        if libs_iter is None:
                            continue
                        for lh in libs_iter:
                            pool.append((lh, rname_str))
                            got_from_this_repo += 1
                        if got_from_this_repo > 0:
                            print("DEBUG: repo '%s' yielded %d libs via .%s" % (rname_str, got_from_this_repo, laccess))
                            break
                    except Exception as laerr:
                        print("DEBUG: %s.%s raised: %s" % (rname_str, laccess, laerr))
        except Exception as iter_err:
            print("DEBUG: per-repo enumeration failed: %s" % iter_err)

    # FALLBACK: global enumeration via lib_mgr.get_all_libraries(). Kept for
    # builds where per-repo iteration isn't exposed.
    if not pool:
        try:
            all_libs = lib_mgr.get_all_libraries()
            for entry in all_libs or []:
                if isinstance(entry, (tuple, list)) and len(entry) >= 1:
                    lh = entry[0]
                    rn = None
                    if len(entry) >= 2:
                        second = entry[1]
                        for nattr in ('get_name', 'name'):
                            if hasattr(second, nattr):
                                try:
                                    v = getattr(second, nattr)
                                    rn = v() if callable(v) else v
                                except Exception:
                                    pass
                                break
                    pool.append((lh, str(rn) if rn else None))
                else:
                    pool.append((entry, None))
        except Exception as ge:
            print("DEBUG: lib_mgr.get_all_libraries() fallback raised: %s" % ge)

    total_seen = len(pool)
    total_kept = 0
    # Diagnostic: dump the first entry's shape so a 0-kept run is debuggable
    # without recompiling. We log type + a probe of common attrs.
    if total_seen > 0:
        first_lh, _ = pool[0]
        probe_attrs = ('get_name', 'name', 'version', 'get_version', 'company', 'get_company',
                       'location', 'path', 'get_path', 'file_path', 'repository', 'identifier',
                       'placeholder', 'effective_resolution')
        present = [a for a in probe_attrs if hasattr(first_lh, a)]
        print("DEBUG: first pool entry: type=%s, hasattr present=%s" % (
            type(first_lh).__name__, present))

    skipped_no_name = 0
    for entry in pool:
        lib_handle, owning_repo_name = entry

        # Extract library metadata. Probe a broader name attribute set
        # since AB 2.9 SP19 exposes name only on identifier/placeholder
        # sub-objects on some builds.
        name = None
        for nattr in ('get_name', 'name', 'identifier', 'display_name'):
            if hasattr(lib_handle, nattr):
                try:
                    v = getattr(lib_handle, nattr)
                    name = v() if callable(v) else v
                except Exception:
                    pass
                if name is not None:
                    break
        # Some builds expose lib_handle.identifier as an object with .name
        if name is None and hasattr(lib_handle, 'identifier'):
            try:
                ident = lib_handle.identifier
                if hasattr(ident, 'name'):
                    name = ident.name
            except Exception:
                pass
        # Fallback: parse from file path basename when name accessor missing
        if name is None:
            for pattr in ('location', 'path', 'get_path', 'file_path'):
                if hasattr(lib_handle, pattr):
                    try:
                        v = getattr(lib_handle, pattr)
                        loc = v() if callable(v) else v
                        if loc:
                            import os as _os
                            base = _os.path.basename(str(loc))
                            # Strip extension (.library, .compiled-library, ...)
                            name = _os.path.splitext(base)[0] or None
                    except Exception:
                        pass
                    if name is not None:
                        break
        if name is None:
            skipped_no_name += 1
            continue

        if name_filter_lower and name_filter_lower not in str(name).lower():
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

    # Diagnostic: when skipped_no_name dominates total_seen the user wants to
    # know WHY 0 libs surfaced (typical when the COM proxy iterator returned
    # opaque category handles instead of library handles).
    diag = {}
    if skipped_no_name and total_kept == 0:
        diag = {
            u'note': u'All %d entries had no extractable name. Probably API-not-exposed on this build.' % skipped_no_name,
            u'firstEntryProbe': u'see DEBUG line in tool output',
            u'repoMethodsAttempted': [_to_unicode(x) for x in repo_methods_seen],
        }

    payload = {
        u'repositories': output,
        u'totalLibraries': total_kept,
        u'totalScanned': total_seen,
        u'skippedNoName': skipped_no_name,
    }
    if diag:
        payload[u'diagnostic'] = diag

    emit_result(payload)
    print("Repositories: %d. Libraries kept: %d / scanned: %d / skipped-no-name: %d (filter=%r)" % (
        len(repos_by_name), total_kept, total_seen, skipped_no_name, name_filter_lower))
    print("SCRIPT_SUCCESS: Library repository enumerated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error listing library repository: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

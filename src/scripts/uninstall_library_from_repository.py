import sys, scriptengine as script_engine, traceback

# Required: the library to uninstall. Either its title ('NexoMqttLib') or the
# full display string the repository uses ('NexoMqttLib, 1.0.10 (NEXO)').
LIBRARY_NAME = "{LIBRARY_NAME}"
# Required: version to uninstall (e.g. '1.0.10'), or '*' for ALL installed
# versions of the library (caller must confirm intent).
LIBRARY_VERSION = "{LIBRARY_VERSION}"
# Optional: only uninstall from this repository. Empty = any repository.
REPOSITORY_NAME = "{REPOSITORY_NAME}"

# 2026-10-18: this returned ERR_LIB_NOT_FOUND for a library that
# install_library_to_repository had installed seconds earlier. Two defects,
# both found by live probe on AB 2.9 SP19:
#   1. It matched on lib.get_name / lib.name. Repository entries (ManagedLib)
#      have neither -- the name is .title -- so nothing ever matched.
#   2. It called uninstall_library(library, repository). The working order
#      is uninstall_library(repository, library); the old candidates never
#      tried it, so even a match would have failed.
# Matching is on the EXACT title (case-insensitive), never a substring: asking
# for 'McpProbeLib' must not touch 'McpProbeLib2'. Every removal is read back
# through find_library; a library still installed afterwards fails the call.

try:
    print("DEBUG: uninstall_library_from_repository: Name='%s' Version='%s' Repo='%s'" % (
        LIBRARY_NAME, LIBRARY_VERSION, REPOSITORY_NAME))

    wanted = _to_unicode(LIBRARY_NAME).strip()
    version = _to_unicode(LIBRARY_VERSION).strip()
    repo_wanted = _to_unicode(REPOSITORY_NAME).strip()
    if not wanted:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("library name is required.")
    if not version:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("version is required (use '*' for all).")

    # A full display string carries its own version and company.
    w_title, w_ver, w_comp = split_library_display(wanted)
    if w_ver:
        if version not in (u'*', w_ver):
            print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
            raise ValueError(
                "libraryName '%s' names version %s but version='%s' was passed. "
                "Pass one or the other." % (wanted, w_ver, version))
        version = w_ver

    lib_mgr = repository_library_manager()
    if lib_mgr is None or not hasattr(lib_mgr, 'get_all_libraries'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError("The library manager (get_all_libraries) is not exposed on this build.")

    installed = repository_libraries(lib_mgr)
    t_low = w_title.lower()
    matches = []
    for e in installed:
        if (e['title'] or u'').lower() != t_low:
            continue
        if w_comp and (e['company'] or u'').lower() != w_comp.lower():
            continue
        if version != u'*' and e['version'] != version:
            continue
        matches.append(e)

    targets = []
    for e in matches:
        hit = find_installed_library(lib_mgr, e['display'])
        if hit is None:
            print("WARN: '%s' is listed but find_library cannot resolve it; skipped." % e['display'])
            continue
        lib, repo = hit
        rname = _to_unicode(_ref_attr(repo, 'name') or u'?')
        if repo_wanted and rname.lower() != repo_wanted.lower():
            continue
        targets.append({'display': e['display'], 'version': e['version'], 'repo': rname,
                        '_lib': lib, '_repo': repo})

    if not targets:
        same_title = installed_versions_of(lib_mgr, w_title)
        similar = sorted(set(e['title'] for e in installed
                             if e['title'] and t_low in e['title'].lower()))[:15]
        hint = []
        if same_title:
            hint.append("installed versions of '%s': %s" % (w_title, ', '.join(same_title)))
        elif similar:
            hint.append("no library is titled '%s'; similar titles: %s" % (w_title, ', '.join(similar)))
        else:
            hint.append("no installed library title contains '%s'" % w_title)
        print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_FOUND")
        raise RuntimeError(
            "No library matching name='%s' version='%s' repo='%s' is installed (%s)." % (
                w_title, version, repo_wanted or '(any)', '; '.join(hint)))

    uninstalled = []
    failures = []
    for t in targets:
        last_err = None
        called = None
        # Verified live first; the others only cover builds with another order.
        for args, label in ((( t['_repo'], t['_lib']), 'uninstall_library(repository, library)'),
                            ((t['_lib'], t['_repo']), 'uninstall_library(library, repository)'),
                            ((t['_lib'],), 'uninstall_library(library)')):
            try:
                lib_mgr.uninstall_library(*args)
                called = label
                break
            except Exception as ue:
                last_err = "%s: %s: %s" % (label, type(ue).__name__, ue)
        if called is None:
            failures.append({u'library': t['display'], u'repository': t['repo'],
                             u'error': _to_unicode(last_err)})
            continue
        if find_installed_library(lib_mgr, t['display']) is not None:
            failures.append({u'library': t['display'], u'repository': t['repo'],
                             u'error': u"%s returned, but find_library still finds it" % called})
            continue
        uninstalled.append({u'library': t['display'], u'version': t['version'],
                            u'repository': t['repo'], u'via': _to_unicode(called)})
        print("DEBUG: uninstalled %s from %s via %s (verified gone)" % (t['display'], t['repo'], called))

    emit_result({
        u'uninstalled': uninstalled,
        u'failures': failures,
        u'requestedName': wanted,
        u'requestedVersion': version,
    })
    if failures:
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "%d of %d librar%s still installed after the uninstall: %s%s" % (
                len(failures), len(targets), 'y is' if len(failures) == 1 else 'ies are',
                '; '.join('%s (%s)' % (f[u'library'], f[u'error']) for f in failures),
                ('. Removed: %s' % ', '.join(x[u'library'] for x in uninstalled)) if uninstalled else ''))
    print("Uninstalled %d library version(s), each verified gone." % len(uninstalled))
    print("SCRIPT_SUCCESS: Library uninstall complete.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error uninstalling library: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

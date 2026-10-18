import sys, scriptengine as script_engine, traceback

# Optional filter: only list libraries whose title contains this substring
# (case-insensitive). Empty = no filter.
NAME_FILTER = "{NAME_FILTER}"

# 2026-10-18: this listed every entry as nameless ("381 scanned, 0 kept") on
# AB 2.9 SP19. It probed get_name / name / identifier / display_name, but a
# repository entry (ManagedLib) carries its name in .title and its full string
# in .displayname -- no underscore. The shapes are documented once, next to
# repository_libraries() in _text_utils, which this and
# uninstall_library_from_repository now share. The output keeps its previous
# shape (repositories[].libraries[].name/version/company/location) and adds
# 'display', the exact string add_library / find_library expect.

try:
    print("DEBUG: list_library_repository: NameFilter='%s'" % NAME_FILTER)

    lib_mgr = repository_library_manager()
    if lib_mgr is None or not hasattr(lib_mgr, 'get_all_libraries'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "The library manager (script_engine.librarymanager.get_all_libraries) "
            "is not exposed on this build.")

    buckets = {}
    order = []
    try:
        for r in lib_mgr.repositories:
            rname = _to_unicode(_ref_attr(r, 'name') or u'?')
            root = _ref_attr(r, 'root_folder')
            buckets[rname] = {
                u'name': rname,
                u'location': _to_unicode(root) if root else None,
                u'editable': bool(_ref_attr(r, 'editable')),
                u'libraries': [],
            }
            order.append(rname)
    except Exception as repos_err:
        print("WARN: could not enumerate repositories: %s" % repos_err)
    if not buckets:
        buckets[u'(default)'] = {u'name': u'(default)', u'location': None, u'libraries': []}
        order.append(u'(default)')

    flt = _to_unicode(NAME_FILTER).strip().lower()
    installed = repository_libraries(lib_mgr)
    kept = 0
    for e in installed:
        if flt and flt not in (e['title'] or u'').lower():
            continue
        # An entry does not know its repository. With one repository there is
        # nothing to resolve; otherwise ask find_library, which returns it.
        if len(order) == 1:
            rname = order[0]
        else:
            hit = find_installed_library(lib_mgr, e['display'])
            rname = _to_unicode(_ref_attr(hit[1], 'name')) if hit else order[0]
        bucket = buckets.get(rname)
        if bucket is None:
            bucket = {u'name': rname, u'location': None, u'libraries': []}
            buckets[rname] = bucket
            order.append(rname)
        location = None
        if flt:
            # Cheap enough for a filtered listing; skipped for the full dump.
            try:
                location = _to_unicode(lib_mgr.get_file_path(e['_lib']))
            except Exception:
                location = None
        bucket[u'libraries'].append({
            u'name': e['title'],
            u'version': e['version'],
            u'company': e['company'],
            u'display': e['display'],
            u'location': location,
        })
        kept += 1

    for b in buckets.values():
        b[u'libraries'].sort(key=lambda x: ((x[u'name'] or u'').lower(), x[u'version'] or u''))

    payload = {
        u'repositories': [buckets[k] for k in order],
        u'totalLibraries': kept,
        u'totalScanned': len(installed),
        u'skippedNoName': len([e for e in installed if not e['title']]),
    }
    emit_result(payload)
    print("Repositories: %d. Libraries listed: %d / installed: %d (filter=%r)" % (
        len(order), kept, len(installed), flt))
    print("SCRIPT_SUCCESS: Library repository enumerated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error listing library repository: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

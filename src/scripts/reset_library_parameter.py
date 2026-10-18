import sys, scriptengine as script_engine, traceback

LIBRARY_NAME = "{LIBRARY_NAME}"
PARAMETER_NAME = "{PARAMETER_NAME}"

# reset_library_parameter
# -----------------------
# Live 2026-10-17 (AB 2.9 SP19): ref.parameters holds only the overrides and
# has no __delitem__/reset. Writing '' neutralises an override but does NOT
# delete it: the name stays listed and reading it raises KeyError, while the
# library default applies again (the downloadable size went back to the
# no-override baseline after save/reopen). library_parameter_overrides skips
# such tombstones, so "gone from the effective overrides" is the right check.
# The reference lookup is the shared lm.references one in _text_utils (the old
# get_children() walk found nothing on AB 2.9).

try:
    print("DEBUG: reset_library_parameter: Lib='%s' Param='%s'" % (LIBRARY_NAME, PARAMETER_NAME))

    if not LIBRARY_NAME or not PARAMETER_NAME:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("libraryName and parameterName are required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    entries = library_reference_entries(primary_project)
    entry, err = resolve_library_reference(entries, LIBRARY_NAME)
    if entry is None:
        print("SCRIPT_ERROR_CODE: %s" % ('ERR_BAD_INPUT' if err.startswith('Ambiguous') else 'ERR_LIB_NOT_FOUND'))
        raise RuntimeError(err)
    ref = entry['_ref']
    display = entry['display']
    if ref is None or library_parameter_names(ref) is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError("Reference '%s' exposes no library-parameter accessor on this build." % display)

    overrides = library_parameter_overrides(ref)
    key = find_name_ci(overrides.keys(), PARAMETER_NAME)
    if key is None:
        emit_result({
            u'library': display,
            u'parameter': _to_unicode(PARAMETER_NAME),
            u'resetVia': None,
            u'note': u"No override present: the parameter already uses the library default.",
            u'overrides': overrides,
        })
        print("SCRIPT_SUCCESS: No override to reset (already the library default).")
        sys.exit(0)

    previous = overrides[key]
    ref.parameters[key] = u''
    after = library_parameter_overrides(entry['_lm'].references[display])
    if find_name_ci(after.keys(), key) is not None:
        print("SCRIPT_ERROR_CODE: ERR_RESET_DID_NOT_STICK")
        raise RuntimeError(
            "Override '%s' of '%s' is still present after the reset (value %r). "
            "Nothing was saved." % (key, display, after.get(key)))

    save_project_checked(primary_project, "the library parameter reset")

    emit_result({
        u'library': display,
        u'parameter': key,
        u'previousOverride': previous,
        u'resetVia': u"parameters[name] = '' (neutralises the override: AB keeps the "
                     u"name listed but unreadable, and the library default applies)",
        u'overridesAfter': after,
    })
    print("SCRIPT_SUCCESS: Library parameter override reset.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error resetting library parameter: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

import sys, scriptengine as script_engine, traceback

# Optional: filter to a specific library name. Empty = all libraries in the
# consumer project's Library Managers.
LIBRARY_NAME = "{LIBRARY_NAME}"

# get_library_parameters
# ----------------------
# Field facts (AB 2.9 SP19, live 2026-10-17), see _text_utils:
#  * references come from lm.references across every Library Manager (the old
#    lm.get_children() walk is empty on AB 2.9 -> 'libraries: []');
#  * ref.parameters lists only the OVERRIDES stored in this project;
#  * the library's own parameters and defaults are read from the library
#    source (.library opened as a secondary project) when a libraryName filter
#    is given -- skipped for the unfiltered dump, which would otherwise open
#    every referenced library. A .compiled-library has no readable source.

try:
    print("DEBUG: get_library_parameters: Project='%s' LibraryName='%s'" % (
        PROJECT_FILE_PATH, LIBRARY_NAME))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    entries = library_reference_entries(primary_project)
    if not entries and not library_managers(primary_project):
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError("Library Manager node not found in project.")

    wanted = LIBRARY_NAME.strip()
    selected = entries
    if wanted:
        q = _norm_lib_query(wanted)
        selected = [e for e in entries
                    if q in (e['display'] or u'').lower()
                    or q in (e['resolution'] or u'').lower()
                    or q == (e['placeholderName'] or u'').lower()]
        if not selected:
            hit, err = resolve_library_reference(entries, wanted)
            if hit is None:
                print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_FOUND")
                raise RuntimeError(err)
            selected = [hit]

    libraries_out = []
    no_accessor = []
    for e in selected:
        ref = e['_ref']
        if ref is None or library_parameter_names(ref) is None:
            no_accessor.append(e['display'])
            continue
        overrides = library_parameter_overrides(ref)
        if not wanted and not overrides:
            # Unfiltered dump: list only references that carry overrides.
            continue
        rec = {
            u'libraryName': e['display'],
            u'reference': library_entry_public(e),
            u'resolvedVersion': e['version'],
            u'overrides': [{u'name': k, u'value': v} for k, v in sorted(overrides.items())],
        }
        params = []
        if wanted:
            decls, source, note = library_parameter_declarations(e)
            rec[u'declarationsSource'] = source
            if decls is None:
                rec[u'declarationsNote'] = _to_unicode(note)
            else:
                for d in decls:
                    ov_key = find_name_ci(overrides.keys(), d['name'])
                    params.append({
                        u'name': d['name'],
                        u'value': overrides[ov_key] if ov_key else d['defaultValue'],
                        u'defaultValue': d['defaultValue'],
                        u'isOverridden': ov_key is not None,
                        u'type': d['type'],
                        u'comment': d['comment'],
                        u'list': d.get('list'),
                    })
                declared = set(d['name'].lower() for d in decls)
                stray = [k for k in overrides if k.lower() not in declared]
                if stray:
                    rec[u'overridesNotDeclared'] = stray
        if not params:
            # No readable declarations: report what the project stores.
            params = [{u'name': k, u'value': v, u'defaultValue': None,
                       u'isOverridden': True, u'type': None, u'comment': None}
                      for k, v in sorted(overrides.items())]
        rec[u'parameters'] = params
        libraries_out.append(rec)

    out = {
        u'libraries': libraries_out,
        u'note': (u"ref.parameters exposes only the overrides stored in the project. "
                  u"Pass libraryName to also read the library's declared parameters "
                  u"and defaults from its source (not possible for a compiled library)."
                  if not wanted else
                  u"value = override when isOverridden, else the library default read "
                  u"from the library source."),
    }
    if no_accessor:
        out[u'noParameterAccessor'] = no_accessor

    emit_result(out)
    print("Libraries reported: %d." % len(libraries_out))
    print("SCRIPT_SUCCESS: Library parameters enumerated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error reading library parameters: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

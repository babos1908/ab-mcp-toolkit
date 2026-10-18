import sys, scriptengine as script_engine, traceback

LIBRARY_NAME = "{LIBRARY_NAME}"
PARAMETER_NAME = "{PARAMETER_NAME}"
PARAMETER_VALUE = """{PARAMETER_VALUE}"""

# set_library_parameter
# ---------------------
# Field facts (AB 2.9 SP19, live 2026-10-17 on a copy of an AC500 V3 consumer;
# details in _text_utils next to library_parameter_overrides):
#  * The references are found through lm.references across ALL Library
#    Managers -- the old lookup walked lm.get_children(), which is empty on
#    AB 2.9, so every reference was "not found" (e.g. 'AC500-V3-utilities-web').
#  * ref.parameters lists only existing OVERRIDES; params[name] = expr writes
#    one and is accepted for ANY name. The name is therefore validated
#    against the constants the library source declares when the source is
#    readable (a .library); for a .compiled-library it cannot be, and the
#    result says so (nameValidated=false) instead of pretending.
#  * Verified effect: gc_udiPageMax := 65536 on AC500-V3-utilities-web 1.0.0
#    persisted across save/reopen and changed the build's memory report.

try:
    print("DEBUG: set_library_parameter: Lib='%s' Param='%s' Value=%r" % (
        LIBRARY_NAME, PARAMETER_NAME, PARAMETER_VALUE))

    if not LIBRARY_NAME or not PARAMETER_NAME:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("libraryName and parameterName are required.")
    value_u = to_codesys_text(PARAMETER_VALUE).strip()
    if not value_u:
        # '' REMOVES the override on this API -- that is reset_library_parameter.
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("value is empty; to drop an override use reset_library_parameter.")

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
        raise RuntimeError(
            "Reference '%s' exposes no library-parameter accessor on this build "
            "(lm.references / ref.parameters)." % display)

    overrides = library_parameter_overrides(ref)
    decls, decl_source, decl_note = library_parameter_declarations(entry)

    # Pick the parameter's real name. IEC is case-insensitive; prefer the
    # library's own spelling, then an existing override's.
    param_name = None
    name_validated = False
    declared = None
    if decls is not None:
        hit = find_name_ci([d['name'] for d in decls], PARAMETER_NAME)
        if hit is not None:
            param_name = hit
            name_validated = True
            declared = [d for d in decls if d['name'] == hit][0]
        elif find_name_ci(overrides.keys(), PARAMETER_NAME) is None:
            print("SCRIPT_ERROR_CODE: ERR_LIB_PARAM_NOT_FOUND")
            raise RuntimeError(
                "Library '%s' declares no parameter '%s' (read from %s). Declared "
                "constants: %s. The scripting API would accept the name anyway and "
                "create an override that does nothing, so it was not written."
                % (display, PARAMETER_NAME, decl_source,
                   u', '.join(d['name'] for d in decls) or u'(none)'))
    if param_name is None:
        param_name = find_name_ci(overrides.keys(), PARAMETER_NAME) or PARAMETER_NAME.strip()
        if decls is None:
            print("WARN: parameter name not validated (%s)" % decl_note)

    previous = overrides.get(find_name_ci(overrides.keys(), param_name)) if overrides else None

    ref.parameters[param_name] = value_u
    print("DEBUG: %s.parameters[%s] = %r" % (display, param_name, value_u))

    # Read back through a FRESH reference object, so a wrapper caching the
    # value cannot hide a write that did not reach the project.
    readback = None
    try:
        fresh = entry['_lm'].references[display]
        readback = library_parameter_value(fresh, param_name)
    except Exception as rb_err:
        print("DEBUG: fresh re-read failed (%s); using the same reference" % rb_err)
        readback = library_parameter_value(ref, param_name)
    if readback is None or readback.strip() != value_u:
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "Parameter '%s' of '%s': wrote %r but read back %r. Nothing was saved."
            % (param_name, display, value_u, readback))

    save_project_checked(primary_project, "the library parameter override")

    result = {
        u'library': display,
        u'libraryManager': entry['manager'],
        u'parameter': _to_unicode(param_name),
        u'newValue': value_u,
        u'valueReadback': readback,
        u'previousOverride': previous,
        u'libraryDefault': declared['defaultValue'] if declared else None,
        u'type': declared['type'] if declared else None,
        u'nameValidated': name_validated,
    }
    if not name_validated:
        why = decl_note if decls is None else (
            "not declared in the library source, but an override with this name "
            "already existed")
        result[u'warning'] = (
            u"The parameter name could not be checked against the library (%s). "
            u"The API accepts any name, so a typo would be a silent no-op "
            u"override: confirm the effect in the build (compile_project memory "
            u"report) or in the AB Library Manager." % _to_unicode(why))
    emit_result(result)
    print("SCRIPT_SUCCESS: Library parameter override set.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error setting library parameter: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

import sys, scriptengine as script_engine, traceback

# Optional: filter to a specific library name. Empty = all libraries in the
# consumer project's Library Manager.
LIBRARY_NAME = "{LIBRARY_NAME}"

try:
    print("DEBUG: get_library_parameters: Project='%s' LibraryName='%s'" % (
        PROJECT_FILE_PATH, LIBRARY_NAME))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    # Locate the consumer-side Library Manager node (NOT the global
    # script_engine.librarymanager, which is the repo manager).
    lib_manager_node = None
    try:
        found = primary_project.find("Library Manager", True)
        if found:
            lib_manager_node = found[0]
    except Exception as ferr:
        print("DEBUG: find('Library Manager') failed: %s" % ferr)

    if lib_manager_node is None:
        # DFS fallback (some library projects expose differently)
        try:
            for child in primary_project.get_children(True):
                cname = getattr(child, 'get_name', lambda: '')()
                if cname and 'library manager' in cname.lower():
                    lib_manager_node = child
                    break
        except Exception:
            pass

    if lib_manager_node is None:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError("Library Manager node not found in project.")

    # Enumerate library references (children of the Library Manager node).
    references = []
    try:
        for child in lib_manager_node.get_children(False):
            references.append(child)
    except Exception as cerr:
        print("WARN: could not enumerate Library Manager children: %s" % cerr)

    name_filter_lower = LIBRARY_NAME.strip().lower() if LIBRARY_NAME else ''

    # The Library Parameters API on consumer-side library references is not
    # well-documented and varies across CODESYS V3.5 SPxx builds. Probe a
    # cascade of attribute names via hasattr (dir() is unreliable on COM
    # proxies). For each library reference we attempt:
    #
    #   - get_parameters() / parameters / get_all_parameters()
    #   - For each parameter: name/value/default_value/is_overridden/comment/type
    #
    # If nothing works on this build, we dump a diagnostic listing of
    # everything that DOES look queryable on the reference so the agent can
    # forward it to maintainers for API discovery.
    probe_attrs = (
        'parameters', 'parameter', 'get_parameters', 'get_all_parameters',
        'overridden_parameters', 'get_overridden_parameters',
        'placeholder', 'placeholders', 'library_parameters',
    )

    libraries_out = []
    diagnostic_dumps = []
    for ref in references:
        ref_name = None
        for nattr in ('get_name', 'name'):
            if hasattr(ref, nattr):
                try:
                    v = getattr(ref, nattr)
                    ref_name = v() if callable(v) else v
                except Exception:
                    pass
                break
        if ref_name is None:
            continue
        if name_filter_lower and name_filter_lower not in str(ref_name).lower():
            continue

        ref_version = None
        for vattr in ('version', 'resolved_version', 'get_version'):
            if hasattr(ref, vattr):
                try:
                    v = getattr(ref, vattr)
                    ref_version = v() if callable(v) else v
                except Exception:
                    pass
                break

        # Try the probe cascade for parameter access.
        params_collection = None
        accessor_used = None
        for attr in probe_attrs:
            if hasattr(ref, attr):
                try:
                    v = getattr(ref, attr)
                    candidate = v() if callable(v) else v
                    if candidate is not None:
                        params_collection = candidate
                        accessor_used = attr
                        break
                except Exception:
                    pass

        parameters_out = []
        if params_collection is None:
            # Diagnostic: list every method/attr starting with common prefixes
            # so we can identify the right API name from the dump.
            attrs_present = []
            for probe in (
                'parameter', 'parameters', 'get_parameter', 'set_parameter',
                'override', 'overridden', 'placeholder', 'resolve',
                'name', 'version', 'resolved_version', 'is_resolved',
            ):
                if hasattr(ref, probe):
                    attrs_present.append(probe)
            diagnostic_dumps.append({
                u'library': _to_unicode(ref_name),
                u'attrs_present': [_to_unicode(a) for a in attrs_present],
            })
        else:
            # Iterate the collection. Could be dict-like (by id) or list-like.
            param_ids = []
            try:
                param_ids = list(params_collection.keys())
            except Exception:
                try:
                    param_ids = list(iter(params_collection))
                except Exception as iter_err:
                    print("DEBUG: parameters collection not iterable: %s" % iter_err)

            for pid in param_ids:
                # The pid may itself BE the parameter object (list-like), or
                # the dict key. Probe.
                slot = pid
                slot_key = pid
                if hasattr(params_collection, '__getitem__'):
                    try:
                        slot = params_collection[pid]
                    except Exception:
                        pass

                # Extract fields.
                p_name = None
                for nattr in ('name', 'get_name', 'identifier'):
                    if hasattr(slot, nattr):
                        try:
                            v = getattr(slot, nattr)
                            p_name = v() if callable(v) else v
                        except Exception:
                            pass
                        break
                if p_name is None:
                    # If pid is a string, use it directly as the param name.
                    if isinstance(pid, (str, unicode)):
                        p_name = pid
                if p_name is None:
                    continue

                p_value = None
                for vattr in ('value', 'get_value', 'effective_value'):
                    if hasattr(slot, vattr):
                        try:
                            v = getattr(slot, vattr)
                            p_value = v() if callable(v) else v
                        except Exception:
                            pass
                        break

                p_default = None
                for dattr in ('default_value', 'default', 'get_default'):
                    if hasattr(slot, dattr):
                        try:
                            v = getattr(slot, dattr)
                            p_default = v() if callable(v) else v
                        except Exception:
                            pass
                        break

                p_overridden = None
                for oattr in ('is_overridden', 'overridden', 'has_override'):
                    if hasattr(slot, oattr):
                        try:
                            v = getattr(slot, oattr)
                            p_overridden = bool(v() if callable(v) else v)
                        except Exception:
                            pass
                        break
                # Fallback: if both value and default present, infer override.
                if p_overridden is None and p_value is not None and p_default is not None:
                    try:
                        p_overridden = (unicode(p_value) != unicode(p_default))
                    except Exception:
                        p_overridden = None

                p_type = None
                for tattr in ('type', 'data_type', 'get_type'):
                    if hasattr(slot, tattr):
                        try:
                            v = getattr(slot, tattr)
                            p_type = v() if callable(v) else v
                        except Exception:
                            pass
                        break

                p_comment = None
                for cattr in ('comment', 'description'):
                    if hasattr(slot, cattr):
                        try:
                            v = getattr(slot, cattr)
                            p_comment = v() if callable(v) else v
                        except Exception:
                            pass
                        break

                parameters_out.append({
                    u'name': _to_unicode(p_name),
                    u'value': _to_unicode(unicode(p_value)) if p_value is not None else None,
                    u'defaultValue': _to_unicode(unicode(p_default)) if p_default is not None else None,
                    u'isOverridden': p_overridden,
                    u'type': _to_unicode(unicode(p_type)) if p_type is not None else None,
                    u'comment': _to_unicode(unicode(p_comment)) if p_comment else None,
                    u'_key': _to_unicode(unicode(slot_key)),
                })

        libraries_out.append({
            u'libraryName': _to_unicode(ref_name),
            u'resolvedVersion': _to_unicode(unicode(ref_version)) if ref_version else None,
            u'accessorUsed': _to_unicode(accessor_used) if accessor_used else None,
            u'parameters': parameters_out,
        })

    out = {u'libraries': libraries_out}
    if diagnostic_dumps:
        out[u'diagnosticNoParameterApi'] = diagnostic_dumps
        out[u'note'] = (
            u"No known library-parameter accessor matched on one or more refs. "
            u"Forward 'diagnosticNoParameterApi' to maintainers so a working "
            u"API path can be wired."
        )

    emit_result(out)
    print("Libraries inspected: %d. Diagnostic dumps: %d." % (len(libraries_out), len(diagnostic_dumps)))
    if not libraries_out and diagnostic_dumps:
        # We found references but no working API. Still SUCCESS so the agent
        # can read the diagnostic and decide what to do.
        print("SCRIPT_SUCCESS: Library parameter accessor not exposed; diagnostic emitted.")
    else:
        print("SCRIPT_SUCCESS: Library parameters enumerated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error reading library parameters: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

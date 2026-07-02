import sys, scriptengine as script_engine, os, traceback

try:
    print("DEBUG: get_project_info: Project='%s'" % PROJECT_FILE_PATH)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    info = None
    info_source = None
    # Primary accessor: callable project.get_project_info() -- the one that
    # actually exists on AB 2.9 AC500 .project files (field-validated
    # 2026-06-12; the attribute probes below all come back empty there but
    # this method returns the info object with version/title/author/company/
    # description settable).
    if hasattr(primary_project, 'get_project_info'):
        try:
            cand = primary_project.get_project_info()
            if cand is not None:
                info = cand
                info_source = "primary_project.get_project_info()"
        except Exception as gpi_err:
            print("DEBUG: get_project_info() raised: %s" % gpi_err)
    for attr in ('project_info', 'project_information', 'information', 'projectinfo'):
        if info is not None:
            break
        if hasattr(primary_project, attr):
            try:
                cand = getattr(primary_project, attr)
                if cand is not None:
                    info = cand
                    info_source = "primary_project.%s" % attr
                    break
            except Exception:
                pass

    if info is None:
        # Recursive find reaches the node even when the plain children walk
        # does not descend into it (same class of issue as the old
        # task-configuration bug).
        try:
            found = primary_project.find('Project Information', True)
            if found:
                info = found[0]
                info_source = "find('Project Information')"
        except Exception:
            pass
    if info is None:
        try:
            for child in primary_project.get_children(True):
                cname = getattr(child, 'get_name', lambda: '')()
                if cname and cname.lower() in ('project information', 'projectinformation'):
                    info = child
                    info_source = "child node '%s'" % cname
                    break
        except Exception:
            pass

    if info is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Project Information node not accessible via ScriptEngine on this build."
        )

    # Probe each known field; missing fields are omitted from the result.
    candidates = {
        'version':     ('version',),
        'title':       ('title',),
        'author':      ('author',),
        'company':     ('company', 'company_name'),
        'description': ('description', 'description_short'),
        'released':    ('released',),
        # AB-specific: 'project_uri' / 'plc_type' / etc. don't have stable names
        # across SP versions; we omit them rather than guess.
    }
    out = {}
    for label, attrs in candidates.items():
        for a in attrs:
            if hasattr(info, a):
                try:
                    val = getattr(info, a)
                    # Convert to a representable type. .NET strings come through as
                    # unicode in IronPython 2.7; ints/bools pass through.
                    if val is None:
                        out[label] = None
                    elif isinstance(val, (int, long, float, bool)):
                        out[label] = val
                    else:
                        out[label] = _to_unicode(val)
                    break
                except Exception as ge:
                    out[label] = "ERR:%s" % ge
                    break

    emit_result(out)

    print("DEBUG: Project Information accessed via %s" % info_source)
    print("Fields returned: %s" % sorted(out.keys()))
    print("SCRIPT_SUCCESS: Project Information retrieved.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error reading Project Information for '%s': %s\n%s" % (
        PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

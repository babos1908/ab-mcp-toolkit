import sys, scriptengine as script_engine, os, traceback

# Empty-string sentinel = "do not touch this field". The MCP tool maps an
# omitted optional argument to "". For the description we also accept newlines.
VERSION     = """{VERSION}"""
TITLE       = """{TITLE}"""
AUTHOR      = """{AUTHOR}"""
COMPANY     = """{COMPANY}"""
DESCRIPTION = """{DESCRIPTION}"""
# 'true' / 'false' / '' (= leave the Released flag alone). Routed through
# opt_placeholder: an older server that does not know the parameter leaves the
# literal "{RELEASED}" here, which must read as "not provided".
RELEASED    = """{RELEASED}"""


def _released_wanted():
    v = opt_placeholder(RELEASED, 'RELEASED')
    if v is None:
        return None
    t = _to_unicode(v).strip().lower()
    if t in (u'true', u'1', u'yes', u'on'):
        return True
    if t in (u'false', u'0', u'no', u'off'):
        return False
    return None


def _set_released(info, want, applied, skipped):
    """Write info.released and verify it. Live 2026-10-17 (AB 2.9 SP19): a
    Released project is open READ-ONLY; clearing the flag in the same session
    makes save() work again, so released=False is applied BEFORE the other
    fields and the save."""
    if not hasattr(info, 'released'):
        skipped.append({'field': 'released', 'reason': 'attribute_not_found'})
        return
    try:
        before = bool(info.released)
    except Exception:
        before = None
    try:
        info.released = want
        rb = bool(info.released)
    except Exception as e:
        skipped.append({'field': 'released', 'reason': 'setattr_failed', 'error': str(e)})
        return
    if rb != want:
        skipped.append({'field': 'released', 'attribute': 'released', 'reason': 'write_did_not_stick',
                        'wrote': want, 'readback': rb})
        print("WARN: info.released did not stick: wrote %r, read back %r" % (want, rb))
    else:
        applied.append({'field': 'released', 'attribute': 'released', 'new_value': want,
                        'readback': rb, 'before': before})
        print("DEBUG: info.released = %r (verified, was %r)" % (want, before))

try:
    print("DEBUG: set_project_info: Project='%s'" % PROJECT_FILE_PATH)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    # The Project Information node is exposed in CODESYS V3 ScriptEngine via
    # a couple of possible entry points. Probe them in order.
    info = None
    info_source = None
    # Primary accessor: callable project.get_project_info() -- the one that
    # works on AB 2.9 AC500 .project files (field-validated 2026-06-12: the
    # attribute probes below come back empty there; this method returns the
    # info object with version/title/author/company/description settable).
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
            except Exception as ae:
                print("DEBUG: primary_project.%s raised: %s" % (attr, ae))

    if info is None:
        # Recursive find reaches the node even when the plain children walk
        # does not descend into it.
        try:
            found = primary_project.find('Project Information', True)
            if found:
                info = found[0]
                info_source = "find('Project Information')"
        except Exception as ferr:
            print("DEBUG: find('Project Information') failed: %s" % ferr)
    if info is None:
        # Alternative: the Project Information POU/node may be findable by name.
        try:
            for child in primary_project.get_children(True):
                cname = getattr(child, 'get_name', lambda: '')()
                if cname and cname.lower() in ('project information', 'projectinformation'):
                    info = child
                    info_source = "child node '%s'" % cname
                    break
        except Exception as cerr:
            print("DEBUG: child-search for Project Information failed: %s" % cerr)

    if info is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Project Information node not accessible via ScriptEngine on this build. "
            "Tried get_project_info(), primary_project.{project_info|project_information|"
            "information|projectinfo}, find('Project Information') and child node lookup."
        )
    print("DEBUG: Project Information accessed via %s" % info_source)

    # Map MCP field names to potential attribute names on the info object.
    # The order in each tuple matters: first present wins. We probe via
    # hasattr() not dir() (COM proxies hide explicit-interface members).
    field_map = [
        ('version',     ('version',),                   VERSION),
        ('title',       ('title',),                     TITLE),
        ('author',      ('author',),                    AUTHOR),
        ('company',     ('company', 'company_name'),    COMPANY),
        ('description', ('description', 'description_short'), DESCRIPTION),
    ]

    applied = []
    skipped = []
    released_wanted = _released_wanted()
    was_released = project_is_released(primary_project)
    if released_wanted is False:
        _set_released(info, False, applied, skipped)
    for label, attrs, value in field_map:
        if value == "":
            skipped.append({'field': label, 'reason': 'omitted'})
            continue
        target_attr = None
        for a in attrs:
            if hasattr(info, a):
                target_attr = a
                break
        if target_attr is None:
            skipped.append({'field': label, 'reason': 'attribute_not_found', 'tried': list(attrs)})
            continue
        try:
            # Decode bytes->unicode before writing to .NET String binding;
            # otherwise non-ASCII chars in author/company/description get
            # corrupted to NUL (see _text_utils.to_codesys_text).
            value_u = to_codesys_text(value)
            setattr(info, target_attr, value_u)
            # Read-back verification: a COM/explicit-interface proxy can accept
            # setattr and discard it ("lying success"). Re-read and compare;
            # treat a mismatch as a skipped (failed) field, not an applied one.
            rb = None
            try:
                rv = getattr(info, target_attr)
                rb = to_codesys_text(rv) if rv is not None else u''
            except Exception:
                rb = None
            if rb is not None and rb.strip() != value_u.strip():
                skipped.append({'field': label, 'attribute': target_attr,
                                'reason': 'write_did_not_stick',
                                'wrote': value_u, 'readback': rb})
                print("WARN: info.%s did not stick: wrote %r, read back %r" % (target_attr, value_u, rb))
            else:
                applied.append({'field': label, 'attribute': target_attr,
                                'new_value': value_u, 'readback': rb})
                print("DEBUG: info.%s = %r (verified)" % (target_attr, value_u))
        except Exception as set_err:
            skipped.append({'field': label, 'reason': 'setattr_failed', 'error': str(set_err)})

    if released_wanted is True:
        # Last, so every other field is in place before the project is marked
        # released (saving right after setting it works in the same session).
        _set_released(info, True, applied, skipped)

    # Save so the change persists. A Released project is read-only: the
    # helper turns that into ERR_PROJECT_READ_ONLY naming released=false as
    # the fix (unless this very call cleared the flag, which makes it work).
    try:
        save_project_checked(primary_project, "the Project Information update")
        print("DEBUG: Project saved after Project Information update.")
    except Exception as save_err:
        if is_read_only_error(save_err) or 'READ-ONLY' in str(save_err):
            raise
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        raise RuntimeError("Failed to save project after info update: %s" % save_err)
    if was_released is not None:
        print("Released flag: was %s, now %s" % (was_released, project_is_released(primary_project)))

    print("Applied fields: %d" % len(applied))
    for a in applied:
        print("  - %s (info.%s) -> %r" % (a['field'], a['attribute'], a['new_value']))
    if skipped:
        print("Skipped fields: %d" % len(skipped))
        for s in skipped:
            print("  - %s : %s" % (s['field'], s))
    # A field the caller asked for that did not take fails the call (fields
    # that did apply are saved above) -- same contract as set_task_parameter.
    failed = [s for s in skipped if s.get('reason') != 'omitted']
    if failed:
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "%d requested Project Information field(s) did not take: %s. Applied and "
            "saved: %s." % (len(failed), ', '.join(s['field'] for s in failed),
                            ', '.join(a['field'] for a in applied) or 'none'))
    print("SCRIPT_SUCCESS: Project Information updated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error updating Project Information for '%s': %s\n%s" % (
        PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

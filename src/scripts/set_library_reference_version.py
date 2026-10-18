import sys, scriptengine as script_engine, traceback

LIBRARY_NAME = "{LIBRARY_NAME}"
NEW_VERSION = "{NEW_VERSION}"  # exact version string (e.g. '1.0.10') or '*' for latest

# set_library_reference_version
# -----------------------------
# 2026-10-18: the old script looked references up through
# lm.get_children(), which is empty on AB 2.9, so it found nothing; it then
# probed set_version() / version=, neither of which exists, and it swallowed a
# failed save as a WARN while reporting success. Rewritten on the mechanisms
# probed live on a copy of an AC500 V3 project (probe_mut / probe_more):
#
#  * PLACEHOLDER reference ('#MProtocol'): its version is not on the
#    reference, it is the project-level PLACEHOLDER REDIRECTION.
#    ref.set_redirection('MProtocol-library, 0.1.4 (ABB)') moves
#    effective_resolution immediately and persists across save/reopen;
#    'Title, * (Company)' floats to the newest installed version.
#    TRAP: set_redirection() to a version that is NOT installed is accepted
#    silently and leaves the reference unresolved (effective_resolution None).
#    So the target is checked with find_library BEFORE anything is written.
#  * MANAGED reference ('AC500-V3-utilities-ip, 1.0.2 (ABB)'): the version is
#    in its name and managed_library is read-only. remove_library(display) +
#    add_library('Title, version (Company)') works and persists; namespace,
#    qualified_only and optional are settable afterwards and are restored,
#    and any parameter overrides are re-applied with a read-back.
#    'Title, * (Company)' is a floating managed reference (resolves to the
#    newest, persists).
# System references (added by the device or a plug-in) are refused, as in
# remove_library. Nothing is saved unless the read-back confirms the change;
# on a failed change the previous state is restored in memory.

def _fresh(display):
    """Re-read the reference from the project (never trust a cached proxy)."""
    for e in library_reference_entries(primary_project):
        if e['display'].lower() == display.lower():
            return e
    return None

try:
    print("DEBUG: set_library_reference_version: Lib='%s' NewVersion='%s'" % (LIBRARY_NAME, NEW_VERSION))
    wanted = _to_unicode(LIBRARY_NAME).strip()
    req = _to_unicode(NEW_VERSION).strip()
    if not wanted or not req:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("libraryName and version are required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    entries = library_reference_entries(primary_project)
    entry, err = resolve_library_reference(entries, wanted)
    if entry is None:
        print("SCRIPT_ERROR_CODE: %s" % ('ERR_BAD_INPUT' if err.startswith('Ambiguous') else 'ERR_LIB_NOT_FOUND'))
        raise RuntimeError(err)
    display = entry['display']
    ref = entry['_ref']
    lm = entry['_lm']
    if ref is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError("Reference '%s' exposes no reference object (lm.references) on this build." % display)
    if entry['isSystem']:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise RuntimeError(
            "'%s' is a system reference (added by the device or a plug-in, "
            "system_library=True); refusing to change its version -- the device "
            "description decides it." % display)

    lib_mgr = repository_library_manager()
    if lib_mgr is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError("The library manager (find_library) is not exposed on this build.")

    if entry['isPlaceholder']:
        # ------------------------------------------------------ placeholder
        try:
            prev_redirect = ref.get_redirection()
        except Exception:
            prev_redirect = None
        prev_redirect = _to_unicode(prev_redirect) if prev_redirect else None
        prev_effective = _to_unicode(_ref_attr(ref, 'effective_resolution') or u'') or None
        basis = prev_redirect or prev_effective or _to_unicode(_ref_attr(ref, 'default_resolution') or u'') or None
        if not basis:
            print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_FOUND")
            raise RuntimeError(
                "Placeholder '%s' has no redirection and no resolution, so the "
                "library it stands for is unknown. Resolve it in AB (Library "
                "Manager > Placeholders) first." % display)
        title, _v, company = split_library_display(basis)
        target = u'%s, %s (%s)' % (title, req, company)

        hit = find_installed_library(lib_mgr, target)
        if hit is None:
            have = installed_versions_of(lib_mgr, title, company)
            print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_FOUND")
            raise RuntimeError(
                "'%s' is not installed, so '%s' was NOT redirected (AB would accept "
                "it and leave the reference unresolved). Installed: %s." % (
                    target, display, ', '.join(have) or 'no version of %s' % title))
        expected_effective = _to_unicode(_ref_attr(hit[0], 'displayname') or hit[0])

        if prev_redirect and prev_redirect.lower() == target.lower():
            emit_result({
                u'library': display, u'kind': u'placeholder',
                u'previousVersion': entry['version'], u'requestedVersion': req,
                u'effectiveVersion': entry['version'], u'redirection': prev_redirect,
                u'effectiveResolution': prev_effective, u'setVia': None,
                u'note': u'Already redirected there; nothing changed.',
            })
            print("SCRIPT_SUCCESS: Library reference already at the requested version.")
            sys.exit(0)

        ref.set_redirection(target)
        after = _fresh(display)
        try:
            got_redirect = _to_unicode(after['_ref'].get_redirection() or u'') if after else u''
        except Exception:
            got_redirect = u''
        got_effective = after['resolution'] if after else None
        if (got_redirect.lower() != target.lower() or not got_effective
                or got_effective.lower() != expected_effective.lower()):
            try:
                ref.set_redirection(prev_redirect)
            except Exception as rb:
                print("WARN: restoring the previous redirection failed: %s" % rb)
            print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
            raise RuntimeError(
                "Redirecting '%s' to '%s' did not take: redirection now %r, effective "
                "resolution %r (expected %r). The previous redirection was restored "
                "in memory and nothing was saved." % (
                    display, target, got_redirect, got_effective, expected_effective))

        save_project_checked(primary_project, "the library reference version change")
        emit_result({
            u'library': display, u'kind': u'placeholder',
            u'previousVersion': entry['version'], u'requestedVersion': req,
            u'effectiveVersion': split_library_display(got_effective)[1],
            u'previousRedirection': prev_redirect, u'redirection': got_redirect,
            u'previousResolution': prev_effective, u'effectiveResolution': got_effective,
            u'setVia': u'set_redirection',
        })
        print("SCRIPT_SUCCESS: Placeholder redirected to %s (resolves to %s)." % (target, got_effective))
        sys.exit(0)

    # ------------------------------------------------------------ managed
    title, cur_ver, company = split_library_display(display)
    if not company:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise RuntimeError("Cannot parse '%s' as 'Title, version (Company)'." % display)
    target = u'%s, %s (%s)' % (title, req, company)
    if target.lower() == display.lower():
        emit_result({
            u'library': display, u'kind': u'managed', u'previousVersion': cur_ver,
            u'requestedVersion': req, u'effectiveVersion': cur_ver, u'setVia': None,
            u'note': u'Already at that version; nothing changed.',
        })
        print("SCRIPT_SUCCESS: Library reference already at the requested version.")
        sys.exit(0)

    hit = find_installed_library(lib_mgr, target)
    if hit is None:
        have = installed_versions_of(lib_mgr, title, company)
        print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_FOUND")
        raise RuntimeError(
            "'%s' is not installed; '%s' was left unchanged. Installed: %s." % (
                target, display, ', '.join(have) or 'no version of %s' % title))
    expected_lib = _to_unicode(_ref_attr(hit[0], 'displayname') or hit[0])

    # Everything remove+add would lose.
    keep = {}
    for a in ('namespace', 'qualified_only', 'optional'):
        v = _ref_attr(ref, a)
        if v is not None:
            keep[a] = v
    overrides = library_parameter_overrides(ref)

    def _rollback(reason):
        try:
            cur = _fresh(target)
            if cur is not None:
                lm.remove_library(cur['display'])
            if _fresh(display) is None:
                lm.add_library(display)
            back = _fresh(display)
            if back is not None:
                for a, v in keep.items():
                    try:
                        setattr(back['_ref'], a, v)
                    except Exception:
                        pass
                for n, v in overrides.items():
                    try:
                        back['_ref'].parameters[n] = v
                    except Exception:
                        pass
                return "restored '%s' in memory" % display
            return "could NOT restore '%s'" % display
        except Exception as rb:
            return "rollback failed (%s)" % rb

    lm.remove_library(display)
    lm.add_library(target)
    new = _fresh(target)
    if new is None or new['_ref'] is None:
        state = _rollback('add failed')
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "add_library('%s') did not produce the reference; %s. Nothing was saved%s." % (
                target, state,
                '' if state.startswith('restored') else
                ' -- the open project is now WITHOUT this reference: close it without '
                'saving (close_project force=true) and reopen'))
    nref = new['_ref']

    problems = []
    restored = {}
    for a, v in keep.items():
        try:
            if _ref_attr(nref, a) != v:
                setattr(nref, a, v)
            got = _ref_attr(_fresh(target)['_ref'], a)
            if got != v:
                problems.append("%s: wanted %r, got %r" % (a, v, got))
            else:
                restored[a] = v
        except Exception as e:
            problems.append("%s: %s" % (a, e))
    reapplied = {}
    for n, v in overrides.items():
        try:
            nref.parameters[n] = v
            got = library_parameter_value(_fresh(target)['_ref'], n)
            if got is None or got.strip() != v.strip():
                problems.append("override %s: wanted %r, got %r" % (n, v, got))
            else:
                reapplied[n] = v
        except Exception as e:
            problems.append("override %s: %s" % (n, e))
    resolved = _to_unicode(_ref_attr(_fresh(target)['_ref'], 'managed_library') or u'') or None
    if not resolved or resolved.lower() != expected_lib.lower():
        problems.append("resolves to %r, expected %r" % (resolved, expected_lib))

    if problems:
        state = _rollback('verification failed')
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "Changing '%s' to '%s' did not fully take (%s); %s. Nothing was saved." % (
                display, target, '; '.join(problems), state))

    save_project_checked(primary_project, "the library reference version change")
    emit_result({
        u'library': target, u'kind': u'managed',
        u'previousReference': display, u'previousVersion': cur_ver,
        u'requestedVersion': req, u'effectiveVersion': split_library_display(resolved)[1],
        u'resolvesTo': resolved, u'restoredSettings': restored,
        u'reappliedOverrides': reapplied,
        u'setVia': u'remove_library + add_library',
    })
    print("SCRIPT_SUCCESS: Library reference changed to %s (resolves to %s)." % (target, resolved))
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error setting library reference version: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

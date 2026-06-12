import sys, scriptengine as script_engine, os, traceback

# remove_library
# --------------
# Removes a library REFERENCE from a project's Library Manager (the project
# stops referencing the library; the machine repository is untouched -- for
# that, see uninstall_library_from_repository).
#
# Mechanism (field-validated 2026-06-12 on an AC500 V3 consumer project):
# ScriptLibManObject exposes get_libraries(recursive: bool) -> IList[str] and
# remove_library(name: str) directly on the Library Manager object, and they
# work even on builds where the manager has 0 enumerable children (references
# are NOT child objects there, which is why delete_object can't reach them).
# Display names look like 'MyLib, * (Vendor)'; system references are
# '#'-prefixed and are refused as removal targets.

LIBRARY_NAME = "{LIBRARY_NAME}"

try:
    print("DEBUG: remove_library: Lib='%s' Project='%s'" % (LIBRARY_NAME, PROJECT_FILE_PATH))
    if not LIBRARY_NAME:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("libraryName is required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    lm = None
    try:
        found = primary_project.find('Library Manager', True)
        if found:
            lm = found[0]
    except Exception as find_err:
        print("DEBUG: find('Library Manager') raised: %s" % find_err)
    if lm is None:
        for child in primary_project.get_children(True):
            cname = getattr(child, 'get_name', lambda: '')()
            if cname and 'library manager' in cname.lower():
                lm = child
                break
    if lm is None:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError("Library Manager node not found in project.")

    if not hasattr(lm, 'get_libraries') or not hasattr(lm, 'remove_library'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Library Manager object does not expose get_libraries/remove_library "
            "on this build. Remove the reference from the AB UI (Library Manager "
            "-> right-click the reference -> Remove).")

    before = [_to_unicode(x) for x in lm.get_libraries(False)]
    print("DEBUG: references before: %s" % u', '.join(before))

    # Match: exact display string first, then case-insensitive substring on
    # the non-hidden references ('#'-prefixed = system, never auto-removed).
    wanted = LIBRARY_NAME.strip()
    target = None
    if wanted in before:
        target = wanted
    else:
        matches = [n for n in before
                   if not n.startswith(u'#') and wanted.lower() in n.lower()]
        if len(matches) == 1:
            target = matches[0]
        elif len(matches) > 1:
            print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
            raise RuntimeError(
                "Ambiguous libraryName '%s': matches %s. Pass the exact display "
                "string." % (wanted, u' | '.join(matches)))

    if target is None:
        print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_FOUND")
        raise RuntimeError(
            "No project reference matches '%s'. Current references: %s"
            % (wanted, u', '.join(before) if before else '(none)'))
    if target.startswith(u'#'):
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise RuntimeError(
            "'%s' is a system reference (hidden, '#'-prefixed); refusing to "
            "remove it -- doing so would break the target support." % target)

    lm.remove_library(target)
    print("DEBUG: remove_library('%s') returned." % target)

    after = [_to_unicode(x) for x in lm.get_libraries(False)]
    still_there = target in after
    if still_there:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "remove_library() returned but '%s' is still referenced. "
            "Remove it from the AB UI." % target)

    primary_project.save()
    print("DEBUG: project saved.")

    emit_result({
        u'removed': _to_unicode(target),
        u'referencesBefore': before,
        u'referencesAfter': after,
    })
    print("Removed library reference: %s" % target)
    print("SCRIPT_SUCCESS: Library reference removed.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error removing library reference '%s': %s\n%s" % (
        LIBRARY_NAME, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

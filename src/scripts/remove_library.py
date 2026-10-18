import sys, scriptengine as script_engine, os, traceback

# remove_library
# --------------
# Removes a library REFERENCE from a project's Library Manager (the project
# stops referencing the library; the machine repository is untouched -- for
# that, see uninstall_library_from_repository).
#
# Mechanism (field-validated 2026-06-12 and 2026-10-17 on AC500 V3 consumers):
# ScriptLibManObject.references / get_libraries() / remove_library() work even
# though the references are not child objects. The reference lookup and the
# placeholder-vs-system distinction live in _text_utils
# (library_reference_entries / resolve_library_reference).
#
# 2026-10-17 regression this fixes: the old script refused EVERY '#'-prefixed
# reference as "system", but '#' only marks a PLACEHOLDER. On a real AC500 V3
# project all user libraries added by name are placeholders ('#LogiQ',
# '#MProtocol', '#AC500-V3-library-MQTT'), so nothing could be removed. Only
# references with system_library=True (added implicitly by the device or a
# plug-in: IoDrv*, Standard, '#System_Visu*') are refused now.

LIBRARY_NAME = "{LIBRARY_NAME}"

try:
    print("DEBUG: remove_library: Lib='%s' Project='%s'" % (LIBRARY_NAME, PROJECT_FILE_PATH))
    if not LIBRARY_NAME:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("libraryName is required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    entries = library_reference_entries(primary_project)
    if not entries and not library_managers(primary_project):
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError("Library Manager node not found in project.")

    target, err = resolve_library_reference(entries, LIBRARY_NAME)
    if target is None:
        print("SCRIPT_ERROR_CODE: %s" % ('ERR_BAD_INPUT' if err.startswith('Ambiguous') else 'ERR_LIB_NOT_FOUND'))
        raise RuntimeError(err)

    display = target['display']
    if target['isSystem']:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise RuntimeError(
            "'%s' is a SYSTEM library reference (added implicitly by the device or "
            "a plug-in, system_library=True); refusing to remove it -- the device "
            "or plug-in needs it and would re-add it or stop building." % display)
    if target['isSystem'] is None and target['isPlaceholder']:
        # Builds without lm.references cannot tell a user placeholder from a
        # system one; keep the old conservative behaviour there.
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "'%s' is a placeholder and this build does not expose system_library "
            "to tell a user placeholder from a system one; remove it from the AB "
            "UI (Library Manager -> right-click -> Delete)." % display)

    lm = target['_lm']
    if not hasattr(lm, 'remove_library'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Library Manager object does not expose remove_library on this build. "
            "Remove the reference from the AB UI (Library Manager -> right-click "
            "the reference -> Delete).")

    before = [_to_unicode(x) for x in lm.get_libraries(False)]
    # remove_library wants the display name WITH the '#' for a placeholder
    # (the bare name raises KeyError -- live 2026-10-17).
    lm.remove_library(display)
    print("DEBUG: remove_library('%s') returned." % display)

    after = [_to_unicode(x) for x in lm.get_libraries(False)]
    if display in after:
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "remove_library() returned but '%s' is still referenced. "
            "Remove it from the AB UI." % display)

    save_project_checked(primary_project, "the library reference removal")
    print("DEBUG: project saved.")

    emit_result({
        u'removed': display,
        u'reference': library_entry_public(target),
        u'libraryManager': target['manager'],
        u'referencesBefore': before,
        u'referencesAfter': after,
    })
    print("Removed library reference: %s" % display)
    print("SCRIPT_SUCCESS: Library reference removed.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error removing library reference '%s': %s\n%s" % (
        LIBRARY_NAME, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

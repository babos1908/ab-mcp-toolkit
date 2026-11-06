import sys, scriptengine as script_engine, os, traceback

# The version release_library_version is about to give the library.
VERSION = "{VERSION}"

# library_release_precheck -- run by release_library_version (2.0.0) BEFORE
# it touches the library: the target number must be MAJOR.MINOR.PATCH and
# must not be installed yet. Refusing here, not at the install step, means a
# taken number leaves the library file exactly as it was -- not bumped,
# rebuilt and marked Released (read-only) under a number it cannot have.

try:
    lib_path = clean_path(PROJECT_FILE_PATH)
    if not os.path.exists(lib_path):
        print("SCRIPT_ERROR_CODE: ERR_PROJECT_NOT_FOUND")
        raise RuntimeError("Library file not found: %s" % PROJECT_FILE_PATH)
    if not is_semver_core(VERSION):
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise RuntimeError(
            "Version '%s' is not MAJOR.MINOR.PATCH (three numbers, no leading zeros; "
            "AB's Version field takes numbers only and a fourth number is a defect)." % VERSION)

    ident = library_identity(lib_path)
    target = u'%s, %s (%s)' % (ident['title'], VERSION, ident['company'])
    lib_mgr = repository_library_manager()
    if lib_mgr is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError("The library manager (script_engine.librarymanager) is not exposed on this build.")
    hit = find_installed_library(lib_mgr, target)
    installed = installed_versions_of(lib_mgr, ident['title'], ident['company'])

    emit_result({
        u'library': target, u'title': ident['title'], u'company': ident['company'],
        u'currentVersion': ident['version'], u'currentlyReleased': ident['released'],
        u'targetInstalled': hit is not None, u'installedVersions': installed,
    })
    if hit is not None:
        print("SCRIPT_ERROR_CODE: ERR_LIB_EXISTS")
        raise RuntimeError(
            "'%s' is already installed: a released version never changes. Pick a number "
            "that is not taken (installed: %s). Nothing was changed." % (target, ', '.join(installed)))
    print("SCRIPT_SUCCESS: %s is free to release (currently %s, Released=%s)." % (
        target, ident['version'], ident['released']))
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Library release precheck failed: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

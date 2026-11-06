import sys, scriptengine as script_engine, os, traceback

# Optional name of the target repository. If empty: a repository named like
# 'user' / 'default', else the first one enumerated ('System' on AB 2.9).
REPOSITORY_NAME = "{REPOSITORY_NAME}"

# install_library_to_repository -- 2.0.0
#
# Until 1.0.0 this passed overwrite=True and was documented as "overwrites
# the same version": it silently replaced an installed name+version with
# different content. The versioning rule (SemVer 2.0.0, global CLAUDE.md)
# forbids exactly that: a library is installed already Released, and every
# installed build has its own number -- a defect found later is the next
# PATCH. Now:
#   * not Released                       -> ERR_LIB_NOT_RELEASED, nothing done;
#   * version not MAJOR.MINOR.PATCH      -> ERR_BAD_INPUT;
#   * same number installed, same bytes  -> success, nothing to do;
#   * same number installed, other bytes -> ERR_LIB_EXISTS, nothing done;
#   * otherwise install with overwrite=False, then read it back.
# The library's identity comes from its Project Information, read through
# library_identity() -- an already-open project is used as is, otherwise the
# file is opened as a SECONDARY project, so the user's primary project is
# never switched. Live AB 2.9 facts: see "library releases" in _text_utils.

try:
    print("DEBUG: install_library_to_repository: Project='%s' Repository='%s'" % (
        PROJECT_FILE_PATH, REPOSITORY_NAME))
    lib_path = clean_path(PROJECT_FILE_PATH)
    if not os.path.exists(lib_path):
        print("SCRIPT_ERROR_CODE: ERR_PROJECT_NOT_FOUND")
        raise RuntimeError("Library file not found: %s" % PROJECT_FILE_PATH)
    if not lib_path.lower().endswith('.library'):
        print("WARN: path does not end with .library; the repository may reject it.")

    ident = library_identity(lib_path)
    display = ident['display']
    print("DEBUG: identity: %s (Released=%s, open as primary=%s, dirty=%s)" % (
        display, ident['released'], ident['primary'], ident['dirty']))

    if not ident['released']:
        print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_RELEASED")
        raise RuntimeError(
            "'%s' is not marked Released, so it was NOT installed. A library is "
            "installed already Released, with a number of its own. Mark the final "
            "version Released first -- set_project_info(released=true) -- or let "
            "release_library_version do the whole sequence." % display)
    if not is_semver_core(ident['version']):
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise RuntimeError(
            "'%s': version '%s' is not MAJOR.MINOR.PATCH (three numbers, no leading "
            "zeros; a fourth number is a defect). Fix it with set_project_info first."
            % (display, ident['version']))

    # Flush unsaved edits so the file is what gets checked and installed. A
    # library released in this session still saves; one OPENED Released is
    # read-only and gets ERR_PROJECT_READ_ONLY -- its edits could not be
    # installed anyway.
    if ident['primary'] and ident['dirty'] and ident['project'] is not None:
        save_project_checked(ident['project'], "the library before installing it")
        print("DEBUG: unsaved changes saved before install")

    lib_mgr = repository_library_manager()
    if lib_mgr is None or not hasattr(lib_mgr, 'install_library'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError("The library manager (script_engine.librarymanager.install_library) is not exposed on this build.")

    src_sha = file_sha256(lib_path)
    hit = find_installed_library(lib_mgr, display)
    if hit is not None:
        inst_path = None
        try:
            inst_path = _to_unicode(lib_mgr.get_file_path(hit[0]))
        except Exception as gp_err:
            print("DEBUG: get_file_path failed: %s" % gp_err)
        same = bool(inst_path) and os.path.exists(inst_path) and file_sha256(inst_path) == src_sha
        if same:
            emit_result({
                u'library': display, u'installed': False, u'alreadyInstalled': True,
                u'repository': _to_unicode(_ref_attr(hit[1], 'name')), u'installedPath': inst_path,
                u'sha256': src_sha,
            })
            print("'%s' is already installed from this very build (identical file); nothing to do." % display)
            print("SCRIPT_SUCCESS: Library already installed (same build).")
            sys.exit(0)
        print("SCRIPT_ERROR_CODE: ERR_LIB_EXISTS")
        raise RuntimeError(
            "'%s' is already installed with DIFFERENT content%s. A released version "
            "never changes -- not even for the Released flag alone. Give this build "
            "the next number (a fix is the next PATCH) and install that." % (
                display, (" (%s)" % inst_path) if inst_path else ""))

    # --- target repository ---
    repo_handles = []
    try:
        for r in lib_mgr.repositories:
            repo_handles.append((_to_unicode(_ref_attr(r, 'name') or u'?'), r))
    except Exception as re_err:
        print("DEBUG: repositories not enumerable: %s" % re_err)
    target_repo = None
    target_repo_name = None
    if REPOSITORY_NAME:
        for n, r in repo_handles:
            if n.strip().lower() == REPOSITORY_NAME.strip().lower():
                target_repo, target_repo_name = r, n
                break
        if target_repo is None:
            print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
            raise RuntimeError("Repository '%s' not found; available: %s" % (
                REPOSITORY_NAME, [h[0] for h in repo_handles]))
    if target_repo is None:
        for n, r in repo_handles:
            if n.strip().lower() in ('user', 'users', 'default', 'user repository', 'default repository'):
                target_repo, target_repo_name = r, n
                break
    if target_repo is None and repo_handles:
        target_repo_name, target_repo = repo_handles[0]
    if target_repo is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError("No library repository is reachable from the scripting API on this build.")

    # --- install, never overwriting ---
    # install_library(String filepath, ILibRepository repository, Boolean
    # overwrite) -- the .NET signature seen in a live stack trace. With
    # overwrite=False AB itself refuses a number that is already there.
    try:
        new_lib = lib_mgr.install_library(lib_path, target_repo, False)
    except Exception as ie:
        if 'already exists' in _to_unicode(ie).lower():
            print("SCRIPT_ERROR_CODE: ERR_LIB_EXISTS")
            raise RuntimeError("'%s' is already installed (AB refused to overwrite it). "
                               "Give this build the next number." % display)
        raise

    # --- read it back ---
    after = find_installed_library(lib_mgr, display)
    inst_path = None
    if after is not None:
        try:
            inst_path = _to_unicode(lib_mgr.get_file_path(after[0]))
        except Exception:
            inst_path = None
    if after is None or not inst_path or not os.path.exists(inst_path) or file_sha256(inst_path) != src_sha:
        installed_as = _to_unicode(_ref_attr(new_lib, 'displayname') or new_lib)
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "install_library returned %s, but '%s' is not in the repository with this "
            "file's content (found: %s)." % (installed_as, display, inst_path))

    emit_result({
        u'library': display, u'installed': True, u'alreadyInstalled': False,
        u'repository': _to_unicode(target_repo_name), u'installedPath': inst_path,
        u'sha256': src_sha,
    })
    print("Library installed: %s -> %s (repository %s), verified byte for byte." % (
        display, inst_path, target_repo_name))
    print("SCRIPT_SUCCESS: Library installed to repository.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error installing library to repository (project='%s', repo='%s'): %s\n%s" % (
        PROJECT_FILE_PATH, REPOSITORY_NAME, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

import sys, scriptengine as script_engine, os, traceback

# Optional name of the target repository. If empty, the script uses the
# default / user repository (the same one the "Save Project and Install
# into Library Repository" UI menu writes to).
REPOSITORY_NAME = "{REPOSITORY_NAME}"

try:
    print("DEBUG: install_library_to_repository: Project='%s' Repository='%s'" % (
        PROJECT_FILE_PATH, REPOSITORY_NAME))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    if not PROJECT_FILE_PATH.lower().endswith('.library'):
        # We allow non-.library extensions but warn -- the underlying API
        # may reject them.
        print("WARN: Project path does not end with .library. The repository may reject the install.")

    # Save the project FIRST so the install reflects the latest edits.
    try:
        if hasattr(primary_project, 'save'):
            primary_project.save()
            print("DEBUG: primary_project.save() succeeded before install.")
    except Exception as save_err:
        raise RuntimeError("Failed to save project before install: %s" % save_err)

    # --- Locate the repository ---
    # CODESYS V3 / AB 2.9 exposes library repositories at multiple possible
    # entry points depending on build. Probe in order:
    #   1. script_engine.librarymanager.repositories  (object collection)
    #   2. script_engine.repositories                  (top-level alias)
    #   3. fall back to "any first repo that has install()"
    #
    # IMPORTANT: do NOT rely on dir() to enumerate -- IronPython proxies to
    # the underlying .NET COM objects often hide explicit-interface members
    # from dir(). Probe known attribute names via hasattr() instead.

    repos = None
    repos_source = None
    for path_chain in (
        ('librarymanager', 'repositories'),
        ('librarymanager', 'library_repositories'),
        ('library_manager', 'repositories'),
        ('repositories',),
        ('library_repositories',),
    ):
        obj = script_engine
        ok = True
        for attr in path_chain:
            if not hasattr(obj, attr):
                ok = False
                break
            obj = getattr(obj, attr)
        if ok and obj is not None:
            repos = obj
            repos_source = '.'.join(('script_engine',) + path_chain)
            print("DEBUG: Repository entry point: %s" % repos_source)
            break

    if repos is None:
        # Last resort: maybe librarymanager itself has install_library
        if hasattr(script_engine, 'librarymanager') and hasattr(
            script_engine.librarymanager, 'install_library'
        ):
            print("DEBUG: Falling back to script_engine.librarymanager.install_library()")
            result = script_engine.librarymanager.install_library(PROJECT_FILE_PATH)
            print("DEBUG: librarymanager.install_library returned: %s" % result)
            print("Library installed (via librarymanager.install_library): %s" % PROJECT_FILE_PATH)
            print("SCRIPT_SUCCESS: Library installed.")
            sys.exit(0)
        raise RuntimeError(
            "Could not locate a library repository entry point on this CODESYS build. "
            "Tried script_engine.librarymanager.repositories, "
            "script_engine.repositories, and script_engine.librarymanager.install_library; "
            "none are present. If you know the correct API path for AB 2.9, please add it "
            "to install_library_to_repository.py."
        )

    # --- Pick the target repository ---
    # `repos` is a collection-like object. Try to iterate; pick a repository
    # matching REPOSITORY_NAME if provided, otherwise the first one (or one
    # named "User" / "Default").
    candidate = None
    fallback = None
    candidates_seen = []
    try:
        for repo in repos:
            rname = None
            for attr in ('get_name', 'name'):
                if hasattr(repo, attr):
                    try:
                        rname = getattr(repo, attr)() if callable(getattr(repo, attr)) else getattr(repo, attr)
                    except Exception:
                        rname = None
                    break
            rloc = None
            for attr in ('get_location', 'location', 'path'):
                if hasattr(repo, attr):
                    try:
                        rloc = getattr(repo, attr)() if callable(getattr(repo, attr)) else getattr(repo, attr)
                    except Exception:
                        rloc = None
                    break
            candidates_seen.append({'name': rname, 'location': rloc})
            if REPOSITORY_NAME and rname and str(rname).strip().lower() == REPOSITORY_NAME.strip().lower():
                candidate = repo
                print("DEBUG: Selected repository by exact name match: '%s' at %s" % (rname, rloc))
                break
            if fallback is None and rname is not None:
                # Prefer one named like "User", "Default", or just take the first
                if str(rname).strip().lower() in ('user', 'default', 'user repository', 'default repository'):
                    fallback = repo
            if fallback is None:
                fallback = repo
    except TypeError:
        # Not iterable. Maybe a singleton; treat as itself.
        if hasattr(repos, 'install'):
            candidate = repos
            print("DEBUG: Repos object is a singleton with install(); using it directly.")

    if candidate is None:
        candidate = fallback
    if candidate is None:
        raise RuntimeError(
            "Repository collection at %s contained no usable entries. "
            "Candidates seen: %s" % (repos_source, candidates_seen)
        )

    chosen_name = None
    for attr in ('get_name', 'name'):
        if hasattr(candidate, attr):
            try:
                chosen_name = getattr(candidate, attr)() if callable(getattr(candidate, attr)) else getattr(candidate, attr)
            except Exception:
                pass
            break
    print("DEBUG: Target repository: '%s' (REPOSITORY_NAME='%s' requested)" % (chosen_name, REPOSITORY_NAME))

    # --- Install ---
    # Try install(project_object) first (preferred -- runs validation), then
    # install(path) as fallback. Some builds expose install_library(path).
    installed_via = None
    last_err = None
    for fn_name in ('install', 'install_library'):
        if not hasattr(candidate, fn_name):
            continue
        fn = getattr(candidate, fn_name)
        # Try with project object first
        try:
            fn(primary_project)
            installed_via = "%s(primary_project)" % fn_name
            break
        except Exception as e1:
            last_err = "%s(primary_project): %s" % (fn_name, e1)
            print("DEBUG: %s" % last_err)
            try:
                fn(PROJECT_FILE_PATH)
                installed_via = "%s(PROJECT_FILE_PATH)" % fn_name
                break
            except Exception as e2:
                last_err = "%s(PROJECT_FILE_PATH): %s" % (fn_name, e2)
                print("DEBUG: %s" % last_err)

    if installed_via is None:
        raise RuntimeError(
            "Could not install library '%s' to repository '%s'. Tried install() and "
            "install_library() with both project object and path arguments. Last error: %s" % (
                PROJECT_FILE_PATH, chosen_name, last_err)
        )

    print("Library installed (via %s): %s" % (installed_via, PROJECT_FILE_PATH))
    print("Repository: %s" % chosen_name)
    print("SCRIPT_SUCCESS: Library installed to repository.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error installing library to repository (project='%s', repo='%s'): %s\n%s" % (
        PROJECT_FILE_PATH, REPOSITORY_NAME, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

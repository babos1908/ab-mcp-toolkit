import sys, scriptengine as script_engine, os, traceback

# Optional name of the target repository. If empty, the script tries the
# manager-level install_library() first (which internally picks the default
# writable repository) and falls back to per-repo install only if needed.
REPOSITORY_NAME = "{REPOSITORY_NAME}"

try:
    print("DEBUG: install_library_to_repository: Project='%s' Repository='%s'" % (
        PROJECT_FILE_PATH, REPOSITORY_NAME))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    if not PROJECT_FILE_PATH.lower().endswith('.library'):
        print("WARN: Project path does not end with .library. The repository may reject the install.")

    # Save the project FIRST so the install reflects the latest edits.
    try:
        if hasattr(primary_project, 'save'):
            primary_project.save()
            print("DEBUG: primary_project.save() succeeded before install.")
    except Exception as save_err:
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        raise RuntimeError("Failed to save project before install: %s" % save_err)

    # --- Locate the library manager ---
    lib_mgr = None
    lib_mgr_source = None
    for attr in ('librarymanager', 'library_manager'):
        if hasattr(script_engine, attr):
            try:
                cand = getattr(script_engine, attr)
                if cand is not None:
                    lib_mgr = cand
                    lib_mgr_source = "script_engine.%s" % attr
                    break
            except Exception:
                pass

    if lib_mgr is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Could not locate library manager on script_engine (tried "
            "librarymanager and library_manager). The CODESYS Scripting API "
            "on this AB build may not expose library repository operations."
        )
    print("DEBUG: Library manager: %s" % lib_mgr_source)

    # --- Diagnostic: probe all callable accessors on the library manager ---
    # Empirical 2026-05-26 on AB 2.9 Standard against NexoMqttLib.library:
    # script_engine.librarymanager.repositories enumerated only the read-only
    # "System" repository, and the repo object did NOT expose install() or
    # install_library() at all (Last error: None when both were tried).
    # So we now try the MANAGER-level install_library() first (which selects
    # the default writable repository internally) and only fall back to
    # iterating .repositories if that path is missing.
    mgr_probe_names = (
        'install_library', 'install', 'add_library', 'import_library',
        'install_project_as_library', 'save_as_library',
        'repositories', 'user_repository', 'default_repository',
        'find_repository',
    )
    mgr_present = [n for n in mgr_probe_names if hasattr(lib_mgr, n)]
    print("DEBUG: lib_mgr methods/attrs present (via hasattr probe): %s" % mgr_present)

    install_log = []
    new_lib = None

    # --- Pre-scan repositories so we have a repo object handy for the
    # 2-arg lib_mgr.install_library(path, repo) signature ---
    # Empirical 2026-05-26 on AB 2.9 Standard: install_library(str) raised
    #     TypeError: Value cannot be null. Parameter name: repo
    # which proved the signature is install_library(file_path, repo). Only
    # the "System" repo was enumerated -- but it's writable in AB so we use
    # it as the install target when REPOSITORY_NAME is unspecified.
    repos = None
    if hasattr(lib_mgr, 'repositories'):
        try:
            repos = lib_mgr.repositories
            if callable(repos):
                repos = repos()
        except Exception as re:
            install_log.append("lib_mgr.repositories access: %s" % re)
            repos = None

    repo_handles = []  # list of (name, repo_object)
    if repos is not None:
        try:
            for repo in repos:
                rname = None
                for nattr in ('get_name', 'name'):
                    if hasattr(repo, nattr):
                        try:
                            val = getattr(repo, nattr)
                            rname = val() if callable(val) else val
                        except Exception:
                            pass
                        break
                repo_handles.append((str(rname) if rname is not None else '?', repo))
        except TypeError as iter_err:
            install_log.append("repos iteration failed: %s" % iter_err)

    # Pick the target repo. If REPOSITORY_NAME specified, exact match.
    # Otherwise prefer one named like 'user' / 'default'; fall back to the
    # first repo enumerated (typically 'System' on AB 2.9).
    target_repo = None
    target_repo_name = None
    if REPOSITORY_NAME:
        for n, r in repo_handles:
            if n.strip().lower() == REPOSITORY_NAME.strip().lower():
                target_repo = r
                target_repo_name = n
                break
        if target_repo is None:
            install_log.append(
                "repository '%s' not found among enumerated %s; falling back" %
                (REPOSITORY_NAME, [h[0] for h in repo_handles])
            )
    if target_repo is None:
        for n, r in repo_handles:
            if n.strip().lower() in ('user', 'users', 'default', 'user repository', 'default repository'):
                target_repo = r
                target_repo_name = n
                break
    if target_repo is None and repo_handles:
        target_repo_name, target_repo = repo_handles[0]

    print("DEBUG: Repositories enumerated: %s" % [h[0] for h in repo_handles])
    print("DEBUG: Target repository: '%s'" % target_repo_name)

    # --- Path A: manager.install_library(filepath, repository, overwrite) ---
    # Empirical 2026-05-26 stack-trace from AB 2.9 SP19 confirmed the .NET
    # signature is:
    #   LibManager.install_library(String filepath, ILibRepository repository,
    #                              Boolean overwrite)
    # Default overwrite is False, which raises
    #   System.IO.IOException: Library already exists
    # when a same-name+version library is already installed -- exactly what
    # we want to AVOID, since the whole point of this tool is to update the
    # library after edits. We pass overwrite=True so re-install replaces the
    # previous version (the UI menu 'File > Save Project and Install into
    # Library Repository' does the same).
    if hasattr(lib_mgr, 'install_library') and target_repo is not None:
        # 3-arg signature (path, repo, overwrite=True) -- preferred.
        try:
            new_lib = lib_mgr.install_library(PROJECT_FILE_PATH, target_repo, True)
            install_log.append("install_library(path, repo='%s', overwrite=True): SUCCESS -> %s" % (target_repo_name, new_lib))
        except Exception as e:
            install_log.append("install_library(path, repo='%s', overwrite=True): %s: %s" % (target_repo_name, type(e).__name__, e))
        # 2-arg fallback for builds that don't accept the overwrite arg.
        if new_lib is None:
            try:
                new_lib = lib_mgr.install_library(PROJECT_FILE_PATH, target_repo)
                install_log.append("install_library(path, repo='%s'): SUCCESS -> %s" % (target_repo_name, new_lib))
            except Exception as e:
                install_log.append("install_library(path, repo='%s'): %s: %s" % (target_repo_name, type(e).__name__, e))

    # --- Path B: legacy single-arg install_library(path) (older builds) ---
    if new_lib is None and hasattr(lib_mgr, 'install_library'):
        for arg_tup in ((PROJECT_FILE_PATH,), (primary_project,)):
            try:
                new_lib = lib_mgr.install_library(*arg_tup)
                install_log.append("install_library(%s): SUCCESS -> %s" % (type(arg_tup[0]).__name__, new_lib))
                break
            except Exception as e:
                install_log.append("install_library(%s): %s: %s" % (type(arg_tup[0]).__name__, type(e).__name__, e))

    # --- Path C: manager.install(path/project) -- alternative API name ---
    if new_lib is None and hasattr(lib_mgr, 'install'):
        for arg_tup in ((PROJECT_FILE_PATH,), (primary_project,)):
            try:
                new_lib = lib_mgr.install(*arg_tup)
                install_log.append("install(%s): SUCCESS -> %s" % (type(arg_tup[0]).__name__, new_lib))
                break
            except Exception as e:
                install_log.append("install(%s): %s: %s" % (type(arg_tup[0]).__name__, type(e).__name__, e))

    # --- Path D: per-repository install (legacy / older API) ---
    candidates_seen = []
    if new_lib is None and repos is not None:
        # Probe each repo for an install method (install_library / install / add).
        repo_method_names = ('install_library', 'install', 'add_library', 'add', 'import_library', 'import')
        try:
            for repo in repos:
                rname = None
                for nattr in ('get_name', 'name'):
                    if hasattr(repo, nattr):
                        try:
                            val = getattr(repo, nattr)
                            rname = val() if callable(val) else val
                        except Exception:
                            pass
                        break
                rloc = None
                for lattr in ('get_location', 'location', 'path'):
                    if hasattr(repo, lattr):
                        try:
                            val = getattr(repo, lattr)
                            rloc = val() if callable(val) else val
                        except Exception:
                            pass
                        break
                repo_methods = [m for m in repo_method_names if hasattr(repo, m)]
                candidates_seen.append({
                    'name': str(rname), 'location': str(rloc),
                    'methods_present': repo_methods,
                })

                # Filter: caller may request a specific repo by name.
                if REPOSITORY_NAME and rname and str(rname).strip().lower() != REPOSITORY_NAME.strip().lower():
                    continue

                # Try every install method on this repo, with both arg types.
                for fn_name in repo_method_names:
                    if not hasattr(repo, fn_name):
                        continue
                    fn = getattr(repo, fn_name)
                    for arg_tup in ((PROJECT_FILE_PATH,), (primary_project,)):
                        try:
                            new_lib = fn(*arg_tup)
                            install_log.append(
                                "repo[%s].%s(%s): SUCCESS -> %s" %
                                (rname, fn_name, type(arg_tup[0]).__name__, new_lib))
                            break
                        except Exception as e:
                            install_log.append(
                                "repo[%s].%s(%s): %s: %s" %
                                (rname, fn_name, type(arg_tup[0]).__name__, type(e).__name__, e))
                    if new_lib is not None:
                        break
                if new_lib is not None:
                    break
        except TypeError as iter_err:
            install_log.append("repos iteration failed (not iterable): %s" % iter_err)

    # Dump candidates_seen as DEBUG so we always know what was enumerated.
    print("DEBUG: Repositories enumerated: %d" % len(candidates_seen))
    for c in candidates_seen:
        print("DEBUG:   - name='%s' location='%s' methods=%s" %
              (c.get('name'), c.get('location'), c.get('methods_present')))

    if new_lib is None:
        # Last-resort diagnostic: list every attribute on lib_mgr via dir() AND
        # via hasattr probe. dir() may miss COM-proxied members but include
        # something not in our probe list.
        try:
            mgr_dir = [a for a in dir(lib_mgr) if not a.startswith('_')]
        except Exception:
            mgr_dir = ['<dir() failed>']
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        raise RuntimeError(
            "Could not install library '%s'. Attempt log:\n  %s\n"
            "Manager (%s) probed methods present: %s\n"
            "Manager dir(): %s\n"
            "Repositories enumerated: %s\n"
            "If your edition is AB 2.9 Standard, the writable User repository "
            "may not be reachable from the scripting API. Workaround: install "
            "the library manually via AB UI menu 'File > Save Project and "
            "Install into Library Repository' for now, and forward the dir() "
            "list above so the right entry point can be wired." %
            (PROJECT_FILE_PATH, "\n  ".join(install_log), lib_mgr_source,
             mgr_present, mgr_dir, candidates_seen)
        )

    # Best-effort name + location of the installed library.
    new_lib_name = None
    new_lib_loc = None
    for attr in ('get_name', 'name'):
        if hasattr(new_lib, attr):
            try:
                val = getattr(new_lib, attr)
                new_lib_name = val() if callable(val) else val
            except Exception:
                pass
            break
    for attr in ('location', 'path'):
        if hasattr(new_lib, attr):
            try:
                new_lib_loc = getattr(new_lib, attr)
            except Exception:
                pass
            break

    print("Library installed: %s (path=%s, location=%s)" % (PROJECT_FILE_PATH, new_lib_name, new_lib_loc))
    print("Attempt log:")
    for line in install_log:
        print("  %s" % line)
    print("SCRIPT_SUCCESS: Library installed to repository.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error installing library to repository (project='%s', repo='%s'): %s\n%s" % (
        PROJECT_FILE_PATH, REPOSITORY_NAME, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

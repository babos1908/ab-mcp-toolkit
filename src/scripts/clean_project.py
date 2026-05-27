import sys, scriptengine as script_engine, os, traceback

# When true, also delete <project>.precompilecache + .compileinfo + .bootinfo
# files from the filesystem. When false, only target_app.clean() is called.
EVICT_PRECOMPILE_CACHE = "{EVICT_PRECOMPILE_CACHE}"

try:
    print("DEBUG: clean_project: Project='%s' EvictPrecompile='%s'" % (
        PROJECT_FILE_PATH, EVICT_PRECOMPILE_CACHE))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    evict = EVICT_PRECOMPILE_CACHE.strip().lower() in ('true', '1', 'yes', 'on')

    actions = []
    files_removed = []
    last_err = None

    # Phase 1: in-AB clean -- clear codegen caches on the active application.
    target_app = None
    try:
        target_app = primary_project.active_application
    except Exception:
        pass
    if not target_app:
        try:
            for child in primary_project.get_children(True):
                if hasattr(child, 'is_application') and child.is_application:
                    target_app = child
                    break
        except Exception:
            pass

    if target_app is not None:
        for mname in ('clean', 'clean_all'):
            if hasattr(target_app, mname):
                try:
                    getattr(target_app, mname)()
                    actions.append('app.%s()' % mname)
                except Exception as e:
                    last_err = '%s: %s' % (mname, e)
    else:
        # Library project: no application. Try project-level clean.
        if hasattr(primary_project, 'clean'):
            try:
                primary_project.clean()
                actions.append('project.clean()')
            except Exception as e:
                last_err = 'project.clean(): %s' % e

    # Phase 2: filesystem cache eviction (cross-AB-version-safe -- these
    # files are written to disk and not always cleared by .clean()).
    if evict:
        project_dir = os.path.dirname(PROJECT_FILE_PATH)
        base = os.path.basename(PROJECT_FILE_PATH)
        stem, ext = os.path.splitext(base)

        # Files we know AB writes near the project. Naming conventions vary:
        #   <stem>.precompilecache
        #   <stem>_<ext>.precompilecache  (e.g. NexoMqttLib_library.precompilecache)
        #   <stem>.compileinfo
        #   <stem>.bootinfo
        candidates = []
        for suffix in ('precompilecache', 'compileinfo', 'bootinfo'):
            candidates.append(os.path.join(project_dir, '%s.%s' % (stem, suffix)))
            candidates.append(os.path.join(project_dir, '%s_%s.%s' % (stem, ext.lstrip('.'), suffix)))
            candidates.append(os.path.join(project_dir, '%s%s.%s' % (stem, ext, suffix)))

        for fp in candidates:
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                    files_removed.append(_to_unicode(fp))
                except Exception as rerr:
                    print("WARN: could not remove %s: %s" % (fp, rerr))

    try:
        primary_project.save()
        actions.append('project.save()')
    except Exception as save_err:
        print("WARN: project.save() raised: %s" % save_err)

    emit_result({
        u'actions': [_to_unicode(a) for a in actions],
        u'filesRemoved': files_removed,
        u'lastError': _to_unicode(last_err) if last_err else None,
    })
    print("Actions: %s. Files removed: %d." % (actions, len(files_removed)))
    print("SCRIPT_SUCCESS: clean_project complete.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error cleaning project '%s': %s\n%s" % (PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

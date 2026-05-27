import sys, scriptengine as script_engine, traceback

# When true (default), the script attempts to regenerate compiled-library
# artifacts embedded in the .library project file -- equivalent to the
# AB UI menu "Build > Generate Library" (Premium-only on some editions).
# When false, only the source-level check_all_pool_objects() is run.
REGENERATE_ARTIFACTS = "{REGENERATE_ARTIFACTS}"

try:
    print("DEBUG: rebuild_library: Project='%s' RegenerateArtifacts='%s'" % (
        PROJECT_FILE_PATH, REGENERATE_ARTIFACTS))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    if not PROJECT_FILE_PATH.lower().endswith('.library'):
        print("WARN: project path does not end with .library; rebuild_library is normally for library projects only.")

    regen = REGENERATE_ARTIFACTS.strip().lower() in ('true', '1', 'yes', 'on')

    actions = []
    last_err = None

    # Step 1: clean caches if available (mirrors compile_project's behavior).
    if hasattr(primary_project, 'clean'):
        try:
            primary_project.clean()
            actions.append('primary_project.clean()')
        except Exception as e:
            last_err = "clean(): %s" % e

    # Step 2: run the source-level check (same as compile_project for .library).
    pool_method_names = (
        'check_all_pool_objects', 'checkall_pool_objects', 'check_pool_objects',
        'compile_pool_objects', 'build_all', 'check_all',
    )
    pool_done = False
    for mname in pool_method_names:
        if hasattr(primary_project, mname):
            try:
                getattr(primary_project, mname)()
                actions.append('primary_project.%s()' % mname)
                pool_done = True
                break
            except Exception as e:
                last_err = '%s: %s' % (mname, e)
    if not pool_done:
        # Best-effort: iterate Pool Objects and check each.
        try:
            count = 0
            for child in primary_project.get_children(True):
                for verb in ('check', 'compile', 'build'):
                    if hasattr(child, verb):
                        try:
                            getattr(child, verb)()
                            count += 1
                            break
                        except Exception:
                            pass
            actions.append('iterated %d pool object(s) with check/compile/build' % count)
        except Exception as e:
            last_err = "pool iteration: %s" % e

    # Step 3: regenerate compiled artifacts if requested. Probe a cascade
    # of plausible method names. This is best-effort -- AB 2.9 Standard may
    # not expose it, in which case we report that and the source-level
    # rebuild is still valid for source consumers.
    artifact_done = False
    artifact_via = None
    if regen:
        for mname in (
            'generate_compiled_library', 'create_compiled_library',
            'save_as_compiled_library', 'regenerate_compiled_library',
            'build_compiled_library', 'compile_library',
        ):
            if hasattr(primary_project, mname):
                try:
                    # Some signatures take an output path; for now we call
                    # the no-arg form (writes alongside the source).
                    getattr(primary_project, mname)()
                    actions.append('primary_project.%s()' % mname)
                    artifact_done = True
                    artifact_via = mname
                    break
                except TypeError:
                    # Maybe needs an output path argument; try with the source
                    # path as a same-dir target.
                    try:
                        out_path = PROJECT_FILE_PATH + '.compiled-library'
                        getattr(primary_project, mname)(out_path)
                        actions.append('primary_project.%s(%s)' % (mname, out_path))
                        artifact_done = True
                        artifact_via = mname
                        break
                    except Exception as e2:
                        last_err = '%s(path): %s' % (mname, e2)
                except Exception as e:
                    last_err = '%s(): %s' % (mname, e)

    # Save so source changes persist even if artifact regen fails.
    try:
        primary_project.save()
        actions.append('primary_project.save()')
    except Exception as save_err:
        last_err = "save(): %s" % save_err

    emit_result({
        u'actionsRun': [_to_unicode(a) for a in actions],
        u'sourceCheckSucceeded': pool_done,
        u'artifactRegenerated': artifact_done,
        u'artifactVia': _to_unicode(artifact_via) if artifact_via else None,
        u'regenerationRequested': regen,
        u'lastError': _to_unicode(last_err) if last_err else None,
    })

    if regen and not artifact_done:
        # Soft warning: caller asked for artifact regen but we couldn't.
        # NOT a fatal error -- the source-level rebuild is still useful.
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        print("Source-level rebuild done. Compiled-artifact regeneration NOT possible "
              "on this build (no generate_compiled_library / create_compiled_library "
              "method exposed). Last error: %s" % last_err)
    print("Actions: %s" % actions)
    print("SCRIPT_SUCCESS: rebuild_library complete.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error rebuilding library '%s': %s\n%s" % (PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

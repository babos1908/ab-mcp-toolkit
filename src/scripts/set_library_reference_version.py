import sys, scriptengine as script_engine, traceback

LIBRARY_NAME = "{LIBRARY_NAME}"
NEW_VERSION = "{NEW_VERSION}"  # exact version string (e.g. '1.0.10') or '*' for latest

try:
    print("DEBUG: set_library_reference_version: Lib='%s' NewVersion='%s'" % (LIBRARY_NAME, NEW_VERSION))
    if not LIBRARY_NAME or not NEW_VERSION:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("libraryName and version are required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    # Locate consumer-side Library Manager (NOT the global librarymanager).
    lib_manager_node = None
    try:
        found = primary_project.find("Library Manager", True)
        if found:
            lib_manager_node = found[0]
    except Exception:
        pass
    if lib_manager_node is None:
        for child in primary_project.get_children(True):
            cname = getattr(child, 'get_name', lambda: '')()
            if cname and 'library manager' in cname.lower():
                lib_manager_node = child
                break
    if lib_manager_node is None:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError("Library Manager node not found in project.")

    # Find the named reference. Track how many children we enumerate so we
    # can distinguish "name mismatch" from "enumeration is the Standard
    # scripting limit" in the error message -- those need different fixes
    # from the caller.
    target_ref = None
    current_version = None
    children_enumerated = 0
    names_seen = []
    for ref in lib_manager_node.get_children(False):
        children_enumerated += 1
        ref_name = getattr(ref, 'get_name', lambda: '')()
        if ref_name:
            names_seen.append(ref_name)
        if ref_name and ref_name.strip().lower() == LIBRARY_NAME.strip().lower():
            target_ref = ref
            for vattr in ('version', 'resolved_version', 'get_version'):
                if hasattr(target_ref, vattr):
                    try:
                        v = getattr(target_ref, vattr)
                        current_version = v() if callable(v) else v
                    except Exception:
                        pass
                    break
            break
    if target_ref is None:
        print("SCRIPT_ERROR_CODE: ERR_LIB_NOT_FOUND")
        if children_enumerated == 0:
            # Standard-edition scripting limit: get_children(False) on the
            # Library Manager yields nothing on this build. Even if the
            # library IS referenced, we cannot see it from scripting -- the
            # only fix is AB UI (Library Manager > Properties > Version) or
            # AB Premium edition.
            raise RuntimeError(
                "Library reference '%s' could not be located: Library Manager "
                "enumeration returned 0 children. This is the AB 2.9 Standard "
                "scripting limit (the Library Manager does not surface its "
                "references via get_children on Standard). "
                "Fallback: AB UI > Library Manager > right-click the reference > "
                "Properties > set Version explicitly. On AB Premium this tool "
                "should work directly." % LIBRARY_NAME
            )
        else:
            # Children enumeration worked but name didn't match. Show what we
            # actually saw so the caller can correct the name.
            raise RuntimeError(
                "Library reference '%s' not found under Library Manager. "
                "Enumerated %d reference(s): %s. Confirm the exact name via "
                "list_project_libraries / inspect_project_tree, or use the "
                "fully-qualified form (e.g. 'MyLib, * (Vendor)')." %
                (LIBRARY_NAME, children_enumerated, names_seen)
            )

    # Probe write paths. Names empirically vary; cascade until one works.
    set_via = None
    last_err = None
    if hasattr(target_ref, 'set_version'):
        try:
            target_ref.set_version(NEW_VERSION)
            set_via = 'set_version()'
        except Exception as e:
            last_err = 'set_version(): %s' % e
    if set_via is None and hasattr(target_ref, 'version'):
        try:
            target_ref.version = NEW_VERSION
            set_via = 'version='
        except Exception as e:
            last_err = (last_err or '') + ' | version=: %s' % e
    # Last resort: remove + re-add via library manager add_library (this
    # IS destructive of any consumer-side overrides on this library, so
    # we only attempt it if explicit set paths fail).
    if set_via is None and hasattr(lib_manager_node, 'add_library'):
        try:
            # Remove first
            for rm in ('remove_library', 'delete'):
                if hasattr(lib_manager_node, rm):
                    try:
                        getattr(lib_manager_node, rm)(target_ref)
                        break
                    except Exception:
                        pass
            # Add with new version
            qualified = '%s, %s' % (LIBRARY_NAME, NEW_VERSION)
            lib_manager_node.add_library(qualified)
            set_via = 'remove+add(%s)' % qualified
        except Exception as e:
            last_err = (last_err or '') + ' | remove+add: %s' % e

    if set_via is None:
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "Could not change version on library reference '%s'. Tried set_version(), "
            "version=, remove+add. Last error: %s" % (LIBRARY_NAME, last_err))

    # Re-read effective version to confirm.
    new_resolved = None
    for vattr in ('version', 'resolved_version', 'get_version'):
        if hasattr(target_ref, vattr):
            try:
                v = getattr(target_ref, vattr)
                new_resolved = v() if callable(v) else v
            except Exception:
                pass
            break

    try:
        primary_project.save()
    except Exception as save_err:
        print("WARN: project.save() raised: %s" % save_err)

    emit_result({
        u'library': _to_unicode(LIBRARY_NAME),
        u'previousVersion': _to_unicode(unicode(current_version)) if current_version else None,
        u'requestedVersion': _to_unicode(NEW_VERSION),
        u'effectiveVersion': _to_unicode(unicode(new_resolved)) if new_resolved else None,
        u'setVia': _to_unicode(set_via),
    })
    print("SCRIPT_SUCCESS: Library reference version updated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error setting library reference version: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

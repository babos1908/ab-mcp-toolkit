import sys, scriptengine as script_engine, os, traceback

OBJECT_PATH = "{OBJECT_PATH}"
NEW_NAME = "{NEW_NAME}"

try:
    print("DEBUG: rename_object script: ObjectPath='%s', NewName='%s', Project='%s'" % (OBJECT_PATH, NEW_NAME, PROJECT_FILE_PATH))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not OBJECT_PATH: raise ValueError("Object path empty.")
    if not NEW_NAME: raise ValueError("New name empty.")

    # Find the target object
    target_object = find_object_by_path_robust(primary_project, OBJECT_PATH, "target object")
    if not target_object:
        raise ValueError("Object not found at path: %s" % OBJECT_PATH)

    old_name = getattr(target_object, 'get_name', lambda: OBJECT_PATH)()
    target_type = type(target_object).__name__
    print("DEBUG: Found target object: %s (Type: %s)" % (old_name, target_type))

    # Rename the object
    if hasattr(target_object, 'set_name'):
        print("DEBUG: Calling set_name('%s') on object '%s'" % (NEW_NAME, old_name))
        target_object.set_name(NEW_NAME)
        print("DEBUG: Object renamed.")
    elif hasattr(target_object, 'rename'):
        print("DEBUG: Calling rename('%s') on object '%s'" % (NEW_NAME, old_name))
        target_object.rename(NEW_NAME)
        print("DEBUG: Object renamed.")
    else:
        raise TypeError("Object '%s' of type %s does not support set_name() or rename()." % (old_name, target_type))

    # Read-back verification: set_name/rename can be accepted without raising
    # yet land a DIFFERENT name than requested (CODESYS may sanitize/normalize
    # an illegal identifier, or silently no-op on a collision) -- the "lying
    # success" failure mode. Re-read the name and fail loudly on mismatch.
    actual_name = None
    try:
        actual_name = getattr(target_object, 'get_name', lambda: None)()
    except Exception:
        pass
    if actual_name is not None and unicode(actual_name).strip() != NEW_NAME.strip():
        print("SCRIPT_ERROR_CODE: ERR_RENAME_DID_NOT_STICK")
        raise RuntimeError(
            "Rename did not stick: requested '%s' but object is now named '%s' "
            "(was '%s'). CODESYS may have rejected/normalized the name or hit a "
            "collision." % (NEW_NAME, actual_name, old_name))

    try:
        print("DEBUG: Saving Project...")
        primary_project.save()
        print("DEBUG: Project saved successfully after rename.")
    except Exception as save_err:
        print("ERROR: Failed to save Project after renaming object: %s" % save_err)
        detailed_error = traceback.format_exc()
        error_message = "Error saving Project after renaming '%s' to '%s': %s\n%s" % (old_name, NEW_NAME, save_err, detailed_error)
        print(error_message); print("SCRIPT_ERROR: %s" % error_message); sys.exit(1)

    print("Object Renamed: '%s' -> '%s'" % (old_name, NEW_NAME))
    print("Object Type: %s" % target_type)
    print("Path: %s" % OBJECT_PATH)
    print("SCRIPT_SUCCESS: Object renamed successfully.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error renaming object '%s' in project '%s': %s\n%s" % (OBJECT_PATH, PROJECT_FILE_PATH, e, detailed_error)
    print(error_message); print("SCRIPT_ERROR: %s" % error_message); sys.exit(1)

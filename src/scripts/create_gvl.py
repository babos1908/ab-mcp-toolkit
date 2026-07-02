import sys, scriptengine as script_engine, os, traceback

GVL_NAME = "{GVL_NAME}"
PARENT_PATH_REL = "{PARENT_PATH}"
DECLARATION_CONTENT = """{DECLARATION_CONTENT}"""

try:
    print("DEBUG: create_gvl script: Name='%s', ParentPath='%s', Project='%s'" % (GVL_NAME, PARENT_PATH_REL, PROJECT_FILE_PATH))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not GVL_NAME: print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT"); raise ValueError("GVL name empty.")
    if not PARENT_PATH_REL: print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT"); raise ValueError("Parent path empty.")

    # Find parent object (same logic as create_pou)
    if PARENT_PATH_REL == "Application":
        project_name = os.path.splitext(os.path.basename(PROJECT_FILE_PATH))[0]
        potential_paths = [
            PARENT_PATH_REL,
            "%s.%s" % (project_name, PARENT_PATH_REL),
            "%s/%s" % (project_name, PARENT_PATH_REL),
        ]
        parent_object = None
        for path in potential_paths:
            parent_candidate = find_object_by_path_robust(primary_project, path, "parent container")
            if parent_candidate:
                parent_object = parent_candidate
                print("DEBUG: Found parent using path: '%s'" % path)
                break
        if not parent_object:
            try:
                if hasattr(primary_project, 'active_application'):
                    app = primary_project.active_application
                    if app:
                        parent_object = app
                        print("DEBUG: Found application directly: %s" % app.get_name())
                if not parent_object and hasattr(primary_project, 'find'):
                    apps = primary_project.find("Application", True)
                    if apps:
                        parent_object = apps[0]
            except Exception as e:
                print("ERROR: Direct application access failed: %s" % e)
    else:
        parent_object = find_object_by_path_robust(primary_project, PARENT_PATH_REL, "parent container")

    if not parent_object:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise ValueError("Parent object not found for path: %s" % PARENT_PATH_REL)

    parent_name = getattr(parent_object, 'get_name', lambda: str(parent_object))()
    print("DEBUG: Using parent object: %s" % parent_name)

    # Create the GVL
    if not hasattr(parent_object, 'create_gvl'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise TypeError("Parent object '%s' of type %s does not support create_gvl." % (parent_name, type(parent_object).__name__))

    print("DEBUG: Calling create_gvl: Name='%s'" % GVL_NAME)
    new_gvl = parent_object.create_gvl(name=GVL_NAME)

    if new_gvl:
        new_gvl_name = getattr(new_gvl, 'get_name', lambda: GVL_NAME)()
        print("DEBUG: GVL object created: %s" % new_gvl_name)

        # Optionally set declaration code
        if DECLARATION_CONTENT.strip():
            print("DEBUG: Setting GVL declaration code...")
            # See _text_utils.to_codesys_text for why this decode is required
            # before writing to .NET text properties (Unicode->NUL corruption
            # via the System.String binding on raw Python 2.7 bytes).
            DECLARATION_CONTENT_U = to_codesys_text(DECLARATION_CONTENT)
            decl_written = False
            if hasattr(new_gvl, 'textual_declaration'):
                try:
                    new_gvl.textual_declaration.replace(DECLARATION_CONTENT_U)
                    print("DEBUG: GVL declaration code set successfully.")
                    decl_written = True
                except Exception as decl_err:
                    print("WARN: Failed to set GVL declaration via textual_declaration.replace: %s" % decl_err)
                    # Try alternative
                    if hasattr(new_gvl.textual_declaration, 'text'):
                        try:
                            new_gvl.textual_declaration.text = DECLARATION_CONTENT_U
                            print("DEBUG: GVL declaration code set via .text property.")
                            decl_written = True
                        except Exception as text_err:
                            print("WARN: Failed to set GVL declaration via .text: %s" % text_err)
            else:
                print("WARN: GVL object does not have textual_declaration attribute.")
            # A requested declaration that was not written (or that reads back
            # different/corrupted) must FAIL the call -- previously a caught
            # write error still ended in SCRIPT_SUCCESS (lying success). The
            # empty GVL is left in place: re-running set_pou_code/create_gvl
            # is cheaper than losing the object.
            if not decl_written:
                print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
                raise RuntimeError(
                    "GVL '%s' was created but its declaration could not be "
                    "written (see WARN lines above). Fix the content or set it "
                    "via set_pou_code." % new_gvl_name)
            try:
                rb = getattr(new_gvl.textual_declaration, 'text', None)
                if rb is not None:
                    rb_u = to_codesys_text(rb)
                    def _norm(s):
                        lines = s.replace(u'\r\n', u'\n').replace(u'\r', u'\n').split(u'\n')
                        return u'\n'.join([ln.rstrip() for ln in lines]).strip()
                    if u'\x00' in rb_u or _norm(rb_u) != _norm(DECLARATION_CONTENT_U):
                        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
                        raise RuntimeError(
                            "GVL '%s' declaration readback differs from what was "
                            "written (or contains NUL) -- content did not stick. "
                            "Not saving." % new_gvl_name)
                    print("DEBUG: GVL declaration verified by readback.")
            except RuntimeError:
                raise
            except Exception as rb_err:
                print("WARN: could not read back GVL declaration to verify (%s)." % rb_err)

        try:
            print("DEBUG: Saving Project...")
            primary_project.save()
            print("DEBUG: Project saved successfully after GVL creation.")
        except Exception as save_err:
            print("ERROR: Failed to save Project after GVL creation: %s" % save_err)
            detailed_error = traceback.format_exc()
            error_message = "Error saving Project after creating GVL '%s': %s\n%s" % (GVL_NAME, save_err, detailed_error)
            print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
            print(error_message); print("SCRIPT_ERROR: %s" % error_message); sys.exit(1)

        print("GVL Created: %s" % new_gvl_name)
        print("Parent Path: %s" % PARENT_PATH_REL)
        print("SCRIPT_SUCCESS: GVL created successfully.")
        sys.exit(0)
    else:
        error_message = "Failed to create GVL '%s'. create_gvl returned None." % GVL_NAME
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        print(error_message); print("SCRIPT_ERROR: %s" % error_message); sys.exit(1)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error creating GVL '%s' in project '%s': %s\n%s" % (GVL_NAME, PROJECT_FILE_PATH, e, detailed_error)
    print(error_message); print("SCRIPT_ERROR: %s" % error_message); sys.exit(1)

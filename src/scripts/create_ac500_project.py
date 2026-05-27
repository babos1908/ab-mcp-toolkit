import sys, scriptengine as script_engine, os, shutil, traceback

# Where to write the new .project file.
NEW_PROJECT_PATH = "{NEW_PROJECT_PATH}"
# Source template file: an existing AC500 V3 .project we copy + sanitize.
# In Standard edition we cannot generate an AC500 project from a stock
# template that ships with AB (the device tree is too specific). The
# caller provides a known-good template path; the easiest is to point at
# a vanilla AC500 V3 project already in the workspace (e.g. a clean
# NexoPlcExample.project before any user code is added).
TEMPLATE_PROJECT_PATH = "{TEMPLATE_PROJECT_PATH}"
# Comma-separated list of fully-qualified libraries to add (e.g.
# 'Standard, * (System), MQTT Client SL, 4.1.0.0 (3S - Smart Software Solutions GmbH)').
# Empty = no libraries beyond what the template already references.
ADD_LIBRARIES_CSV = "{ADD_LIBRARIES_CSV}"
# When true (default), overwrite NEW_PROJECT_PATH if it exists.
OVERWRITE = "{OVERWRITE}"

try:
    print("DEBUG: create_ac500_project: New='%s' Template='%s' AddLibs='%s'" % (
        NEW_PROJECT_PATH, TEMPLATE_PROJECT_PATH, ADD_LIBRARIES_CSV))

    if not NEW_PROJECT_PATH:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("newProjectPath is required.")
    if not TEMPLATE_PROJECT_PATH:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("templateProjectPath is required (point at an existing clean AC500 V3 project).")
    if not os.path.exists(TEMPLATE_PROJECT_PATH):
        print("SCRIPT_ERROR_CODE: ERR_PROJECT_NOT_FOUND")
        raise RuntimeError("Template project does not exist: %s" % TEMPLATE_PROJECT_PATH)

    overwrite = OVERWRITE.strip().lower() in ('true', '1', 'yes', 'on') or OVERWRITE == ''

    if os.path.exists(NEW_PROJECT_PATH):
        if not overwrite:
            print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
            raise RuntimeError("Target path exists and overwrite=false: %s" % NEW_PROJECT_PATH)
        try:
            os.remove(NEW_PROJECT_PATH)
        except Exception as rm_err:
            raise RuntimeError("Could not remove existing target: %s" % rm_err)

    target_dir = os.path.dirname(NEW_PROJECT_PATH)
    if target_dir and not os.path.exists(target_dir):
        os.makedirs(target_dir)

    # Copy template to new path. This preserves the AC500 device tree
    # exactly as the template has it. The .lock / cache siblings are NOT
    # copied (they're transient).
    shutil.copyfile(TEMPLATE_PROJECT_PATH, NEW_PROJECT_PATH)
    print("DEBUG: copied template -> new project: %s -> %s" % (TEMPLATE_PROJECT_PATH, NEW_PROJECT_PATH))

    # Open via AB so we can manipulate it (rename + sanitize).
    primary_project = ensure_project_open(NEW_PROJECT_PATH)

    # Best-effort: clear out any user POUs the template might carry
    # (TODO add a SANITIZE_USER_CODE flag if we want to be stricter).
    # For now we just save so the new file is registered.
    try:
        primary_project.save()
        print("DEBUG: new project saved.")
    except Exception as se:
        print("WARN: project.save() raised: %s" % se)

    # Add libraries if requested.
    libs_added = []
    libs_failed = []
    if ADD_LIBRARIES_CSV.strip():
        # Locate Library Manager
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

        if lib_manager_node is not None and hasattr(lib_manager_node, 'add_library'):
            # Split on comma but be careful: library names themselves often
            # contain comma (e.g. 'Standard, * (System)'). Use a semicolon
            # separator instead.
            entries = [e.strip() for e in ADD_LIBRARIES_CSV.split(';') if e.strip()]
            for entry in entries:
                try:
                    lib_manager_node.add_library(entry)
                    libs_added.append(_to_unicode(entry))
                except Exception as ae:
                    libs_failed.append({'lib': _to_unicode(entry), 'error': _to_unicode(str(ae))})
            try:
                primary_project.save()
            except Exception:
                pass
        else:
            print("WARN: Library Manager not found or doesn't support add_library; libraries not added.")

    emit_result({
        u'projectPath': _to_unicode(NEW_PROJECT_PATH),
        u'templateUsed': _to_unicode(TEMPLATE_PROJECT_PATH),
        u'librariesAdded': libs_added,
        u'librariesFailed': libs_failed,
    })
    print("SCRIPT_SUCCESS: AC500 project created.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error creating AC500 project: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

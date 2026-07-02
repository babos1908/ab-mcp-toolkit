import sys, scriptengine as script_engine, os, traceback

# create_boot_application
# -----------------------
# Generates a boot application (.app + .crc) for the project's active
# application via ScriptApplication.create_boot_application(). This is the
# deployable artifact a PLC loads at startup. Confirmed working 2026-05-30 on
# AB 2.9 SP19 Premium (produced a 215 KB .app + sibling .crc for Test.project).
#
# Verified .NET overloads on this build:
#   create_boot_application(output_filename)
#   create_boot_application(output_filename, update_compile_info, write_visu_files)
#
# A fresh generate_code() is run first so the boot image reflects current
# source (create_boot_application on a stale model can emit an outdated image).

OUTPUT_APP_PATH = "{OUTPUT_APP_PATH}"
WRITE_VISU_FILES = "{WRITE_VISU_FILES}"

try:
    print("DEBUG: create_boot_application: Output='%s' WriteVisu='%s'" % (
        OUTPUT_APP_PATH, WRITE_VISU_FILES))
    if not OUTPUT_APP_PATH:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("outputAppPath is required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    write_visu = WRITE_VISU_FILES.strip().lower() in ('true', '1', 'yes', 'on')

    # --- Ensure output directory exists ---
    out_dir = os.path.dirname(OUTPUT_APP_PATH)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # --- Locate the active application ---
    target_app = None
    app_name = "N/A"
    try:
        target_app = primary_project.active_application
        if target_app:
            app_name = getattr(target_app, 'get_name', lambda: "Unnamed App (Active)")()
    except Exception as active_err:
        print("WARN: active_application access failed: %s" % active_err)
    if not target_app:
        try:
            for child in primary_project.get_children(True):
                if hasattr(child, 'is_application') and child.is_application:
                    target_app = child
                    app_name = getattr(child, 'get_name', lambda: "Unnamed App")()
                    break
        except Exception as find_err:
            print("WARN: application search failed: %s" % find_err)
    if not target_app:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError(
            "No application found. A boot application is generated from an "
            "Application node; open the project and set an active application.")
    print("DEBUG: target application: %s" % app_name)

    if not hasattr(target_app, 'create_boot_application'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "create_boot_application not exposed on the application object for "
            "this CODESYS build.")

    # --- Generate code first so the boot image is current ---
    try:
        if hasattr(target_app, 'generate_code'):
            target_app.generate_code()
            print("DEBUG: generate_code() executed for '%s'." % app_name)
    except Exception as gen_err:
        # Surface but don't abort: create_boot_application may still succeed
        # against the last good model, and we verify the output below.
        print("WARN: generate_code() raised (continuing): %s" % gen_err)

    # --- Create the boot application ---
    # Probe signature variants: the 3-arg form (output, update_compile_info,
    # write_visu_files) when visu files are requested, else the 1-arg form.
    created = False
    method_used = None
    last_err = None
    if write_visu:
        try:
            target_app.create_boot_application(OUTPUT_APP_PATH, True, True)
            created = True
            method_used = "create_boot_application(path, update_compile_info=True, write_visu_files=True)"
        except TypeError as te:
            last_err = "3-arg form rejected: %s" % te
        except Exception as e:
            last_err = "3-arg form: %s: %s" % (type(e).__name__, e)
    if not created:
        try:
            target_app.create_boot_application(OUTPUT_APP_PATH)
            created = True
            method_used = "create_boot_application(path)"
        except Exception as e:
            last_err = "1-arg form: %s: %s" % (type(e).__name__, e)

    if not created:
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        raise RuntimeError(
            "create_boot_application failed for '%s'. Last error: %s" % (app_name, last_err))

    # --- Verify the artifact was written ---
    if not os.path.exists(OUTPUT_APP_PATH):
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "create_boot_application reported success but output file does not "
            "exist: %s" % OUTPUT_APP_PATH)
    app_size = os.path.getsize(OUTPUT_APP_PATH)

    # The .crc sibling is written next to the .app; report it if present.
    crc_path = os.path.splitext(OUTPUT_APP_PATH)[0] + '.crc'
    crc_exists = os.path.exists(crc_path)

    emit_result({
        u'outputAppPath': _to_unicode(OUTPUT_APP_PATH),
        u'sizeBytes': app_size,
        u'crcPath': _to_unicode(crc_path) if crc_exists else None,
        u'application': _to_unicode(app_name),
        u'methodUsed': _to_unicode(method_used),
        u'writeVisuFiles': write_visu,
    })
    print("Boot application written: %d bytes to %s (crc=%s) via %s" % (
        app_size, OUTPUT_APP_PATH, crc_exists, method_used))
    print("SCRIPT_SUCCESS: Boot application created.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error creating boot application: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

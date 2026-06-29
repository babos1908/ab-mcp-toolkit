import sys, scriptengine as script_engine, os, traceback

OUTPUT_XML_PATH = "{OUTPUT_XML_PATH}"
# When true, export only the active application's POUs (smaller XML);
# when false, attempt project-level export of everything (POUs + DUTs + GVLs).
APPLICATION_ONLY = "{APPLICATION_ONLY}"
# When true, recurse into library content (heavy -- usually NOT what you want).
INCLUDE_LIBRARIES = "{INCLUDE_LIBRARIES}"

try:
    print("DEBUG: export_project_to_plcopen_xml: Output='%s' AppOnly='%s' IncludeLibs='%s'" % (
        OUTPUT_XML_PATH, APPLICATION_ONLY, INCLUDE_LIBRARIES))
    if not OUTPUT_XML_PATH:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("outputXmlPath is required.")

    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    app_only = APPLICATION_ONLY.strip().lower() in ('true', '1', 'yes', 'on')
    include_libs = INCLUDE_LIBRARIES.strip().lower() in ('true', '1', 'yes', 'on')

    # Ensure output directory exists.
    out_dir = os.path.dirname(OUTPUT_XML_PATH)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # CODESYS V3 PLCopen XML export is exposed via export_plcopenxml on
    # project / application / individual objects. Try the broadest scope
    # first when app_only=False; otherwise prefer the active application.
    exported = False
    last_err = None
    method_used = None

    # Method names seen across CODESYS V3.5 SPxx / AB builds. export_plcopenxml
    # is the documented one; the *_native / ExportPLCopenXML / export_xml
    # variants appear on some builds where the documented name is not bound.
    _EXPORT_METHOD_NAMES = (
        'export_plcopenxml', 'export_plc_open_xml', 'export_xml',
        'ExportPLCopenXML', 'export_native', 'export',
    )

    def _try_export(target, name):
        """Probe export method names + signature variants on target. Returns
        True on success, an Exception on a matched-signature real error, or
        False when nothing was callable."""
        tried_any = False
        for mname in _EXPORT_METHOD_NAMES:
            if not hasattr(target, mname):
                continue
            fn = getattr(target, mname)
            if not callable(fn):
                continue
            tried_any = True
            # Signature variants:
            #   m(filepath) / m(filepath, recursive) / m(filepath, recursive, declarations)
            for args in (
                (OUTPUT_XML_PATH,),
                (OUTPUT_XML_PATH, True),
                (OUTPUT_XML_PATH, True, True),
            ):
                try:
                    fn(*args)
                    print("DEBUG: %s.%s%s succeeded" % (name, mname, '(...)' if len(args) > 1 else '(path)'))
                    return True
                except TypeError:
                    continue
                except Exception as e:
                    return e
        return False if tried_any else False

    if app_only:
        # Try application-level first
        target_app = None
        try:
            target_app = primary_project.active_application
        except Exception:
            pass
        if not target_app:
            for child in primary_project.get_children(True):
                if hasattr(child, 'is_application') and child.is_application:
                    target_app = child
                    break
        if target_app is not None:
            res = _try_export(target_app, 'application')
            if res is True:
                exported = True
                method_used = 'application.export_plcopenxml(...)'
            elif isinstance(res, Exception):
                last_err = "application.export: %s: %s" % (type(res).__name__, res)

    if not exported:
        # Project-level export
        res = _try_export(primary_project, 'project')
        if res is True:
            exported = True
            method_used = 'project.export_plcopenxml(...)'
        elif isinstance(res, Exception):
            last_err = "project.export: %s: %s" % (type(res).__name__, res)

    if not exported:
        # Last resort: export each top-level object individually and concat
        # (this would produce multiple files; we skip for now and surface
        # ERR_API_NOT_EXPOSED instead since the per-object approach doesn't
        # produce a single XML the diff tool can consume).
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise RuntimeError(
            "PLCopen XML export is not exposed on the project or active "
            "application on this CODESYS build (probed: %s). Last error: %s. "
            "The offline tools (get_all_pou_code_offline / search_code_offline) "
            "depend on this export, so they are unavailable on this build. To "
            "read a single object's code without the export, use get_object_code "
            "(declaration + implementation of one POU/DUT/GVL); for the whole "
            "project use get_all_pou_code." % (
                ', '.join(_EXPORT_METHOD_NAMES), last_err)
        )

    # Verify the file was actually written.
    if not os.path.exists(OUTPUT_XML_PATH):
        raise RuntimeError(
            "export_plcopenxml call succeeded but output file does not exist: %s" %
            OUTPUT_XML_PATH
        )
    out_size = os.path.getsize(OUTPUT_XML_PATH)

    emit_result({
        u'outputXmlPath': _to_unicode(OUTPUT_XML_PATH),
        u'sizeBytes': out_size,
        u'methodUsed': _to_unicode(method_used),
        u'applicationOnly': app_only,
        u'includeLibraries': include_libs,
    })
    print("Exported %d bytes to %s via %s" % (out_size, OUTPUT_XML_PATH, method_used))
    print("SCRIPT_SUCCESS: PLCopen XML export complete.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error exporting PLCopen XML: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

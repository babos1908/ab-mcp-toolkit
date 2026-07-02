import sys, scriptengine as script_engine, os, traceback

POU_FULL_PATH = "{POU_FULL_PATH}" # Expecting format like "Application/MyPOU" or "Folder/SubFolder/MyPOU"
DECLARATION_CONTENT = """{DECLARATION_CONTENT}"""
IMPLEMENTATION_CONTENT = """{IMPLEMENTATION_CONTENT}"""
UPDATE_DECL_FLAG = "{UPDATE_DECL}"  # "1" if caller passed declarationCode, "0" if omitted/empty
UPDATE_IMPL_FLAG = "{UPDATE_IMPL}"  # "1" if caller passed implementationCode, "0" if omitted/empty

try:
    print("DEBUG: set_pou_code script: POU_FULL_PATH='%s', Project='%s'" % (POU_FULL_PATH, PROJECT_FILE_PATH))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not POU_FULL_PATH: print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT"); raise ValueError("POU full path empty.")

    # Find the target POU/Method/Property object
    target_object = find_object_by_path_robust(primary_project, POU_FULL_PATH, "target object")
    if not target_object: print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND"); raise ValueError("Target object not found using path: %s" % POU_FULL_PATH)

    target_name = getattr(target_object, 'get_name', lambda: POU_FULL_PATH)()
    print("DEBUG: Found target object: %s" % target_name)

    # Decode the incoming bytes->unicode BEFORE writing to .NET text props.
    # Empirical 2026-05-27 (NEXO PLC): non-ASCII chars (e.g. U+2500 box
    # drawing, U+2014 em-dash) in comments were silently corrupted to NUL
    # bytes when the raw Python 2.7 `str` (containing UTF-8 bytes) was
    # assigned to obj.textual_declaration.text -- the System.String binding
    # misinterpreted control-range bytes. The CODESYS tokenizer then exited
    # the comment scanner early on the first NUL and skipped any struct
    # fields declared after the affected line. See _text_utils.to_codesys_text
    # for the full diagnosis.
    DECLARATION_CONTENT_U = to_codesys_text(DECLARATION_CONTENT)
    IMPLEMENTATION_CONTENT_U = to_codesys_text(IMPLEMENTATION_CONTENT)

    def _norm_code(s):
        """Normalize code text for write-verification compare: unify line
        endings and strip trailing whitespace per line (CODESYS normalizes
        both on store, so a raw string compare would false-mismatch)."""
        if s is None:
            return u''
        u = to_codesys_text(s)
        lines = u.replace(u'\r\n', u'\n').replace(u'\r', u'\n').split(u'\n')
        return u'\n'.join([ln.rstrip() for ln in lines]).strip()

    def _verify_section(obj, label, written_u):
        """Read the section text back and compare to what we wrote. Raises on
        mismatch. This catches BOTH silent no-op writes and content corruption
        in transit -- e.g. the 2026-05-27 Unicode->NUL bug (non-ASCII comment
        chars persisted as NUL, silently swallowing struct fields declared
        after them) would have been caught here instantly instead of surfacing
        as 56 mysterious compile errors downstream."""
        rb = None
        try:
            rb = getattr(obj, 'text', None)
        except Exception as rb_err:
            print("WARN: could not read back %s to verify (%s); write unverified." % (label, rb_err))
            return
        if rb is None:
            print("WARN: %s has no readable .text; write unverified." % label)
            return
        rb_u = to_codesys_text(rb)
        if u'\x00' in rb_u:
            print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
            raise RuntimeError(
                "%s readback contains NUL bytes after the write -- content was "
                "corrupted in the .NET String binding. Not saving." % label)
        if _norm_code(rb_u) != _norm_code(written_u):
            a = _norm_code(rb_u).split(u'\n')
            b = _norm_code(written_u).split(u'\n')
            first_diff = None
            for i in range(min(len(a), len(b))):
                if a[i] != b[i]:
                    first_diff = (i + 1, b[i][:80], a[i][:80])
                    break
            if first_diff is None:
                first_diff = (min(len(a), len(b)) + 1, '(missing/extra lines)', '(missing/extra lines)')
            print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
            raise RuntimeError(
                "%s readback differs from what was written (first diff at line %d: "
                "wrote %r, read back %r). The write did not fully stick. Not saving." % (
                    label, first_diff[0], first_diff[1], first_diff[2]))
        print("DEBUG: %s verified by readback." % label)

    # --- Set Declaration Part ---
    declaration_updated = False
    if UPDATE_DECL_FLAG == "1":
        if hasattr(target_object, 'textual_declaration'):
            decl_obj = target_object.textual_declaration
            if decl_obj and hasattr(decl_obj, 'replace'):
                try:
                    print("DEBUG: Accessing textual_declaration...")
                    decl_obj.replace(DECLARATION_CONTENT_U)
                    print("DEBUG: Set declaration text using replace().")
                    _verify_section(decl_obj, 'textual_declaration', DECLARATION_CONTENT_U)
                    declaration_updated = True
                except Exception as decl_err:
                    print("ERROR: Failed to set declaration text: %s" % decl_err)
                    traceback.print_exc() # Print stack trace for detailed error
            else:
                 print("WARN: Target '%s' textual_declaration attribute is None or does not have replace(). Skipping declaration update." % target_name)
        else:
            print("WARN: Target '%s' does not have textual_declaration attribute. Skipping declaration update." % target_name)
    else:
         print("DEBUG: Declaration content not provided or is None. Skipping declaration update.")


    # --- Set Implementation Part ---
    implementation_updated = False
    if UPDATE_IMPL_FLAG == "1":
        if hasattr(target_object, 'textual_implementation'):
            impl_obj = target_object.textual_implementation
            if impl_obj and hasattr(impl_obj, 'replace'):
                try:
                    print("DEBUG: Accessing textual_implementation...")
                    impl_obj.replace(IMPLEMENTATION_CONTENT_U)
                    print("DEBUG: Set implementation text using replace().")
                    _verify_section(impl_obj, 'textual_implementation', IMPLEMENTATION_CONTENT_U)
                    implementation_updated = True
                except Exception as impl_err:
                     print("ERROR: Failed to set implementation text: %s" % impl_err)
                     traceback.print_exc() # Print stack trace for detailed error
            else:
                 print("WARN: Target '%s' textual_implementation attribute is None or does not have replace(). Skipping implementation update." % target_name)
        else:
            print("WARN: Target '%s' does not have textual_implementation attribute. Skipping implementation update." % target_name)
    else:
        print("DEBUG: Implementation content not provided or is None. Skipping implementation update.")


    # --- HARD FAIL when a REQUESTED section was not written+verified ---
    # Previously a caught write error (or a section object without replace())
    # still fell through to SCRIPT_SUCCESS with only a WARN/ERROR print -- a
    # lying success. If the caller asked for a section, it must have been
    # written AND read-back-verified, or the whole call fails.
    failed_sections = []
    if UPDATE_DECL_FLAG == "1" and not declaration_updated:
        failed_sections.append('declaration')
    if UPDATE_IMPL_FLAG == "1" and not implementation_updated:
        failed_sections.append('implementation')
    if failed_sections:
        print("SCRIPT_ERROR_CODE: ERR_WRITE_DID_NOT_STICK")
        raise RuntimeError(
            "Requested section(s) not written/verified on '%s': %s. See the "
            "ERROR/WARN lines above for the cause. Project NOT saved." % (
                target_name, ', '.join(failed_sections)))

    # --- SAVE THE PROJECT TO PERSIST THE CODE CHANGE ---
    # Only save if something was actually updated to avoid unnecessary saves
    if declaration_updated or implementation_updated:
        try:
            print("DEBUG: Saving Project (after code change)...")
            primary_project.save() # Save the overall project file
            print("DEBUG: Project saved successfully after code change.")
        except Exception as save_err:
            print("ERROR: Failed to save Project after setting code: %s" % save_err)
            detailed_error = traceback.format_exc()
            error_message = "Error saving Project after code change for '%s': %s\\n%s" % (target_name, save_err, detailed_error)
            print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
            print(error_message); print("SCRIPT_ERROR: %s" % error_message); sys.exit(1)
    else:
         print("DEBUG: No code parts were updated, skipping project save.")
    # --- END SAVING ---

    print("Code Set For: %s" % target_name)
    print("Path: %s" % POU_FULL_PATH)
    print("SCRIPT_SUCCESS: Declaration and/or implementation set successfully.")
    sys.exit(0)

except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error setting code for object '%s' in project '%s': %s\\n%s" % (POU_FULL_PATH, PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

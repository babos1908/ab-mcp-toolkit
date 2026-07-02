import sys, scriptengine as script_engine, os, traceback

POU_NAME = "{POU_NAME}"
POU_TYPE_STR = "{POU_TYPE_STR}"
IMPL_LANGUAGE_STR = "{IMPL_LANGUAGE_STR}"
PARENT_PATH_REL = "{PARENT_PATH}"
RETURN_TYPE = "{RETURN_TYPE}"  # Required for Function POUs (e.g. "BOOL", "STRING"); ignored for Program/FunctionBlock

pou_type_map = {
    "Program": script_engine.PouType.Program,
    "FunctionBlock": script_engine.PouType.FunctionBlock,
    "Function": script_engine.PouType.Function,
}
# Interface is exposed by AB 2.9 / CODESYS V3.5 SP19 but not on every build.
# Probe for the enum member at module-load time rather than at call time so
# the failure mode is obvious in the DEBUG log.
if hasattr(script_engine.PouType, 'Interface'):
    pou_type_map["Interface"] = script_engine.PouType.Interface
# ParameterList: V3 exposes it via parent.create_parameterlist(name) on
# AB 2.9. Same probe pattern as Interface -- if the enum member exists
# it acts as a fallback path; otherwise the dedicated method below covers
# every shipping build.
if hasattr(script_engine.PouType, 'ParameterList'):
    pou_type_map["ParameterList"] = script_engine.PouType.ParameterList
# Map common language names to ImplementationLanguages attributes if needed (optional, None usually works)
# lang_map = { "ST": script_engine.ImplementationLanguage.st, ... }

try:
    print("DEBUG: create_pou script: Name='%s', Type='%s', Lang='%s', ParentPath='%s', Project='%s'" % (POU_NAME, POU_TYPE_STR, IMPL_LANGUAGE_STR, PARENT_PATH_REL, PROJECT_FILE_PATH))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not POU_NAME: print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT"); raise ValueError("POU name empty.")
    if not PARENT_PATH_REL: print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT"); raise ValueError("Parent path empty.")

    # Resolve POU Type Enum (Interface / ParameterList may be None here --
    # we have dedicated create_interface() / create_parameterlist() methods
    # to fall back to below on builds that don't expose the enum members).
    pou_type_enum = pou_type_map.get(POU_TYPE_STR)
    if pou_type_enum is None and POU_TYPE_STR not in ("Interface", "ParameterList"):
        available = sorted(pou_type_map.keys())
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError(
            "Invalid POU type string: '%s'. Use one of: %s" % (POU_TYPE_STR, available)
        )

    # For common case where user just specified "Application", automatically try to find it
    if PARENT_PATH_REL == "Application":
        # Get project name from file path to build the likely full path
        project_name = os.path.splitext(os.path.basename(PROJECT_FILE_PATH))[0]
        potential_paths = [
            PARENT_PATH_REL,                                      # Original "Application"
            "%s.%s" % (project_name, PARENT_PATH_REL),           # "projectName.Application"
            "%s/%s" % (project_name, PARENT_PATH_REL),           # "projectName/Application"
            "PLCWinNT/Plc Logic/Application",                    # Common CODESYS structure
            "PLCWinNT.Plc Logic.Application",                    # Using dots instead
            project_name                                         # Just the project name itself might work
        ]

        print("DEBUG: Parent path is simply 'Application', trying several variants to find it")

        # Try each potential path until one works
        parent_object = None
        for path in potential_paths:
            print("DEBUG: Attempting to find parent with path: '%s'" % path)
            parent_candidate = find_object_by_path_robust(primary_project, path, "parent container")
            if parent_candidate:
                parent_object = parent_candidate
                print("DEBUG: Successfully found parent using path: '%s'" % path)
                break

        if not parent_object:
            # For diagnostics, try to get the application object directly as a fallback
            print("DEBUG: All path attempts failed. Trying to access application directly...")
            try:
                if hasattr(primary_project, 'active_application'):
                    app = primary_project.active_application
                    if app:
                        parent_object = app
                        print("DEBUG: Found application object directly: %s" % app.get_name())
                if not parent_object and hasattr(primary_project, 'find'):
                    apps = primary_project.find("Application", True)
                    if apps:
                        parent_object = apps[0]
                        print("DEBUG: Found application via search: %s" % parent_object.get_name())
            except Exception as e:
                print("ERROR: Direct application access also failed: %s" % e)
    else:
        # Use the provided path normally
        parent_object = find_object_by_path_robust(primary_project, PARENT_PATH_REL, "parent container")

    # Final check if parent was found
    if not parent_object:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise ValueError("Parent object not found for path: %s. Try using the full path like 'ProjectName.Application' or run get_project_structure first to see the correct structure." % PARENT_PATH_REL)

    parent_name = getattr(parent_object, 'get_name', lambda: str(parent_object))()
    print("DEBUG: Using parent object: %s (Type: %s)" % (parent_name, type(parent_object).__name__))

    # Check if parent object supports creating POUs (should implement ScriptIecLanguageObjectContainer)
    if not hasattr(parent_object, 'create_pou'):
        print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
        raise TypeError("Parent object '%s' of type %s does not support create_pou." % (parent_name, type(parent_object).__name__))

    # Set language GUID to None (let CODESYS default based on parent/settings)
    lang_guid = None
    print("DEBUG: Setting language to None (will use default).")
    # Example if mapping language string: lang_guid = lang_map.get(IMPL_LANGUAGE_STR, None)

    print("DEBUG: Calling parent_object.create_pou: Name='%s', Type=%s, Lang=%s, ReturnType='%s'" % (POU_NAME, pou_type_enum, lang_guid, RETURN_TYPE))

    # Interface POUs in CODESYS V3 / AB 2.9 are typically created via a
    # SEPARATE method `parent.create_interface(name)` rather than via
    # `create_pou(type=PouType.Interface)`. Try the separate method first;
    # fall back to create_pou with the enum if the build exposes it.
    if POU_TYPE_STR == "Interface":
        new_pou = None
        # Path A: dedicated create_interface() method
        if hasattr(parent_object, 'create_interface'):
            try:
                new_pou = parent_object.create_interface(POU_NAME)
                print("DEBUG: parent_object.create_interface() succeeded.")
            except TypeError:
                # Some builds want extra kwargs; retry common signatures.
                try:
                    new_pou = parent_object.create_interface(name=POU_NAME)
                except Exception as ci_err:
                    print("WARN: create_interface(name=...) raised: %s" % ci_err)
            except Exception as ci_err:
                print("WARN: create_interface() raised: %s" % ci_err)
        # Path B: create_pou with PouType.Interface enum
        if new_pou is None and hasattr(script_engine.PouType, 'Interface'):
            try:
                new_pou = parent_object.create_pou(
                    name=POU_NAME,
                    type=script_engine.PouType.Interface
                )
                print("DEBUG: parent_object.create_pou(type=PouType.Interface) succeeded.")
            except TypeError:
                try:
                    new_pou = parent_object.create_pou(
                        name=POU_NAME,
                        type=script_engine.PouType.Interface,
                        language=lang_guid
                    )
                except Exception as cp_err:
                    print("WARN: create_pou(type=Interface, language=...) raised: %s" % cp_err)
            except Exception as cp_err:
                print("WARN: create_pou(type=Interface) raised: %s" % cp_err)
        # Path C: diagnostic dump if both paths failed
        if new_pou is None:
            pou_types = [a for a in dir(script_engine.PouType) if not a.startswith('_')]
            parent_creates = [a for a in dir(parent_object) if a.lower().startswith('create')]
            print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
            raise RuntimeError(
                "Could not create Interface '%s'. Neither parent.create_interface() nor "
                "parent.create_pou(type=PouType.Interface) succeeded on this build. "
                "Available PouType members: %s. Parent create_* methods: %s." %
                (POU_NAME, pou_types, parent_creates)
            )
    elif POU_TYPE_STR == "ParameterList":
        # Parameter List POUs in CODESYS V3 / AB 2.9 are created via a
        # dedicated method (analogous to create_interface). The resulting
        # POU exposes a single VAR_GLOBAL CONSTANT block on its
        # textual_declaration -- consumers of the library can override
        # these constants without forking, and they show up under the
        # Library Manager 'Parameters' tab.
        #
        # Empirical 2026-05-17 on AB 2.9 Standard against
        # `NexoMqttLib.library`: PouType.ParameterList is NOT in the
        # PouType enum, AND `parent.create_parameterlist` is not exposed
        # on the library root either. Diagnostic showed dir() returning
        # zero `create_*` methods despite create_pou being callable,
        # confirming AB's parent objects are .NET COM proxies where dir()
        # does not enumerate explicit-interface members. We therefore
        # probe candidate method names with hasattr() (which DOES probe
        # the COM proxy correctly), and report which ones are present in
        # the diagnostic so the next failure surfaces actionable info.
        new_pou = None
        attempt_log = []

        # Candidate method names worth trying. Order: most-likely-correct
        # first based on CODESYS V3 naming conventions and the Interface
        # path that already works on AB 2.9 Standard via create_interface().
        candidate_methods = (
            'create_parameterlist',
            'create_parameter_list',
            'create_global_textual_list',
            'create_constants_list',
            'create_parameters',
            'add_parameterlist',
            'add_parameter_list',
        )
        for method_name in candidate_methods:
            if not hasattr(parent_object, method_name):
                attempt_log.append("%s: not present on parent" % method_name)
                continue
            method = getattr(parent_object, method_name)
            try:
                new_pou = method(POU_NAME)
                print("DEBUG: parent_object.%s(%r) succeeded." % (method_name, POU_NAME))
                break
            except TypeError as te:
                try:
                    new_pou = method(name=POU_NAME)
                    print("DEBUG: parent_object.%s(name=%r) succeeded." % (method_name, POU_NAME))
                    break
                except Exception as e2:
                    attempt_log.append("%s positional + named: TypeError positional (%s), then %s named" % (method_name, te, type(e2).__name__))
            except Exception as e:
                attempt_log.append("%s: %s: %s" % (method_name, type(e).__name__, e))

        # Path B: create_pou with PouType.ParameterList enum (future builds
        # that expose the member -- known absent on AB 2.9 Standard SP19).
        if new_pou is None and hasattr(script_engine.PouType, 'ParameterList'):
            try:
                new_pou = parent_object.create_pou(
                    name=POU_NAME,
                    type=script_engine.PouType.ParameterList
                )
                print("DEBUG: parent_object.create_pou(type=PouType.ParameterList) succeeded.")
            except TypeError:
                try:
                    new_pou = parent_object.create_pou(
                        name=POU_NAME,
                        type=script_engine.PouType.ParameterList,
                        language=lang_guid
                    )
                    print("DEBUG: parent_object.create_pou(type=PouType.ParameterList, language=...) succeeded.")
                except Exception as cp_err:
                    attempt_log.append("create_pou(type=ParameterList, language=...): %s" % cp_err)
            except Exception as cp_err:
                attempt_log.append("create_pou(type=ParameterList): %s" % cp_err)
        elif new_pou is None:
            attempt_log.append("PouType.ParameterList: not in enum (typical on AB 2.9 Standard)")

        # Path C: template-based creation. CODESYS V3 exposes
        # create_pou_with_template / create_object_from_template on some
        # parent types; the template GUID for Parameter List would have
        # to be discovered (likely vendor-private). We probe for the
        # methods so the diagnostic surfaces them if they exist.
        if new_pou is None:
            for tmpl_method in ('create_pou_with_template', 'create_object_from_template'):
                if hasattr(parent_object, tmpl_method):
                    attempt_log.append(
                        "%s: present but template GUID for ParameterList is unknown on this build; "
                        "cannot probe without a template registry" % tmpl_method
                    )

        # Path D: enhanced diagnostic. dir() is unreliable on COM proxies,
        # so probe a known list via hasattr() and report what's actually
        # callable on the parent. This is the info to forward upstream if
        # the failure recurs.
        if new_pou is None:
            probe_names = (
                'create_pou', 'create_method', 'create_interface', 'create_property',
                'create_gvl', 'create_dut', 'create_folder', 'create_action',
                'create_parameterlist', 'create_parameter_list',
                'create_pou_with_template', 'create_object_from_template',
                'create_global_textual_list', 'create_constants_list',
                'add_object', 'add_pou', 'add_parameterlist', 'add_parameter_list',
                'children', 'templates', 'import_native', 'export_native',
            )
            present_on_parent = [n for n in probe_names if hasattr(parent_object, n)]
            pou_types = [a for a in dir(script_engine.PouType) if not a.startswith('_')]
            print("SCRIPT_ERROR_CODE: ERR_API_NOT_EXPOSED")
            raise RuntimeError(
                "Could not create ParameterList '%s'. No working API path found on this "
                "AB / CODESYS build (likely the Standard edition, which does not surface "
                "Parameter List creation through the IronPython ScriptEngine). "
                "Workaround: create the POU manually in the AB UI "
                "(Add Object -> Parameter List), then populate it via set_pou_code on "
                "the declaration section. "
                "Attempt log: %s. "
                "Available PouType members: %s. "
                "Methods present on parent (probed via hasattr, not dir): %s." %
                (POU_NAME, attempt_log, pou_types, present_on_parent)
            )
    elif pou_type_enum == script_engine.PouType.Function:
        actual_return_type = RETURN_TYPE if RETURN_TYPE else None
        if actual_return_type is None:
            print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
            raise ValueError("Function POU '%s' requires a return_type. Provide the 'returnType' tool parameter (e.g. 'BOOL', 'STRING', 'INT')." % POU_NAME)
        new_pou = parent_object.create_pou(
            name=POU_NAME,
            type=pou_type_enum,
            language=lang_guid, # Pass None to use default
            return_type=actual_return_type
        )
    else:
        new_pou = parent_object.create_pou(
            name=POU_NAME,
            type=pou_type_enum,
            language=lang_guid # Pass None
        )

    print("DEBUG: parent_object.create_pou returned: %s" % new_pou)
    if new_pou:
        new_pou_name = getattr(new_pou, 'get_name', lambda: POU_NAME)()
        print("DEBUG: POU object created: %s" % new_pou_name)

        # --- SAVE THE PROJECT TO PERSIST THE NEW POU ---
        try:
            print("DEBUG: Saving Project...")
            primary_project.save() # Save the overall project file
            print("DEBUG: Project saved successfully after POU creation.")
        except Exception as save_err:
            print("ERROR: Failed to save Project after POU creation: %s" % save_err)
            detailed_error = traceback.format_exc()
            error_message = "Error saving Project after creating POU '%s': %s\\n%s" % (new_pou_name, save_err, detailed_error)
            print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
            print(error_message); print("SCRIPT_ERROR: %s" % error_message); sys.exit(1)
        # --- END SAVING ---

        print("POU Created: %s" % new_pou_name)
        print("Type: %s" % POU_TYPE_STR)
        print("Language: %s (Defaulted)" % IMPL_LANGUAGE_STR)
        print("Parent Path: %s" % PARENT_PATH_REL)
        print("SCRIPT_SUCCESS: POU created successfully.")
        sys.exit(0)
    else:
        error_message = "Failed to create POU '%s'. create_pou returned None." % POU_NAME
        print(error_message)
        print("SCRIPT_ERROR_CODE: ERR_UNKNOWN")
        print("SCRIPT_ERROR: %s" % error_message)
        sys.exit(1)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error creating POU '%s' in project '%s': %s\\n%s" % (POU_NAME, PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: Error creating POU '%s': %s" % (POU_NAME, e))
    sys.exit(1)

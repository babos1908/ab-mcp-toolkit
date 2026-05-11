import sys, scriptengine as script_engine, os, traceback, json

# Build / code-check message category GUIDs (CODESYS V3 internal).
# These are the categories that contain the actual compile-time errors /
# warnings, discovered via system.get_message_categories().
#
# - 'Build'                  : 97F48D64-A2A3-4856-B640-75C046E37EA9
# - 'Additional code checks' : 220493A1-F49B-4416-9A3F-A545DB707CBE
# - 'Precompile'             : 217BC73E-759B-4A3C-BFA1-991C938A6541
COMPILE_CATEGORY_GUIDS = [
    '97F48D64-A2A3-4856-B640-75C046E37EA9',  # Build
    '220493A1-F49B-4416-9A3F-A545DB707CBE',  # Additional code checks
    '217BC73E-759B-4A3C-BFA1-991C938A6541',  # Precompile
]

try:
    print("DEBUG: compile_project script: Project='%s'" % PROJECT_FILE_PATH)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    project_name = os.path.basename(PROJECT_FILE_PATH)

    # --- Locate the application to compile ---
    target_app = None
    app_name = "N/A"
    try:
        target_app = primary_project.active_application
        if target_app:
            app_name = getattr(target_app, 'get_name', lambda: "Unnamed App (Active)")()
            print("DEBUG: Found active application: %s" % app_name)
    except Exception as active_err:
        print("WARN: Could not get active application: %s. Searching..." % active_err)

    if not target_app:
        print("DEBUG: Searching for first compilable application...")
        apps = []
        try:
            all_children = primary_project.get_children(True)
            for child in all_children:
                if hasattr(child, 'is_application') and child.is_application and hasattr(child, 'generate_code'):
                    app_name_found = getattr(child, 'get_name', lambda: "Unnamed App")()
                    print("DEBUG: Found potential application object: %s" % app_name_found)
                    apps.append(child)
                    break
        except Exception as find_err:
            print("WARN: Error finding application object: %s" % find_err)

        if not apps:
            raise RuntimeError("No compilable application found in project '%s'" % project_name)
        target_app = apps[0]
        app_name = getattr(target_app, 'get_name', lambda: "Unnamed App (First Found)")()
        print("WARN: Compiling first found application: %s" % app_name)

    # --- Save any pending edits so the build sees them ---
    try:
        if hasattr(primary_project, 'dirty') and primary_project.dirty:
            if hasattr(primary_project, 'save'):
                primary_project.save()
                print("DEBUG: Saved dirty project before build.")
    except Exception as save_err:
        print("WARN: Pre-build save failed (continuing): %s" % save_err)

    # --- Clear cached messages from compile categories ---
    # Without this, get_message_objects() returns stale entries from previous
    # builds and severity counts are wrong.
    # NOTE: Guid type must be accessed via script_engine.Guid (it's a .NET
    # type imported into the scriptengine module, not a Python builtin).
    for guid_str in COMPILE_CATEGORY_GUIDS:
        try:
            cat_guid = script_engine.Guid('{%s}' % guid_str)
            script_engine.system.clear_messages(cat_guid)
        except Exception as clr_err:
            print("WARN: clear_messages(%s) failed: %s" % (guid_str, clr_err))

    # --- Trigger code generation (F11 equivalent) ---
    # generate_code() is the right API for the "Build > Build" UI command.
    # application.build() does a softer pass that doesn't always invoke the
    # full semantic analyzer; users would see "0 errors" via API while the
    # IDE displays dozens of "Identifier not defined" / type mismatches.
    print("DEBUG: Calling generate_code() on app '%s'..." % app_name)
    if hasattr(target_app, 'generate_code'):
        try:
            target_app.generate_code()
            print("DEBUG: generate_code() executed for application '%s'." % app_name)
        except Exception as gen_err:
            print("WARN: generate_code() failed, falling back to build(): %s" % gen_err)
            if hasattr(target_app, 'build'):
                target_app.build()
    elif hasattr(target_app, 'build'):
        target_app.build()
        print("DEBUG: build() executed (no generate_code available).")
    else:
        raise TypeError("Application '%s' supports neither generate_code() nor build()." % app_name)

    # --- Collect messages from every compile category, filtered by severity ---
    messages = []
    severity_labels = {}
    severity_filter_mask = None
    try:
        Severity = script_engine.Severity
        severity_labels = {
            Severity.FatalError: 'fatal',
            Severity.Error: 'error',
            Severity.Warning: 'warning',
            Severity.Information: 'info',
            Severity.Text: 'text',
        }
        # Only pull errors/warnings/fatals - skip text noise like 'Build started'.
        severity_filter_mask = Severity.FatalError | Severity.Error | Severity.Warning
    except Exception as se_err:
        print("WARN: Could not set up severity filter: %s" % se_err)

    def _sev_to_string(sev):
        try:
            return severity_labels.get(sev, str(sev).lower())
        except Exception:
            return 'unknown'

    for guid_str in COMPILE_CATEGORY_GUIDS:
        try:
            cat_guid = script_engine.Guid('{%s}' % guid_str)
            try:
                cat_name = script_engine.system.get_message_category_description(cat_guid)
            except Exception:
                cat_name = guid_str

            if severity_filter_mask is not None:
                cat_msgs = script_engine.system.get_message_objects(cat_guid, severity_filter_mask)
            else:
                cat_msgs = script_engine.system.get_message_objects(cat_guid)
            if cat_msgs is None:
                continue
            for msg in cat_msgs:
                entry = {
                    'category': cat_name,
                    'severity': _sev_to_string(getattr(msg, 'severity', None)),
                    'text': getattr(msg, 'text', getattr(msg, 'message', str(msg))),
                }
                # Stable error code like "C0046" when available.
                if hasattr(msg, 'prefix') and hasattr(msg, 'number'):
                    try:
                        entry['code'] = "%s%s" % (msg.prefix, msg.number)
                    except Exception:
                        pass
                # Object/POU where the error occurred.
                if hasattr(msg, 'object_name'):
                    entry['object'] = msg.object_name
                elif hasattr(msg, 'source'):
                    entry['object'] = str(msg.source)
                # Line number.
                if hasattr(msg, 'line_number'):
                    entry['line'] = msg.line_number
                elif hasattr(msg, 'position'):
                    entry['line'] = msg.position
                messages.append(entry)
        except Exception as cat_err:
            print("WARN: failed to collect messages for category %s: %s"
                  % (guid_str, cat_err))

    # --- Serialize as JSON between markers for the Node.js side to parse ---
    for entry in messages:
        for k in ('text', 'object', 'severity', 'category', 'code'):
            if k in entry:
                entry[k] = _to_unicode(entry[k])

    messages_json = json.dumps(messages, ensure_ascii=False, default=_json_default)
    if isinstance(messages_json, unicode):
        messages_json_bytes = messages_json.encode('utf-8')
    else:
        messages_json_bytes = messages_json
    sys.stdout.write("### COMPILE_MESSAGES_START ###\n")
    sys.stdout.write(messages_json_bytes)
    sys.stdout.write("\n### COMPILE_MESSAGES_END ###\n")
    sys.stdout.flush()

    print("Compile Initiated For Application: %s" % app_name)
    print("In Project: %s" % project_name)
    print("Message Count: %d" % len(messages))
    print("SCRIPT_SUCCESS: Application compilation initiated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error initiating compilation for project %s: %s\n%s" % (PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

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

    # --- Discover all message categories dynamically ---
    #
    # Hardcoded GUIDs (Build / Additional code checks / Precompile) cover the
    # common cases but on bigger projects compile errors land in OTHER
    # categories too (e.g. Library Manager, POU-specific, project-tree).
    # Enumerate every category exposed by the runtime; fall back to the
    # hardcoded triple if enumeration fails. Each entry is (Guid, name_str).
    # NOTE: Guid is the .NET type exposed as script_engine.Guid, not a Python
    # builtin -- using bare Guid("{...}") raises NameError silently.
    all_categories = []
    try:
        cats = script_engine.system.get_message_categories()
        if cats is not None:
            for cat in cats:
                cat_guid = None
                cat_name = None
                try:
                    if hasattr(cat, 'guid'):
                        cat_guid = cat.guid
                        cat_name = getattr(cat, 'description', None) or getattr(cat, 'name', None)
                    elif isinstance(cat, (tuple, list)) and len(cat) > 0:
                        cat_guid = cat[0]
                        if len(cat) > 1:
                            cat_name = cat[1]
                    else:
                        # Probably a bare Guid
                        cat_guid = cat
                except Exception:
                    pass
                if cat_guid is None:
                    continue
                if cat_name is None:
                    try:
                        cat_name = script_engine.system.get_message_category_description(cat_guid)
                    except Exception:
                        cat_name = str(cat_guid)
                all_categories.append((cat_guid, cat_name))
    except Exception as cat_enum_err:
        print("WARN: get_message_categories() enumeration failed: %s" % cat_enum_err)

    if not all_categories:
        print("DEBUG: Dynamic enumeration empty -- falling back to hardcoded compile categories.")
        for guid_str in COMPILE_CATEGORY_GUIDS:
            try:
                cat_guid = script_engine.Guid('{%s}' % guid_str)
                try:
                    cat_name = script_engine.system.get_message_category_description(cat_guid)
                except Exception:
                    cat_name = guid_str
                all_categories.append((cat_guid, cat_name))
            except Exception as fallback_err:
                print("WARN: hardcoded fallback for %s failed: %s" % (guid_str, fallback_err))

    print("DEBUG: %d message categories will be scanned" % len(all_categories))

    # --- Clear cached messages in every discovered category ---
    # Without this, get_message_objects() returns stale entries from prior
    # builds and severity counts are wrong.
    for cat_guid, cat_name in all_categories:
        try:
            script_engine.system.clear_messages(cat_guid)
        except Exception as clr_err:
            print("WARN: clear_messages('%s') failed: %s" % (cat_name, clr_err))

    # --- Trigger build ---
    # Call BOTH build() and generate_code(): on bigger projects (libraries,
    # multi-POU device trees), generate_code() alone can skip the semantic
    # check and silently report 0 errors while the UI shows C0046. build() is
    # the F11 equivalent and forces the full semantic analyzer. We run build()
    # first then generate_code() for redundancy; clear_messages() above
    # ensures we still get a clean message store.
    build_invoked = False
    if hasattr(target_app, 'build'):
        try:
            target_app.build()
            print("DEBUG: build() executed for application '%s'." % app_name)
            build_invoked = True
        except Exception as build_err:
            print("WARN: build() raised: %s" % build_err)
    if hasattr(target_app, 'generate_code'):
        try:
            target_app.generate_code()
            print("DEBUG: generate_code() executed for application '%s'." % app_name)
            build_invoked = True
        except Exception as gen_err:
            print("WARN: generate_code() raised: %s" % gen_err)
    if not build_invoked:
        raise TypeError(
            "Application '%s' supports neither build() nor generate_code()." % app_name
        )

    # --- Collect messages from every compile category ---
    #
    # No severity_filter_mask passed to get_message_objects(): the bitwise OR
    # of Severity enum members is fragile across CODESYS versions (Severity is
    # sometimes a plain Enum, not [Flags]) and produces silent under-counts
    # where Warning messages come through but Error messages do not. On
    # AB 2.9 / CODESYS V3.5 SP19 this reproduces deterministically: a project
    # with 2 errors + 1 warning returns 1 entry (the warning), 0 errors.
    # Fetch everything and filter Python-side via the decoded severity string
    # -- robust across runtime versions.
    messages = []
    severity_labels = {}
    try:
        Severity = script_engine.Severity
        severity_labels = {
            Severity.FatalError: 'fatal',
            Severity.Error: 'error',
            Severity.Warning: 'warning',
            Severity.Information: 'info',
            Severity.Text: 'text',
        }
    except Exception as se_err:
        print("WARN: Could not set up severity labels: %s" % se_err)

    def _sev_to_string(sev):
        try:
            return severity_labels.get(sev, str(sev).lower())
        except Exception:
            return 'unknown'

    # Severities worth reporting. Info/text are noise (Build started, etc.).
    KEEP_SEVS = ('fatal', 'error', 'warning')

    # Iterate the dynamic category list built earlier. Print a per-category
    # severity histogram to stdout so the watcher.log captures it for
    # post-mortem if we miss something on bigger projects.
    for cat_guid, cat_name in all_categories:
        try:
            cat_msgs = script_engine.system.get_message_objects(cat_guid)
            if cat_msgs is None:
                continue

            # Diagnostic histogram (visible in watcher.log per session).
            counts = {}
            collected_in_cat = 0
            for msg in cat_msgs:
                sev_str = _sev_to_string(getattr(msg, 'severity', None))
                counts[sev_str] = counts.get(sev_str, 0) + 1
                if sev_str not in KEEP_SEVS:
                    continue
                collected_in_cat += 1
                entry = {
                    'category': cat_name,
                    'severity': sev_str,
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
            if counts:
                print("DEBUG: category '%s' (%d msgs total, %d kept): %s"
                      % (cat_name, sum(counts.values()), collected_in_cat, counts))
        except Exception as cat_err:
            print("WARN: failed to collect messages for category '%s': %s"
                  % (cat_name, cat_err))

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

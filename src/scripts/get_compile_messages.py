import sys, scriptengine as script_engine, os, traceback, json

# Same hardcoded compile-category GUIDs as compile_project.py. These are the
# CODESYS V3 internal IDs for Build / Additional code checks / Precompile;
# we force-include them in the scan list because on library projects the
# dynamic get_message_categories() enumeration can return only "Script
# Messages" and hide real errors.
COMPILE_CATEGORY_GUIDS = [
    '97F48D64-A2A3-4856-B640-75C046E37EA9',  # Build
    '220493A1-F49B-4416-9A3F-A545DB707CBE',  # Additional code checks
    '217BC73E-759B-4A3C-BFA1-991C938A6541',  # Precompile
]

try:
    print("DEBUG: get_compile_messages script: Project='%s'" % PROJECT_FILE_PATH)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    project_name = os.path.basename(PROJECT_FILE_PATH)

    # --- Detect project kind (application vs library) ---
    # We no longer bail out when no Application is found: library projects
    # have legitimate compile messages that live at system scope.
    target_app = None
    app_name = "N/A"
    project_kind = "unknown"
    try:
        target_app = primary_project.active_application
        if target_app:
            app_name = getattr(target_app, 'get_name', lambda: "Unnamed App")()
            project_kind = "application"
    except Exception as active_err:
        print("WARN: Could not get active application: %s" % active_err)

    if not target_app:
        try:
            for child in primary_project.get_children(True):
                if hasattr(child, 'is_application') and child.is_application:
                    target_app = child
                    app_name = getattr(child, 'get_name', lambda: "Unnamed App")()
                    project_kind = "application"
                    break
        except Exception as find_err:
            print("WARN: Error finding application object: %s" % find_err)

    if not target_app:
        # Library project (or unusual project layout). Compile messages still
        # live in the system message store; just skip the app-scoped fetch
        # below and go straight to the category-aware path.
        is_library_ext = PROJECT_FILE_PATH.lower().endswith('.library')
        if is_library_ext:
            project_kind = "library"
            app_name = "(library pool)"
        print("DEBUG: No Application found (kind=%s); falling back to system-scope category scan."
              % project_kind)

    # --- Build the category scan list ---
    # Mirror of compile_project.py: dynamic enumeration via
    # get_message_categories() UNION the hardcoded compile-category GUIDs.
    # The hardcoded set is critical for library projects where the dynamic
    # enumeration may return only "Script Messages".
    all_categories = []
    enum_used = "none"
    try:
        cats = script_engine.system.get_message_categories() if hasattr(
            script_engine.system, 'get_message_categories'
        ) else None
        if cats is not None:
            enum_used = "dynamic"
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

    # Force-merge the hardcoded GUIDs (de-dup by stringified Guid)
    existing_guid_strs = set()
    for cat_guid, _ in all_categories:
        try:
            existing_guid_strs.add(str(cat_guid).strip('{}').upper())
        except Exception:
            pass
    for guid_str in COMPILE_CATEGORY_GUIDS:
        if guid_str.upper() in existing_guid_strs:
            continue
        try:
            cat_guid = script_engine.Guid('{%s}' % guid_str)
            try:
                cat_name = script_engine.system.get_message_category_description(cat_guid)
            except Exception:
                cat_name = guid_str
            all_categories.append((cat_guid, cat_name))
            print("DEBUG: force-added hardcoded compile category '%s' (guid=%s)"
                  % (cat_name, guid_str))
        except Exception as merge_err:
            print("WARN: could not force-add hardcoded category %s: %s" % (guid_str, merge_err))

    print("DEBUG: %d message categories will be scanned (source: %s)"
          % (len(all_categories), enum_used))

    # --- Severity decoding ---
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

    KEEP_SEVS = ('fatal', 'error', 'warning')

    def _build_entry(msg, cat_name_override=None, sev_str_override=None):
        sev_str = sev_str_override or _sev_to_string(getattr(msg, 'severity', None))
        entry = {
            'category': cat_name_override or 'unknown',
            'severity': sev_str,
            'text': getattr(msg, 'text', getattr(msg, 'message', str(msg))),
        }
        if hasattr(msg, 'prefix') and hasattr(msg, 'number'):
            try:
                entry['code'] = "%s%s" % (msg.prefix, msg.number)
            except Exception:
                pass
        if hasattr(msg, 'object_name'):
            entry['object'] = msg.object_name
        elif hasattr(msg, 'source'):
            entry['object'] = str(msg.source)
        if hasattr(msg, 'line_number'):
            entry['line'] = msg.line_number
        elif hasattr(msg, 'position'):
            entry['line'] = msg.position
        return entry

    # --- Collect cached messages from every category ---
    messages = []
    seen_keys = set()
    for cat_guid, cat_name in all_categories:
        try:
            cat_msgs = script_engine.system.get_message_objects(cat_guid)
            if cat_msgs is None:
                continue
            counts = {}
            collected_in_cat = 0
            for msg in cat_msgs:
                sev_raw = getattr(msg, 'severity', None)
                sev_str = _sev_to_string(sev_raw)
                counts[sev_str] = counts.get(sev_str, 0) + 1
                if sev_str not in KEEP_SEVS:
                    continue
                collected_in_cat += 1
                entry = _build_entry(msg, cat_name_override=cat_name)
                key = (entry.get('category'), entry.get('text'), entry.get('object'), entry.get('line'))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                messages.append(entry)
            if counts:
                print("DEBUG: category '%s' (%d msgs total, %d kept): %s"
                      % (cat_name, sum(counts.values()), collected_in_cat, counts))
        except Exception as cat_err:
            print("WARN: failed to read category '%s': %s" % (cat_name, cat_err))

    # Global no-filter sweep -- catches messages emitted to categories that
    # were not enumerated for any reason.
    try:
        if hasattr(script_engine.system, 'get_message_objects'):
            global_msgs = script_engine.system.get_message_objects()
            if global_msgs is not None:
                added_from_global = 0
                for msg in global_msgs:
                    sev_raw = getattr(msg, 'severity', None)
                    sev_str = _sev_to_string(sev_raw)
                    if sev_str not in KEEP_SEVS:
                        continue
                    entry = _build_entry(msg, cat_name_override='(global)')
                    key = (None, entry.get('text'), entry.get('object'), entry.get('line'))
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    messages.append(entry)
                    added_from_global += 1
                if added_from_global:
                    print("DEBUG: global get_message_objects() added %d new entries." % added_from_global)
    except Exception as global_err:
        print("WARN: global get_message_objects() failed: %s" % global_err)

    # --- Serialize ---
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
    print("Project Kind: %s" % project_kind)
    print("Target: %s" % app_name)
    print("Message Count: %d" % len(messages))
    print("SCRIPT_SUCCESS: Compile messages retrieved.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error getting compile messages for project %s: %s\n%s" % (PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

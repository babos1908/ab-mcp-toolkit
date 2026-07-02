import sys, scriptengine as script_engine, os, traceback, json

# run_static_analysis
# -------------------
# Triggers CODESYS Static Analysis (Premium-only "Code Analysis" add-on) via
# the scripting command bus, then reads the findings back from the message
# store. Confirmed working 2026-05-30 on AB 2.9 SP19 Premium.
#
# Mechanism (empirically verified):
#   - se.system.commands contains a ScriptCommand "Run Static Analysis"
#     with guid AE97B6F4-DC9A-480E-AAC8-6061E684F3C0 (tokens
#     ('staticanalysis','run')). ScriptCommand.execute() runs it.
#   - Findings land in message category "Additional code checks"
#     guid 220493A1-F49B-4416-9A3F-A545DB707CBE, readable via
#     se.system.get_message_objects(System.Guid(...)).
#
# IMPORTANT: do NOT use the "...export to Sarif file" command
# (guid AAAAAAAA-0E82-46EF-BAEC-B2DEAE722D28). Its execute() opens a modal
# Save-As dialog on the primary thread, which deadlocks the watcher. We read
# findings from the message store instead.
#
# Output format mirrors compile_project so the Node-side parseCompileMessages()
# parser is reused verbatim (### COMPILE_MESSAGES_START/END ### + JSON array).

# Stable command + category GUIDs (CODESYS V3.5 SP19 / AB 2.9).
SA_RUN_COMMAND_GUID = 'AE97B6F4-DC9A-480E-AAC8-6061E684F3C0'
# Categories where SA / code-check findings can surface. "Additional code
# checks" is the primary SA bucket; Precompile sometimes carries
# rule-violation entries too. Both scanned defensively.
SA_CATEGORY_GUIDS = [
    '220493A1-F49B-4416-9A3F-A545DB707CBE',  # Additional code checks (SA)
    '217BC73E-759B-4A3C-BFA1-991C938A6541',  # Precompile
]

try:
    print("DEBUG: run_static_analysis: Project='%s'" % PROJECT_FILE_PATH)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    project_name = os.path.basename(PROJECT_FILE_PATH)

    # --- Locate the active application (SA runs against it) ---
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
            "No application found in project '%s'. Static Analysis runs against "
            "an Application node; open the project and set an active application." % project_name)
    print("DEBUG: target application: %s" % app_name)

    # --- Generate code first: SA needs a current compiled model ---
    # Without a fresh generate_code(), SA can run against a stale model or
    # report nothing. Best-effort: a failure here is surfaced but not fatal,
    # because SA may still produce useful rule-violation output.
    try:
        if hasattr(target_app, 'generate_code'):
            target_app.generate_code()
            print("DEBUG: generate_code() executed for '%s'." % app_name)
    except Exception as gen_err:
        print("WARN: generate_code() raised (continuing): %s" % gen_err)

    # --- Resolve the SA category GUIDs to (Guid, name) and clear them ---
    sa_categories = []
    for guid_str in SA_CATEGORY_GUIDS:
        try:
            cat_guid = script_engine.Guid('{%s}' % guid_str)
        except Exception as guid_err:
            print("WARN: could not build Guid for %s: %s" % (guid_str, guid_err))
            continue
        try:
            cat_name = script_engine.system.get_message_category_description(cat_guid)
        except Exception:
            cat_name = guid_str
        sa_categories.append((cat_guid, cat_name))
        try:
            script_engine.system.clear_messages(cat_guid)
        except Exception as clr_err:
            print("WARN: clear_messages('%s') failed: %s" % (cat_name, clr_err))

    # --- Find and execute the "Run Static Analysis" command ---
    sa_cmd = None
    sa_cmd_name = None
    try:
        for c in script_engine.system.commands:
            try:
                cg = str(getattr(c, 'guid', '')).strip('{}').upper()
            except Exception:
                continue
            if cg == SA_RUN_COMMAND_GUID.upper():
                sa_cmd = c
                try:
                    sa_cmd_name = getattr(c, 'name', None)
                    sa_cmd_name = sa_cmd_name() if callable(sa_cmd_name) else sa_cmd_name
                except Exception:
                    sa_cmd_name = 'Run Static Analysis'
                break
    except Exception as enum_err:
        print("WARN: command enumeration failed: %s" % enum_err)

    if sa_cmd is None:
        print("SCRIPT_ERROR_CODE: ERR_SA_NOT_AVAILABLE")
        raise RuntimeError(
            "Static Analysis command (guid %s) not found in se.system.commands. "
            "Code Analysis is a Premium-only add-on; confirm the AB edition is "
            "Premium and the Static Analysis package is installed." % SA_RUN_COMMAND_GUID)

    print("DEBUG: executing command '%s' (guid %s)" % (sa_cmd_name, SA_RUN_COMMAND_GUID))
    sa_cmd.execute()
    print("DEBUG: Static Analysis command executed.")

    # --- Collect findings ---
    Severity = None
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
        print("WARN: severity labels unavailable: %s" % se_err)

    def _sev_to_string(sev):
        try:
            return severity_labels.get(sev, str(sev).lower())
        except Exception:
            return 'unknown'

    # SA findings are warnings/errors; keep info/text out of the structured
    # list but count them so a "0 findings" run is distinguishable from "ran
    # but produced only the completion banner".
    KEEP_SEVS = ('fatal', 'error', 'warning')

    def _build_entry(msg, cat_name_override=None):
        entry = {
            'category': cat_name_override or 'unknown',
            'severity': _sev_to_string(getattr(msg, 'severity', None)),
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

    messages = []
    seen_keys = set()
    total_seen = 0
    banner_seen = False

    for cat_guid, cat_name in sa_categories:
        try:
            cat_msgs = script_engine.system.get_message_objects(cat_guid)
        except Exception as read_err:
            print("WARN: get_message_objects('%s') failed: %s" % (cat_name, read_err))
            continue
        if cat_msgs is None:
            continue
        counts = {}
        for msg in cat_msgs:
            total_seen += 1
            sev_str = _sev_to_string(getattr(msg, 'severity', None))
            counts[sev_str] = counts.get(sev_str, 0) + 1
            try:
                txt = getattr(msg, 'text', '') or ''
                if 'static analysis' in str(txt).lower():
                    banner_seen = True
            except Exception:
                pass
            if sev_str not in KEEP_SEVS:
                continue
            entry = _build_entry(msg, cat_name_override=cat_name)
            key = (entry.get('category'), entry.get('text'), entry.get('object'), entry.get('line'))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            messages.append(entry)
        print("DEBUG: category '%s': %s" % (cat_name, counts))

    # --- Serialize: reuse compile_project's marker format + parser ---
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

    error_count = len([m for m in messages if m.get('severity') in ('error', 'fatal')])
    warning_count = len([m for m in messages if m.get('severity') == 'warning'])
    print("Static Analysis run for application: %s" % app_name)
    print("In project: %s" % project_name)
    print("Findings: %d (%d error/fatal, %d warning); messages scanned: %d; banner_seen=%s"
          % (len(messages), error_count, warning_count, total_seen, banner_seen))
    if total_seen == 0:
        print("NOTE: Static Analysis produced no messages at all. Likely no SA rule "
              "set is configured for this project (Project Settings -> Static "
              "Analysis Light/rules). The command ran successfully regardless.")
    print("SCRIPT_SUCCESS: Static Analysis completed.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error running Static Analysis for project %s: %s\n%s" % (
        PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

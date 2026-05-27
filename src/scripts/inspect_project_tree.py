import sys, scriptengine as script_engine, traceback

# If 'true', include declaration excerpts for POUs/GVLs/DUTs (first 200 chars).
# Default false to keep payload compact.
INCLUDE_SYMBOLS = "{INCLUDE_SYMBOLS}"

try:
    print("DEBUG: inspect_project_tree: IncludeSymbols='%s'" % INCLUDE_SYMBOLS)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    include_symbols = INCLUDE_SYMBOLS.strip().lower() in ('true', '1', 'yes', 'on')

    project_name = None
    try:
        project_name = primary_project.get_name() if hasattr(primary_project, 'get_name') else None
    except Exception:
        pass

    # Categorize each node we walk. The kind is best-effort: AB does not
    # tag children with a stable type enum exposed to scripting, so we
    # infer from probed attributes (is_application / is_folder / etc).
    def _kind_of(node):
        if getattr(node, 'is_application', False):
            return 'Application'
        if getattr(node, 'is_folder', False):
            return 'Folder'
        if getattr(node, 'is_device', False):
            return 'Device'
        name_lower = (getattr(node, 'get_name', lambda: '')() or '').lower()
        # Normalize BOTH sides (name + pattern) before matching: empirically
        # the internal node names are spaceless ('LibraryManager',
        # 'TaskConfiguration') while the AB UI displays them with spaces.
        # The previous version normalized only one side and missed every
        # match (2026-05-27 feedback: inspect_project_tree.libraries=0,
        # tasks=0 on a project that has both).
        normalized = name_lower.replace(' ', '').replace('_', '')
        if 'librarymanager' in normalized:
            return 'LibraryManager'
        if 'taskconfiguration' in normalized:
            return 'TaskConfiguration'
        # Probe textual_declaration to distinguish POU vs DUT vs GVL.
        if hasattr(node, 'is_gvl') and getattr(node, 'is_gvl', False):
            return 'GVL'
        if hasattr(node, 'is_dut') and getattr(node, 'is_dut', False):
            return 'DUT'
        if hasattr(node, 'is_pou') and getattr(node, 'is_pou', False):
            return 'POU'
        if hasattr(node, 'textual_declaration'):
            # Has decl text => POU-ish. Subdivide if we can detect TYPE...END_TYPE for DUT.
            try:
                decl = node.textual_declaration.text or ''
                if 'TYPE' in decl.upper().split('\n', 1)[0]:
                    return 'DUT'
                if decl.strip().upper().startswith('VAR_GLOBAL'):
                    return 'GVL'
                return 'POU'
            except Exception:
                return 'POU'
        return 'Other'

    devices = []
    libraries_ref = []
    pous = []
    gvls = []
    duts = []
    folders = []
    tasks = []

    def _walk(node, parent_path, depth):
        if depth > 12:
            return
        try:
            children = node.get_children(False)
        except Exception:
            return
        for child in children:
            cname = getattr(child, 'get_name', lambda: '')()
            if not cname:
                continue
            full_path = parent_path + '/' + cname if parent_path else cname
            kind = _kind_of(child)
            entry = {
                u'name': _to_unicode(cname),
                u'path': _to_unicode(full_path),
                u'kind': _to_unicode(kind),
            }

            if include_symbols and kind in ('POU', 'GVL', 'DUT'):
                try:
                    if hasattr(child, 'textual_declaration'):
                        decl_text = child.textual_declaration.text or ''
                        entry[u'declarationExcerpt'] = _to_unicode(decl_text[:200])
                except Exception:
                    pass

            if kind == 'Device':
                devices.append(entry)
            elif kind == 'LibraryManager':
                # Enumerate references underneath the LM. On AB 2.9 Standard,
                # get_children(False) on the Library Manager often returns an
                # empty iterator (the references aren't surfaced as ScriptObject
                # children but as a separate ScriptLibrary collection that
                # requires going through script_engine.librarymanager). We try
                # the children path first and let the count surface the
                # outcome; downstream callers should NOT assume 0 means "no
                # libraries referenced" -- it means "scripting enumeration
                # failed" on Standard.
                ref_count_before = len(libraries_ref)
                try:
                    for ref in child.get_children(False):
                        ref_name = getattr(ref, 'get_name', lambda: '')()
                        if not ref_name:
                            continue
                        ref_version = None
                        for vattr in ('version', 'resolved_version'):
                            if hasattr(ref, vattr):
                                try:
                                    v = getattr(ref, vattr)
                                    ref_version = v() if callable(v) else v
                                except Exception:
                                    pass
                                break
                        libraries_ref.append({
                            u'name': _to_unicode(ref_name),
                            u'version': _to_unicode(unicode(ref_version)) if ref_version else None,
                            u'path': _to_unicode(full_path + '/' + ref_name),
                        })
                except Exception as lib_err:
                    print("DEBUG: LibraryManager.get_children raised: %s" % lib_err)
                if len(libraries_ref) == ref_count_before:
                    print("DEBUG: LibraryManager '%s' yielded 0 references via get_children(False) -- this is the known Standard-edition enumeration limit." % cname)
                # Don't recurse into LM children as POUs.
                continue
            elif kind == 'TaskConfiguration':
                try:
                    for tc in child.get_children(False):
                        t_name = getattr(tc, 'get_name', lambda: '')()
                        if t_name:
                            tasks.append({
                                u'name': _to_unicode(t_name),
                                u'path': _to_unicode(full_path + '/' + t_name),
                            })
                except Exception:
                    pass
                continue
            elif kind == 'GVL':
                gvls.append(entry)
            elif kind == 'DUT':
                duts.append(entry)
            elif kind == 'POU':
                pous.append(entry)
            elif kind == 'Folder':
                folders.append(entry)

            # Recurse into ANY node (devices have children, folders too).
            _walk(child, full_path, depth + 1)

    _walk(primary_project, '', 0)

    # Heuristic: did we see a LibraryManager node? If yes but libraries_ref
    # is empty, the enumeration is the standard-edition limit (not a real
    # "no libraries"). Annotate the response so callers know.
    saw_library_manager = any(
        'librarymanager' in (f.get(u'name', '') or '').lower().replace(' ', '').replace('_', '')
        for f in folders
    )
    # _kind_of returns 'LibraryManager' for the node but we don't store it
    # in folders/devices/pous etc; flag via a separate boolean and a hint.
    counts_hint = {}
    if len(libraries_ref) == 0:
        counts_hint[u'libraries'] = u'enumeration_unavailable_on_this_build_or_no_library_manager_present'

    emit_result({
        u'projectName': _to_unicode(project_name) if project_name else None,
        u'devices': devices,
        u'libraries': libraries_ref,
        u'pous': pous,
        u'gvls': gvls,
        u'duts': duts,
        u'folders': folders,
        u'tasks': tasks,
        u'counts': {
            u'devices': len(devices),
            u'libraries': len(libraries_ref),
            u'pous': len(pous),
            u'gvls': len(gvls),
            u'duts': len(duts),
            u'folders': len(folders),
            u'tasks': len(tasks),
        },
        u'countsHint': counts_hint if counts_hint else None,
    })
    print("SCRIPT_SUCCESS: Project tree inspected.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error inspecting project tree: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

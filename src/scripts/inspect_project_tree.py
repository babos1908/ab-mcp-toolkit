import sys, scriptengine as script_engine, traceback

# If 'true', include declaration excerpts for POUs/GVLs/DUTs (first 200 chars).
# Default false to keep payload compact.
INCLUDE_SYMBOLS = "{INCLUDE_SYMBOLS}"
# Optional path of ONE node whose direct children should be listed (with the
# raw object type of each). Full path or an unambiguous tail ('App/Visu').
# Through opt_placeholder: an older server leaves the literal "{CHILDREN_OF}".
CHILDREN_OF = "{CHILDREN_OF}"

# Object-type GUIDs (ScriptObject.type) seen live on AB 2.9 SP19 (2026-10-17)
# plus the well-known CODESYS ones. Only used to NAME a node's type; a node
# whose GUID is not listed is still reported, with the raw GUID.
_TYPE_NAMES = {
    '6f9dac99-8de1-4efc-8465-68ac443b7d08': 'POU',
    'ffbfa93a-b94d-45fc-a329-229860183b1d': 'GVL',
    '2db5746d-d284-4425-9f7f-2663a34b0ebc': 'DUT',
    'f8a58466-d7f6-439f-bbb8-d4600e41d099': 'Method',
    '8ac092e5-3128-4e26-9e7e-11016c6684f2': 'Action',
    '5a3b8626-d3e9-4f37-98b5-66420063d91e': 'Property',
    '792f2eb6-721e-4e64-ba20-bc98351056db': 'PropertyAccessor',
    '6654496c-404d-479a-aad2-8551054e5f1e': 'Interface',
    '738bea1e-99bb-4f04-90bb-a7a567e74e3a': 'Folder',
    '225bfe47-7336-4dbc-9419-4105a7c831fa': 'Device',
    '40b404f9-e5dc-42c6-907f-c89f4a517386': 'PlcLogic',
    '639b491f-5557-464c-af91-1471bac9f549': 'Application',
    'ae1de277-a207-4a28-9efb-456c06bd52f3': 'TaskConfiguration',
    '98a2708a-9b18-4f31-82ed-a1465b24fa2d': 'Task',
    '413e2a7d-adb1-4d2c-be29-6ae6e4fab820': 'TaskPouCall',
    'adb5cb65-8e1d-4a00-b70a-375ea27582f3': 'LibraryManager',
    '8753fe6f-4a22-4320-8103-e553c4fc8e04': 'ProjectSettings',
    '085afe48-c5d8-4ea5-ab0d-b35701fa6009': 'ProjectInformation',
    'a95bbd79-008c-49e5-9e3c-6090b53a773b': 'CheckConfiguration',
    'bb0b9044-714e-4614-ad3e-33cbdf34d16b': 'ImagePool',
    'f18bec89-9fef-401d-9953-2f11739a6808': 'Visualization',
    '4d3fdb8f-ab50-4c35-9d3a-d4bb9bb9a628': 'VisualizationManager',
    '2bef0454-1bd3-412a-ac2c-af0f31dbc40f': 'TextList',
    '63784cbb-9ba0-45e6-9d69-babf3f040511': 'GlobalTextList',
    '9001d745-b9c5-4d77-90b7-b29c3f77a23b': 'ExternalFile',
}

# Marker properties the scripting API adds to typed objects (stubs).
_MARKER_KINDS = (
    ('is_imagepool', 'ImagePool'),
    ('is_textlist', 'TextList'),
    ('is_task', 'Task'),
    ('is_project_info', 'ProjectInformation'),
    ('is_recipemanager', 'RecipeManager'),
    ('is_recipedefinition', 'RecipeDefinition'),
    ('is_symbol_config', 'SymbolConfiguration'),
    ('is_external_file_object', 'ExternalFile'),
)


def _raw_type(node):
    try:
        t = node.type
        return _to_unicode(t).strip('{}').lower() if t is not None else None
    except Exception:
        return None


def _type_name(node):
    """(typeGuid, typeName) -- marker first, then the GUID table."""
    tg = _raw_type(node)
    for attr, label in _MARKER_KINDS:
        try:
            if getattr(node, attr, False):
                return tg, label
        except Exception:
            pass
    return tg, _TYPE_NAMES.get(tg)


try:
    print("DEBUG: inspect_project_tree: IncludeSymbols='%s'" % INCLUDE_SYMBOLS)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    include_symbols = INCLUDE_SYMBOLS.strip().lower() in ('true', '1', 'yes', 'on')
    children_of = _to_unicode(opt_placeholder(CHILDREN_OF, 'CHILDREN_OF')).strip().strip('/')

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
        if getattr(node, 'is_libman', False) or 'librarymanager' in normalized:
            return 'LibraryManager'
        if getattr(node, 'is_task_configuration', False) or 'taskconfiguration' in normalized:
            return 'TaskConfiguration'
        # Non-code objects (ImagePool, Visualization, TextList, Project
        # Settings, ...) by marker / type GUID BEFORE the textual heuristic:
        # 2026-10-17 an ImagePool fell through to 'Other' and was dropped from
        # the dump, so an App/Visu folder looked empty.
        tg, tname = _type_name(node)
        if tname and tname not in ('POU', 'GVL', 'DUT', 'Method', 'Action', 'Property',
                                   'PropertyAccessor', 'Interface', 'Folder', 'Device',
                                   'Application'):
            return tname
        if tname in ('GVL', 'DUT'):
            return tname
        # Probe textual_declaration to distinguish POU vs DUT vs GVL.
        if hasattr(node, 'is_gvl') and getattr(node, 'is_gvl', False):
            return 'GVL'
        if hasattr(node, 'is_dut') and getattr(node, 'is_dut', False):
            return 'DUT'
        if hasattr(node, 'is_pou') and getattr(node, 'is_pou', False):
            return 'POU'
        if hasattr(node, 'textual_declaration'):
            # Has decl text => POU-ish. Subdivide if we can detect
            # TYPE...END_TYPE for DUT or VAR_GLOBAL for GVL. Be tolerant of
            # leading comment lines: strip // single-line and /* ... */
            # block comments before testing the first keyword.
            try:
                decl = node.textual_declaration.text or ''
                # Strip leading comments line-by-line until we find code.
                stripped_lines = []
                in_block_comment = False
                for ln in decl.split('\n'):
                    stripped = ln.strip()
                    if in_block_comment:
                        if '*)' in stripped or '*/' in stripped:
                            in_block_comment = False
                        continue
                    if stripped.startswith('(*') or stripped.startswith('/*'):
                        if not (stripped.endswith('*)') or stripped.endswith('*/')):
                            in_block_comment = True
                        continue
                    if stripped.startswith('//') or stripped == '':
                        continue
                    stripped_lines.append(stripped)
                    break  # first non-comment line is enough
                first_code = stripped_lines[0].upper() if stripped_lines else decl.upper()
                if first_code.startswith('TYPE'):
                    return 'DUT'
                if first_code.startswith('VAR_GLOBAL'):
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
    others = []
    children_matches = []

    def _matches_children_of(full_path):
        if not children_of:
            return False
        p = _to_unicode(full_path).lower()
        w = children_of.lower()
        return p == w or p.endswith(u'/' + w)

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
            if _matches_children_of(full_path):
                children_matches.append((child, full_path))
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
            else:
                # Everything else is reported too, with its raw object type,
                # instead of silently vanishing (ImagePool, Visualization,
                # TextList, Project Settings, Plc Logic, ...).
                tg, tname = _type_name(child)
                entry[u'typeGuid'] = tg
                entry[u'className'] = _to_unicode(type(child).__name__)
                if tname is None:
                    entry[u'kind'] = u'Other'
                others.append(entry)

            # Recurse into ANY node (devices have children, folders too).
            _walk(child, full_path, depth + 1)

    _walk(primary_project, '', 0)

    if children_of:
        # Focused answer: the direct children of ONE node.
        if not children_matches:
            print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
            raise RuntimeError(
                "No node matches childrenOf='%s'. Folders: %s" % (
                    children_of, u', '.join(f[u'path'] for f in folders[:40]) or u'(none)'))
        if len(children_matches) > 1:
            print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
            raise RuntimeError(
                "childrenOf='%s' is ambiguous: %s. Pass a longer path." % (
                    children_of, u' | '.join(_to_unicode(p) for _, p in children_matches)))
        node, node_path = children_matches[0]
        listed = []
        try:
            kids = list(node.get_children(False))
        except Exception as kerr:
            kids = []
            print("WARN: get_children on '%s' failed: %s" % (node_path, kerr))
        for k in kids:
            try:
                kname = _to_unicode(k.get_name())
            except Exception:
                kname = u'?'
            tg, tname = _type_name(k)
            try:
                nkids = len(k.get_children(False))
            except Exception:
                nkids = None
            listed.append({
                u'name': kname,
                u'path': _to_unicode(node_path) + u'/' + kname,
                u'kind': _to_unicode(_kind_of(k)),
                u'typeName': tname,
                u'typeGuid': tg,
                u'className': _to_unicode(type(k).__name__),
                u'childCount': nkids,
            })
        ntg, ntname = _type_name(node)
        emit_result({
            u'projectName': _to_unicode(project_name) if project_name else None,
            u'childrenOf': {u'path': _to_unicode(node_path), u'kind': _to_unicode(_kind_of(node)),
                            u'typeName': ntname, u'typeGuid': ntg},
            u'children': listed,
            u'count': len(listed),
        })
        print("SCRIPT_SUCCESS: Children of '%s' listed (%d)." % (node_path, len(listed)))
        sys.exit(0)

    # Surface countsHint for any category that came up empty. The hint
    # disambiguates "genuinely none" from "enumeration failed on this build
    # / Standard edition limit / detection heuristic didn't fire". Downstream
    # callers should NOT assume 0 means "none referenced".
    counts_hint = {}
    if len(libraries_ref) == 0:
        counts_hint[u'libraries'] = u'enumeration_unavailable_on_this_build_or_no_library_manager_present'
    if len(gvls) == 0:
        # GVL detection relies on is_gvl flag OR textual_declaration starting
        # with VAR_GLOBAL after comment-stripping. If neither fires, GVLs
        # might exist but be invisible (e.g. compiled-only or behind a
        # custom node type).
        counts_hint[u'gvls'] = u'detection_heuristic_did_not_fire_or_no_gvls_present'
    if len(duts) == 0:
        counts_hint[u'duts'] = u'detection_heuristic_did_not_fire_or_no_duts_present'
    if len(tasks) == 0:
        counts_hint[u'tasks'] = u'no_task_configuration_found_typical_for_library_projects'

    emit_result({
        u'projectName': _to_unicode(project_name) if project_name else None,
        u'devices': devices,
        u'libraries': libraries_ref,
        u'pous': pous,
        u'gvls': gvls,
        u'duts': duts,
        u'folders': folders,
        u'tasks': tasks,
        u'others': others,
        u'counts': {
            u'devices': len(devices),
            u'libraries': len(libraries_ref),
            u'pous': len(pous),
            u'gvls': len(gvls),
            u'duts': len(duts),
            u'folders': len(folders),
            u'tasks': len(tasks),
            u'others': len(others),
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

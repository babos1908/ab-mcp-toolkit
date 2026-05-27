import sys, scriptengine as script_engine, re, traceback

# Root POU name from which to compute reachability (e.g. 'PLC_PRG'). When
# omitted, reachability is left blank and we report ALL POUs without
# classifying them as dead/live.
ROOT_POU = "{ROOT_POU}"

try:
    print("DEBUG: get_pou_dependency_graph: Root='%s'" % ROOT_POU)
    primary_project = ensure_project_open(PROJECT_FILE_PATH)

    # Collect every POU/FB/Method in the project with its body text. The
    # body is the textual_declaration + textual_implementation concatenated.
    pou_bodies = {}   # name -> body text (lowercased for matching)
    pou_paths = {}    # name -> full path under the project

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
            # Skip system nodes
            cname_lower = cname.lower()
            if cname_lower in ('library manager', 'project settings'):
                continue
            if 'task configuration' in cname_lower:
                continue
            # Try to grab textual_declaration + implementation
            decl = ''
            impl = ''
            if hasattr(child, 'textual_declaration'):
                try:
                    decl = child.textual_declaration.text or ''
                except Exception:
                    pass
            if hasattr(child, 'textual_implementation'):
                try:
                    impl = child.textual_implementation.text or ''
                except Exception:
                    pass
            if decl or impl:
                # Use the SHORT name as the node key (most call sites use
                # bare names, not full paths). When two POUs share a name
                # we keep the deeper one's full path for diagnostics.
                body = decl + '\n' + impl
                pou_bodies[cname] = body.lower()
                pou_paths[cname] = full_path
            _walk(child, full_path, depth + 1)

    _walk(primary_project, '', 0)

    if not pou_bodies:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise RuntimeError("No POUs found in project (project may be empty or library-only).")

    # Build edges by scanning each POU's body for word-boundary matches of
    # other POU names. This catches:
    #   fbInstance.SomeMethod()  -> edge to 'SomeMethod'
    #   fbInstance := FB_X();    -> edge to 'FB_X'
    #   y := Function_Y(...);    -> edge to 'Function_Y'
    # But it also catches false positives when a POU name collides with
    # a user variable. The trade-off is acceptable for dead-code detection;
    # the graph leans toward NOT calling something dead.
    pou_names_sorted = sorted(pou_bodies.keys(), key=len, reverse=True)
    edges = []  # list of (caller, callee)
    edge_set = set()
    for caller, body in pou_bodies.items():
        for callee in pou_names_sorted:
            if callee == caller:
                continue
            # Word-boundary match, case-insensitive (body already lowered).
            pat = r'\b' + re.escape(callee.lower()) + r'\b'
            if re.search(pat, body):
                key = (caller, callee)
                if key not in edge_set:
                    edge_set.add(key)
                    edges.append({u'from': _to_unicode(caller), u'to': _to_unicode(callee)})

    # Compute reachability from ROOT_POU if provided.
    reachable = set()
    if ROOT_POU and ROOT_POU in pou_bodies:
        # BFS
        from collections import deque
        adj = {}
        for e in edges:
            adj.setdefault(str(e[u'from']), []).append(str(e[u'to']))
        queue = deque([ROOT_POU])
        reachable.add(ROOT_POU)
        while queue:
            cur = queue.popleft()
            for nxt in adj.get(cur, []):
                if nxt not in reachable:
                    reachable.add(nxt)
                    queue.append(nxt)

    nodes = []
    for n in pou_bodies.keys():
        is_dead = None
        if ROOT_POU:
            is_dead = (n not in reachable)
        nodes.append({
            u'name': _to_unicode(n),
            u'path': _to_unicode(pou_paths.get(n, n)),
            u'isDeadCode': is_dead,
        })

    nodes.sort(key=lambda x: x[u'name'])

    summary = {
        u'totalPOUs': len(nodes),
        u'totalEdges': len(edges),
        u'rootPOU': _to_unicode(ROOT_POU) if ROOT_POU else None,
        u'reachableCount': len(reachable) if ROOT_POU else None,
        u'deadPOUs': sorted([str(n[u'name']) for n in nodes if n[u'isDeadCode']]) if ROOT_POU else None,
    }

    emit_result({
        u'nodes': nodes,
        u'edges': edges,
        u'summary': summary,
    })
    print("SCRIPT_SUCCESS: POU dependency graph built.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error building POU dependency graph: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

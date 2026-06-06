import traceback
# --- Find object by path function ---
def _recursive_find_last_segment(start_node, path_parts, target_type_name="object"):
    """Fallback resolver: when strict folder-by-folder traversal fails, try a
    recursive find of the LAST path segment from the project root (and from the
    Application node). This makes inconsistent path forms resolve uniformly
    across tools:
      - 'Folder/Leaf'                 (folder/leaf, used to FAIL everywhere)
      - 'NexoMqttLib/Function Blocks/FB_X' (full-from-root)
      - 'FB_X' / 'VerifyDiag'         (bare leaf / nested method)
    all collapse to the same object as long as the leaf name is unambiguous.
    Returns the object, or None if not found / ambiguous (ambiguity is reported
    by the caller's strict pass; here we stay quiet to avoid double-logging).
    """
    if not path_parts:
        return None
    leaf = path_parts[-1]
    # Build the list of roots to search from: the raw start node, its project,
    # and the Application node if reachable.
    roots = []
    roots.append(start_node)
    try:
        if hasattr(start_node, 'project') and not hasattr(start_node, 'active_application'):
            roots.append(start_node.project)
    except Exception:
        pass
    try:
        proj_for_app = start_node
        if hasattr(proj_for_app, 'active_application'):
            app = proj_for_app.active_application
            if not app:
                apps = proj_for_app.find("Application", True)
                if apps:
                    app = apps[0]
            if app:
                roots.append(app)
    except Exception:
        pass
    seen_ids = set()
    for root in roots:
        if root is None or id(root) in seen_ids:
            continue
        seen_ids.add(id(root))
        try:
            matches = root.find(leaf, True)
        except Exception:
            continue
        if matches:
            if len(matches) > 1:
                # Ambiguous from this root -- don't guess. The strict pass
                # already prints a clear ambiguity error for the user.
                print("DEBUG: fallback recursive find for '%s' is ambiguous (%d matches) from a root; not guessing." % (leaf, len(matches)))
                return None
            print("DEBUG: resolved '%s' via fallback recursive find (leaf-name search)." % leaf)
            return matches[0]
    return None


def find_object_by_path_robust(start_node, full_path, target_type_name="object"):
    # Handle both dot and slash separators. Normalise backslashes first.
    path_with_slashes = full_path.replace('\\', '/').strip('/')
    # Only treat '.' as a separator when no '/' separator was used at all -
    # otherwise we corrupt namespaced names like 'MyLib.MyType' that
    # legitimately contain a dot inside a single path segment.
    if '/' in path_with_slashes:
        normalized_path = path_with_slashes
    else:
        normalized_path = path_with_slashes.replace('.', '/')
    path_parts = [p for p in normalized_path.split('/') if p]
    if not path_parts:
        print("ERROR: Path is empty.")
        return None

    # Determine the actual starting node (project or application)
    project = start_node
    if not hasattr(start_node, 'active_application') and hasattr(start_node, 'project'):
         try: project = start_node.project
         except Exception as proj_ref_err:
             print("WARN: Could not get project reference from start_node: %s" % proj_ref_err)

    # Try to get the application object robustly if we think we have the project
    app = None
    if hasattr(project, 'active_application'):
        try: app = project.active_application
        except Exception: pass
        if not app:
            try:
                 apps = project.find("Application", True)
                 if apps: app = apps[0]
            except Exception: pass

    app_name_lower = ""
    if app:
        try: app_name_lower = (app.get_name() or "application").lower()
        except Exception: app_name_lower = "application"

    # Decide where to start the traversal
    current_obj = start_node
    if hasattr(project, 'active_application'):
        if app and path_parts[0].lower() == app_name_lower:
             current_obj = app
             path_parts = path_parts[1:]
             if not path_parts:
                 return current_obj
        else:
            current_obj = project

    # Traverse the remaining path parts
    parent_path_str = getattr(current_obj, 'get_name', lambda: str(current_obj))()

    for i, part_name in enumerate(path_parts):
        is_last_part = (i == len(path_parts) - 1)
        found_in_parent = None
        try:
            children_of_current = current_obj.get_children(False)
            for child in children_of_current:
                 child_name = getattr(child, 'get_name', lambda: None)()
                 if child_name == part_name:
                     found_in_parent = child
                     break

            # If not found directly AND it's the last part, try recursive find.
            if not found_in_parent and is_last_part:
                 found_recursive_list = current_obj.find(part_name, True)
                 if found_recursive_list:
                     # Refuse to silently pick the first match when ambiguous -
                     # the caller asked for a specific path.
                     if len(found_recursive_list) > 1:
                         print("ERROR: Recursive find for '%s' under '%s' is ambiguous (%d matches). Refusing to pick a winner." % (part_name, parent_path_str, len(found_recursive_list)))
                         return None
                     found_in_parent = found_recursive_list[0]

            if found_in_parent:
                current_obj = found_in_parent
                parent_path_str = getattr(current_obj, 'get_name', lambda: part_name)()
            else:
                # Strict folder-by-folder traversal failed at this segment.
                # Before giving up, try the leaf-name recursive fallback so that
                # 'Folder/Leaf' forms (which are not direct children of the root,
                # e.g. a library's 'Function Blocks/FB_X') still resolve -- the
                # same way a bare leaf name already does. Keeps tools consistent.
                fb = _recursive_find_last_segment(start_node, path_parts, target_type_name)
                if fb is not None:
                    return fb
                print("ERROR: Path part '%s' not found under '%s'." % (part_name, parent_path_str))
                return None

        except Exception as find_err:
            print("ERROR: Exception while searching for '%s' under '%s': %s" % (part_name, parent_path_str, find_err))
            traceback.print_exc()
            # Last-ditch fallback on unexpected traversal errors too.
            try:
                fb = _recursive_find_last_segment(start_node, path_parts, target_type_name)
                if fb is not None:
                    return fb
            except Exception:
                pass
            return None

    # Final verification: name on the resolved object must match the last requested part.
    final_expected_name = path_parts[-1] if path_parts else full_path.split('/')[-1]
    found_final_name = getattr(current_obj, 'get_name', lambda: None)()

    if found_final_name == final_expected_name:
        return current_obj
    else:
        print("ERROR: Traversal ended on object '%s' but expected final name was '%s'." % (found_final_name, final_expected_name))
        return None

# --- End of find object function ---

import sys, re, scriptengine as script_engine, os, traceback

PARENT_DEVICE_PATH = "{PARENT_DEVICE_PATH}"
DEVICE_NAME = "{DEVICE_NAME}"
DEVICE_TYPE_STR = "{DEVICE_TYPE}"  # numeric string (CODESYS device type id)
DEVICE_ID_STR = "{DEVICE_ID}"  # numeric string (CODESYS device id) or empty
DEVICE_VERSION = "{DEVICE_VERSION}"  # version string, may be empty

# Modes, selected via PARENT_DEVICE_PATH sentinels:
#   '<path>'              add child device under <path> (default)
#   '__root__'            add top-level device via project.add()
#   '__update__:<path>'   swap device at <path> in place (CODESYS "Update device"),
#                         children/application are preserved
#
# DeviceID resolution: vendor ids like ABB's are strings ('1020 0703') that
# don't survive the integer deviceId tool parameter. The repository scan
# matches type + numeric tail token + version and reuses the repo's own
# DeviceID handle, so the caller only needs the numeric tail (703, 1000, ...).

try:
    print("DEBUG: add_device: parent='%s' name='%s' type='%s' id='%s' ver='%s'" %
          (PARENT_DEVICE_PATH, DEVICE_NAME, DEVICE_TYPE_STR, DEVICE_ID_STR, DEVICE_VERSION))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not PARENT_DEVICE_PATH:
        raise ValueError("Parent device path empty.")

    mode = 'add_child'
    target_path = PARENT_DEVICE_PATH
    if PARENT_DEVICE_PATH == '__root__':
        mode = 'add_root'
        target_path = None
    elif PARENT_DEVICE_PATH.startswith('__update__:'):
        mode = 'update'
        target_path = PARENT_DEVICE_PATH[len('__update__:'):]
        if not target_path:
            raise ValueError("__update__: sentinel requires a device path after the colon.")

    if mode != 'update' and not DEVICE_NAME:
        raise ValueError("Device name empty.")

    try:
        device_type = int(DEVICE_TYPE_STR)
    except Exception:
        raise ValueError("deviceType must be a numeric CODESYS device type id (e.g. 33000 for S500 modules).")

    try:
        device_id = int(DEVICE_ID_STR) if DEVICE_ID_STR else None
    except Exception:
        raise ValueError("deviceId must be numeric or empty.")

    # ---- Resolve a DeviceID handle from the device repository -------------
    _DID_RE = re.compile(r"type=(\d+),\s*Id='([^']*)',\s*Version='([^']*)'")

    def _did_fields(did):
        """(type:int, id:str, version:str) from a DeviceID, via attrs or repr."""
        t = i = v = None
        for a in ('type', 'Type', 'device_type'):
            if hasattr(did, a):
                try:
                    t = int(getattr(did, a)); break
                except Exception:
                    pass
        for a in ('id', 'Id'):
            if hasattr(did, a):
                try:
                    i = unicode(getattr(did, a)); break
                except Exception:
                    pass
        for a in ('version', 'Version'):
            if hasattr(did, a):
                try:
                    v = unicode(getattr(did, a)); break
                except Exception:
                    pass
        if t is None or i is None or v is None:
            m = _DID_RE.search(unicode(did))
            if m:
                t = t if t is not None else int(m.group(1))
                i = i if i is not None else m.group(2)
                v = v if v is not None else m.group(3)
        return t, i, v

    def _id_tail_matches(id_string, wanted_int):
        """True when the last whitespace token of Id parses to wanted_int."""
        if not id_string:
            return False
        tail = id_string.split()[-1]
        try:
            return int(tail, 10) == wanted_int
        except Exception:
            return False

    did_obj = None
    did_repr = None
    candidates = []
    if device_id is not None:
        repo = getattr(script_engine, 'device_repository', None)
        if repo is None:
            raise RuntimeError("script_engine.device_repository unavailable; cannot resolve DeviceID.")
        for entry in repo.get_all_devices():
            did = getattr(entry, 'device_id', entry)
            t, i, v = _did_fields(did)
            if t != device_type:
                continue
            if not (_id_tail_matches(i, device_id) or i == DEVICE_ID_STR):
                continue
            if DEVICE_VERSION and v != DEVICE_VERSION:
                candidates.append("type=%s Id='%s' Version='%s' (version mismatch)" % (t, i, v))
                continue
            if did_obj is not None:
                raise RuntimeError(
                    "Ambiguous DeviceID match for type=%d id=%d version='%s': both '%s' and type=%s Id='%s' Version='%s'. "
                    "Pass an exact version to disambiguate." %
                    (device_type, device_id, DEVICE_VERSION, did_repr, t, i, v))
            did_obj = did
            did_repr = "type=%s Id='%s' Version='%s'" % (t, i, v)
        if did_obj is None:
            raise RuntimeError(
                "No repository device matches type=%d id=%d version='%s'. Near-misses: %s" %
                (device_type, device_id, DEVICE_VERSION,
                 '; '.join(candidates[:10]) if candidates else '(none)'))
        print("DEBUG: Resolved DeviceID: %s" % did_repr)

    # ---- Execute ----------------------------------------------------------
    attempts = []
    last_err = None
    new_device = None

    def _try(label, fn):
        global new_device, last_err
        if new_device is not None:
            return
        try:
            result = fn()
            new_device = result if result is not None else True
            attempts.append(label + " OK")
        except Exception as e:
            last_err = e
            attempts.append("%s failed: %s" % (label, e))

    if mode == 'update':
        dev_obj = find_object_by_path_robust(primary_project, target_path, "device to update")
        if dev_obj is None:
            raise ValueError("Device to update not found at path: %s" % target_path)
        if did_obj is None:
            raise ValueError("update mode requires deviceId (and ideally version).")
        if not hasattr(dev_obj, 'update'):
            public = sorted([m for m in dir(dev_obj) if not m.startswith('_')])
            raise TypeError("Device at '%s' has no update(); exposes: %s" % (target_path, ', '.join(public)))
        _try("update(deviceid=did)", lambda: dev_obj.update(deviceid=did_obj))
        _try("update(did)", lambda: dev_obj.update(did_obj))
        _try("update(name, did)", lambda: dev_obj.update(DEVICE_NAME or None, did_obj))
        if new_device is None:
            raise RuntimeError("All update() signatures failed. Tried: %s" % ' | '.join(attempts))
        result_name = getattr(dev_obj, 'get_name', lambda: target_path)()

    elif mode == 'add_root':
        if did_obj is None:
            raise ValueError("add_root mode requires deviceId.")
        if not hasattr(primary_project, 'add'):
            raise TypeError("project object has no add(); cannot create top-level device.")
        _try("project.add(name, did)", lambda: primary_project.add(DEVICE_NAME, did_obj))
        if new_device is None:
            raise RuntimeError("project.add failed. Tried: %s" % ' | '.join(attempts))
        result_name = DEVICE_NAME

    else:
        parent_obj = find_object_by_path_robust(primary_project, PARENT_DEVICE_PATH, "parent device")
        if parent_obj is None:
            raise ValueError("Parent device not found at path: %s" % PARENT_DEVICE_PATH)

        if did_obj is not None:
            if hasattr(parent_obj, 'add'):
                _try("parent.add(name, did)", lambda: parent_obj.add(DEVICE_NAME, did_obj))
            if hasattr(parent_obj, 'add_device'):
                _try("parent.add_device(name, did)", lambda: parent_obj.add_device(DEVICE_NAME, did_obj))
        # Legacy integer-id signatures (pre-DeviceID behaviour, non-ABB repos).
        if hasattr(parent_obj, 'add_device'):
            if device_id is not None and DEVICE_VERSION:
                _try("legacy add_device(name, type, id, ver)",
                     lambda: parent_obj.add_device(DEVICE_NAME, device_type, device_id, DEVICE_VERSION))
            elif device_id is not None:
                _try("legacy add_device(name, type, id)",
                     lambda: parent_obj.add_device(DEVICE_NAME, device_type, device_id))
            else:
                _try("legacy add_device(name, type)",
                     lambda: parent_obj.add_device(DEVICE_NAME, device_type))

        if new_device is None or new_device is True:
            # SP16-style None return: discover the node by name.
            try:
                for child in parent_obj.get_children(False):
                    child_name = getattr(child, 'get_name', lambda: '')()
                    if child_name == DEVICE_NAME:
                        new_device = child
                        attempts.append("verified-by-children-walk")
                        break
            except Exception as walk_err:
                attempts.append("post-create walk failed: %s" % walk_err)

        if new_device is None:
            public = sorted([m for m in dir(parent_obj) if not m.startswith('_')])
            raise RuntimeError(
                "add_device produced no node. Tried: %s. Last error: %s. Parent exposes: %s" %
                (' | '.join(attempts), last_err, ', '.join(public)))
        result_name = getattr(new_device, 'get_name', lambda: DEVICE_NAME)() if new_device is not True else DEVICE_NAME

    print("DEBUG: %s '%s' (mode=%s)" % ("Updated" if mode == 'update' else "Added", result_name, mode))

    primary_project.save()
    print("DEBUG: Project saved.")

    emit_result({
        u"mode": _to_unicode(mode),
        u"parent_path": _to_unicode(PARENT_DEVICE_PATH),
        u"device_name": _to_unicode(result_name),
        u"device_type": device_type,
        u"device_id": device_id,
        u"resolved_device_id": _to_unicode(did_repr) if did_repr else None,
        u"version": _to_unicode(DEVICE_VERSION) if DEVICE_VERSION else None,
        u"add_attempts": attempts,
    })
    print("Device %s: %s" % ("updated" if mode == 'update' else "added", result_name))
    print("SCRIPT_SUCCESS: Device %s." % ("updated" if mode == 'update' else "added"))
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error in add_device (parent='%s'): %s\n%s" % (PARENT_DEVICE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

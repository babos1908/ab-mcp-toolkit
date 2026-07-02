import sys, scriptengine as script_engine, os, traceback

DEVICE_PATH = "{DEVICE_PATH}"

try:
    print("DEBUG: inspect_device_node: device='%s'" % DEVICE_PATH)
    primary_project = require_project_open(PROJECT_FILE_PATH)
    if not DEVICE_PATH:
        print("SCRIPT_ERROR_CODE: ERR_BAD_INPUT")
        raise ValueError("Device path empty.")

    device = find_object_by_path_robust(primary_project, DEVICE_PATH, "device")
    if device is None:
        print("SCRIPT_ERROR_CODE: ERR_OBJECT_NOT_FOUND")
        raise ValueError("Device not found at path: %s" % DEVICE_PATH)

    device_name = getattr(device, 'get_name', lambda: '?')()
    device_class = type(device).__name__

    # Probe the parameter accessor. Different CODESYS versions expose the
    # parameter list differently; we try the canonical names in order.
    param_records = []
    parameter_accessors_tried = []

    def _coerce_value(v):
        if v is None:
            return None
        try:
            return _to_unicode(unicode(v) if not isinstance(v, unicode) else v)
        except Exception:
            try:
                return _to_unicode(repr(v))
            except Exception:
                return None

    # Primary accessor: device.parameter (a dict-like keyed by parameter id)
    params_obj = getattr(device, 'parameter', None)
    parameter_accessors_tried.append('parameter')
    if params_obj is not None:
        # Some CODESYS versions expose iteration via .keys() or just iter().
        param_ids = []
        try:
            param_ids = list(params_obj.keys())
        except Exception:
            try:
                param_ids = list(iter(params_obj))
            except Exception as iter_err:
                print("DEBUG: parameter accessor not iterable: %s" % iter_err)
        for pid in param_ids:
            try:
                slot = params_obj[pid]
                rec = {
                    u"id": pid if isinstance(pid, int) else _to_unicode(unicode(pid)),
                    u"value": _coerce_value(getattr(slot, 'value', None)),
                }
                # Optional metadata if exposed.
                for meta_attr in ('name', 'type', 'description', 'default_value', 'unit'):
                    if hasattr(slot, meta_attr):
                        try:
                            rec[_to_unicode(meta_attr)] = _coerce_value(getattr(slot, meta_attr))
                        except Exception:
                            pass
                param_records.append(rec)
            except Exception as slot_err:
                param_records.append({
                    u"id": pid if isinstance(pid, int) else _to_unicode(unicode(pid)),
                    u"error": _to_unicode(str(slot_err)),
                })

    # Fallback: device.parameters (some versions)
    if not param_records:
        params_obj = getattr(device, 'parameters', None)
        parameter_accessors_tried.append('parameters')
        if params_obj is not None:
            try:
                for pid in params_obj:
                    try:
                        rec = {u"id": _to_unicode(unicode(pid)), u"value": _coerce_value(params_obj[pid])}
                        param_records.append(rec)
                    except Exception as e:
                        param_records.append({u"id": _to_unicode(unicode(pid)), u"error": _to_unicode(str(e))})
            except Exception:
                pass

    # Identify children (sub-devices) - useful context for callers planning
    # add_device under this node.
    children = []
    try:
        for child in device.get_children(False):
            children.append({
                u"name": _to_unicode(getattr(child, 'get_name', lambda: '?')()),
                u"type": _to_unicode(type(child).__name__),
            })
    except Exception:
        pass

    # Identify the device's own type/id metadata if exposed.
    descriptor = {}
    for meta_attr in ('device_id', 'device_type', 'version', 'vendor', 'description'):
        if hasattr(device, meta_attr):
            try:
                descriptor[_to_unicode(meta_attr)] = _coerce_value(getattr(device, meta_attr))
            except Exception:
                pass
    # get_device_identification() is the authoritative source on builds where
    # the attribute probes above come back empty (AB 2.9 device nodes).
    if hasattr(device, 'get_device_identification'):
        try:
            ident = device.get_device_identification()
            descriptor[u"device_identification"] = _coerce_value(ident)
        except Exception as ident_err:
            descriptor[u"device_identification_error"] = _to_unicode(str(ident_err))

    # Connector / parameter-set probe. On AC500 (and most fieldbus devices)
    # the I/O channels are NOT child objects: they are parameters inside the
    # device connectors. This dump is what map_io_channel needs to address
    # a channel.
    connector_records = []
    io_probe = {}
    try:
        conns = getattr(device, 'connectors', None)
        if conns is None and hasattr(device, 'get_connectors'):
            conns = device.get_connectors()
        if conns is not None:
            conn_list = list(conns)
            io_probe[u"connector_count"] = len(conn_list)
            for ci, conn in enumerate(conn_list[:6]):
                crec = {}
                for a in ('connector_id', 'interface', 'interface_name', 'host_path'):
                    if hasattr(conn, a):
                        try:
                            crec[_to_unicode(a)] = _coerce_value(getattr(conn, a))
                        except Exception:
                            pass
                if ci == 0:
                    io_probe[u"connector_dir"] = [_to_unicode(m) for m in dir(conn) if not m.startswith('_')]
                pset = getattr(conn, 'host_parameters', None)
                if pset is None:
                    pset = getattr(conn, 'host_parameter_set', None)
                if pset is None and hasattr(conn, 'get_host_parameter_set'):
                    try:
                        pset = conn.get_host_parameter_set()
                    except Exception:
                        pset = None
                params = []
                if pset is not None:
                    try:
                        plist = list(pset)
                        if ci == 0 and plist:
                            io_probe[u"parameter_set_dir"] = [_to_unicode(m) for m in dir(pset) if not m.startswith('_')]
                            io_probe[u"first_param_dir"] = [_to_unicode(m) for m in dir(plist[0]) if not m.startswith('_')]
                        for p in plist[:90]:
                            prec = {}
                            for a in ('id', 'name', 'visible_name', 'unit', 'value', 'io_mapping', 'channel_type', 'direction'):
                                if hasattr(p, a):
                                    try:
                                        prec[_to_unicode(a)] = _coerce_value(getattr(p, a))
                                    except Exception:
                                        pass
                            # Resolve the actual bound variable out of the
                            # ScriptIoMapping handle (the repr above is opaque).
                            try:
                                iom = getattr(p, 'io_mapping', None)
                                if iom is not None:
                                    for battr in ('variable', 'mapped_variable', 'symbol'):
                                        if hasattr(iom, battr):
                                            bv = getattr(iom, battr)
                                            if bv:
                                                prec[u"mapped_variable"] = _coerce_value(bv)
                                                break
                            except Exception:
                                pass
                            params.append(prec)
                        if len(plist) > 90:
                            crec[u"params_truncated"] = len(plist)
                    except Exception as pe:
                        crec[u"param_iter_error"] = _to_unicode(str(pe))
                crec[u"parameters"] = params
                connector_records.append(crec)
    except Exception as ce:
        io_probe[u"connector_probe_error"] = _to_unicode(str(ce))

    emit_result({
        u"device_path": _to_unicode(DEVICE_PATH),
        u"device_name": _to_unicode(device_name),
        u"device_class": _to_unicode(device_class),
        u"descriptor": descriptor,
        u"parameters": param_records,
        u"parameter_count": len(param_records),
        u"children": children,
        u"connectors": connector_records,
        u"io_probe": io_probe,
        u"parameter_accessors_tried": parameter_accessors_tried,
    })
    print("Inspected: %s (%d parameters, %d children)" % (device_name, len(param_records), len(children)))
    print("SCRIPT_SUCCESS: inspect_device_node complete.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error inspecting device '%s': %s\n%s" % (DEVICE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

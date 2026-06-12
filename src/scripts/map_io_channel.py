import sys, scriptengine as script_engine, os, traceback

DEVICE_PATH = "{DEVICE_PATH}"
CHANNEL_PATH = "{CHANNEL_PATH}"  # "[ifaceSubstring:]<paramIdOrName>[/<subIndex>]" e.g. "IOBus:7000/3"
VARIABLE_NAME = "{VARIABLE_NAME}"
CLEAR_BINDING = "{CLEAR_BINDING}"  # "1" / "0" - if "1", remove the existing binding (variable_name ignored)

# I/O channels live in the device CONNECTORS (connector.host_parameters), not
# as child objects. A channel parameter (is_mappable_io) carries a
# ScriptIoMapping; bit-level mapping goes through the parameter's sub-elements
# (the parameter object is itself a collection of data elements).
#
# CHANNEL_PATH grammar:
#   "7000"        -> parameter id 7000 (byte/word channel)
#   "7000/3"      -> sub-element 3 (bit) of parameter 7000
#   "IOBus:7000"  -> restrict the search to connectors whose interface
#                    contains 'IOBus' (case-insensitive) - needed when the
#                    same param ids exist on several fieldbus connectors
#   names work too: "IOBus:Digital inputs I0 - I7/0"

try:
    print("DEBUG: map_io_channel: device='%s' channel='%s' var='%s' clear=%s" %
          (DEVICE_PATH, CHANNEL_PATH, VARIABLE_NAME, CLEAR_BINDING))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not DEVICE_PATH:
        raise ValueError("Device path empty.")
    if not CHANNEL_PATH:
        raise ValueError("Channel path empty.")

    clear_binding = (CLEAR_BINDING == "1")
    if not clear_binding and not VARIABLE_NAME:
        raise ValueError("variableName is required unless clearBinding is true.")

    device = find_object_by_path_robust(primary_project, DEVICE_PATH, "device")
    if device is None:
        raise ValueError("Device not found at path: %s" % DEVICE_PATH)

    # ---- Parse CHANNEL_PATH ------------------------------------------------
    iface_filter = None
    spec = CHANNEL_PATH
    if ':' in spec:
        iface_filter, spec = spec.split(':', 1)
        iface_filter = iface_filter.strip().lower()
    sub_index = None
    if '/' in spec:
        spec, sub_part = spec.rsplit('/', 1)
        sub_part = sub_part.strip()
        if not sub_part.isdigit():
            raise ValueError("Sub-element index must be numeric, got '%s'." % sub_part)
        sub_index = int(sub_part)
    spec = spec.strip()
    spec_is_id = spec.isdigit()

    # ---- Locate the channel parameter across connectors --------------------
    conns = getattr(device, 'connectors', None)
    if conns is None:
        raise RuntimeError("Device has no 'connectors'; cannot reach I/O channels on this node.")

    matches = []  # (connector, param, iface_name)
    seen_ifaces = []
    for conn in conns:
        iface = u''
        try:
            iface = unicode(getattr(conn, 'interface', '') or '')
        except Exception:
            pass
        seen_ifaces.append(iface)
        if iface_filter and iface_filter not in iface.lower():
            continue
        pset = getattr(conn, 'host_parameters', None)
        if pset is None:
            continue
        try:
            plist = list(pset)
        except Exception:
            continue
        for p in plist:
            try:
                if spec_is_id:
                    if int(getattr(p, 'id', -1)) != int(spec):
                        continue
                else:
                    pname = unicode(getattr(p, 'name', '') or '')
                    pvis = unicode(getattr(p, 'visible_name', '') or '')
                    if spec.lower() not in (pname.lower(), pvis.lower()):
                        continue
                matches.append((conn, p, iface))
            except Exception:
                continue

    if not matches:
        raise ValueError(
            "No parameter matching '%s' found on '%s' (interface filter: %s). "
            "Connector interfaces present: %s. Use inspect_device_node to list channels." %
            (spec, DEVICE_PATH, iface_filter or '(none)', ', '.join(seen_ifaces)))
    if len(matches) > 1:
        raise ValueError(
            "Parameter '%s' is ambiguous on '%s': found on connectors %s. "
            "Prefix the channel path with an interface substring, e.g. 'IOBus:%s'." %
            (spec, DEVICE_PATH, ', '.join(m[2] for m in matches), spec))

    conn, param, iface = matches[0]
    target = param
    target_label = u"%s (id=%s)" % (unicode(getattr(param, 'name', '?')), unicode(getattr(param, 'id', '?')))

    # ---- Optional bit-level sub-element ------------------------------------
    if sub_index is not None:
        subs = None
        sub_errors = []
        try:
            subs = list(param)
        except Exception as e:
            sub_errors.append("list(param) failed: %s" % e)
        if subs is None and hasattr(param, 'DataElement'):
            try:
                subs = list(param.DataElement)
            except Exception as e:
                sub_errors.append("list(param.DataElement) failed: %s" % e)
        if not subs:
            raise ValueError(
                "Parameter %s has no enumerable sub-elements (%s). has_sub_elements=%s" %
                (target_label, ' | '.join(sub_errors),
                 getattr(param, 'has_sub_elements', '?')))
        if sub_index >= len(subs):
            raise ValueError("Sub-element index %d out of range: %s has %d sub-elements." %
                             (sub_index, target_label, len(subs)))
        target = subs[sub_index]
        target_label = u"%s / bit %d (%s)" % (target_label, sub_index,
                                              unicode(getattr(target, 'name', '?')))

    print("DEBUG: Resolved channel: %s on connector '%s'" % (target_label, iface))

    # ---- Get the ScriptIoMapping handle ------------------------------------
    iom = getattr(target, 'io_mapping', None)
    if iom is None:
        raise RuntimeError(
            "Element %s exposes no io_mapping (is_mappable_io=%s). Element members: %s" %
            (target_label, getattr(target, 'is_mappable_io', '?'),
             ', '.join(sorted(m for m in dir(target) if not m.startswith('_')))))

    iom_dir = sorted(m for m in dir(iom) if not m.startswith('_'))
    print("DEBUG: io_mapping members: %s" % ', '.join(iom_dir))

    def _read_binding(m):
        for attr in ('variable', 'mapped_variable', 'symbol'):
            if hasattr(m, attr):
                try:
                    v = getattr(m, attr)
                    if v is not None:
                        s = unicode(v)
                        if s:
                            return s
                except Exception:
                    pass
        return None

    before_binding = _read_binding(iom)
    target_value = u"" if clear_binding else _to_unicode(VARIABLE_NAME)

    set_attempts = []
    success = False
    last_err = None

    # Attempt 1: iom.variable = name (canonical ScriptIoMapping surface)
    if not success and hasattr(iom, 'variable'):
        try:
            iom.variable = target_value
            success = True
            set_attempts.append("io_mapping.variable = name")
        except Exception as e:
            last_err = e
            set_attempts.append("io_mapping.variable= failed: %s" % e)

    # Attempt 2: iom.set_variable(name)
    if not success and hasattr(iom, 'set_variable'):
        try:
            iom.set_variable(target_value)
            success = True
            set_attempts.append("io_mapping.set_variable(name)")
        except Exception as e:
            last_err = e
            set_attempts.append("io_mapping.set_variable failed: %s" % e)

    # Attempt 3: legacy element-level surface (non-driver descriptors)
    for attr in ('set_variable',):
        if not success and hasattr(target, attr):
            try:
                getattr(target, attr)(target_value)
                success = True
                set_attempts.append("element.%s(name)" % attr)
            except Exception as e:
                last_err = e
                set_attempts.append("element.%s failed: %s" % (attr, e))

    if not success:
        raise RuntimeError(
            "Could not %s channel binding. Tried: %s. Last error: %s. "
            "io_mapping members: %s" %
            ("clear" if clear_binding else "set", ' | '.join(set_attempts),
             last_err, ', '.join(iom_dir)))

    after_binding = _read_binding(iom)

    primary_project.save()
    print("DEBUG: Project saved.")

    emit_result({
        u"device_path": _to_unicode(DEVICE_PATH),
        u"channel_path": _to_unicode(CHANNEL_PATH),
        u"channel_name": _to_unicode(target_label),
        u"connector_interface": _to_unicode(iface),
        u"variable_before": _to_unicode(before_binding) if before_binding else None,
        u"variable_after": _to_unicode(after_binding) if after_binding else None,
        u"cleared": clear_binding,
        u"set_attempts": set_attempts,
        u"io_mapping_members": [_to_unicode(m) for m in iom_dir],
    })
    if clear_binding:
        print("Cleared binding on %s :: %s (was: %s)" % (DEVICE_PATH, target_label, before_binding))
    else:
        print("Mapped %s :: %s -> %s (was: %s)" % (DEVICE_PATH, target_label, VARIABLE_NAME, before_binding))
    print("SCRIPT_SUCCESS: I/O channel binding updated.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error mapping I/O channel: %s\n%s" % (e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)

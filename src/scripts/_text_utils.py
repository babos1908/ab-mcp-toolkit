# Shared text-encoding helpers for IronPython 2.7 inside CODESYS.
# Prepended to other scripts via ScriptManager.prepareScriptWithHelpers.

def _to_unicode(s):
    """Coerce any byte/str/unicode value to unicode, defensively.

    CODESYS textual fields can return cp1252-encoded bytes (e.g. lone 0xA7
    for the section sign). IronPython 2.7's json.dumps with the default
    ensure_ascii=True invokes a defective decode path
    (py_encode_basestring_ascii calls s.decode('utf-8') even on unicode),
    so callers must serialise with ensure_ascii=False AND ensure all
    string values are unicode (not raw bytes that fail to round-trip).
    """
    if s is None:
        return u""
    if isinstance(s, unicode):
        return s
    # Non-string objects (e.g. a .NET Version proxy from project_info.version)
    # have no .decode(). Coerce them to unicode via their string repr instead
    # of crashing with "'Version' object has no attribute 'decode'". Only raw
    # byte strings (Python 2 str) take the decode path below.
    if not isinstance(s, str):
        try:
            return unicode(s)
        except Exception:
            try:
                return str(s).decode('utf-8', 'replace')
            except Exception:
                return u"?"
    try:
        return s.decode('utf-8')
    except UnicodeDecodeError:
        try:
            return s.decode('cp1252')
        except UnicodeDecodeError:
            return s.decode('latin-1', errors='replace')


def _json_default(o):
    """Default for json.dumps: coerce IronPython long ints (and other .NET-
    backed numeric proxies) to plain int, falling back to str. Without this,
    json.dumps raises 'TypeError: ... is not JSON serializable' on the 48-bit
    sentinel values that CODESYS message positions occasionally return.
    """
    try:
        return int(o)
    except Exception:
        try:
            return str(o)
        except Exception:
            return None


def emit_result(payload):
    """Write a structured result block to stdout for Node-side parsing.

    Format: a single fenced JSON block delimited by `### RESULT_JSON ###` and
    `### END_RESULT_JSON ###` markers. Keeps debug prints (everywhere else
    in the script) out of the structured channel. Encodes as utf-8 bytes so
    non-ASCII data round-trips through subprocess stdout under IronPython.
    """
    import json
    import sys
    text = json.dumps(payload, ensure_ascii=False, default=_json_default)
    if isinstance(text, unicode):
        text = text.encode('utf-8')
    sys.stdout.write("### RESULT_JSON ###\n")
    sys.stdout.write(text)
    sys.stdout.write("\n### END_RESULT_JSON ###\n")
    sys.stdout.flush()


def to_codesys_text(value):
    """Convert a Python value to a unicode object safe to assign to CODESYS
    .NET text properties (e.g. textual_declaration.text).

    Empirical 2026-05-27 (NEXO PLC): assigning a Python 2.7 `str` containing
    raw UTF-8 bytes to `obj.textual_declaration.text` causes a byte-level
    misinterpretation through the System.String binding. Control-range bytes
    (0x00-0x1f) end up persisted as NUL in the project file; the CODESYS
    tokenizer then exits the comment scanner early on the first NUL, and
    any struct fields declared AFTER the affected comment are silently
    skipped during compilation. Symptom: compile_project reports
    "'fieldname' is no component of 'StructName'" even though search_code
    shows the field IS in the source text.

    Pipeline that produces the bug:
        Node writes a .py file as UTF-8 bytes.
        IronPython reads the file with open(path, 'r') -> str (bytes).
        exec(script_code) is run on a Python str argument; PEP 263 does
        NOT apply to bytes passed to exec (only to file imports), so the
        string literal `"\xe2\x94\x80"` (3 UTF-8 bytes for U+2500) stays
        as raw bytes in the Python value -- not decoded.
        Assignment to .NET System.String (UTF-16) misinterprets the bytes.

    Fix: explicitly decode the bytes as UTF-8 here, so what reaches the
    .NET String binding is a true unicode object with the right code points.
    Falls back to 'replace' error handler if the input contains bytes that
    aren't valid UTF-8, so a malformed input never crashes the entire tool.
    """
    if value is None:
        return u''
    if isinstance(value, unicode):
        return value
    # Bytes path: try UTF-8 decode (the encoding the Node side wrote with).
    # On failure, replace invalid sequences with the Unicode replacement
    # char rather than raising; the alternative is to crash the whole
    # script over a stray byte that was never going to be valid anyway.
    try:
        return value.decode('utf-8')
    except UnicodeDecodeError:
        return value.decode('utf-8', 'replace')


def opt_placeholder(value, name=None):
    """Normalise a template placeholder the TS layer did not substitute.

    ScriptManager.interpolate only replaces {KEY} for keys the tool handler
    actually passed; an unknown placeholder is left VERBATIM in the generated
    source. The scripts in src/scripts are template-side (re-read from disk on
    every call) while the tool handlers live in the server process, so after a
    build the new script can run against the old handler until Claude Code is
    restarted -- any placeholder added in that window arrives as the literal
    string "{NAME}".

    That literal is non-empty, so a naive "is it empty?" check reads it as a
    REAL value. It bit for real on 2026-10-12: a new WATCHDOG_ENABLED
    placeholder reached set_task_parameter as "{WATCHDOG_ENABLED}", was parsed
    as an explicit false, and DISABLED a task watchdog that the caller had
    asked to arm -- failing toward the unsafe side, silently.

    Returns '' (= not provided, fall back to prior behaviour) for an
    unsubstituted placeholder, and warns so the version skew is visible
    instead of looking like a deliberate value. Otherwise returns the value
    unchanged.
    """
    try:
        txt = value if isinstance(value, (str, unicode)) else unicode(value)
    except Exception:
        return value
    stripped = txt.strip()
    if (len(stripped) > 2 and stripped.startswith('{') and stripped.endswith('}')
            and ' ' not in stripped):
        inner = stripped[1:-1]
        if inner and inner.replace('_', '').replace(':', '').isalnum() and inner.upper() == inner:
            print("WARN: placeholder %s was not substituted by the tool handler "
                  "-- treating it as 'not provided'. This means the running MCP "
                  "server is older than this script (restart Claude Code to pick "
                  "up the new tool parameters)." % (name or stripped))
            return ''
    return value


def safe_online_login(online_app, change_option=None):
    """Call online_app.login(...) with the right signature for the current
    CODESYS build.

    Empirical 2026-05-27 (NEXO PLC): on AB 2.9 SP19 the .NET binding rejects
    the no-arg call with
        TypeError: login() takes exactly 2 arguments (0 given)
    because the bound method signature is ILoginManager.Login(bool bForceLogin)
    plus the implicit self -- so the IronPython-side arity required is 1
    positional bool. Older CODESYS builds accepted login() with 0 args.

    Strategy: try the change_option variant first when given (TryOnlineChange
    etc.), then try the 1-arg bool form, then the no-arg form. The first
    invocation that doesn't raise a TypeError-about-arity wins. Genuine
    runtime errors (auth refused, project mismatch, ...) propagate normally
    because they are not TypeError.

    Returns the value login() returned (usually None). Raises the last
    TypeError if every variant rejected the args, or whatever genuine
    exception the first variant that accepted the args produced.
    """
    if not hasattr(online_app, 'login'):
        raise TypeError("Online application does not support login().")

    attempts = []
    if change_option is not None:
        attempts.append(((change_option,), 'change_option'))
    # SP19 expects login(bForceLogin: bool). False = do not force when
    # online change is possible; this matches the UI default behavior.
    attempts.append(((False,), 'force=False'))
    attempts.append(((True,), 'force=True'))
    # Legacy no-arg call (older builds).
    attempts.append(((), 'no-args'))

    last_arity_err = None
    for args, label in attempts:
        try:
            result = online_app.login(*args)
            print("DEBUG: safe_online_login: %s succeeded" % label)
            return result
        except TypeError as te:
            # Check if the TypeError is about arity (signature mismatch),
            # not about something else (e.g. wrong type of change_option).
            # The IronPython error text is stable: "takes exactly N arguments
            # (M given)" / "takes N positional arguments but M were given".
            msg = str(te)
            if 'argument' in msg.lower() and 'given' in msg.lower():
                last_arity_err = te
                continue
            # Different TypeError -- bubble up.
            raise
    raise RuntimeError(
        "safe_online_login: all signature variants rejected. Last arity error: %s" %
        last_arity_err
    )


# ===========================================================================
# Shared project helpers.
#
# These live in _text_utils on purpose: every tool handler already prepends
# _text_utils, and scripts are re-read from disk on every call while the
# handlers' helper lists live in the running server. A NEW helper file would
# only be included after the server restarts, so a script depending on it
# would NameError in every Claude Code session still running the old server.
# Code here reaches all of them on the next call (same version-skew window
# as opt_placeholder above).
# ===========================================================================

# --- Read-only (Released) projects -----------------------------------------
#
# Live-verified 2026-10-17 (AB 2.9 SP19): a project whose Project Information
# says released=True opens READ-ONLY and save() raises
#   StandardError: The project could not be saved.
#   (Reason: This project has been opened in read-only mode and cannot be
#   saved to this file location. ...)
# even when nothing changed. projects.open(..., allow_readonly=True/False)
# makes no difference. Setting info.released = False in the SAME session
# makes save() work again (no reopen needed).

_READ_ONLY_MARKERS = ('opened in read-only mode', 'read-only mode', 'read only mode')


def is_read_only_error(err):
    """True when an exception is AB's 'opened in read-only mode' save error."""
    try:
        msg = unicode(err).lower()
    except Exception:
        try:
            msg = str(err).lower()
        except Exception:
            return False
    for m in _READ_ONLY_MARKERS:
        if m in msg:
            return True
    return False


def project_is_released(project):
    """True/False from the Project Information 'released' flag; None when the
    project has no readable Project Information."""
    try:
        info = project.get_project_info()
        return bool(info.released)
    except Exception:
        return None


def save_project_checked(project, what='the change'):
    """project.save(), turning the read-only failure into
    ERR_PROJECT_READ_ONLY with a message that says what to do. Any other
    save error propagates unchanged."""
    try:
        project.save()
    except Exception as e:
        if not is_read_only_error(e):
            raise
        print("SCRIPT_ERROR_CODE: ERR_PROJECT_READ_ONLY")
        if project_is_released(project):
            why = "its Project Information is marked Released"
            fix = ("call set_project_info(released=false) first (and bump the "
                   "version: a released version should not change), then retry")
        else:
            why = "AB opened it read-only"
            fix = "check the file is writable and not opened read-only elsewhere"
        raise RuntimeError(
            "Cannot save %s: the project is open READ-ONLY (%s). Nothing was "
            "written to disk. To modify it, %s." % (what, why, fix))


# --- Library Manager references --------------------------------------------
#
# Field facts (AB 2.9 SP19, AC500 V3 consumer, live 2026-10-17):
#  * An application project has TWO Library Managers: Application/Library
#    Manager (the user's references) and a project-root 'Library Manager'
#    (POU pool: the Visu system placeholders). project.find('Library
#    Manager', True) returns both; the old lookups took only [0].
#  * The references are NOT child objects (get_children() is empty), but
#    lm.references is iterable and lm.references[name] works. Each item has
#    name ('#Placeholder' or 'Name, 1.0.0 (Vendor)' -- the same strings
#    get_libraries(False) returns), is_placeholder, is_managed,
#    system_library, placeholder_name, effective/default_resolution.
#  * '#' only means PLACEHOLDER, not system: '#LogiQ', '#MProtocol', '#Util'
#    are ordinary user placeholders (system_library=False); the IoDrv*,
#    Standard, IoStandard, '#System_Visu*' ones are system_library=True.
#  * lm.remove_library() takes the display name WITH the '#'
#    ('#AC500-V3-utilities-rtc'); the bare name raises KeyError.
#  * ref.parameters is a sequence of parameter NAMES; params[name] returns
#    the IEC expression string and params[name] = 'expr' writes it.

def _lm_node_path(node):
    parts = []
    cur = node
    for _ in range(16):
        try:
            parts.append(_to_unicode(cur.get_name()))
        except Exception:
            break
        try:
            cur = cur.parent
        except Exception:
            break
        if cur is None:
            break
    parts.reverse()
    return u'/'.join(parts)


def library_managers(project):
    """Every Library Manager of the project as (lm, path), application-level
    (deeper) first."""
    found = []
    try:
        for n in project.find('Library Manager', True) or []:
            found.append(n)
    except Exception as e:
        print("DEBUG: find('Library Manager') raised: %s" % e)
    if not found:
        try:
            for c in project.get_children(True):
                if getattr(c, 'is_libman', False):
                    found.append(c)
        except Exception:
            pass
    out = []
    for n in found:
        if hasattr(n, 'get_libraries') or hasattr(n, 'references'):
            out.append((n, _lm_node_path(n)))
    out.sort(key=lambda t: -t[1].count(u'/'))
    return out


def split_library_display(display):
    """'Name, 1.0.0 (Vendor)' -> (Name, 1.0.0, Vendor); '#Name' -> (Name, None, None)."""
    d = display[1:] if display.startswith(u'#') else display
    if u',' in d:
        base, rest = d.split(u',', 1)
        rest = rest.strip()
        ver, comp = rest, None
        if rest.endswith(u')') and u'(' in rest:
            v, c = rest.rsplit(u'(', 1)
            ver, comp = v.strip(), c[:-1].strip()
        return base.strip(), ver or None, comp or None
    return d.strip(), None, None


def _ref_attr(obj, name):
    try:
        return getattr(obj, name)
    except Exception:
        return None


def library_reference_entries(project):
    """Describe every library reference of every Library Manager. Each entry
    is a dict; keys starting with '_' hold the live objects (strip them with
    library_entry_public before emitting)."""
    entries = []
    for lm, lm_path in library_managers(project):
        refs = None
        if hasattr(lm, 'references'):
            try:
                refs = list(lm.references)
            except Exception as e:
                print("DEBUG: %s: references not iterable (%s); using get_libraries()" % (lm_path, e))
                refs = None
        if refs is not None:
            for r in refs:
                display = _to_unicode(_ref_attr(r, 'name'))
                if not display:
                    continue
                is_ph = bool(_ref_attr(r, 'is_placeholder'))
                sysflag = _ref_attr(r, 'system_library')
                resolution = None
                if is_ph:
                    resolution = _ref_attr(r, 'effective_resolution') or _ref_attr(r, 'default_resolution')
                resolution = _to_unicode(resolution) if resolution else None
                if resolution in (u'None', u''):
                    resolution = None
                ph_name = _ref_attr(r, 'placeholder_name') if is_ph else None
                base, ver, comp = split_library_display(display)
                rbase = split_library_display(resolution)[0] if resolution else None
                if is_ph and resolution:
                    ver, comp = split_library_display(resolution)[1:]
                entries.append({
                    'display': display,
                    'name': display[1:] if display.startswith(u'#') else display,
                    'base': base,
                    'version': ver,
                    'company': comp,
                    'isPlaceholder': is_ph,
                    'isManaged': bool(_ref_attr(r, 'is_managed')),
                    'isSystem': (bool(sysflag) if sysflag is not None else None),
                    'placeholderName': _to_unicode(ph_name) if ph_name else None,
                    'resolution': resolution,
                    'resolutionBase': rbase,
                    'namespace': _to_unicode(_ref_attr(r, 'namespace')) or None,
                    'manager': lm_path,
                    '_lm': lm,
                    '_ref': r,
                })
        else:
            try:
                names = [_to_unicode(x) for x in lm.get_libraries(False)]
            except Exception as e:
                print("WARN: %s: get_libraries() failed: %s" % (lm_path, e))
                names = []
            for display in names:
                base, ver, comp = split_library_display(display)
                is_ph = display.startswith(u'#')
                entries.append({
                    'display': display,
                    'name': display[1:] if is_ph else display,
                    'base': base, 'version': ver, 'company': comp,
                    'isPlaceholder': is_ph, 'isManaged': not is_ph,
                    'isSystem': None,  # not knowable without lm.references
                    'placeholderName': base if is_ph else None,
                    'resolution': None, 'resolutionBase': None, 'namespace': None,
                    'manager': lm_path, '_lm': lm, '_ref': None,
                })
    return entries


def library_entry_public(e):
    out = {}
    for k, v in e.items():
        if not k.startswith('_'):
            out[_to_unicode(k)] = v
    return out


def _norm_lib_query(s):
    import re as _re
    q = _to_unicode(s).strip()
    if q.startswith(u'#'):
        q = q[1:].strip()
    # list_project_libraries renders a reference as 'Name (v1.0.0) [Vendor]'.
    m = _re.match(u'^(.*?)\\s*\\(v\\d[^)]*\\)\\s*(\\[[^\\]]*\\])?\\s*$', q)
    if m:
        q = m.group(1).strip()
    return q.lower()


def resolve_library_reference(entries, wanted):
    """Find ONE reference for a user-supplied name.

    Accepted forms: the exact display string ('#Util', 'MyLib, 1.0.0 (Vendor)'),
    the name without '#', the base name ('AC500-V3-utilities-web'), the
    placeholder name, the list_project_libraries rendering ('Name (v1.0.0)
    [Vendor]'), the name a placeholder resolves to ('MProtocol-library'), or
    an unambiguous substring. Tiers are tried in that order; a tier with more
    than one hit is an error (never pick a winner).

    Returns (entry, None) or (None, error_text).
    """
    full = _to_unicode(wanted).strip().lower()
    q = _norm_lib_query(wanted)
    if not q:
        return None, "Empty library name."

    def lw(v):
        return (v or u'').lower()

    tiers = (
        ('exact name', lambda e: lw(e['display']) == full or lw(e['name']) == q
            or lw(e['base']) == q or lw(e['placeholderName']) == q),
        ('resolved library', lambda e: lw(e['resolutionBase']) == q or lw(e['resolution']) == full),
        ('substring', lambda e: q in lw(e['display']) or q in lw(e['resolution'])),
    )
    for label, pred in tiers:
        hits = [e for e in entries if pred(e)]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, ("Ambiguous library name '%s' (%s match): %s. Pass the exact "
                          "display string." % (wanted, label, u' | '.join(
                              u'%s [%s]' % (e['display'], e['manager']) for e in hits)))
    return None, ("No library reference matches '%s'. References: %s" % (
        wanted, u', '.join(e['display'] for e in entries) if entries else u'(none)'))


def library_parameter_names(ref):
    """Names of the parameters the scripting API LISTS for a reference, or
    None when the reference has no parameter accessor. NOTE: on AB 2.9 a
    managed reference ('Name, 1.0.0 (Vendor)') can list nothing even though
    params[name] = expr works for its parameters -- see set_library_parameter."""
    if ref is None:
        return None
    try:
        params = ref.parameters
    except Exception:
        return None
    if params is None:
        return None
    try:
        return [_to_unicode(n) for n in params]
    except Exception:
        return None


def library_parameter_value(ref, name):
    """Current IEC expression of a library parameter, or None if unreadable."""
    try:
        v = ref.parameters[name]
    except Exception:
        return None
    return _to_unicode(v) if v is not None else None


def library_parameter_overrides(ref):
    """{NAME: expression} of the EFFECTIVE consumer-side overrides.

    Live 2026-10-17: ref.parameters lists ONLY the parameters that already
    carry an override in this project (stored upper-case), not every
    parameter of the library -- that is why AC500-V3-utilities-web 1.0.0
    looked parameterless. Writing params[name] = expr creates or changes an
    override (any name is accepted, even a non-existent one).

    Writing '' does NOT remove the name: it stays in the listing and reading
    it raises KeyError (live probe_reset). It does neutralise the override --
    after save and reopen the downloadable size returned exactly to the
    no-override baseline -- so a listed name whose value is unreadable or
    empty is a tombstone, not an override. It is left out here, which is the
    single place get/export/set/reset learn what is overridden: counting
    tombstones made reset report a false ERR_RESET_DID_NOT_STICK and would
    have shown isOverridden=true / exported a dead value."""
    out = {}
    names = library_parameter_names(ref)
    for n in names or []:
        v = library_parameter_value(ref, n)
        if v is None or not v.strip():
            continue
        out[n] = v
    return out


def _strip_iec_comments(text):
    import re as _re
    text = _re.sub(r'\(\*.*?\*\)', ' ', text, flags=_re.S)
    text = _re.sub(r'/\*.*?\*/', ' ', text, flags=_re.S)
    return text


def parse_constant_declarations(decl_text):
    """Parse 'name : TYPE := value; // comment' lines inside VAR_GLOBAL
    CONSTANT ... END_VAR blocks. Returns a list of dicts (name, type,
    defaultValue, comment). One declaration per line, which is how parameter
    lists are written; anything fancier is skipped, not guessed."""
    import re as _re
    out = []
    if not decl_text:
        return out
    in_block = False
    rx = _re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^:;]+?)\s*(?::=\s*(.*?))?\s*;\s*(?://\s*(.*))?$')
    for raw in _to_unicode(decl_text).split(u'\n'):
        line = raw.strip()
        up = line.upper()
        if not in_block:
            if up.startswith(u'VAR_GLOBAL') and u'CONSTANT' in up:
                in_block = True
            continue
        if up.startswith(u'END_VAR'):
            in_block = False
            continue
        m = rx.match(_strip_iec_comments(line) if u'(*' in line or u'/*' in line else line)
        if m:
            out.append({
                'name': m.group(1),
                'type': m.group(2).strip(),
                'defaultValue': (m.group(3) or u'').strip() or None,
                'comment': (m.group(4) or u'').strip() or None,
            })
    return out


def library_parameter_declarations(entry):
    """Best-effort list of the constants a referenced library declares in its
    VAR_GLOBAL CONSTANT lists (where library parameters live), with their
    default values, read from the library SOURCE through the public API:
    the managed library's file (librarymanager.get_file_path) is opened as a
    secondary, non-primary project, read, and closed again (0.1-0.3 s,
    live 2026-10-17; the primary project is not touched).

    Returns (decls, source, note). decls is None when the declarations are
    not readable -- typically a .compiled-library (no source text), or a
    placeholder that does not resolve."""
    import os as _os
    import scriptengine as _se
    ref = entry.get('_ref')
    lmgr = None
    for attr in ('librarymanager', 'library_manager'):
        if lmgr is None and hasattr(_se, attr):
            try:
                lmgr = getattr(_se, attr)
            except Exception:
                lmgr = None
    if lmgr is None or ref is None:
        return None, None, "library manager / reference object not available on this build"
    ml = None
    try:
        if entry.get('isManaged'):
            ml = ref.managed_library
        elif entry.get('resolution'):
            found = lmgr.find_library(entry['resolution'])
            ml = found[0] if found else None
    except Exception as e:
        return None, None, "could not resolve the library: %s" % e
    if ml is None:
        return None, None, "the reference does not resolve to an installed library"
    try:
        path = _to_unicode(lmgr.get_file_path(ml))
    except Exception as e:
        return None, None, "get_file_path failed: %s" % e
    if not path or not _os.path.exists(path):
        return None, path, "library file not found"
    if not path.lower().endswith(u'.library'):
        return None, path, ("compiled library (no source text): parameter names "
                            "cannot be read, so they are not validated")
    already = None
    try:
        for p in _se.projects.all:
            if _os.path.normcase(_os.path.abspath(p.path)) == _os.path.normcase(_os.path.abspath(path)):
                already = p
                break
    except Exception:
        already = None
    proj = already
    try:
        if proj is None:
            flags = _se.VersionUpdateFlags.NoUpdates | _se.VersionUpdateFlags.SilentMode
            proj = _se.projects.open(path, primary=False, update_flags=flags)
        decls = []
        for o in proj.get_children(True):
            if not hasattr(o, 'textual_declaration'):
                continue
            try:
                text = o.textual_declaration.text
            except Exception:
                continue
            if not text or u'CONSTANT' not in _to_unicode(text).upper():
                continue
            try:
                owner = _to_unicode(o.get_name())
            except Exception:
                owner = None
            for d in parse_constant_declarations(text):
                d['list'] = owner
                decls.append(d)
        return decls, path, None
    except Exception as e:
        return None, path, "could not read the library source: %s" % e
    finally:
        if already is None and proj is not None:
            try:
                proj.close()
            except Exception:
                pass


# --- Build output -------------------------------------------------------------

def is_memory_usage_line(text):
    """True for the info lines of the build's memory report (live format,
    AB 2.9 SP19): 'User program code and data: ...' and 'Total maximum
    downloadable application size: ...' (category 'Memory Usage',
    ee56da69-d42b-478e-bd3c-2b4494e512c6), plus 'Memory usage on device ...'
    and 'Memory area N contains ...' (category 'Build'). The TS side parses
    them (src/compile-report.ts)."""
    t = _to_unicode(text).strip().lower()
    return (u'user program code and data:' in t
            or u'total maximum downloadable application size:' in t
            or t.startswith(u'memory area ')
            or t.startswith(u'memory usage on device'))


_BUILD_CACHE_SUFFIXES = (u'.compileinfo', u'.bootinfo', u'.bootinfo_guids', u'.precompilecache')


def build_cache_files(project_path):
    """Names of the build-state files AB keeps next to a project:
    <stem>.<Device>.<App>.<guid>.compileinfo / .bootinfo / .bootinfo_guids and
    <stem>_<ext>.precompilecache. Live 2026-10-17: app.clean() deletes the
    .compileinfo/.bootinfo/.bootinfo_guids ones and a scripted build does NOT
    rewrite them (download / online change / boot application does)."""
    import os as _os
    d = _os.path.dirname(clean_path_text(project_path))
    stem = _os.path.splitext(_os.path.basename(clean_path_text(project_path)))[0].lower()
    out = []
    try:
        names = _os.listdir(d)
    except Exception:
        return out
    for n in names:
        nl = _to_unicode(n).lower()
        if not (nl.startswith(stem + u'.') or nl.startswith(stem + u'_')):
            continue
        for suf in _BUILD_CACHE_SUFFIXES:
            if nl.endswith(suf):
                out.append(_to_unicode(n))
                break
    return sorted(out)


def clean_path_text(p):
    return _to_unicode(p).strip().strip('"\'')


def find_name_ci(names, wanted):
    """Case-insensitive lookup (IEC identifiers are case-insensitive)."""
    w = _to_unicode(wanted).strip().lower()
    for n in names or []:
        if _to_unicode(n).lower() == w:
            return n
    return None


# ------------------------------------------------------- library repository
#
# Live AB 2.9 SP19 (probe_api, 2026-10-18), the shapes every repository tool
# relies on:
#   se.librarymanager.get_all_libraries() -> ManagedLib objects, NOT tuples.
#     The name is in .title. There is no .name and no .get_name -- probing
#     those is why list_library_repository reported every entry nameless and
#     uninstall_library_from_repository found nothing it had just installed.
#     Also .version, .company and .displayname ('Title, 1.0.0 (Company)').
#     The entry does not know its repository.
#   find_library('Title, 1.0.0 (Company)') -> (ManagedLib, LibRepository), or
#     None when not installed (no exception). 'Title, * (Company)' returns the
#     newest installed version; a bare 'Title' raises SystemError.
#   uninstall_library(repository, library) -- repository FIRST.
#   get_file_path(library) -> path of the installed .library file.
#   LibRepository: .name, .root_folder, .editable.

def repository_library_manager():
    """The global library manager (se.librarymanager), or None."""
    import scriptengine as _se
    for attr in ('librarymanager', 'library_manager'):
        try:
            cand = getattr(_se, attr, None)
        except Exception:
            cand = None
        if cand is not None:
            return cand
    return None


def repository_libraries(lib_mgr):
    """Every installed library as {title, version, company, display, _lib}.

    title/version/company come from the ManagedLib attributes, falling back
    to parsing .displayname (or str()) when an attribute is missing, so a
    build that renames one of them degrades instead of going nameless."""
    out = []
    try:
        items = list(lib_mgr.get_all_libraries())
    except Exception as e:
        print("DEBUG: get_all_libraries() failed: %s" % e)
        return out
    for item in items:
        lib = item[0] if isinstance(item, (tuple, list)) and item else item
        display = _ref_attr(lib, 'displayname')
        display = _to_unicode(display) if display else _to_unicode(lib)
        p_title, p_ver, p_comp = split_library_display(display)
        title = _ref_attr(lib, 'title')
        version = _ref_attr(lib, 'version')
        company = _ref_attr(lib, 'company')
        out.append({
            'title': _to_unicode(title) if title else p_title,
            'version': _to_unicode(version) if version is not None else p_ver,
            'company': _to_unicode(company) if company else p_comp,
            'display': display,
            '_lib': lib,
        })
    return out


def find_installed_library(lib_mgr, display):
    """(ManagedLib, LibRepository) for 'Title, version (Company)' -- or
    'Title, * (Company)' for the newest -- or None when not installed."""
    try:
        hit = lib_mgr.find_library(display)
    except Exception as e:
        print("DEBUG: find_library(%r) raised: %s" % (display, e))
        return None
    if not hit:
        return None
    try:
        lib, repo = hit[0], hit[1]
    except Exception:
        return None
    if lib is None:
        return None
    return lib, repo


def installed_versions_of(lib_mgr, title, company=None):
    """Sorted display strings of every installed version of a library title
    (case-insensitive), optionally restricted to one company. Used to turn a
    'not found' into an actionable list instead of a dead end."""
    t = _to_unicode(title).strip().lower()
    c = _to_unicode(company).strip().lower() if company else None
    hits = []
    for e in repository_libraries(lib_mgr):
        if (e['title'] or u'').lower() != t:
            continue
        if c is not None and (e['company'] or u'').lower() != c:
            continue
        hits.append(e['display'])
    return sorted(hits)

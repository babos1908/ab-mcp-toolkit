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

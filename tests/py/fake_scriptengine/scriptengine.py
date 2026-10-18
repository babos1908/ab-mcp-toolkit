# Fake `scriptengine` for running the real tool scripts under CPython 2.7
# (the closest thing to CODESYS' IronPython 2.7 that runs without AB).
#
# The shapes mirror what AB 2.9 SP19 returned in live probes on 2026-10-17
# (AC500 V3 consumer project), NOT an idealised API:
#   * library references are not child objects; lm.references iterates them
#     and lm.references[name] indexes them;
#   * ref.parameters lists only OVERRIDES (upper-case keys), accepts any name
#     on write, '' removes an override, unknown key -> KeyError;
#   * lm.remove_library() wants the '#'-prefixed display name of a placeholder;
#   * task.priority / watchdog.sensitivity are str properties (int -> TypeError);
#   * a Released project is read-only: save() raises the AB message.
# A test builds its world in a fixture file (see tests/py/run_script.py).

import os

READ_ONLY_MSG = ("The project could not be saved.\n(Reason: This project has been opened in "
                 "read-only mode and cannot be saved to this file location. You can use the "
                 "\"Save As\" command to save this project to a different path.)")


class StandardError_(Exception):
    pass


class _Enum(object):
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name

    __repr__ = __str__


class VersionUpdateFlags(object):
    NoUpdates = 1
    SilentMode = 2


class KindOfTask(object):
    Cyclic = _Enum('Cyclic')
    Freewheeling = _Enum('Freewheeling')
    Event = _Enum('Event')
    Status = _Enum('Status')
    ExternalEvent = _Enum('ExternalEvent')


class Severity(object):
    FatalError = _Enum('FatalError')
    Error = _Enum('Error')
    Warning = _Enum('Warning')
    Information = _Enum('Information')
    Text = _Enum('Text')


CALLS = []  # (what, detail) log the fixture's dump() can report


# --------------------------------------------------------------------- tree

class Node(object):
    def __init__(self, name, children=None, type_guid=None, **markers):
        self._name = name
        self._children = []
        self.parent = None
        self.type = type_guid
        for k, v in markers.items():
            setattr(self, k, v)
        for c in children or []:
            self.add(c)

    def add(self, child):
        child.parent = self
        self._children.append(child)
        return child

    def get_name(self):
        return self._name

    def get_children(self, recursive=False):
        if not recursive:
            return list(self._children)
        out = []
        for c in self._children:
            out.append(c)
            out.extend(c.get_children(True))
        return out

    def find(self, name, recursive=False):
        pool = self.get_children(recursive)
        return [c for c in pool if c.get_name() == name]


class TextBlock(object):
    def __init__(self, text):
        self.text = text


class Pou(Node):
    def __init__(self, name, decl='', type_guid='6f9dac99-8de1-4efc-8465-68ac443b7d08'):
        Node.__init__(self, name, type_guid=type_guid)
        self.textual_declaration = TextBlock(decl)


# ------------------------------------------------------------------ project

class ProjectInfo(object):
    def __init__(self, released=False):
        self.released = released
        self.version = '1.0.0'
        self.title = 'T'
        self.author = ''
        self.company = ''
        self.description = ''


class Project(Node):
    def __init__(self, path, children=None, released=False):
        Node.__init__(self, os.path.basename(path), children)
        self.path = path
        self.dirty = False
        self.primary = True
        self.info = ProjectInfo(released)
        # Live 2026-10-17: read-only is decided when a RELEASED project is
        # opened, and lifted by clearing info.released in that session;
        # setting released=True and saving in the same session still works.
        self.opened_released = released
        self.saves = 0
        self.closed = False
        self.active_application = None

    def get_name(self):
        # The real ScriptProject is a tree root without a name: walking
        # .parent up from a node stops here (live probe paths start at the
        # device, e.g. 'PLC_AC500_V3/Plc Logic/Application/Library Manager').
        raise AttributeError("ScriptProject has no get_name")

    def get_project_info(self):
        return self.info

    def save(self):
        if self.opened_released and self.info.released:
            raise StandardError_(READ_ONLY_MSG)
        self.saves += 1
        self.dirty = False
        CALLS.append(('save', self.path))

    def close(self):
        self.closed = True
        CALLS.append(('close', self.path))


class Projects(object):
    def __init__(self):
        self.primary = None
        self.all = []
        self.openable = {}  # path -> Project returned by open()
        self.open_calls = []

    def open(self, path, password=None, primary=True, update_flags=None, **kw):
        self.open_calls.append((path, primary))
        p = self.openable.get(path)
        if p is None:
            raise StandardError_("fake: open(%s) not expected" % path)
        if primary:
            self.primary = p
        if p not in self.all:
            self.all.append(p)
        return p


projects = Projects()


# ---------------------------------------------------------------- libraries

class Params(object):
    """ScriptLibraryParameters as observed: a dict of OVERRIDES.

    Writing '' leaves a TOMBSTONE, as live AB does (probe_reset 2026-10-17):
    the name stays in the listing and reading it raises KeyError, while the
    library default applies again. An earlier version of this fake popped the
    key instead, which encoded the wrong assumption and let a reset check that
    fails on real AB pass here."""

    _TOMBSTONE = object()

    def __init__(self, overrides=None):
        self._d = {}
        for k, v in (overrides or {}).items():
            self._d[k.upper()] = v

    def __iter__(self):
        return iter(list(self._d.keys()))

    def __len__(self):
        return len(self._d)

    def __getitem__(self, name):
        v = self._d[name.upper()]
        if v is Params._TOMBSTONE:
            raise KeyError(name)
        return v

    def __setitem__(self, name, expr):
        if expr is None:
            raise TypeError("Value cannot be null.")
        if expr == '' or expr == u'':
            self._d[name.upper()] = Params._TOMBSTONE
        else:
            self._d[name.upper()] = expr


def _split_display(display):
    """'Title, 1.0.0 (Company)' -> ('Title', '1.0.0', 'Company')."""
    d = display[1:] if display.startswith('#') else display
    if ',' not in d:
        return d.strip(), None, None
    base, rest = d.split(',', 1)
    rest = rest.strip()
    if rest.endswith(')') and '(' in rest:
        v, c = rest.rsplit('(', 1)
        return base.strip(), v.strip(), c[:-1].strip()
    return base.strip(), rest, None


def _vkey(v):
    out = []
    for part in (v or '').split('.'):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return out


class ManagedLib(object):
    """A repository entry as live AB 2.9 has it (probe_api 2026-10-18):
    title / version / company / displayname / default_namespace -- and NO
    name, get_name or path. Scripts that probed name/get_name found every
    entry nameless; the file is reachable only via
    librarymanager.get_file_path(lib)."""

    def __init__(self, display, path=None, default_namespace=None):
        self.displayname = display
        self.title, self.version, self.company = _split_display(display)
        self.default_namespace = default_namespace or self.title
        self._path = path

    def __str__(self):
        return self.displayname


class Ref(object):
    """A Library Manager reference. Placeholder references ('#X') have
    get_redirection/set_redirection and no managed_library; managed ones
    ('X, 1.0.0 (C)') have a READ-ONLY managed_library and no redirection
    methods -- both as on live AB (probe_api / probe_mut 2026-10-18)."""

    def __init__(self, name, placeholder=False, system=False, resolution=None,
                 overrides=None, namespace=None, managed_lib=None, redirection=None,
                 qualified_only=None):
        self.name = name
        self.is_placeholder = placeholder
        self.is_managed = not placeholder
        self.system_library = system
        self.placeholder_name = name[1:] if placeholder else None
        self.effective_resolution = resolution
        self.default_resolution = resolution
        self.namespace = namespace
        self.qualified_only = bool(qualified_only) if qualified_only is not None else (not placeholder)
        self.optional = False
        self.parameters = Params(overrides)
        self._managed_lib = managed_lib
        self._redirect = redirection
        self.is_redirected = redirection is not None

    @property
    def managed_library(self):
        if self.is_placeholder:
            raise AttributeError("'ScriptPlaceholderReference' object has no attribute 'managed_library'")
        if self._managed_lib is not None:
            return self._managed_lib
        hit = librarymanager.find_library(self.name)
        return hit[0] if hit else None

    @managed_library.setter
    def managed_library(self, value):
        raise AttributeError("can't assign to read-only property managed_library "
                             "of type 'ScriptManagedLibraryReference'")

    def get_redirection(self):
        if not self.is_placeholder:
            raise AttributeError("'ScriptManagedLibraryReference' object has no attribute 'get_redirection'")
        return self._redirect

    def set_redirection(self, target):
        """Live semantics: None clears the redirection; '' leaves an empty
        one; a target that is NOT installed is accepted silently and leaves
        the reference unresolved (effective_resolution None)."""
        if not self.is_placeholder:
            raise AttributeError("'ScriptManagedLibraryReference' object has no attribute 'set_redirection'")
        CALLS.append(('set_redirection', self.name, target))
        if target is None:
            self._redirect, self.is_redirected, self.effective_resolution = None, False, None
        elif target == '':
            self._redirect, self.is_redirected, self.effective_resolution = '', True, None
        else:
            self._redirect, self.is_redirected = target, True
            hit = librarymanager.find_library(target)
            self.effective_resolution = hit[0].displayname if hit else None


class LibMan(Node):
    def __init__(self, name='Library Manager', refs=None):
        Node.__init__(self, name, type_guid='adb5cb65-8e1d-4a00-b70a-375ea27582f3', is_libman=True)
        self._refs = list(refs or [])
        self.references = _Refs(self)

    def get_libraries(self, recursive=False):
        return [r.name for r in self._refs]

    def remove_library(self, name):
        for r in self._refs:
            if r.name == name:
                self._refs.remove(r)
                CALLS.append(('remove_library', name))
                return
        raise KeyError("library '%s' was not found." % name)

    def add_library(self, display):
        """Adds a MANAGED reference. Like AB, the new reference takes the
        library's own defaults (namespace = its default namespace, not
        qualified-only), which is why a version change by remove+add has to
        restore the project's settings."""
        hit = librarymanager.find_library(display)
        if hit is None:
            raise KeyError("library '%s' is not installed." % display)
        r = Ref(display, namespace=hit[0].default_namespace, qualified_only=False)
        self._refs.append(r)
        CALLS.append(('add_library', display))
        return r


class _Refs(object):
    def __init__(self, lm):
        self._lm = lm

    def __iter__(self):
        return iter(list(self._lm._refs))

    def __len__(self):
        return len(self._lm._refs)

    def __getitem__(self, name):
        for r in self._lm._refs:
            if r.name == name:
                return r
        raise KeyError(name)


class Repo(object):
    def __init__(self, name='System', root_folder=r'C:\ProgramData\AutomationBuilder\AB_Managed Libraries_2.9'):
        self.name = name
        self.root_folder = root_folder
        self.editable = True


class LibraryManager(object):
    """se.librarymanager, shaped on probe_api / probe_more (2026-10-18)."""

    def __init__(self):
        self.repositories = [Repo()]
        self.installed = []
        self.by_display = {}  # display -> ManagedLib
        self.file_meta = {}   # library file path -> the display it installs as

    def install_library(self, path, repo=None, overwrite=False):
        if repo is None:
            raise TypeError("Value cannot be null.\nParameter name: repo")
        self.installed.append(path)
        CALLS.append(('install_library', path))
        display = self.file_meta.get(path) or '%s, 0.0.1 (Fake)' % os.path.splitext(os.path.basename(path))[0]
        ml = ManagedLib(display, path)
        self.by_display[display] = ml
        return ml

    def get_all_libraries(self):
        """ManagedLib objects, not (lib, repo) tuples."""
        return sorted(self.by_display.values(), key=lambda m: (m.title.lower(), _vkey(m.version)))

    def find_library(self, display):
        """(ManagedLib, LibRepository) or None. 'Title, * (Company)' -> the
        newest installed version; a bare title raises SystemError."""
        if ',' not in display:
            raise SystemError('stDisplayName')
        title, version, company = _split_display(display)
        if version == '*':
            cands = [m for m in self.by_display.values() if m.title == title and m.company == company]
            if not cands:
                return None
            return (max(cands, key=lambda m: _vkey(m.version)), self.repositories[0])
        ml = self.by_display.get(display)
        return (ml, self.repositories[0]) if ml else None

    def uninstall_library(self, repo, lib):
        """Repository FIRST, as on live AB."""
        if not isinstance(repo, Repo) or not isinstance(lib, ManagedLib):
            raise TypeError("expected (LibRepository, ManagedLib), got (%s, %s)" % (
                type(repo).__name__, type(lib).__name__))
        self.by_display.pop(lib.displayname, None)
        CALLS.append(('uninstall_library', lib.displayname))

    def get_file_path(self, ml):
        return ml._path


librarymanager = LibraryManager()


# -------------------------------------------------------------------- tasks

class Watchdog(object):
    def __init__(self):
        self.enabled = True
        self._time = 't#20ms'
        self.time_unit = 'ms'
        self._sens = '1'

    def _get_time(self):
        return self._time

    def _set_time(self, v):
        if not isinstance(v, basestring):
            raise TypeError("expected str, got %s" % type(v).__name__)
        self._time = v
    time = property(_get_time, _set_time)

    def _get_sens(self):
        return self._sens

    def _set_sens(self, v):
        if not isinstance(v, basestring):
            raise TypeError("expected str, got %s" % type(v).__name__)
        self._sens = v
    sensitivity = property(_get_sens, _set_sens)


class Pous(object):
    """Live: iterating yields the program NAMES; [i] yields (name, comment)."""

    def __init__(self):
        self._items = []

    def add(self, name, comment=None):
        self._items.append((name, comment or ''))

    def __iter__(self):
        return iter([n for n, _ in self._items])

    def __len__(self):
        return len(self._items)

    def __getitem__(self, i):
        return self._items[i]


class Task(Node):
    def __init__(self, name):
        Node.__init__(self, name, type_guid='98a2708a-9b18-4f31-82ed-a1465b24fa2d', is_task=True)
        self.kind_of_task = KindOfTask.Cyclic
        self._interval = 't#10ms'
        self.interval_unit = 'ms'
        self._prio = '14'
        self.watchdog = Watchdog()
        self.pous = Pous()

    def _gi(self):
        return self._interval

    def _si(self, v):
        if not isinstance(v, basestring):
            raise TypeError("expected str, got %s" % type(v).__name__)
        self._interval = v
    interval = property(_gi, _si)

    def _gp(self):
        return self._prio

    def _sp(self, v):
        if not isinstance(v, basestring):
            raise TypeError("expected str, got %s" % type(v).__name__)
        self._prio = v
    priority = property(_gp, _sp)


class TaskConfig(Node):
    def __init__(self, tasks=None):
        Node.__init__(self, 'TaskConfiguration', tasks,
                      type_guid='ae1de277-a207-4a28-9efb-456c06bd52f3', is_task_configuration=True)

    def create_task(self, name):
        t = Task(name)
        self.add(t)
        CALLS.append(('create_task', name))
        return t


# ------------------------------------------------------------------ system

class Message(object):
    def __init__(self, severity, text, prefix='C', number=None):
        self.severity = severity
        self.text = text
        self.prefix = prefix
        self.number = number


class System(object):
    def __init__(self):
        self.categories = {}  # guid -> (description, [messages])
        self.prompt_handling = None

    def get_message_categories(self):
        return list(self.categories.keys())

    def get_message_category_description(self, guid):
        return self.categories.get(guid, (str(guid), []))[0]

    def get_message_objects(self, guid=None):
        if guid is None:
            # The no-category sweep in the compile scripts is a safety net for
            # categories that enumeration missed; modelled as empty here (if it
            # returned everything, its de-dup would double every message).
            return []
        return list(self.categories.get(guid, ('', []))[1])

    def clear_messages(self, guid):
        pass


system = System()


def Guid(s):
    return s.strip('{}').lower()

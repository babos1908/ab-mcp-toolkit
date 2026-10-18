# Changelog

## Unreleased — 2026-10-17

Nine limits hit while cleaning up MPLUS IO 1.4.0 and starting 1.5.0 (AB 2.9 SP19 Premium, AC500 V3 PM5032), each of which forced a detour through the AB GUI. Every fix was first reproduced with live probes in a separate headless AB on temporary copies of the project and a throw-away library; the findings below are what AB actually did, not what the stubs suggest.

### Fixed

- **`remove_library` could remove nothing on a real AC500 V3 project.** It refused every `#`-prefixed reference as "system", but `#` only means *placeholder*: every library added by name (`#LogiQ`, `#MProtocol`, `#AC500-V3-library-MQTT`) is one. References now come from `ScriptLibManObject.references`, which carries `system_library`; only those (IoDrv*, Standard, IoStandard, `#System_Visu*`, added by the device or a plug-in) are refused. The name may be given without `#`, as the base name, as the library a placeholder resolves to, in the `list_project_libraries` form, or as an unambiguous substring (ambiguity is an error, never a guess). `remove_library()` is called with the `#`-prefixed display name; the bare one raises `KeyError`.
- **Library parameters were unreachable** (`set_library_parameter` "not found", `get_library_parameters` → `libraries: []` for `AC500-V3-utilities-web`). Two causes: the lookup walked `lm.get_children()`, empty on AB 2.9, and only the first of the project's **two** Library Managers (Application + project-root POU pool) was searched. Beyond that, `ref.parameters` lists only the **overrides** already stored in the project, which is why the web library looked parameterless; `params[name] = expr` writes one for **any** name (a typo becomes a silent no-op override), and `''` neutralises it without removing it: the name stays listed and reading it raises `KeyError`, while the library default applies again (live: the downloadable size returned to the no-override baseline after save/reopen). Now: all Library Managers via `references`; names validated against the constants the library declares in its `.library` source (opened as a secondary project, 0.1-0.3 s, primary untouched), `ERR_LIB_PARAM_NOT_FOUND` otherwise; `get_library_parameters(libraryName=...)` returns declared parameters with defaults and `isOverridden`; `reset_library_parameter` neutralises the override and counts the unreadable leftover as reset (see *Fixed after hand-over* below); export/import round-trip the overrides with a read-back per value. For a `.compiled-library` the source is not readable: the write still works and the result says `nameValidated=false`. Live: `gc_udiPageMax := 65536` on AC500-V3-utilities-web 1.0.0 persisted across save/reopen and changed the build memory report.
- **`install_library_to_repository` could not install a Released library.** It always opened the project (switching away from the user's) and always saved it; a Released library opens read-only and `save()` fails even with nothing to save. It now installs from the file: not opened when it is not the primary project, saved only when open **and** dirty (a dirty read-only library is refused with `ERR_PROJECT_READ_ONLY`, since its edits could not be included). Live: installed a released test library with it closed, and with it open.
- **`compile_project` / `get_compile_messages` dropped the memory report.** Info-severity lines were filtered out with the rest, so "User program code and data …", "Total maximum downloadable application size …" (category "Memory Usage", `ee56da69-d42b-478e-bd3c-2b4494e512c6`) and "Memory area N contains …" (Build) were only visible in a screenshot. They are now returned as a structured `memoryUsage` (user program variables/POUs/total/%, downloadable used/max/%, areas with size / highest used address / largest gap, plus the raw lines), separate from errors and warnings, together with the "Build complete -- …" line. The decimal separator follows the Windows locale (`50,53%`).
- **`compile_project` always ran `clean()`**, which deletes `<project>.<Device>.<App>.<guid>.compileinfo` / `.bootinfo` / `.bootinfo_guids` (tracked in git in several repos, and what online change needs). Measured live: a scripted build, **even a successful one**, never rewrites them — only a download / online change / boot application does — and `clean()` does not touch `<name>.precompilecache` (a build right after it can still say "The application is up to date"). New `incremental=true` skips `clean()`; every compile reports which cache files were present, which `clean()` removed and which are still missing. The default stays the clean build (it is what older servers do; see below).
- **`cleanup_backups(keep=0)` removed nothing** ("Examined 5, removed 0, kept 5") although documented as "delete all": `keep <= 0` was read as "unbounded" like the retention setting. An explicit `keep=0` now deletes every auto-backup; only the default taken from an unbounded `--backup-retention 0` keeps everything.
- **`set_task_parameter` priority and watchdog sensitivity always failed on AC500 V3**: they are string properties and assigning an int raises `TypeError: expected str, got int`. They are written as strings now and read back (priority was previously not verified at all).
- **`inspect_project_tree` dropped every node it could not file** as POU/GVL/DUT/folder/device, so an `App/Visu` folder holding an ImagePool looked empty. Such nodes now land in `others` with their raw object type GUID and a name from the API markers (`is_imagepool`, `is_textlist`, …) or a GUID table.

### Added

- **`create_task`** — creates a task in the active application's Task Configuration (created if missing): kind, interval, priority, watchdog on/off/time/sensitivity, POU calls; every knob read back, `ERR_OBJECT_EXISTS` if it exists. A new task starts with AB's defaults (cyclic `t#10ms`, priority 14, watchdog ON `t#20ms`), so e.g. `create_task(p, 'WebTask', cycleTimeMs=20, priority=16, watchdogEnabled=false, pous=['WEB_PRG'])`. `set_task_parameter` gains `kind` and `addPous`; both tools share `set_task_parameter.py`.
- **`set_project_info(released=true|false)`**. A Released project opens READ-ONLY; `projects.open(..., allow_readonly=...)` makes no difference (live). Clearing the flag in the same session makes `save()` work again, so `released=false` is applied before the other fields and the save. A requested field that does not take now fails the call (`ERR_WRITE_DID_NOT_STICK`).
- **Read-only diagnosis**: `save_project_checked()` turns AB's "opened in read-only mode" into `ERR_PROJECT_READ_ONLY` with the fix in the message (in the scripts touched here), and `formatToolResponse` adds the same hint to any tool whose output carries that message. New error codes `ERR_PROJECT_READ_ONLY`, `ERR_OBJECT_EXISTS`.
- **`inspect_project_tree(childrenOf=<path>)`** lists one node's direct children (full path or unambiguous tail such as `App/Visu`) with kind, typeName, typeGuid, className, childCount.
- `list_project_libraries` lists every Library Manager and marks placeholders (`#X -> resolved library`) and system references.

### Compatibility with servers that are still running

The scripts are re-read from disk on every call, the tool handlers live in the running server: after `npm run build`, sessions that have not restarted run the new scripts with the old handlers. Therefore every new placeholder (`INCREMENTAL`, `RELEASED`, `CHILDREN_OF`, `CREATE_TASK`, `TASK_KIND`, `ADD_POUS`) goes through `opt_placeholder()` and falls back to the old behaviour, and the shared code (library-reference resolution, read-only handling, memory-line detection) lives in `_text_utils.py`, which every handler already prepends — a new helper file would NameError under an old handler. New tools and parameters need a Claude Code restart.

### Tests

- `tests/integration/scripts-fake-engine.test.ts` runs the real scripts (helpers + template, prepared by `ScriptManager`) under CPython 2.7 — the interpreter Automation Builder ships — against `tests/py/fake_scriptengine`, a fake whose shapes are the live AB 2.9 behaviour listed above (overrides-only parameters, `#`-display removal, string task properties, read-only Released projects). 33 cases, including the old-server/missing-placeholder paths. Skipped when no 2.7 interpreter is found (`CODESYS_MCP_PY27` overrides the lookup).
- Unit tests for the memory-report parser (verbatim live lines), the cache report, `cleanup_backups` keep semantics and the read-only hint.

### Fixed after hand-over (2026-10-18)

- **`reset_library_parameter` reported a false `ERR_RESET_DID_NOT_STICK`.** Writing `''` does not delete the name on AB 2.9: it stays listed and reading it raises `KeyError` (live probe), while the library default applies again (downloadable size back to the no-override baseline after save/reopen). The reset checked "is the name still listed?", saw the leftover and failed a reset that had worked. `library_parameter_overrides()` -- the single place get/export/set/reset learn what is overridden -- now skips listed names whose value is unreadable or empty, so the reset succeeds, `get_library_parameters` no longer shows such a parameter as `isOverridden`, and export no longer writes a dead value. The fake scriptengine popped the key on `''`, i.e. it encoded the wrong assumption and let the broken check pass; it now leaves the same tombstone AB does. Mutation-checked: with the filter removed, exactly the two new tests fail.
- `create_task`'s POU-call read-back (iterating `task.pous` yields names, indexing yields `(name, comment)`) was fixed at the end of the original session without a re-run; the suite has since been re-run on that code (90/90). Re-run live 2026-10-18 on a copy of an AC500 V3 project in a headless AB: `create_task('WebTask', cyclic 20 ms, priority 16, watchdog off, pous=['PLC_PRG'])` applied and read back every field including the POU call, and a fresh AB process read the task back from disk with `PLC_PRG` attached.

### Fixed 2026-10-18: the two known issues left open

Both designed from live probes (separate headless AB, temporary copy of an AC500 V3 project, a throw-away library) rather than guesses; the shapes are documented next to `repository_libraries()` in `_text_utils.py`.

- **`uninstall_library_from_repository` could not remove a library it had just installed.** Two defects: it matched on `lib.get_name` / `lib.name`, but a repository entry (`ManagedLib`) has neither -- its name is `.title`, with `.version`, `.company` and `.displayname`; and it called `uninstall_library(library, repository)`, while the working order is `uninstall_library(repository, library)`, which it never tried. It now matches the **exact** title (case-insensitive; `McpProbeLib` never touches `McpProbeLib2`) or a full display string, resolves each entry's repository through `find_library`, uninstalls in the verified order and reads every removal back -- a library still installed fails the call (`ERR_WRITE_DID_NOT_STICK`). Not found now lists the installed versions or similar titles.
- **`list_library_repository` listed every entry as nameless** ("381 scanned, 0 kept"): same root cause -- it probed `name` / `display_name` (with an underscore) instead of `title` / `displayname`. It now lists title, version, company and the exact display string, the repository's root folder, and each library file's path when filtered. Fixed with the uninstall because both share the new helper.
- **`set_library_reference_version` found no reference on AB 2.9** (it walked `lm.get_children()`, empty there), then tried `set_version()` / `version=`, which do not exist, and reported success even when the save failed. Rewritten on what the API actually offers: a **placeholder** reference's version is the project-level redirection (`set_redirection('Title, version (Company)')`, live: takes effect at once and persists); a **managed** reference's `managed_library` is read-only, so it is removed and re-added at the new version with namespace / `qualified_only` / `optional` restored and parameter overrides re-applied. `'*'` floats to the newest installed version for both. Probing found a trap: AB **accepts** a redirection to a version that is not installed and leaves the reference unresolved, so the target is checked with `find_library` before anything is written. Every change is read back before the save; one that does not take is rolled back in memory and not saved.
- **Live-verified** with the real scripts in a headless AB (temp copy of the project, throw-away library): the repository list shows titles, versions, display strings and file paths with 0 nameless entries out of 381; a library installed with `install_library_to_repository` was removed by `uninstall_library_from_repository` and confirmed gone; `#MProtocol` redirected 1.0.0 -> 0.1.4; a redirect to 9.9.9 refused with nothing written; `AC500-V3-utilities-ip` 1.0.2 -> 1.0.1 with its namespace and `qualified_only` restored, then -> `*` resolving to 1.0.2; a fresh AB process read both changes back from disk.
- The fake scriptengine now has the live repository and reference shapes (title-only entries, `find_library` with `*` and `None`, repository-first `uninstall_library`, read-only `managed_library`, `set_redirection` accepting a missing version), so the tests could fail for the old code -- and they do: with the previous three scripts, all 14 new tests fail.

### Fixed 2026-10-18: one IEC TIME parser instead of two

- `set_task_parameter` and `get_task_configuration` each carried a copy of the IEC TIME literal parser, kept in step by hand. Both now use `iec_time_literal_to_ms` / `time_value_to_ms` in `_text_utils` (every handler, old ones included, already prepends it). A differential run on AB's Python 2.7 over 37 inputs -- TimeSpans, numbers, unicode, compound and underscored literals, us/ns -- found the two old copies identical everywhere, and the shared version identical to them on 35.
- The other 2 are a latent bug the copies shared and the unified parser fixes: they only checked that the LAST component ended the literal, so `'t#1msGARBAGE5s'` read as 5001 ms and `'t#5x10ms'` as 10 ms. Components must now cover the literal back to back. That matters most in `set_task_parameter`'s read-back, where a misparse could "verify" a write that did not happen.
- Live (headless AB, copy of an AC500 V3 project): `get_task_configuration` read the task at 10 ms / watchdog 20 ms; `set_task_parameter` wrote 50 ms and 100 ms and read both back; a fresh AB process read them from disk. The same run disarmed the watchdog (`watchdogEnabled=false`, a real change from armed) and it read back disarmed -- the toggle verification still open from 2026-10-12.

### Fixed 2026-10-18: one server could break another server's live AB session

Reported by the MPLUS IO session: at 18:40:50 the IPC folder of its live session (AB PID 26312, healthy watcher) was deleted, and so was the one of a second AB (PID 13804). Every command then failed with `ENOENT` on `commands/<id>.py.tmp`, `diagnose_mcp_state` answered "Healthy" with "Heartbeat: never", and the 13804 watcher logged the same error about 16 times a second -- 8 MB in 40 minutes -- until its folders were recreated by hand. Which process did it could not be established: the registration has no `--log-file`, so nothing recorded it. What the code review did establish is how one server could do this to another, and both paths are closed:

- **Adoption took other agents' AB.** `adoptExisting()` without a `projectFilePath` adopted the newest live session, whoever was driving it. Each session folder now carries an `owner.json` (`{serverPid}` while a server drives it, `{serverPid: null}` once a keep-alive detach releases it). A session driven by another live MCP server is never adopted -- not even probed. Without a project, only a released or orphaned session is adopted (the keep-alive recycle case), or, for sessions started by older servers without a marker, an idle one. `launch_codesys` now says which live sessions it passed over and why; `list_ab_sessions` shows `ownedBy`.
- **Shutdown and reset deleted live folders.** `shutdown()` and `forceReset()` always removed the IPC folder at the end, even when the AB was still running or its PID was unknown. The folder is now removed only when its watcher is gone: the AB process has exited, or -- PID unknown -- its heartbeat is missing or older than 30 s.
- **Nothing healed.** The client now recreates `commands/` and `results/` before sending, so a deleted folder costs nothing; newly launched watchers recreate them too instead of failing every 50 ms, and log a repeating error once per ~1000 repeats instead of every time. `diagnose_mcp_state` reports the folder MISSING and warns not to `force_reset_watcher` for it, which would kill a healthy AB.
- `sessionBaseDir` makes the session folder configurable: the default is shared by every server on the machine, and the new tests must never touch it. 12 tests; disabling the four guards fails exactly the six that test them, while the six describing allowed behaviour (adopting released, orphaned, idle or matching sessions; deleting after the AB exited) keep passing.
- Repaired by hand on this machine: the 13804 session (its folders recreated, non-destructively). The MPLUS IO session had already repaired its own.

Running servers keep their old TypeScript code until Claude Code is restarted, and running watchers keep theirs until their AB is relaunched.

### Known issues found, not fixed here

- None left from this round.

## 0.6.2 — 2026-05-09

Bug-fix release after a multi-agent + live-test deep audit of v0.6.1.

### Fixed

- **`inspect_device_node`, `create_project_archive`, and the `pou-code` resource were broken.** All three scripts referenced `PROJECT_FILE_PATH` but only worked because their helper chain previously included `ensure_project_open.py` (which declares the placeholder). When they switched to `require_project_open` for read-only safety, the placeholder declaration disappeared with no replacement, producing `NameError: name 'PROJECT_FILE_PATH' is not defined` on every call. Caught by live test, not by the static `dev/check-scripts.ps1` checker. Fixed by mirroring `ensure_project_open`'s convention - `require_project_open.py` now also declares the placeholder at module scope.
- **`list_device_repository` returned 2045 entries with all descriptor fields null.** SP21's `ScriptDeviceRepository` is not iterable directly; the listing comes from `repo.get_all_devices()` (now probed first), which returns lightweight `DeviceID` handles - not full descriptors. Each entry now also enriches via `repo.get_device_description(deviceID)` to pull `name`, `vendor`, `category`, `description`. (Note: enrichment may still return null for some entries on SP21 - the descriptor object's exact attribute names continue to vary; the structural call is reliable.)
- **`dist/mutation-tracker.*` orphan build artefacts** (.js, .d.ts, .js.map, .d.ts.map) were left behind by 0.6.1's `tsc + cpSync` build because there was no `dist` clean step. Would have been published to npm. Build script now runs `npm run clean` first; new `clean` script wipes `dist/` before `tsc` regenerates it.
- **Test asserted cache behaviour against a removed cache.** `tests/unit/script-manager.test.ts` had a `'cache hit - second load returns same content'` test that passed by accident after the cache was deleted in 0.6.1 (Vitest's `toBe` on identical short strings can pass via Node's string interning). Renamed to `'two reads of the same template return identical content'` and switched to `toEqual` so the assertion describes the actual contract.
- **`ARCHITECTURE.md:168` claimed "reads `.py` files from disk with caching".** Stale after 0.6.1's cache removal. Fixed.

### Known issues NOT fixed in this release (documented for awareness)

- **Project-lock contention** when CODESYS isn't running persistently. Each tool call spawns a `--noUI` headless instance; concurrent tool calls and prior orphans contend for the project file lock and produce `StandardError: The selected project is currently in use` (MEMORY.md pitfall #5). Workarounds: keep persistent mode running, or pass `--kill-existing-codesys` to wipe orphans on launch.
- **`formatToolResponse(result, '')` silent-success on `parseResultJson` failure** in ~7 tools (`search_code`, `read_variable`, `monitor_variables`, `list_device_repository`, `inspect_device_node`, `add_device`, `set_device_parameter`). When the script ran (`SCRIPT_SUCCESS` in stdout) but the RESULT_JSON marker block was malformed, the caller sees an empty success response instead of an error. The diagnostic in `parsed.error` is dropped. Tracked.
- **`list_device_repository` field enrichment is partial.** Structural call works; some descriptors on SP21 don't expose name/vendor under the probed attribute names. Need a sample inspection of a real `DeviceDescription` object on the live runtime to map field names. Tracked.
- **Capability gaps** flagged by the audit (no priority order): `force_variable` / `release_force` (bench commissioning), `write_variables_batch` (recipe atomic write), array-slice `read_variable`, `set_active_application` (multi-app projects), `generate_boot_application` (already on roadmap), `configure_task` (already on roadmap), value-change-event subscription, debugger primitives.

## 0.6.1 — 2026-05-08

Simplification pass after a multi-agent over-engineering audit. ~270 lines removed. No public-API changes — all 39 tests pass.

### Cuts

- **Removed `MutationTracker`** (src/mutation-tracker.ts deleted, ~90 lines across server.ts). The per-project compile/mutation timestamping was lossy bandaid masquerading as substrate: it tracked only TS-side tool calls, missed IDE edits and watcher restarts, and the value it produced was a single warning string ("WARN: Project was modified Xs ago") that a static note in `get_compile_messages`'s description delivers identically. Tools that previously routed through `formatMutatorResponse` now go through `formatToolResponse` directly.
- **Removed the script-template cache** (src/script-manager.ts, ~30 lines). The Map of file contents solved an imaginary perf problem (~1ms savings per call vs. 100ms+ CODESYS calls); its only user-visible artifact was the `CODESYS_MCP_NO_CACHE` env var that existed because the cache broke template iteration during dev. `loadTemplate()` now reads from disk every call.
- **Deleted dead `PouTypeEnum` and `ImplementationLanguageEnum`** at server.ts:20-26 — declared but never referenced (`create_pou` redeclares inline).
- **Deduplicated `_json_default`** in `compile_project.py` and `get_compile_messages.py` — `_text_utils.py` already provides it via the helper-prepend chain.
- **Stripped narrative `DEBUG:` prints** from `find_object_by_path.py` (the most-called helper in the codebase, was emitting 5-10 lines per CRUD tool invocation) and `ensure_project_open.py` (~18 flow-trace prints + commented-out dead code blocks). All `WARN:` and `ERROR:` diagnostic prints retained.
- **Trimmed verbose tool descriptions** for `add_device`, `set_device_parameter`, `find_references`, `rename_symbol`, `monitor_variables`, `list_device_repository`, `inspect_device_node`, `map_io_channel`, `search_code`. Each was 300-700 chars and loaded into every model turn; trimmed to ~150 chars (~3-4K tokens off the tool-list payload). Detail moved to parameter `.describe()` strings.

### Not done (deliberately deferred)

- **Tool-registration `simpleTool()` helper** that would collapse ~12 mutator registrations into a 6-line declaration. ~600-line cut estimated, but introduces a generalised abstraction and the bespoke shape of `compile_project` / `read_variable` / `monitor_variables` / `search_code` / `rename_symbol` would need to remain custom anyway. Held for a future pass once the helper's shape is clearer.
- **Stripping per-script `try/except SCRIPT_ERROR; sys.exit(1)`** boilerplate. The watcher catches uncaught exceptions, but `SCRIPT_SUCCESS` is load-bearing (server.ts checks `result.output.includes('SCRIPT_SUCCESS')`); reworking is invasive enough to merit its own release.
- **Multi-version API probes** in `add_device`, `set_device_parameter`, `list_device_repository`, `create_project_archive`. Auditor flagged some as speculative; not pruned without grounding in actual user reports of CODESYS version divergence.
- **`ExecutorProxy.swapVersion`** monotonic-counter logic. Small win (~25 lines) and the race it guards is hard to test for; left in place.

## 0.6.0 — 2026-05-08

Substrate + capability release. Closes the five remaining still-open bugs from 0.5.x and ships ten new tools (search_code, find_references, rename_symbol, monitor_variables, create_project_archive, inspect_device_node, add_device, set_device_parameter, list_device_repository, map_io_channel).

### Substrate primitives (foundational, used by multiple tools)

- **`ExecutorProxy` (src/executor-proxy.ts)** — stable proxy reference replacing the `let executor` rebind. `executeScript` awaits a readiness promise then delegates; `swap()` and `swapNow()` mutate the inner without breaking captured closures. Closes B3 (background-launcher 30s race) and gives long-lived tools (monitor_variables) a clean substrate.
- **`require_project_open` helper (src/scripts/require_project_open.py)** — read-only sibling of `ensure_project_open`. Raises if the requested project isn't currently primary; never opens or switches. Used by resource handlers (B1 fix) and read-only tools (create_project_archive, inspect_device_node).
- **`### RESULT_JSON ###` marker protocol (src/scripts/_text_utils.py emit_result + src/result-parser.ts)** — standardised structured-result channel for scripts. Pairs with `parseResultJson<T>()` on the Node side. Closes B4 (read_variable multi-line truncation) and underpins every new structured-output tool.
- **`MutationTracker` (src/mutation-tracker.ts)** — per-project compile/mutation timestamps in TS memory. Mutators call `markMutated`; `compile_project` calls `markCompiled`; `get_compile_messages` prepends a "stale, run compile_project" warning when mutations followed the last compile. Closes B2.
- **`atomic_write` via .NET `File.Replace` (src/scripts/watcher.py)** — atomic NTFS rename replacing the os.remove+os.rename pair, with a retry-loop fallback for AV-locked files. Closes B5.

### New tools (capability adds)

- **`search_code`** — regex (or literal substring) search across every POU/Method/Property/DUT/GVL declaration and implementation body. Returns `{path, section, line, col, text}` hit list via RESULT_JSON. Reports skipped graphical bodies so callers know coverage.
- **`find_references`** — TS-only wrapper around `search_code` with a word-boundary regex (`\bsymbol\b`). Single source of truth for traversal — does not duplicate the script.
- **`rename_symbol`** — best-effort textual rename across all POU bodies. Two-phase write: phase 1 plans every change, phase 2 applies all-or-rollback. dryRun=true by default. Refuses IEC keywords as the new name. Project save() runs only when every section rewrites cleanly; partial failures DON'T save (caller reopens to discard in-memory state).
- **`monitor_variables`** — sample one or more PLC variables at a fixed interval over a bounded duration. Returns the timeseries via RESULT_JSON. Duration capped at 60s, interval floor 10ms. Anti-drift sample loop (`next_t = start_t + n*interval`).
- **`create_project_archive`** — wraps `primary.save_archive(path, comment, content)` with multi-version probing. Saves the project before archiving so unsaved edits are captured. Read-only with respect to project state (uses require_project_open). Includes/excludes libraries via `includeLibraries` / `includeCompiledLibraries` flags.
- **`add_device` (EXPERIMENTAL)** — wrap `parent.add_device(name, type, id, version)` with multi-version signature probing and post-hoc child enumeration for SP16's None-return path. Marked EXPERIMENTAL — `deviceType` / `deviceId` are unvalidated and wrong ids produce wrong-but-valid project nodes. Recommended workflow: add one device manually in IDE, run `inspect_device_node` to capture ids, then automate.
- **`set_device_parameter` (EXPERIMENTAL)** — wrap `device.parameter[id].value =` with fallbacks to `set_parameter_value` / `parameters[id]`. Marked EXPERIMENTAL — many fieldbus parameters are GUI-only. Pair with `inspect_device_node` to discover writable parameters.
- **`inspect_device_node`** — read-only introspection of a device node: descriptor metadata (device_id, type, version, vendor when exposed), parameter list with current values + types, and child sub-devices. Substrate for the device-tree mutation tools.
- **`list_device_repository`** — read-only enumeration of every device descriptor installed in the local CODESYS Device Repository. Probes `script_engine.device_repository` / `device_descriptions` / `devicerepository` and surfaces `{name, vendor, device_type, device_id, version, description, category}` per entry, with optional case-insensitive `vendor` and `nameContains` substring filters and a `maxResults` cap. Closes the validation gap for `add_device` (callers can now look up canonical ids instead of guessing).
- **`map_io_channel`** — bind (or clear) a fieldbus I/O channel to a global variable symbol. Resolves the channel by slash-separated name path (`Inputs/Byte 0/Bit 3`) or numeric child indices (`0/3`) for descriptors that don't expose stable channel names. Tries `channel.set_variable(name)`, then `channel.variable = name`, then `channel.symbol = name` to cover descriptor variants. `clearBinding: true` removes an existing binding (variableName ignored). RESULT_JSON returns `{channel_name, channel_class, variable_before, variable_after, cleared, resolution_attempts, set_attempts}`.

### Bug fixes leveraging substrate

- **B1: Resource handlers no longer silently switch projects.** Both `pou-code` and `project-structure` resources now use `require_project_open` instead of `ensure_project_open`.
- **B2: get_compile_messages warns when stale.** Mutators (set_pou_code, create_*, delete_object, rename_object, add_library, set_simulation_mode, etc.) call `markMutated`; `compile_project` calls `markCompiled`; `get_compile_messages` prepends a clear staleness warning when mutated > compiled.
- **B3: Launcher executor swap is race-free.** ExecutorProxy serialises tool calls behind a readiness promise around the auto-launch transition.
- **B4: read_variable returns multi-line struct values intact.** Switched from regex `/Value:\s*(.+)/` to RESULT_JSON marker block; `value`, `type`, `raw`, `application` returned structurally.
- **B5: atomic_write is atomic on Windows NTFS.** `.NET File.Replace` for existing destinations, `File.Move` for new files, retry-loop fallback for AV-locked files.

### Cut from this release

- **C5 export_project_xml** cut by the implementation-order analyst — overlaps with `create_project_archive` for backup/diff use cases. Track on roadmap.

### Tests

- 39/39 tests pass (4 new pyEscape coverage tests carried over from 0.5.1).
- Static checks (`dev/check-scripts.ps1`): all 41 scripts ASCII-clean, all template references resolve.

## 0.5.2 — 2026-05-08

Second adversarial-review pass. Tightens schemas, fixes path-resolution corruption, replaces a too-broad delete allowlist with exact-path matching, and stops `set_pou_code` from silently overwriting code with empty strings.

### Schema hardening (Zod)
- `create_pou.type` is now `z.enum(['Program', 'FunctionBlock', 'Function'])` (was `z.string()`).
- `create_pou.language` is now `z.enum(['ST', 'LD', 'FBD', 'SFC', 'IL', 'CFC'])`.
- `create_pou.name` and `parentPath` now require `min(1)`.
- `create_dut.dutType` is now `z.enum(['Structure', 'Enumeration', 'Union', 'Alias'])`.
- `create_dut.name` and `parentPath` now require `min(1)`.
- `start_stop_application.action` is now `z.enum(['start', 'stop'])` (was `z.string()`).
- `set_pou_code.pouPath` now requires `min(1)`.

### Fixed
- **`find_object_by_path_robust` no longer corrupts namespaced names.** Previously `path.replace('.', '/')` was applied unconditionally, so a path like `Application/MyLib.MyType` got split into 4 parts and the find always returned `None`. Now `.` is only treated as a separator when the input has no `/` at all.
- **`find_object_by_path_robust` recursive fallback no longer silently picks the first match.** When the project tree contains multiple objects with the same name, the helper used to return `[0]` from `find(part_name, True)` which could resolve to the wrong object. Now ambiguous matches return `None` with a clear error.
- **`find_object_by_path_robust` final-name verification uses normalised path parts.** The previous `full_path.split('/')[-1]` returned the whole input when `.` was used as a separator, causing successful traversals to be reported as name-mismatch errors.
- **`delete_object` allowlist is now an exact-path match, not a last-segment match.** Prior implementation false-positively refused legitimate user objects whose final name happened to match a system node (e.g. `Application/MyFolder/MainTask` for a user folder named `MainTask`). The new check uses an explicit set of canonical system paths.
- **`set_pou_code` no longer silently overwrites with empty string.** Empty-string values for `declarationCode` or `implementationCode` are now treated the same as omitted (don't change). Previously only `=== undefined` was checked, so an empty string from a buggy client wiped the section. New `UPDATE_DECL` / `UPDATE_IMPL` flag params explicitly mark which sections to update.
- **`ensure_project_open` final RuntimeError now includes the last underlying error.** Previously the helper raised a generic "after 3 attempts" message; now it appends the most recent `projects.open()` exception text so callers can distinguish "file locked", "file missing", "version mismatch", etc.

### Known issues (still not fixed; documented for awareness)
- Resource handler can switch projects via `ensure_project_open` (treat resource URIs as potentially state-mutating).
- Compile message store can go stale after `set_pou_code` (auto-saves but doesn't invalidate cache); call `compile_project` again to refresh.
- `read_variable` regex captures only the first line; multi-line struct values get truncated.
- Background-launcher swap mid-tool-call has a 30s race window where headless and persistent executors can both be live.
- Watcher `atomic_write` is not strictly atomic on Windows (`os.remove` + `os.rename`).

## 0.5.1 — 2026-05-08

Hardening pass after multi-agent adversarial review. Centralizes Python escaping, blocks destructive deletes, and fixes additional CODESYS scripting API mismatches.

### Security / correctness
- **Central Python string escape in `ScriptManager.interpolate()`**. Every `{KEY}` placeholder is now Python-escaped before substitution (backslashes, double/single quotes, newlines, tabs). This closes a class of injection bugs where a `"` or newline in a user-controlled identifier (POU name, variable path, library name, password) could break out of the string literal in the generated IronPython source. Use `{KEY:raw}` for the rare case where a value should bypass escaping (currently only `set_pou_code`'s declaration/implementation blocks no longer need it - the `:raw` form is provided as an escape hatch).
- **`delete_object` allowlist.** The tool now refuses to delete system nodes (`Application`, `Device`, `Plc Logic`, `Library Manager`, `Project Settings`, `Task Configuration`, `MainTask`, `Communication`, `Ethernet`, `SoftMotion General Axis Pool`, `__VisualizationStyle`) and any path with no `/` separator. Pre-fix, deleting these silently bricked the project.
- **Server.ts no longer pre-escapes `set_pou_code` content.** The redundant `\\` and `"""` escape that used to live at the call site is now handled by `interpolate()` for all params.

### Fixed
- `create_folder.py` no longer requires `create_folder()` to return a non-`None` object. SP16 returns `None` on success and the new folder must be discovered by walking the parent's children. The script now does that and only fails when post-creation enumeration also doesn't find the folder.
- Raw-string templates (`r"{KEY}"`) in `create_project.py`, `ensure_project_open.py`, `get_project_structure.py`, and `watcher.py` converted to regular strings (`"{KEY}"`). Raw strings can't survive central escaping; the regular form is now consistent across all templates.
- `launcher.ts` no longer pre-escapes `IPC_BASE_DIR` - `interpolate()` handles it.

### Tests
- 4 new unit tests in `tests/unit/script-manager.test.ts` covering pyEscape behavior: backslashes, triple quotes, single quotes, newlines, `:raw` bypass, and `$` not being a regex backref.
- E2E tests updated to expect Python-escaped paths in generated source.

### Known issues surfaced (not fixed in this release)
- **Resource URIs can silently switch projects** when the requested project differs from the currently-open one (`ensure_project_open` opens the new one, closing any unsaved work). Resources should be read-only; tracked for a future fix that adds a `verify-only` mode.
- **`atomic_write` is not strictly atomic on Windows.** The `os.remove` + `os.rename` pair leaves a window where readers see no file. Rare in practice but worth replacing with `os.replace` (Python 3.3+; for IronPython 2.7, retry-rename loop).
- **CODESYS doesn't enforce IEC identifier length** at create time; very long names are accepted and may surface as cryptic compile errors later. Consider a TS-side length cap (~24-32 chars) for new POU/DUT/GVL names.

## 0.5.0 — 2026-05-08

New tools and parameters for runtime work without dedicated hardware.

### Added
- **`set_simulation_mode` tool** — toggle device-level simulation mode on/off. Run before `connect_to_device` when no physical PLC is available. Supports a `verbose` flag (default `false` returns a terse summary; `true` returns the full script output).
- **`set_credentials` tool** — set the default username/password used for subsequent PLC logins. Username must be non-empty; for no-auth runtimes do not call this tool.
- **`connect_to_device` `ipAddress` and `gatewayName` parameters** — when `ipAddress` is provided, `set_gateway_and_address` is called on the device before login. `gatewayName` defaults to `Gateway-1` (the CODESYS install default).
- **`download_to_device` `mode` parameter** — `auto` (default; try online change, fall back to full), `online_change` (fail if rejected), or `full` (skip online change).
- **`--kill-existing-codesys` CLI flag** — opt-in: kills any pre-existing `CODESYS.exe` before launching. Off by default so an external IDE session is never killed.
- **`CODESYS_MCP_NO_CACHE` environment variable** — set to `1` to disable the in-memory Python script template cache. Useful for iterating on script templates without restarting the server.

### Changed
- **Cache is ON by default again** (was temporarily off during dev). Opt out via `CODESYS_MCP_NO_CACHE=1`.
- **Launcher uses `spawn(exe, args)` instead of `spawn(cmd, [], { shell: true })`** so the tracked PID is the actual `CODESYS.exe` PID rather than a wrapping `cmd.exe` shell PID. Health-check and shutdown paths now operate on the right process.
- **`connect_to_device` timeout reduced from 240s back to 60s** (the 240s was a debug bump; the IDE `Login` command path that needed it is no longer invoked from script).
- **`watcher.py` primary-thread `WaitOne` reduced from 240s back to 120s** for the same reason.

### Fixed
- Removed the IDE `Login` command invocation chain from `ensure_online_connection` — it hung the CODESYS primary thread indefinitely. The helper now calls `online.create_online_application` directly and returns an actionable error if it fails (with hints to enable simulation, set the gateway/address, or click `Online -> Login` in the IDE for the session if the scripting API hits its known `Stack empty` limitation).
- Em-dashes purged from `set_simulation_mode.py` (IronPython 2.7 source must stay ASCII-only without a UTF-8 coding header).
- `create_folder.py` now passes the folder name as a positional argument (CODESYS SP16 raised `TypeError: create_folder() got an unexpected keyword argument 'name'` with the previous keyword-arg call).
- `disconnect_from_device.py` no longer goes through `ensure_online_connection`. Disconnecting when not connected is now a no-op success rather than a `Stack empty` failure.
- `add_library.py` reports the actual API failure (e.g. "placeholder library X could not be resolved") instead of masking it with the generic "Library Manager does not support known add methods" message.
- `set_credentials` now Zod-validates `username.min(1)` — CODESYS rejects empty usernames with `ValueError`.

### Encoder fixes (carried forward from 0.4.x)
- Bulk POU read (`get_all_pou_code`), `get_compile_messages`, `compile_project`, `list_project_libraries`, and the single-POU resource read all handle non-ASCII content (e.g. cp1252 bytes for `§`) via the shared `_text_utils._to_unicode` helper plus `json.dumps(..., ensure_ascii=False)` and utf-8 byte-stdout writes. IronPython 2.7's default JSON encoder path crashes on such input.

## 0.4.x

Internal dev iterations. See git history.

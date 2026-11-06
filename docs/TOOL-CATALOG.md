# Tool catalog (auto-generated)

> Generated from `src/server.ts` by `scripts/gen-tool-catalog.js` (`npm run docs`, also run by `npm run build`).
> Do not edit by hand: fix the tool registration in `server.ts` and regenerate.

**76 tools, 214 parameters.** Tool names, parameter names, types, required-ness and allowed values are part of the public API -- see [PUBLIC-API.md](PUBLIC-API.md) for what that guarantees. Optional parameters are marked `?`.

| Tool | Parameters |
|---|---|
| [`add_device`](#add_device) | `projectFilePath`, `parentDevicePath`, `deviceName`, `deviceType`, `deviceId?`, `version?` |
| [`add_library`](#add_library) | `projectFilePath`, `libraryName` |
| [`attach_codesys`](#attach_codesys) | `confirm?` |
| [`clean_project`](#clean_project) | `projectFilePath`, `alsoEvictPrecompileCache?` |
| [`cleanup_backups`](#cleanup_backups) | `directory`, `keep?` |
| [`close_project`](#close_project) | `projectFilePath`, `force?` |
| [`compile_project`](#compile_project) | `projectFilePath`, `incremental?` |
| [`connect_to_device`](#connect_to_device) | `projectFilePath`, `ipAddress?`, `gatewayName?` |
| [`create_ac500_project`](#create_ac500_project) | `newProjectPath`, `templateProjectPath`, `addLibraries?`, `overwrite?` |
| [`create_boot_application`](#create_boot_application) | `projectFilePath`, `outputAppPath`, `writeVisuFiles?` |
| [`create_dut`](#create_dut) | `projectFilePath`, `name`, `dutType`, `parentPath` |
| [`create_folder`](#create_folder) | `projectFilePath`, `folderName`, `parentPath` |
| [`create_gvl`](#create_gvl) | `projectFilePath`, `name`, `parentPath`, `declarationCode?` |
| [`create_method`](#create_method) | `projectFilePath`, `parentPouPath`, `methodName?`, `name?`, `returnType?` |
| [`create_pou`](#create_pou) | `projectFilePath`, `name`, `type`, `language`, `parentPath`, `returnType?` |
| [`create_project`](#create_project) | `filePath`, `templatePath?`, `templateName?` |
| [`create_project_archive`](#create_project_archive) | `projectFilePath`, `outputPath`, `comment?`, `includeLibraries?`, `includeCompiledLibraries?` |
| [`create_property`](#create_property) | `projectFilePath`, `parentPouPath`, `propertyName`, `propertyType` |
| [`create_task`](#create_task) | `projectFilePath`, `taskName`, `cycleTimeMs?`, `watchdogTimeMs?`, `watchdogEnabled?`, `watchdogSensitivity?`, `priority?`, `stackSizeBytes?`, `kind?`, `pous?` |
| [`delete_object`](#delete_object) | `projectFilePath`, `objectPath` |
| [`diagnose_mcp_state`](#diagnose_mcp_state) | -- |
| [`diff_libraries_via_export`](#diff_libraries_via_export) | `sourceLibraryPath`, `targetLibraryPath`, `xmlOutputDir?`, `keepXml?` |
| [`diff_library_versions`](#diff_library_versions) | `sourceLibraryPath`, `targetLibraryPath` |
| [`disconnect_from_device`](#disconnect_from_device) | `projectFilePath` |
| [`download_to_device`](#download_to_device) | `projectFilePath`, `mode?` |
| [`export_library_parameters`](#export_library_parameters) | `projectFilePath`, `outputPath`, `libraryName?` |
| [`export_project_to_plcopen_xml`](#export_project_to_plcopen_xml) | `projectFilePath`, `outputXmlPath`, `applicationOnly?`, `includeLibraries?` |
| [`find_references`](#find_references) | `projectFilePath`, `symbol`, `caseSensitive?`, `maxHits?` |
| [`force_reset_watcher`](#force_reset_watcher) | -- |
| [`get_all_pou_code`](#get_all_pou_code) | `projectFilePath` |
| [`get_all_pou_code_offline`](#get_all_pou_code_offline) | `projectFilePath` |
| [`get_application_state`](#get_application_state) | `projectFilePath` |
| [`get_codesys_status`](#get_codesys_status) | -- |
| [`get_compile_messages`](#get_compile_messages) | `projectFilePath` |
| [`get_library_parameters`](#get_library_parameters) | `projectFilePath`, `libraryName?` |
| [`get_mcp_version`](#get_mcp_version) | -- |
| [`get_object_code`](#get_object_code) | `projectFilePath`, `objectPath` |
| [`get_pou_dependency_graph`](#get_pou_dependency_graph) | `projectFilePath`, `rootPOU?` |
| [`get_project_info`](#get_project_info) | `projectFilePath` |
| [`get_server_log`](#get_server_log) | `lines?` |
| [`get_task_configuration`](#get_task_configuration) | `projectFilePath` |
| [`import_library_parameters`](#import_library_parameters) | `projectFilePath`, `inputPath`, `skipDefaults?` |
| [`inspect_device_node`](#inspect_device_node) | `projectFilePath`, `devicePath` |
| [`inspect_project_tree`](#inspect_project_tree) | `projectFilePath`, `includeSymbols?`, `childrenOf?` |
| [`install_library_to_repository`](#install_library_to_repository) | `libraryProjectFilePath`, `repositoryName?` |
| [`launch_codesys`](#launch_codesys) | `projectFilePath?` |
| [`list_ab_sessions`](#list_ab_sessions) | -- |
| [`list_device_repository`](#list_device_repository) | `vendor?`, `nameContains?`, `maxResults?` |
| [`list_library_repository`](#list_library_repository) | `nameFilter?` |
| [`list_project_libraries`](#list_project_libraries) | `projectFilePath` |
| [`list_project_templates`](#list_project_templates) | `extraTemplateDir?` |
| [`map_io_channel`](#map_io_channel) | `projectFilePath`, `devicePath`, `channelPath`, `variableName?`, `clearBinding?` |
| [`monitor_variables`](#monitor_variables) | `projectFilePath`, `variablePaths`, `durationMs`, `intervalMs` |
| [`open_project`](#open_project) | `filePath` |
| [`read_variable`](#read_variable) | `projectFilePath`, `variablePath` |
| [`rebuild_library`](#rebuild_library) | `libraryProjectFilePath`, `regenerateCompiledArtifacts?` |
| [`release_library_version`](#release_library_version) | `libraryProjectFilePath`, `version`, `distFolder?`, `gitTag?`, `ghRelease?` |
| [`remove_library`](#remove_library) | `projectFilePath`, `libraryName` |
| [`rename_object`](#rename_object) | `projectFilePath`, `objectPath`, `newName` |
| [`rename_symbol`](#rename_symbol) | `projectFilePath`, `oldName`, `newName`, `dryRun?`, `includeDeclaration?`, `includeImplementation?` |
| [`reset_library_parameter`](#reset_library_parameter) | `projectFilePath`, `libraryName`, `parameterName` |
| [`save_project`](#save_project) | `projectFilePath` |
| [`search_code`](#search_code) | `projectFilePath`, `pattern`, `regex?`, `caseSensitive?`, `includeDeclaration?`, `includeImplementation?`, `maxHits?` |
| [`search_code_offline`](#search_code_offline) | `projectFilePath`, `pattern`, `regex?`, `caseSensitive?`, `maxHits?` |
| [`set_credentials`](#set_credentials) | `username`, `password` |
| [`set_device_parameter`](#set_device_parameter) | `projectFilePath`, `devicePath`, `parameterId`, `value` |
| [`set_library_parameter`](#set_library_parameter) | `projectFilePath`, `libraryName`, `parameterName`, `value` |
| [`set_library_reference_version`](#set_library_reference_version) | `projectFilePath`, `libraryName`, `version` |
| [`set_pou_code`](#set_pou_code) | `projectFilePath`, `pouPath`, `declarationCode?`, `implementationCode?` |
| [`set_project_info`](#set_project_info) | `projectFilePath`, `version?`, `title?`, `author?`, `company?`, `description?`, `released?` |
| [`set_simulation_mode`](#set_simulation_mode) | `projectFilePath`, `enable`, `verbose?` |
| [`set_task_parameter`](#set_task_parameter) | `projectFilePath`, `taskName`, `cycleTimeMs?`, `watchdogTimeMs?`, `watchdogEnabled?`, `watchdogSensitivity?`, `priority?`, `stackSizeBytes?`, `kind?`, `addPous?` |
| [`shutdown_codesys`](#shutdown_codesys) | -- |
| [`start_stop_application`](#start_stop_application) | `projectFilePath`, `action` |
| [`uninstall_library_from_repository`](#uninstall_library_from_repository) | `libraryName`, `version`, `repositoryName?` |
| [`write_variable`](#write_variable) | `projectFilePath`, `variablePath`, `value` |

## add_device

Add a device under an existing parent device. Use list_device_repository to source canonical deviceType/deviceId/version. Wrong ids produce a wrong-but-syntactically-valid node that fails at compile time.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `parentDevicePath` | string | yes | min 1 | Path to the parent device in the project tree, e.g. 'Device' for the root PLC, 'Device/Ethernet' for a fieldbus master. |
| `deviceName` | string | yes | min 1 | Name for the new device node (must be a valid CODESYS object name). |
| `deviceType` | number | yes | int | CODESYS device type id (numeric, from the device repository). |
| `deviceId` | number | no | int | CODESYS device id (numeric). Some add_device signatures don't require this. |
| `version` | string | no |  | Version string for the device (e.g. '3.5.16.0'). |

## add_library

Adds a library reference to the CODESYS project. The library must be installed in the CODESYS library repository.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `libraryName` | string | yes |  | Name of the library to add (e.g., 'Standard', 'Util', 'CAA Memory'). |

## attach_codesys

Attach to an ALREADY-RUNNING CODESYS / Automation Builder. Two-step flow that puts the user in control of the GUI lifecycle (no auto-spawn, no lock conflicts). Step 1: call without confirm — returns a watcher.py path. The user opens that file in CODESYS via "Tools → Scripting → Execute Script File..." (CODESYS must already be running; open the project there if needed). Step 2: call again with confirm=true — the server polls for the watcher's ready signal and switches to persistent mode. Use this instead of launch_codesys when the user wants to drive the GUI themselves.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `confirm` | boolean | no |  | Pass false (or omit) on the first call to prepare the watcher. Pass true on the second call after the user has started the watcher script inside CODESYS. |

## clean_project

Force a clean rebuild state. Runs target_app.clean() (or project.clean() for library projects) and -- when alsoEvictPrecompileCache=true (default) -- also deletes the .precompilecache / .compileinfo / .bootinfo cache files next to the source. Use when compile_project results don't reflect recent edits (cache lying) or before measuring a true cold-compile time.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `alsoEvictPrecompileCache` | boolean | no |  | If true (default), also delete <project>.precompilecache / .compileinfo / .bootinfo files from disk. |

## cleanup_backups

Sweep up the auto-backup snapshots (<file>.backup-YYYYMMDDTHHMMSSZ) that destructive tools leave next to .project/.library files, keeping only the newest N per source. Going forward, backups are auto-pruned and identical-to-newest snapshots are skipped, so this is mainly for clearing piles left by older sessions. ONLY deletes files matching the exact timestamped auto-backup pattern -- manual '<name>.backup' files and anything else are never touched. Does not require CODESYS to be running.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `directory` | string | yes | min 1 | Folder to sweep (typically the project folder containing the .project/.library and its .backup-* files). |
| `keep` | number | no | int, min 0 | How many newest backups to keep per source file. 0 = delete all auto-backups. Default: the server's --backup-retention (5). |

## close_project

Closes the currently open primary CODESYS project so that another project can be opened. Saves first unless 'force' is true. No-op if no project is currently open. Use this when switching between a library project and a consumer project to avoid the ~30-60s shutdown_codesys/launch_codesys cycle.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file expected to be open (used only for diagnostics; the tool closes whichever project is the current primary). |
| `force` | boolean | no |  | If true, skip saving and discard unsaved changes. Default false (saves first). |

## compile_project

Builds the active application. Returns errors/warnings, the memory report (memoryUsage) and which build-cache files clean() removed; incremental=true skips clean().

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file containing the application to compile. |
| `incremental` | boolean | no |  | true = build WITHOUT target_app.clean(). clean() (the default) deletes the <project>.<Device>.<App>.<guid>.compileinfo / .bootinfo / .bootinfo_guids files next to the project -- often tracked in git, and what online change needs -- and a scripted build does not rewrite them (only a download / online change / boot application does). Use true in repos that track them or before an online change. |

## connect_to_device

Connects (logs in) to the PLC runtime for the active application. If ipAddress is provided, set_gateway_and_address is called on the device first; otherwise the device must already have a configured gateway/address (or be in simulation mode via set_simulation_mode).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `ipAddress` | string | no |  | Optional PLC IP address. Sets the device gateway/address before login. Leave unset to use whatever is configured on the device, or to use simulation mode. |
| `gatewayName` | string | no |  | Optional gateway name (defaults to 'Gateway-1', the CODESYS install default). Only used if ipAddress is also provided. |

## create_ac500_project

Create a new AC500 V3 .project file by copying an existing clean AC500 template and optionally adding initial libraries. AB Standard does NOT ship with an AC500-specific stock template that the scripting API can use directly, so the caller provides a known-good AC500 project to use as the base (typically a vanilla NexoPlcExample.project with no user code). The template's device tree (PM5650-2ETH / PM5032 / etc) is preserved exactly. To use a different PLC model, point the templateProjectPath at a project that already targets that model.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `newProjectPath` | string | yes | min 1 | Path where the new .project file should be created (parent directory is auto-created). |
| `templateProjectPath` | string | yes | min 1 | Path to an existing AC500 V3 .project file to use as the template (its device tree is preserved). |
| `addLibraries` | string | no |  | Optional SEMICOLON-separated list of fully-qualified libraries to add (e.g. 'Standard, * (System); MQTT Client SL, 4.1.0.0 (3S - Smart Software Solutions GmbH)'). Use semicolons to avoid colliding with the commas inside library names. |
| `overwrite` | boolean | no |  | If true (default), overwrite newProjectPath if it exists. |

## create_boot_application

Generate a deployable boot application (.app + .crc) from the project's active application via ScriptApplication.create_boot_application(). Equivalent to AB UI 'Online > Create Boot Application' but offline (no PLC connection needed). Runs generate_code() first so the image is current. Premium-confirmed. Returns the output path and byte size; the .crc sibling is written automatically next to the .app.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the .project file. |
| `outputAppPath` | string | yes | min 1 | Path where the .app file will be written (e.g. C:/out/MyApp.app). Parent directory is auto-created; a sibling .crc is written alongside. |
| `writeVisuFiles` | boolean | no |  | If true, also write visualization files (uses the 3-arg create_boot_application overload). Default false. |

## create_dut

Creates a new Data Unit Type (DUT) - structure, enumeration, union, or alias - within the specified CODESYS project.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `name` | string | yes | min 1 | Name for the new DUT (must be a valid IEC identifier). |
| `dutType` | 'Structure' \| 'Enumeration' \| 'Union' \| 'Alias' | yes |  | Type of DUT. |
| `parentPath` | string | yes | min 1 | Relative path under project root or application (e.g., 'Application'). |

## create_folder

Creates an organizational folder within the CODESYS project tree.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `folderName` | string | yes |  | Name for the new folder. |
| `parentPath` | string | yes |  | Relative path under project root or application (e.g., 'Application'). |

## create_gvl

Creates a new Global Variable List (GVL) within the specified CODESYS project.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `name` | string | yes |  | Name for the new GVL (must be a valid IEC identifier). |
| `parentPath` | string | yes |  | Relative path under project root or application (e.g., 'Application'). |
| `declarationCode` | string | no |  | Optional initial declaration code for the GVL (VAR_GLOBAL...END_VAR). |

## create_method

Creates a new Method within a specific Function Block POU.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `parentPouPath` | string | yes |  | Relative path to the parent Function Block POU (e.g., 'Application/MyFB'). |
| `methodName` | string | no |  | Name of the new method (must be a valid IEC identifier). Alias of `name`. |
| `name` | string | no |  | Name of the new method (alias of `methodName`, matches create_pou's param). |
| `returnType` | string | no |  | Return type (e.g., 'BOOL', 'INT'). Leave empty or omit for no return value. |

## create_pou

Creates a new Program, Function Block, Function, Interface, or Parameter List POU within the specified CODESYS project.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `name` | string | yes | min 1 | Name for the new POU (must be a valid IEC identifier). |
| `type` | 'Program' \| 'FunctionBlock' \| 'Function' \| 'Interface' \| 'ParameterList' | yes |  | Type of POU. 'Interface' creates an abstract OOP contract with no implementation; add methods to it via the create_method tool. 'ParameterList' creates a CODESYS Parameter List (library consumer-overridable VAR_GLOBAL CONSTANT block surfaced under the Library Manager 'Parameters' tab); populate it with set_pou_code on the declaration section. NOTE: ParameterList creation is empirically not supported by the IronPython ScriptEngine on AB 2.9 Standard edition (PouType.ParameterList enum member is absent and no create_parameterlist* method is exposed on parent objects). If the call fails with a diagnostic RuntimeError, fall back to creating the POU manually in the AB UI (Add Object -> Parameter List) and then use set_pou_code to populate its declaration. May work on AB 2.9 Premium or future CODESYS V3.5 SPxx builds that expose the API. |
| `language` | 'ST' \| 'LD' \| 'FBD' \| 'SFC' \| 'IL' \| 'CFC' | yes |  | Implementation language. Ignored for Interface and ParameterList POUs (no implementation section). |
| `parentPath` | string | yes | min 1 | Relative path under project root or application (e.g., 'Application'). |
| `returnType` | string | no |  | Return type for Function POUs (e.g., 'BOOL', 'STRING', 'INT', 'REAL'). Required when type is 'Function'; ignored for 'Program', 'FunctionBlock', 'Interface', and 'ParameterList'. |

## create_project

Creates a new CODESYS project. Two modes: (A, default) copy a .project file and open it -- either the auto-discovered Standard.project, or an explicit templatePath; (B) instantiate a template registered with CODESYS's own Template Manager by templateName -- required for package-installed templates (e.g. a vendor device package) that have no free-standing .project file on disk. Use list_project_templates to discover which kwarg to pass.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `filePath` | string | yes |  | Path where the new project file should be created. |
| `templatePath` | string | no |  | Optional: explicit path to a .project file to copy (mode A). If omitted and templateName is also omitted, the auto-discovered Standard.project is used. |
| `templateName` | string | no |  | Optional: name of a template registered with CODESYS's Template Manager to instantiate (mode B). Takes precedence over templatePath/auto-discovery when set. Use list_project_templates to find valid names. |

## create_project_archive

Saves the currently-open project as a .projectarchive. Read-only with respect to the project itself - the project must already be open (this tool will not switch projects). Output path may be absolute or relative to the workspace.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file (must be the currently-open project). |
| `outputPath` | string | yes | min 1 | Output .projectarchive path (absolute or workspace-relative). |
| `comment` | string | no |  | Optional comment embedded in the archive metadata. |
| `includeLibraries` | boolean | no |  | If true (default), include referenced library sources in the archive. |
| `includeCompiledLibraries` | boolean | no |  | If true (default), include compiled library binaries. Set false to keep archives small for plain-text version control. |

## create_property

Creates a new Property within a specific Function Block POU.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `parentPouPath` | string | yes |  | Relative path to the parent Function Block POU (e.g., 'Application/MyFB'). |
| `propertyName` | string | yes |  | Name for the new property (must be a valid IEC identifier). |
| `propertyType` | string | yes |  | Data type of the property (e.g., 'BOOL', 'INT', 'MyDUT'). |

## create_task

Creates a task in the active application's Task Configuration (kind, interval, priority, watchdog) and adds its POU calls, all read back and saved. Fails if it exists.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `taskName` | string | yes | min 1 | Name of the new task (e.g. 'WebTask'). A new task starts with AB's defaults (live AB 2.9 AC500 V3: cyclic t#10ms, priority 14, watchdog ON t#20ms, sensitivity 1) -- pass the knobs you need, e.g. watchdogEnabled=false for a task that makes blocking calls. |
| `cycleTimeMs` | number | no | int, positive | Cycle time / interval in milliseconds. |
| `watchdogTimeMs` | number | no | int, positive | Watchdog timeout in milliseconds. Also arms the watchdog unless watchdogEnabled is passed explicitly. NOTE: the watchdog measures EXECUTION time per cycle, not the cycle period. |
| `watchdogEnabled` | boolean | no |  | Arm (true) or disable (false) the task watchdog. Pass false when the task makes blocking calls that legitimately exceed the timeout -- e.g. NBS.ResolveHostname on a bench program -- instead of disabling it by hand in the AB task editor. Overrides the implicit arming done by watchdogTimeMs. |
| `watchdogSensitivity` | number | no | int, positive | Watchdog sensitivity: the number of consecutive cycles that must exceed the timeout before the watchdog trips (AC500 V3 default 1). |
| `priority` | number | no | int, min 0, max 31 | Task priority (0 = highest, 31 = lowest on AC500 V3). |
| `stackSizeBytes` | number | no | int, positive | Stack size in bytes. Required when a library has large STRING(N) buffers that overflow the default ~128KB stack; common bump is 262144 (256KB). |
| `kind` | 'cyclic' \| 'freewheeling' \| 'event' \| 'status' \| 'externalevent' | no |  | Kind of task (KindOfTask). cycleTimeMs applies to cyclic tasks. |
| `pous` | string[] | no |  | Programs the task calls, in order (e.g. ['WEB_PRG']). A name not found in the project tree is reported as a warning (it may be a library program); compile_project is the final check. |

## delete_object

Deletes a project object (POU, DUT, GVL, folder, etc.) from the CODESYS project. WARNING: This is destructive and cannot be undone. System nodes (Application, Device, Plc Logic, Library Manager, Project Settings, Task Configuration, etc.) are refused.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `objectPath` | string | yes |  | Path to the object to delete. Accepted forms (any of): full-from-root 'Application/MyPOU' or library 'MyLib/Function Blocks/FB_X[/Method]'; an unambiguous bare leaf name 'FB_X'. System/top-level nodes (Application, Device, Library Manager, Task Configuration, etc.) are refused. |

## diagnose_mcp_state

Read-only diagnostic dump for when something feels off with the MCP. Returns: launcher lifecycle state, process liveness, watcher heartbeat age, pending command queue depth, orphan result file count, last watcher_error.txt contents, plus a human-readable interpretation telling you whether the state is healthy / stalled / process-died / recovering. Use this BEFORE force_reset_watcher so you know whether the reset is actually needed (vs. e.g. a long-running command in flight).

No parameters.

## diff_libraries_via_export

Compose-tool: opens libraryA, exports PLCopen XML, closes; opens libraryB, exports XML, closes; runs the structured diff on the two XML files. Solves the binary-format limitation of diff_library_versions in one tool call. SLOW (~30-90s) because it round-trips through CODESYS for both exports. xmlOutputDir (optional) keeps the intermediate XML files for inspection; omit to use %TEMP%.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `sourceLibraryPath` | string | yes | min 1 | Path to the OLDER .library file. |
| `targetLibraryPath` | string | yes | min 1 | Path to the NEWER .library file. |
| `xmlOutputDir` | string | no |  | Optional directory to keep the intermediate XML exports. Defaults to %TEMP%. |
| `keepXml` | boolean | no |  | If true, keep the intermediate XML files after diffing (default true when xmlOutputDir is set, false otherwise). |

## diff_library_versions

Compare two PLCopen XML exports of a library (or two snapshots across versions) and return a structured diff: POUs/GVLs/DUTs added/removed/modified, library references added/removed/version-changed, Project Information field changes. **IMPORTANT**: Native CODESYS .library files are binary and unsupported. First export PLCopen XML from each version's library (File > Export PLCopen XML... in AB), then diff the XML files. Useful for release notes auto-generation, pre-install validation, and 'what changed' investigations across versions.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `sourceLibraryPath` | string | yes | min 1 | Path to the OLDER .library file (the 'from' side). |
| `targetLibraryPath` | string | yes | min 1 | Path to the NEWER .library file (the 'to' side). |

## disconnect_from_device

Disconnects (logs out) from the PLC runtime. No-op (success) if not connected.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |

## download_to_device

Downloads the compiled application to the PLC device. mode controls strategy: 'auto' (default) tries online change then falls back to full; 'online_change' fails if online change is rejected; 'full' always does a full download.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `mode` | 'auto' \| 'online_change' \| 'full' | no |  | Download strategy. Default 'auto'. |

## export_library_parameters

Export the consumer-side Library Parameter values to a JSON file. Useful for replicating a consumer's parameter config across projects or stashing a baseline before mass-editing. By default exports ALL parameters with their current value + isOverridden flag; pair with import_library_parameters to restore.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the source consumer .project file. |
| `outputPath` | string | yes | min 1 | Path where the JSON export will be written. Overwritten if exists. |
| `libraryName` | string | no |  | Optional library name filter (case-insensitive substring). |

## export_project_to_plcopen_xml

Export the project's POUs/DUTs/GVLs to a PLCopen XML file via project.export_plcopenxml(). Equivalent to AB UI 'File > Export PLCopen XML...'. Use as a precursor to the offline / diff tools that need XML input (.project files are binary). Probes export_plcopenxml signature variants since the .NET binding accepts varying numbers of args across CODESYS V3.5 SPxx builds.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the .project or .library file to export. |
| `outputXmlPath` | string | yes | min 1 | Path where the .xml file will be written. Parent directory is auto-created. |
| `applicationOnly` | boolean | no |  | If true, export only the active application's tree (smaller, recommended). If false, project-level export including non-application objects. |
| `includeLibraries` | boolean | no |  | If true, recurse into referenced libraries and include their content (heavy; rarely needed). Default false. |

## find_references

Find every word-boundary reference to a symbol (\bsymbol\b) across textual POU/Method/Property/DUT/GVL bodies. Wraps search_code. Comments and string literals are not excluded.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `symbol` | string | yes | min 1 | Identifier to find references to (e.g. 'GVL_Cameras', 'fbParser1'). |
| `caseSensitive` | boolean | no |  | If true (default), match case-sensitively per IEC 61131-3 conventions. |
| `maxHits` | number | no | int, positive | Cap on returned hits (default 1000). |

## force_reset_watcher

Recovery tool for when the CODESYS MCP appears 'locked' (commands time out / state is 'stalled' / agent suspects watcher is dead). Kills the CODESYS process, cleans up the IPC directory, and re-launches CODESYS with a fresh watcher in a single operation. Equivalent to shutdown_codesys + launch_codesys but faster (~10-30s) and with stale-file cleanup in between. Does NOT save any open project (the project state is unknown when the watcher is stalled). Use after diagnose_mcp_state confirms a stall.

No parameters.

## get_all_pou_code

Reads the declaration and implementation code of every POU/DUT/GVL in the project. Returns all code in a single response for bulk review. For a SINGLE object, prefer get_object_code (much less output).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |

## get_all_pou_code_offline

Read POU/GVL/DUT declaration + implementation bodies from a PLCopen XML export by parsing the file directly -- NO CODESYS instance required. **IMPORTANT**: Native CODESYS .project / .library files on AB 2.9 are in a proprietary BINARY container format and CANNOT be parsed by this tool (it will throw with a guiding error). To use this tool, first run File > Export PLCopen XML... in AB on the project of interest to produce an XML file, then point this tool at the .xml. Useful for concurrent reads while user has the (binary) project open in AB UI -- the export XML is a static snapshot and can be re-parsed at any time.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the .project / .library file. |

## get_application_state

Gets the current state of the PLC application (running, stopped, exception, etc.).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |

## get_codesys_status

Get the current status of the CODESYS instance: lifecycle state, PID, mode, and watcher heartbeat age. State='stalled' means the watcher heartbeat has gone stale (worker thread dead or primary UI thread deadlocked) and force_reset_watcher should be called to recover.

No parameters.

## get_compile_messages

Reads the last build's messages (errors, warnings, memory report) without building. Cached from the last compile_project; rebuild after edits.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |

## get_library_parameters

Library Parameters per reference: the project's overrides; with libraryName also the library's declared parameters and defaults (read from its .library source).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the consumer .project file. |
| `libraryName` | string | no |  | Library filter, case-insensitive substring of the reference ('AC500-V3-utilities-web', '#Util'). With a filter the library's own parameter list and defaults are read too (not possible for a compiled library); without one only references that carry overrides are listed. |

## get_mcp_version

Returns the version and commit of the build this server process loaded (stamped at build time), the build whose Python scripts are on disk now, whether Claude Code needs a restart to load it, and the list of named patches in this fork. Versions follow Semantic Versioning 2.0.0 (docs/PUBLIC-API.md). Use to verify which fixes are active before assuming a workaround is needed for a known-fixed bug.

No parameters.

## get_object_code

Reads the declaration + implementation code of a SINGLE POU/DUT/GVL/Method/Property by path -- the surgical 'read the minimum' reader, vs get_all_pou_code which dumps the whole project. Accepts the same path forms as set_pou_code: full-from-root 'Application/MyPOU', library 'MyLib/Function Blocks/FB_X[/Method]', or an unambiguous bare leaf name. Read-only: refuses to switch the open project.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file (must already be the open project). |
| `objectPath` | string | yes | min 1 | Path to the target object. Forms: 'Application/MyPOU', 'MyLib/Function Blocks/FB_X[/Method]', or an unambiguous bare leaf name ('FB_X', 'MyGVL'). |

## get_pou_dependency_graph

Build a directed call graph of POUs/FBs/Methods in the project: for each pair (caller, callee) the script detects whether the callee's name appears word-boundary-matched in the caller's body. Optionally compute reachability from a root POU (typically 'PLC_PRG') to flag dead-code POUs not reachable from the application's entry point. Useful for architecture review, refactoring impact analysis, and understanding why a typo in an unreferenced POU did NOT show up in compile (CODESYS doesn't analyze unreachable code).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `rootPOU` | string | no |  | Optional root POU name (e.g. 'PLC_PRG'). When provided, the graph is annotated with isDeadCode=true for POUs unreachable from this root. |

## get_project_info

Reads the Project Information node fields (version, title, author, company, description). Returns a JSON object with the present fields. Mirrors what is shown in the AB UI menu 'Project > Project Information'.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |

## get_server_log

Returns the tail of the MCP server's lifecycle log file (--log-file). Use to self-diagnose AB lifecycle events (detachKeepAlive / Force-killing / soft-probe / adoption / teardown cause=...) without hunting for files on disk. Errors clearly if --log-file was not configured.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `lines` | number | no | int, min 1, max 2000 | How many trailing lines to return. Default 100. |

## get_task_configuration

Lists every Task Configuration node in the project with its child tasks and their current properties (cycle time, priority, watchdog, stack size where exposed). Library projects have no Task Configuration -- this tool is for application/consumer projects (typically PLC_AC500_V3 / Plc Logic / Application / Task Configuration).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |

## import_library_parameters

Import Library Parameter values from a JSON file (produced by export_library_parameters) into a consumer project. By default applies only entries that were marked isOverridden=true in the export (skipping defaults that the library already provides); set skipDefaults=false to import every entry blindly. Returns per-parameter applied/skipped/failed lists for review.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the target consumer .project file. |
| `inputPath` | string | yes | min 1 | Path to the JSON export to import. |
| `skipDefaults` | boolean | no |  | If true (default), skip entries whose isOverridden was false in the export. |

## inspect_device_node

Read-only introspection of a device node: descriptor metadata, parameter list with current values, child sub-devices. Pair with set_device_parameter to discover writable IDs.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file (must be the currently-open project). |
| `devicePath` | string | yes | min 1 | Path to the device node, e.g. 'Device' for the PLC root, 'Device/Ethernet/EIP_Adapter' for a fieldbus adapter. |

## inspect_project_tree

JSON dump of the project tree (devices, POUs, GVLs, DUTs, folders, tasks, others with raw type GUID, e.g. ImagePool). childrenOf lists one node's direct children instead.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `includeSymbols` | boolean | no |  | If true, embed first 200 chars of each POU/GVL/DUT declaration. Default false (compact dump). |
| `childrenOf` | string | no |  | Path of ONE node (full, or an unambiguous tail such as 'App/Visu') whose direct children to list, each with kind, typeName, raw typeGuid, className and childCount. Returns only that list. |

## install_library_to_repository

Installs a Released .library into the Library Repository, never overwriting: the same build already installed is a no-op, the same name+version with different content is ERR_LIB_EXISTS (a fix is the next PATCH), a library not marked Released is ERR_LIB_NOT_RELEASED, a version that is not MAJOR.MINOR.PATCH is ERR_BAD_INPUT. The install is read back byte for byte. The user's primary project is not switched.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `libraryProjectFilePath` | string | yes |  | Path to the .library file to install. If it is not the open project it is installed straight from disk without opening it (the user's open project is not switched). If it is open: saved only when dirty -- a Released library opens read-only, so it is installed as saved. |
| `repositoryName` | string | no |  | Optional name of the target repository (e.g. 'User', 'Default'). If omitted, the script picks the User repository if available, otherwise the first repository. |

## launch_codesys

Manually launch CODESYS with UI. Use when --no-auto-launch was set. If a still-running AB from a previous keep-alive session is detected, this adopts it (no cold start) instead of spawning a second instance. Adoption NEVER takes an AB that another live MCP server is driving (owner.json marker). Pass projectFilePath to resume YOUR AB that has that project open; without it only a released/orphaned session, or an idle one, is adopted, and the result lists any live session it passed over and why.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | no |  | Optional: the project you intend to work on. Lets adoption resume an AB that already has it open; sessions with another project, or driven by another live server, are never taken. |

## list_ab_sessions

Lists every LIVE Automation Builder/CODESYS watcher session on this machine (fresh heartbeat + alive PID), with each one's PID, heartbeat age, and OPEN PROJECT. On a shared box where several agents each drive their own AB, use this to see who owns which project before launching/adopting -- and to confirm this server adopted the right instance ('isMine'). Read-only; safe anytime. Requires --mode persistent.

No parameters.

## list_device_repository

Enumerate device descriptors from the local CODESYS Device Repository. Returns {name, vendor, device_type, device_id, version, description, category} per entry. Use to discover canonical ids for add_device.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `vendor` | string | no |  | Optional case-insensitive vendor substring filter (e.g. '3S', 'ifm', 'Beckhoff'). |
| `nameContains` | string | no |  | Optional case-insensitive substring filter on the device name. |
| `maxResults` | number | no | int, positive | Cap on returned entries (default 500). |

## list_library_repository

Enumerate libraries installed in the CODESYS Library Repository (the System / User / Default repos). Returns one JSON entry per repository (with its root folder) containing its libraries with name, version, company and display -- the exact 'Title, version (Company)' string add_library and set_library_reference_version expect; location (the installed .library file) is filled when nameFilter is given. Use to verify which versions are installed before/after install_library_to_repository or uninstall_library_from_repository -- saves the round-trip to 'Tools > Library Repository' in the AB UI.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `nameFilter` | string | no |  | Optional case-insensitive substring filter on library name (e.g. 'Nexo' returns only libs whose name contains 'Nexo'). |

## list_project_libraries

Lists the project's library references per Library Manager, marking placeholders ('#X' -> resolved library) and system references.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |

## list_project_templates

Enumerates project templates known to the local CODESYS install via two channels: (1) ScriptEngine projects.templates-style probes, which picks up templates registered by package installers (no free-standing .project file needed); (2) a filesystem scan of %ProgramData%/CODESYS template directories. Returns {name, path, source} per template so you know which kwarg to pass to create_project (templateName for API-sourced, templatePath for filesystem-sourced). Read-only.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `extraTemplateDir` | string | no |  | Optional additional directory to scan for .project/.projecttemplate/.projectarchive files. |

## map_io_channel

Bind (or clear) a fieldbus I/O channel to a global variable symbol. Use inspect_device_node first to discover the channel layout.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `devicePath` | string | yes | min 1 | Path to the device node (e.g. 'Device/Ethernet/EIP_Adapter'). |
| `channelPath` | string | yes | min 1 | Channel address relative to the device. Either a name path ('Inputs/Byte 0/Bit 3') or numeric indices ('0/3'). |
| `variableName` | string | no |  | Global variable to bind (e.g. 'GVL.bSensor', 'PLC_PRG.xMotor'). Required unless clearBinding is true. |
| `clearBinding` | boolean | no |  | If true, remove the existing binding instead of setting one. variableName is ignored. |

## monitor_variables

Sample one or more PLC variables at a fixed interval over a bounded duration; returns the timeseries. Blocks the CODESYS UI thread (capped at 60s).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `variablePaths` | string[] | yes | min 1 | List of variable paths to sample (e.g. ['PLC_PRG.x', 'GVL.nCounter']). |
| `durationMs` | number | yes | int, positive | Total sampling duration in ms. Capped at 60000. |
| `intervalMs` | number | yes | int, positive | Sample interval in ms. Floor 10ms. |

## open_project

Opens an existing CODESYS project file.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `filePath` | string | yes |  | Path to the project file (e.g., 'C:/Projects/MyPLC.project'). |

## read_variable

Reads the current value of a variable from the running PLC application. Must be connected first.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `variablePath` | string | yes |  | Variable path (e.g., 'PLC_PRG.bMotorRunning', 'GVL.nCounter'). |

## rebuild_library

Force a full rebuild of a .library project. Runs target_app.clean() (cache invalidation) + check_all_pool_objects() (source-level semantic check) and, when regenerateCompiledArtifacts=true (default), attempts to regenerate the compiled-library artifacts embedded in the .library project file -- mirrors the AB UI 'Build > Generate Library'. The compiled-artifact regeneration is best-effort: not all CODESYS builds expose generate_compiled_library() and the tool surfaces ERR_API_NOT_EXPOSED with a SOFT warning (source rebuild still succeeded) when not available.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `libraryProjectFilePath` | string | yes |  | Path to the .library project file to rebuild. |
| `regenerateCompiledArtifacts` | boolean | no |  | If true (default), also attempt to regenerate compiled-library artifacts inside the .library file. |

## release_library_version

Release a library in one call, following SemVer 2.0.0: (1) refuse a version that is not MAJOR.MINOR.PATCH or is already installed -- before touching anything; (2) set the version, clearing Released for the edit; (3) rebuild_library; (4) mark Released; (5) install_library_to_repository, which reads the install back; optionally (6) copy to distFolder/v{version}/{name}-v{version}.library, git tag v{version}, gh release. A library is installed already Released, and a taken number is never overwritten: a fix is the next PATCH. Every step is reported in the returned JSON.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `libraryProjectFilePath` | string | yes |  | Path to the .library project file to release. |
| `version` | string | yes | min 1 | New version, MAJOR.MINOR.PATCH only (e.g. '1.0.11'): AB's Version field takes numbers only, and a fourth number is a defect. Must not be installed yet. |
| `distFolder` | string | no |  | Optional path to a dist folder. The .library file is copied to {distFolder}/v{version}/{name}-v{version}.library after install. |
| `gitTag` | boolean | no |  | If true, run 'git tag v{version}' in the library's repo directory after install. Off by default. |
| `ghRelease` | boolean | no |  | If true and gitTag is also true, run 'gh release create v{version} --generate-notes' after the tag. Off by default. |

## remove_library

Removes a library REFERENCE (placeholder '#X' or managed 'X, 1.0 (Vendor)') from the project's Library Managers; the repository is untouched. System references are refused.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `libraryName` | string | yes | min 1 | Reference to remove, case-insensitive: the display string ('#LogiQ', 'MyLib, 1.0.0 (Vendor)'), the name without '#', the base name ('AC500-V3-utilities-web'), what a placeholder resolves to ('MProtocol-library'), the list_project_libraries form, or an unambiguous substring. Only system_library=True references (added by the device/plug-ins: IoDrv*, Standard, #System_Visu*) are refused -- '#' alone just means placeholder. |

## rename_object

Renames a project object (POU, DUT, GVL, folder, etc.) in the CODESYS project.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `objectPath` | string | yes |  | Full relative path to the object to rename (e.g., 'Application/MyPOU'). |
| `newName` | string | yes |  | New name for the object (must be a valid IEC identifier). |

## rename_symbol

Best-effort word-boundary textual rename across textual POU/Method/Property/DUT/GVL bodies. Defaults to dryRun=true. Does not rename the project object node (use rename_object) or graphical bodies.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `oldName` | string | yes | min 1 | Existing symbol name. |
| `newName` | string | yes | min 1 | Replacement name. |
| `dryRun` | boolean | no |  | If true (default), report matches without writing. Set false to apply. |
| `includeDeclaration` | boolean | no |  | If true (default), rewrite declaration sections. |
| `includeImplementation` | boolean | no |  | If true (default), rewrite implementation sections. |

## reset_library_parameter

Remove the consumer-side override for a Library Parameter, falling back to the library's default value. Use when a stale override from an old library version is silently masking a default change (the canonical cause of 'why is my consumer still seeing the old value' debugging spirals).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the consumer .project file. |
| `libraryName` | string | yes | min 1 | Library name. |
| `parameterName` | string | yes | min 1 | Parameter name to reset. |

## save_project

Saves the currently open CODESYS project.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file to ensure is open before saving. |

## search_code

Regex (or literal substring) search across every POU/Method/Property/DUT/GVL textual body. Returns file:line:col hits. Graphical bodies with no textual_implementation are skipped.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `pattern` | string | yes | min 1 | Pattern to search for. Treated as a regex unless regex=false. |
| `regex` | boolean | no |  | If true (default), pattern is a regex. If false, pattern is a literal substring. |
| `caseSensitive` | boolean | no |  | If true (default), matching is case-sensitive. |
| `includeDeclaration` | boolean | no |  | If true (default), search declaration sections. |
| `includeImplementation` | boolean | no |  | If true (default), search implementation sections. |
| `maxHits` | number | no | int, positive | Cap the number of returned hits (default 1000). |

## search_code_offline

Search POU/GVL/DUT bodies in a PLCopen XML export by parsing the file directly. **IMPORTANT**: Native CODESYS .project / .library files are binary and unsupported (throws with guiding error). Export PLCopen XML from AB first, then point this tool at the .xml. Use for fast searches when AB is busy / locked / would be slow to launch.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the .project / .library file. |
| `pattern` | string | yes | min 1 | Search pattern. Literal substring by default; pass regex=true to interpret as regex. |
| `regex` | boolean | no |  | If true, interpret pattern as a regex. Default false (literal substring). |
| `caseSensitive` | boolean | no |  | If true, case-sensitive match. Default false. |
| `maxHits` | number | no | int, positive | Maximum hits to return. Default 500. |

## set_credentials

Set default username/password used for subsequent PLC logins. Use this once per session before connect_to_device when the runtime requires authentication. Both fields must be non-empty: CODESYS rejects empty username strings. If your runtime has no auth, do not call this tool.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `username` | string | yes | min 1 | Username (must be non-empty; CODESYS rejects empty strings). |
| `password` | string | yes |  | Password. |

## set_device_parameter

EXPERIMENTAL. Set a parameter value on a device. Use inspect_device_node first to find writable IDs. Many fieldbus parameters are GUI-only; this tool returns a clear error in that case.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `devicePath` | string | yes | min 1 | Path to the device in the project tree, e.g. 'Device/Ethernet/EIP_Adapter_X'. |
| `parameterId` | number \| string | yes |  | Parameter id (numeric for most CODESYS device descriptors; string accepted as a fallback). |
| `value` | string | yes |  | Value to write. Use the type-appropriate textual representation (e.g. '192.168.1.10' for IP, 'TRUE' for BOOL, '42' for INT). |

## set_library_parameter

Sets a consumer-side Library Parameter override (e.g. gc_udiPageMax := 65536), read back and saved. The name is checked against the library source when readable.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the consumer .project file. |
| `libraryName` | string | yes | min 1 | Library reference: display string, base name ('AC500-V3-utilities-web'), placeholder name ('Util') or unambiguous substring. |
| `parameterName` | string | yes | min 1 | Parameter name, case-insensitive (e.g. 'gc_udiPageMax'). The scripting API accepts ANY name, so for a .library source it is validated against the declared constants (ERR_LIB_PARAM_NOT_FOUND otherwise); for a compiled library it cannot be and the result says nameValidated=false. |
| `value` | string | yes |  | New value as a string (e.g. '1024', 'TRUE', "'foo'"). Use the IEC literal form the parameter expects. |

## set_library_reference_version

Change which version of a library a reference in the consumer project's Library Manager uses. PLACEHOLDER references ('#MProtocol', how AC500 V3 adds libraries by name) get a project-level placeholder redirection to 'Title, version (Company)'. MANAGED references ('AC500-V3-utilities-ip, 1.0.2 (ABB)') are removed and re-added at the new version, restoring their namespace / qualified_only / optional and re-applying parameter overrides. '*' floats to the newest installed version in both cases. The target version must be INSTALLED -- AB itself accepts a redirection to a missing version and leaves the reference unresolved, so this refuses it (ERR_LIB_NOT_FOUND, listing the installed versions) before writing anything. Read back before saving; on a change that does not take, the previous state is restored in memory and nothing is saved (ERR_WRITE_DID_NOT_STICK). System references (added by the device) are refused.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the consumer .project file. |
| `libraryName` | string | yes | min 1 | The reference: '#Placeholder', the name without '#', the base name, the library it resolves to, or an unambiguous substring (same forms as remove_library). |
| `version` | string | yes | min 1 | Target version (e.g. '1.0.10') or '*' for latest available. |

## set_pou_code

Sets the declaration and/or implementation code for a specific POU, Method, or Property. Omit (or pass empty string for) a section to leave it unchanged.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `pouPath` | string | yes | min 1 | Path to the target POU/Method/Property. Accepted forms (any of): full-from-root 'Application/MyPOU' or library 'MyLib/Function Blocks/FB_X[/Method]'; an unambiguous bare leaf name 'FB_X' or even a nested method 'VerifyInput' (resolved by recursive search). Ambiguous bare names error cleanly. |
| `declarationCode` | string | no |  | Code for the declaration part (VAR...END_VAR). If omitted or empty, not changed. |
| `implementationCode` | string | no |  | Code for the implementation logic. If omitted or empty, not changed. |

## set_project_info

Updates Project Information (version, title, author, company, description, released) and saves. Only passed fields change. released=false unlocks a Released (read-only) project.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `version` | string | no |  | Project version. Format: 'MAJOR.MINOR.SERVICEPACK[.BUILD]', e.g. '1.0.5' or '1.0.5.42'. |
| `title` | string | no |  | Project title. |
| `author` | string | no |  | Project author. |
| `company` | string | no |  | Project company. |
| `description` | string | no |  | Project description (multi-line allowed). |
| `released` | boolean | no |  | The 'Released' flag. AB opens a Released project/library READ-ONLY and every save fails ('opened in read-only mode'); false clears it in the same session so this call and later edits can save (bump the version too -- a released version should not change). true marks it released after the other fields are applied. |

## set_simulation_mode

Toggle PLC simulation mode on/off for the project Device. Run before connect_to_device when no physical PLC is available; CODESYS will then simulate execution without a runtime gateway.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `enable` | boolean | yes |  | True to enable simulation mode, false to disable. |
| `verbose` | boolean | no |  | If true, return the full script output (device list, verification, etc.). Default false returns a terse summary. |

## set_task_parameter

Updates a Task: cycle time, priority, watchdog time/enable/sensitivity, kind, stack size, extra POU calls (addPous). Every write is read back; a knob that did not take FAILS the call (ERR_WRITE_DID_NOT_STICK). AC500 V3 stack size usually lives on the Device (set_device_parameter).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `taskName` | string | yes | min 1 | Exact name of the task as shown under Task Configuration (e.g. 'MainTask'). Use get_task_configuration to discover. |
| `cycleTimeMs` | number | no | int, positive | Cycle time / interval in milliseconds. |
| `watchdogTimeMs` | number | no | int, positive | Watchdog timeout in milliseconds. Also arms the watchdog unless watchdogEnabled is passed explicitly. NOTE: the watchdog measures EXECUTION time per cycle, not the cycle period. |
| `watchdogEnabled` | boolean | no |  | Arm (true) or disable (false) the task watchdog. Pass false when the task makes blocking calls that legitimately exceed the timeout -- e.g. NBS.ResolveHostname on a bench program -- instead of disabling it by hand in the AB task editor. Overrides the implicit arming done by watchdogTimeMs. |
| `watchdogSensitivity` | number | no | int, positive | Watchdog sensitivity: the number of consecutive cycles that must exceed the timeout before the watchdog trips (AC500 V3 default 1). |
| `priority` | number | no | int, min 0, max 31 | Task priority (0 = highest, 31 = lowest on AC500 V3). |
| `stackSizeBytes` | number | no | int, positive | Stack size in bytes. Required when a library has large STRING(N) buffers that overflow the default ~128KB stack; common bump is 262144 (256KB). |
| `kind` | 'cyclic' \| 'freewheeling' \| 'event' \| 'status' \| 'externalevent' | no |  | Kind of task (KindOfTask). cycleTimeMs applies to cyclic tasks. |
| `addPous` | string[] | no |  | Programs to add to the task's call list (skipped if already called), e.g. ['WEB_PRG']. |

## shutdown_codesys

Shut down the persistent CODESYS instance.

No parameters.

## start_stop_application

Starts or stops the PLC application on the connected device.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `action` | 'start' \| 'stop' | yes |  | Action to perform. |

## uninstall_library_from_repository

Remove a library version from the CODESYS Library Repository. Pass '*' as version to remove ALL versions of the named library. Use after release iteration to clean up superseded versions (e.g. uninstall v1.0.5 once v1.0.10 is installed and validated). Matches the EXACT library title (case-insensitive) -- 'McpProbeLib' never touches 'McpProbeLib2' -- or a full display string. Every removal is read back: a library still installed afterwards fails with ERR_WRITE_DID_NOT_STICK. ERR_LIB_NOT_FOUND lists the versions that ARE installed (or similar titles).

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `libraryName` | string | yes | min 1 | Library title (e.g. 'NexoMqttLib') or the full display string ('NexoMqttLib, 1.0.10 (NEXO)'). Case-insensitive, exact title. |
| `version` | string | yes | min 1 | Version string to uninstall (e.g. '1.0.10') or '*' for all versions. |
| `repositoryName` | string | no |  | Optional repository name (e.g. 'System', 'User'). If omitted, matches across all repositories. |

## write_variable

Writes a value to a variable in the running PLC application. Must be connected first.

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `projectFilePath` | string | yes |  | Path to the project file. |
| `variablePath` | string | yes |  | Variable path (e.g., 'PLC_PRG.bMotorRunning'). |
| `value` | string | yes |  | Value to write (e.g., 'TRUE', '42', '3.14'). |

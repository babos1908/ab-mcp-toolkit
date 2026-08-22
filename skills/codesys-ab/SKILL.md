---
name: codesys-ab
description: Use when working with ABB Automation Builder 2.9 (CODESYS V3.5 SP19) PLC projects. Triggered by mentions of "automation builder", "AB 2.9", "codesys", ".project file", "POU" (Program/FunctionBlock/Function), "GVL", "DUT", "ladder/ST/FBD", "compile project", "PLC code", "AC500", "IEC 61131", or by paths under AutomationBuilder/Projects. Use also when the user asks to open/edit/create/build a CODESYS project, read POU code, search IEC code, manage libraries, or interact with the AC500 device tree. Do NOT use for unrelated topics (web dev, generic Python, etc.).
---

# CODESYS / Automation Builder 2.9 — Workflow Skill

Skill operativa per pilotare AB 2.9 / CODESYS V3.5 SP19 dall'MCP server `codesys-persistent` (fork `ab-mcp-toolkit` con patch ABB-specific). Dà per scontato che la macchina sia già configurata (vedi "Setup macchina" in fondo, e `ONBOARDING.md` nel repo per il setup completo); copre il workflow: aprire/leggere/editare/compilare progetti, gestire library e device tree AC500.

## ⚠️ Marker di attivazione (OBBLIGATORIO)

**La PRIMA volta che questa skill viene attivata in una sessione**, devi aprire la tua risposta con la riga esatta:

```
📡 codesys-ab skill attiva — workflow AB 2.9.
```

Una sola volta per sessione (o dopo `shutdown_codesys`). Serve all'utente per verificare a colpo d'occhio che la skill sia stata effettivamente caricata. Non ripetere il marker nelle risposte successive della stessa sessione.

## ⚠️ UINT/USINT underflow in FOR loop bounds (silent → AccessViolation)

I tipi unsigned IEC 61131-3 (`UINT`, `USINT`, `UDINT`, `BYTE`, `WORD`) wrappano in underflow **senza trap**. Un FOR come

```iec
FOR ui := 0 TO (uiLen - keyLen - 3) DO   // operandi UINT
```

diventa `*EXCEPTION* [AccessViolation]` quando `uiLen < keyLen + 3`: la sottrazione wrappa a ~65530, il loop itera 65k volte oltre il buffer. **Il compilatore NON avverte.**

**Regola**: ogni FOR bound (o array index) della forma `a - b` o `a - b - c` con operandi unsigned richiede una guardia esplicita PRIMA del loop:

```iec
IF uiLen < (keyLen + 3) THEN
    RETURN;
END_IF;
FOR ui := 0 TO (uiLen - keyLen - 3) DO ...
```

Stesso pattern per `uiPos - 1`, `_uiLen - 1`, ecc. (Caso reale 2026-05-14: parser JSON, payload corto + chiave di 4 char → `0-4-3` underflow → AccessViolation a runtime. Fix = guardia di 3 righe.)

## Stato note importanti

- **Edizione**: verificare la licenza attiva sulla macchina (Standard vs Premium). Differenze pratiche: `attach_codesys` richiede `Tools → Scripting → Execute Script File…` (Premium); `run_static_analysis` richiede l'add-on Code Analysis (Premium). Tutto il resto (project/POU/compile/library/device tree) funziona da Standard in su.
- **Modalità**: `launch_codesys` (l'MCP spawna AB visibile) per il lavoro normale. `attach_codesys` (Premium) quando l'utente vuole guidare lui la GUI — utile per coesistenza umano+Claude su una sola istanza, zero lock conflict.
- **NON aprire AB manualmente prima del MCP** se lavori in `launch_codesys` mode: il watcher non riesce ad acquisire il lock se la GUI utente lo tiene.
- **keep-alive + adoption**: con `--keep-alive` nella config, AB sopravvive ai recycle del server MCP e il `launch_codesys` successivo **adotta** l'istanza viva ("Adopted the already-running CODESYS instance") invece di fare cold start.
- **Cold start AB**: ~2 minuti (CPU + cache .NET + plugin ABB). È normale, non è un bug.
- **Tool MCP**: prefisso `mcp__codesys-persistent__`. Caricare schema via `ToolSearch select:` solo on-demand. `get_mcp_version()` lista le patch attive — controllalo **prima** di assumere che serva un workaround per un bug (potrebbe essere già fissato).

### ⭐ Premium — cosa si sblocca

Passando a Premium si abilitano **2 cose già costruite**:

1. **`attach_codesys` diventa percorribile** → il menu `Tools → Scripting → Execute Script File…` esiste. Diventa la **modalità raccomandata su macchina condivisa**: l'utente apre e guida la sua AB, l'MCP si attacca; `force_reset_watcher` NON gli killa la GUI. Zero contesa. (Su Standard non è possibile.)
2. **`run_static_analysis` produce finding veri** → ma SOLO se un **rule set SA è configurato** nel progetto (Project Settings → Static Analysis). Setup una-tantum in GUI sul template, poi ogni compile ha SA nel loop. Senza rule set torna solo il summary "0 findings".

**Online ops**: Premium **non** cambiava nulla storicamente (stesso `Stack empty`) — ma dal 2026-06-29 c'è un fix portato non ancora verificato che potrebbe cambiare il quadro su entrambe le edition. Vedi la sezione "Online / runtime" più sotto: è lì che sta lo stato aggiornato, non qui.

## Workflow base (sempre questo ordine)

1. **Status check** — `get_codesys_status`. Se già `state: ready`, salta al punto 3.
2. **Launch** — `launch_codesys`. ~2 min al primo avvio della giornata (o istantaneo se adotta un AB vivo con keep-alive). Se ritorna error o `Mode: headless`: `shutdown_codesys` → ri-`launch_codesys`.
3. **Open project** — `open_project(filePath)`. Path assoluto. La prima volta su un progetto può eccedere il timeout client; se vedi `Command timed out`, il watcher **sta comunque completando**: richiamare lo stesso `open_project` — sarà istantaneo perché AB l'ha caricato in memoria.
4. **Operate** — read/edit/create/compile/search.
5. **Save** — la maggior parte dei tool che modificano salvano da soli; `save_project` per sicurezza prima di chiudere.
6. **End** — `shutdown_codesys` solo se richiesto o per liberare risorse. Altrimenti AB resta su tra interazioni.

## Tool catalog (75 tool)

Elenco completo e sempre aggiornato: `docs/TOOL-CATALOG.md` nel repo (auto-generato a ogni build, non può andare stale). Qui sotto il sottoinsieme che serve conoscere a memoria, con i caveat.

### Lifecycle / status
- `launch_codesys(projectFilePath?)` → spawna AB visibile + watcher (o adotta un'istanza viva con keep-alive). Il `projectFilePath` opzionale attiva l'**owner-guard**: adotta solo una sessione che ha aperto quel progetto (o nessuno) — mai l'AB di un altro agente su un progetto diverso.
- `shutdown_codesys()` → chiude AB controllatamente.
- `get_codesys_status()` → state (`stopped` | `launching` | `ready` | `stalled` | `error`), mode, pid, **heartbeat age**. State `stalled` = watcher muto da >30s (worker morto o primary thread deadlockato) → `force_reset_watcher`.
- `force_reset_watcher()` → recovery quando l'MCP è "locked": kill AB + cleanup IPC + relaunch in un solo step (~10-30s vs ~30-60s di shutdown+launch manuale). **NON salva il progetto** (stato unknown se il watcher è locked → rischio corruzione).
- `diagnose_mcp_state()` → diagnostic read-only: state, heartbeat age, profondità coda comandi, orphan result count, contenuto di `watcher_error.txt` + interpretazione testuale. Usa **PRIMA** di `force_reset_watcher` per verificare che il reset serva davvero (e non sia un'operazione lunga in corso).
- `get_mcp_version()` → JSON con mcpVersion, buildSha e lista delle patch attive nel fork.
- `get_server_log(lines?)` → coda del `--log-file`: marker di lifecycle (`detachKeepAlive` / `Force-killing` / `soft-probe` / `cause=`). È il modo per capire perché AB si è chiusa.
- `list_ab_sessions()` → tutte le sessioni AB vive: pid, heartbeat age, progetto aperto, `isMine`. Da usare su macchina condivisa prima di toccare qualcosa.
- `attach_codesys(confirm?)` → **Premium-only**. Flusso 2-step: chiamata senza `confirm` → ritorna un path `watcher.py`; l'utente lo esegue da `Tools → Scripting → Execute Script File…`; seconda chiamata con `confirm=true`.

### Project
- `open_project(filePath)` → apre `.project` esistente. Lock-aware retry: se trova un `.lock` orfano con PID morto lo rimuove e ritenta.
- `close_project(projectFilePath, force?)` → chiude il progetto corrente (salva prima, a meno di `force=true`). **Critico nel workflow library dev**: senza, lo switch lib↔consumer richiede shutdown+launch (~30-60s); con `close_project` è <5s.
- `create_project(filePath, templatePath?, templateName?)` → nuovo progetto. `templatePath` = copia un `.project` esistente; `templateName` = istanzia un template registrato nel Template Manager di CODESYS (necessario per i template installati da package, che non hanno un `.project` free-standing su disco). Senza nessuno dei due, prova ad auto-scoprire `Standard.project`.
- `list_project_templates()` → enumera i template noti (API ScriptEngine + scan filesystem), così sai quale dei due argomenti passare a `create_project`.
- `create_ac500_project(newProjectPath, templateProjectPath, addLibraries?, overwrite?)` → bootstrap di un nuovo progetto AC500 V3 copiando un template esistente (es. un progetto vanilla del target). Preserva il device tree esatto. `addLibraries` separato da **`;`** (non virgole: collidono coi nomi delle lib).
- `save_project(projectFilePath)` / `create_project_archive(projectFilePath, archivePath?, ...)`.
- `clean_project(projectFilePath, alsoEvictPrecompileCache?)` → clean + cancella `.precompilecache` / `.compileinfo` / `.bootinfo`. Usa quando il compile sembra stale (cache che mente).
- `inspect_project_tree(projectFilePath, includeSymbols?)` → JSON strutturato: devices, libraries (con versione), POU, GVL, DUT, task, folder. Sostituisce 3 round-trip.
- `get_project_info` / `set_project_info(version?, title?, author?, company?, description?)` → campi Project Information. Sblocca il version bump automatico nelle release.
- `cleanup_backups(...)` → spazza i `<file>.backup-<TS>Z` lasciati da sessioni vecchie. Cancella **solo** file che matchano esattamente quel pattern; i `<name>.backup` manuali non vengono mai toccati.

### Read / Search
- `get_object_code(projectFilePath, objectPath)` → declaration + implementation di **UN SOLO** oggetto (POU/DUT/GVL/Method/Property). **Preferiscilo sempre** quando sai cosa cercare: `get_all_pou_code` scarica l'intero progetto.
- `get_all_pou_code(projectFilePath)` → dump bulk di tutti gli oggetti. Primo strumento di esplorazione su progetto sconosciuto, non per leggere una GVL.
- `search_code(projectFilePath, pattern, regex?, caseSensitive?, ...)` → regex/literal su tutti i corpi testuali; ritorna `path:line:col`.
- `find_references(projectFilePath, symbol, ...)` → riferimenti a un simbolo.
- `get_pou_dependency_graph(projectFilePath, rootPOU?)` → call graph diretto FB/Function/Method. Con `rootPOU='PLC_PRG'` annota `isDeadCode` sui POU non raggiungibili — **risolve il mistero "il compile non vede il typo"**.
- `get_all_pou_code_offline` / `search_code_offline` → varianti pure-Node che bypassano AB. **Richiedono un export PLCopen XML** (il `.project` nativo è binario); inutili sul file binario diretto.
- `export_project_to_plcopen_xml(projectFilePath, outputXmlPath, ...)` → wrap di `project.export_plcopenxml(...)`. Su alcune build l'API non è esposta: in quel caso la via di lettura è `get_object_code`/`get_all_pou_code`.

### CRUD POU / Code units
- `create_pou(projectFilePath, name, type, language, parentPath, returnType?)`
  - `type`: `Program` | `FunctionBlock` | `Function` | `Interface` | `ParameterList`
  - **Function richiede `returnType`** (es. `"BOOL"`, `"STRING"`, `"INT"`). Senza, errore a livello handler.
  - **`Interface`** crea un contratto OOP astratto (solo signature); i metodi si aggiungono dopo con `create_method`.
  - **`ParameterList`** — **CAVEAT**: su AB 2.9 Standard la creazione da scripting empiricamente **non funziona** (`PouType.ParameterList` non è nell'enum esposto dall'IronPython ScriptEngine e nessun `create_parameterlist*` è sul parent). Il tool prova una cascade di nomi candidati + fallback enum e, se fallisce, ritorna un errore descrittivo con l'attempt log. **Workaround**: creare il POU a mano in AB UI (`Add Object → Parameter List`), poi popolarlo con `set_pou_code(..., declaration=...)`. Lettura e populate funzionano una volta che il POU esiste.
- `set_pou_code(projectFilePath, pouPath, declaration?, implementation?)` → modifica il codice. Fa **read-back verification**: se la scrittura non attacca fallisce con `ERR_WRITE_DID_NOT_STICK` invece di riportare un falso successo.
- `create_method(parentPouPath, name|methodName, returnType?, ...)` / `create_property` / `create_dut` / `create_gvl` / `create_folder`.
- `delete_object(objectPath)` / `rename_object(objectPath, newName)` / `rename_symbol(oldName, newName, ...)` (refactor).
- **Path forms accettate ovunque** (uniformate su tutti i tool): full-from-root `Application/MyPOU`; folder/leaf `MyLib/Function Blocks/FB_X[/Method]`; **bare leaf univoco** `FB_X` (anche metodi nested). Se il nome è ambiguo l'errore lo dice esplicitamente.

### Build
- `compile_project(projectFilePath)` → sincrono, ritorna `N error(s), M warning(s)`. Supporta sia `.project` (compila l'Application via `clean()` + `build()` + `generate_code()`) sia `.library` (Pool Objects via `check_all_pool_objects()`). **Category scan**: enumerazione dinamica UNION i 3 GUID hardcoded delle categorie compile (Build / Precompile / Additional code checks), più re-enumerazione DOPO il build — critico sui library project dove l'enumerazione dinamica può ritornare solo "Script Messages" e nascondere errori C0418/C0046 reali.
- `get_compile_messages(projectFilePath)` → ultimi messaggi cached (nessun nuovo build). Stessa logica di category scan; funziona anche sui library project.
- `run_static_analysis(projectFilePath)` → **Premium**. Esegue la Static Analysis e ritorna i finding. 0 finding se nessun rule set è configurato in Project Settings. **Non** usa l'export SARIF (apre un dialog modale che deadlocka il watcher).
- `create_boot_application(projectFilePath, outputAppPath, writeVisuFiles?)` → genera `.app` + `.crc` deployabile, **offline, senza PLC**. Lancia `generate_code()` prima, così l'immagine è aggiornata. Verificato su AB 2.9 SP19 (215KB `.app` + `.crc`).

### Libraries
- `list_project_libraries(projectFilePath)` → riferimenti correnti.
- `add_library(projectFilePath, libraryName, version?, ...)` → nome **fully-qualified**, es. `'Pm, 1.2.11.4 (ABB)'`.
- `remove_library(projectFilePath, libraryName)` → rimuove un **riferimento** dal Library Manager (via `get_libraries(recursive)`, perché su AB 2.9 i riferimenti non sono figli enumerabili). Rifiuta i riferimenti di sistema (prefisso `#`).
- `install_library_to_repository(libraryProjectFilePath, repositoryName?)` → installa il `.library` corrente nel Library Repository (equivale a "File → Save Project and Install into Library Repository"). **Critico nel library dev**: senza, i consumer continuano a vedere la versione precedente. Stesso nome+versione → overwrite; altrimenti installazione side-by-side.
- `list_library_repository(nameFilter?)` / `uninstall_library_from_repository(libraryName, version, repositoryName?)` (`version='*'` per tutte).
- `get_library_parameters(projectFilePath, libraryName?)` → JSON dei Library Parameters (VAR_GLOBAL CONSTANT overridabili dal consumer): name, value, defaultValue, **isOverridden**, type, comment. **Risolve il classico "consumer vede valore stale"**.
- `set_library_parameter` / `reset_library_parameter` / `export_library_parameters` / `import_library_parameters`.
- `set_library_reference_version(projectFilePath, libraryName, version)` → pin/update della versione di un riferimento. ⚠️ **Su Standard l'enumerazione può tornare 0 children** (limite scripting): workflow alternativo = bump version nella lib + `install_library_to_repository` + riferimento a `*` che floata sull'ultima.
- `rebuild_library(libraryProjectFilePath, regenerateCompiledArtifacts?)` → clean + `check_all_pool_objects` + tentativo di rigenerare gli artifact compilati. Su Standard la regen artifact spesso fallisce con `ERR_API_NOT_EXPOSED` (warning soft: il rebuild del source funziona).
- `release_library_version(libraryProjectFilePath, version, distFolder?, gitTag?, ghRelease?)` → orchestratore: set_project_info → rebuild → install → copia in distFolder → opzionale git tag + gh release.
- `diff_library_versions(sourceLibraryPath, targetLibraryPath)` → diff strutturato tra 2 versioni **da XML** (no AB). Per i `.library` nativi (binari) usa `diff_libraries_via_export`.
- `diff_libraries_via_export(sourceLibraryPath, targetLibraryPath, xmlOutputDir?, keepXml?)` → composite: apre lib A → export XML → chiude; idem lib B; diff. ~30-90s perché fa round-trip su AB due volte.

### Task Configuration (AC500)
- `get_task_configuration(projectFilePath)` → Task Configuration node + task figli con cycle time, priority, watchdog, stack size correnti.
- `set_task_parameter(projectFilePath, taskName, cycleTimeMs?, watchdogTimeMs?, priority?, stackSizeBytes?)` → modifica le property di un task. Use case: bump dello stack a 256KB quando una lib con buffer `STRING(32767)` causa stack overflow (~133KB vs 128KB di default). Lo stack può non essere settabile a livello task su AC500 V3 (sta su Device.parameter): il tool walka l'ancestry e ritorna un hint se serve `set_device_parameter`.

> **Nota AC500 V3**: l'attributo `interval` di un task è una **stringa** con un literal IEC TIME (`'t#10ms'`), **non** un `TimeSpan`. Scriverci un TimeSpan viene accettato senza errore ma è un **no-op silenzioso** (il PLC continua col vecchio ciclo). Il tool ora scrive il literal e fa read-back.

### Device tree (AC500 / drives / IO)
- `list_device_repository()` → device installabili (con probing esteso di nome/vendor/categoria/descrizione).
- `inspect_device_node(projectFilePath, nodePath)` → dettagli nodo: device identification, connector/channel, mapped_variable.
- `add_device(projectFilePath, parentPath, deviceName, deviceType, ...)` → risoluzione del DeviceID dal repository. Sentinelle: `__update__:<path>` per swap in-place di un device preservando l'Application (validato PM5650→PM5670), `__root__` per add top-level.
- `set_device_parameter(projectFilePath, devicePath, parameterName, value)`.
- `map_io_channel(projectFilePath, channelPath, variableName, ...)` → grammatica `[iface:]<paramId>[/<bit>]` sui channel di `connector.host_parameters`.

### Online / runtime — ⚠️ FIX PORTATO 2026-06-29, NON ANCORA VERIFICATO su questa build

**Storico (confermato empiricamente più volte, Standard E Premium, attach mode incluso)**: gli online ops via scripting davano SEMPRE `Stack empty` da `se.online.create_online_application`, edition-independent, nessun accessor di riuso della sessione UI. La `OnlineManager` (`se.online`) esponeva **un solo metodo**: `create_online_application`, che falliva con `RuntimeError: Stack empty.` perché lo stack di selezione dell'IDE non è popolato da un contesto script. **Nessun** accessor alternativo esisteva: `target_app` ha solo `create_call/get_call/is_active_application/set_active_application` (niente `online_application`), il device node `PLC_AC500_V3` non ha attributi online, `se.online` non ha metodi reuse/observe. Riusare una sessione UI Login era impossibile. Tutti questi tool fallivano con `ERR_ONLINE_STACK_EMPTY`: `connect_to_device`, `get_application_state`, `read_variable`, `write_variable`, `monitor_variables`, `download_to_device`, `start_stop_application`, `disconnect_from_device`.

**Novità 2026-06-29**: trovato un fix indipendente su `luke-harriman/Codesys-MCP` (commit `a063aad`) con **la stessa diagnosi di causa** scritta qui (stack IDE-interno popolato solo dal dispatcher comandi dell'IDE, bypassato dalle chiamate IPC) — due progetti diversi, stessa scoperta. Il fix: reflection sul campo privato `_executor` di `se.online` per invocare `ExecuteSource()`, che fa scattare l'evento giusto. **Portato in questo fork** (`with_executor()` in `ensure_online_connection.py`, applicato a tutti i tool online). Verificato da upstream su **CODESYS V3 SP16 Patch 5, hardware ifm** — vendor e service pack diversi da AB 2.9/SP19/AC500.

- Se la reflection fallisce su questa build → degrada a chiamata diretta = comportamento identico allo storico sopra (stesso `ERR_ONLINE_STACK_EMPTY`). **Il porting non può peggiorare nulla.**
- Se la reflection funziona → i tool online potrebbero funzionare per la prima volta. Da verificare su PLC reale prima di fidarsi.

**Tool interessati** (tutti passano da `with_executor`): `connect_to_device`, `get_application_state`, `read_variable`, `write_variable`, `monitor_variables`, `download_to_device`, `start_stop_application`. (`disconnect_from_device` non toccato — resta il limite noto.)

⚠️ **`write_variable` ora usa `set_prepared_value` + `force_prepared_values`** (i metodi `write_value`/`write` non esistono su `IScriptOnlineApplication` da SP14 in poi). `force_prepared_values` **FORZA** la variabile: resta forzata finché non la sforzi. Non usarlo su variabili critiche senza saperlo.

**Se testi e funziona**: aggiorna questa sezione — il workaround mixed-mode qui sotto diventa opzionale invece che obbligatorio.
**Se testi e NON funziona**: comportamento identico allo storico, nessuna sorpresa — usa il workaround.

**Workaround mixed-mode (ancora lo standard finché non c'è verifica)**:
- **MCP**: project prep + compile + library release (`set_pou_code`, `compile_project`, `release_library_version`, `install_library_to_repository`…) — funzionano perfettamente
- **AB UI**: `Online → Login` + Download + Watch panel per osservazione/controllo runtime
- **Out-of-band**: per smoke test automatizzati, parla col PLC tramite il suo protocollo applicativo (MQTT, OPC UA, Modbus, HTTP) invece che via scripting

**Utili comunque**: `set_credentials`, `set_simulation_mode` — settano valori nel progetto, non richiedono sessione online.

> **Nota attach mode**: `attach_codesys` aveva un bug che uccideva la sessione attached entro ~5s (l'health monitor controllava un PID che in attach mode è `null` by design → falso "process died"). Corretto con un flag `attached` che salta il check PID-based (in attach mode la liveness è data solo dall'heartbeat). Attach mode è utile per pilotare i **tool offline** dentro una GUI gestita dall'utente (zero lock conflict).

### Static Analysis (Code Analysis) — Premium

Confermato empiricamente su Premium: la Static Analysis si può **sia lanciare sia leggere** via scripting (il tool `run_static_analysis` fa esattamente questo). Dettagli utili se devi debuggarlo o estenderlo:

- ✅ **Trigger**: comando `Run Static Analysis` (`se.system.commands`, guid `ae97b6f4-dc9a-480e-aac8-6061e684f3c0`, tokens `('staticanalysis','run')`) — è uno `ScriptCommand`, `.execute()` gira senza errori.
- ✅ **Read-back**: i messaggi finiscono nella categoria **"Additional code checks"**, guid **`220493a1-f49b-4416-9a3f-a545db707cbe`**, leggibili con `se.system.get_message_objects(System.Guid('220493a1-...'))`. Stesso identico plumbing di `compile_project`.
- ⚠️ **Caveat rule-set**: su un progetto senza rule set SA attivo il read-back ritorna solo la riga di summary, 0 violazioni — perché non ci sono regole abilitate, **non** perché il canale non funzioni.
- ❌ **SARIF export**: il comando `Run Static Analysis and export to Sarif file` (guid `aaaaaaaa-0e82-46ef-baec-b2deae722d28`) ha `execute(*stBatchArguments)` variadico, MA eseguirlo **apre un dialog Save-As modale sul primary thread → deadlocka il watcher** (heartbeat stallato, serve force_reset). **NON headless-safe.** Usa il read-back via categoria, mai il SARIF.

> **Message API note (utile in generale)**: `se.system.get_message_objects(category)` e `clear_messages(category)` vogliono un `System.Guid`, **non** una stringa. Categorie viste su un progetto AC500 V3: Script Messages `194b48a9`, Build `97f48d64`, Precompile `217bc73e`, Memory Usage `ee56da69`, AC500 V3 Configuration `d761e059`, Additional code checks (= Static Analysis) `220493a1`.

## Pattern ricorrenti

### Esplorare un progetto sconosciuto
```
1. open_project(path)
2. inspect_project_tree(path)     # struttura: device, lib, POU, task
3. get_all_pou_code(path)         # architettura SW (se serve tutto)
   oppure get_object_code(path, 'Application/X')   # lettura chirurgica
4. list_project_libraries(path)   # dipendenze
5. (se serve) search_code(...)    # trovare punti specifici
```

### Function POU che ritorna stringa
```
create_pou(name="GetMsg", type="Function", language="ST",
           parentPath="Application", returnType="STRING")
set_pou_code(pouPath="Application/GetMsg",
             implementation="GetMsg := 'value';")
```

Se ottieni `ValueError: ... Parameter name: return_type`, l'MCP attivo è la versione npm pubblica senza la patch. Fallback semantico:
```
create_pou(name="GetMsgFB", type="FunctionBlock", language="ST", parentPath="Application")
set_pou_code(pouPath="Application/GetMsgFB",
  declaration="FUNCTION_BLOCK GetMsgFB\nVAR_OUTPUT\n  result : STRING;\nEND_VAR",
  implementation="result := 'value';")
# uso: instanzia, chiama, leggi .result
```

### Compilazione + diagnosi errori
```
result = compile_project(path)     # "Compilation complete... N error(s), M warning(s)"
if N > 0:
    msgs = get_compile_messages(path)
# dettaglio completo su disco: %TEMP%\codesys-mcp-compile-debug.txt
```

### Workflow release library v1.0.x
```
1. set_project_info(libPath, version='1.0.11')
2. rebuild_library(libPath)
3. install_library_to_repository(libPath)
4. (nel consumer) reset_library_parameter(...) per eventuali override stale
5. (nel consumer) compile_project + download
# Tutto in uno step:
release_library_version(libPath, '1.0.11', distFolder='./dist', gitTag=true)
```

### Diff fra 2 versioni library (`.library` è binary!)
```
# I .library sono in formato binario CODESYS: diff_library_versions DA SOLO
# non funziona su quelli. Due strade:

# A) Composite (una chiamata, ~30-90s):
diff_libraries_via_export(
    sourceLibraryPath='dist/v1.0.5/MyLib-v1.0.5.library',
    targetLibraryPath='dist/v1.0.10/MyLib-v1.0.10.library')

# B) Manuale in due step (se l'XML ti serve anche per altro):
export_project_to_plcopen_xml('dist/v1.0.5/lib.library', 'dist/v1.0.5/lib.xml')
export_project_to_plcopen_xml('dist/v1.0.10/lib.library', 'dist/v1.0.10/lib.xml')
diff_library_versions('dist/v1.0.5/lib.xml', 'dist/v1.0.10/lib.xml')
```

### Debugging "il consumer vede un valore stale" della library
```
# Sintomo: edit lib v1.0.x → install → consumer compile → a runtime il vecchio valore.
# Root cause #1 (la più comune): override parametro stale lato consumer.
get_library_parameters(consumerPath, 'MyLib')
# Cerca isOverridden=true con value != defaultValue → è quello.
reset_library_parameter(consumerPath, 'MyLib', 'GC_MAX_TAG_DEFINITIONS')
# Root cause #2: cache del repo stale → list_library_repository per confermare la versione installata.
# Root cause #3: cache di compile stale → clean_project(consumerPath).
```

### Path conventions
- I tool accettano tre forme: full-from-root (`Application/MyPOU`), folder/leaf (`MyLib/Function Blocks/FB_X/Method`), leaf univoco (`FB_X`). Se ambiguo → errore pulito che lo dice.
- `parentPath: "Application"` → fuzzy-match interno che tenta `Application`, `<projectName>.Application`, `PLC_AC500_V3/Plc Logic/Application`, ecc. Copre la stragrande maggioranza dei casi.
- Se la risoluzione fallisce: usa il path esatto stampato da `inspect_project_tree` / `get_all_pou_code`.
- Separatore sempre `/`.

### Naming consigliato
- Programmi: `<Modulo>_PRG`
- FunctionBlock: `FB_<Nome>`
- Function: `<Verbo><Oggetto>` (es. `GetMsg`, `CalcChecksum`)
- GVL: `GVL_<scope>` (es. `GVL_IO`, `GVL_Recipe`)
- DUT: `ST_<Nome>` (struct) · `E_<Nome>` (enum)

## Stile commenti (regola permanente)

Commenti **minimi ed essenziali**. **NIENTE tag di versione nei commenti** (`v1.1`/`v1.2`…): la storia sta in git. Scrivi solo ciò che il codice NON dice: il *perché* non ovvio, le trappole hardware, gli invarianti. Quando tocchi un POU con vecchi commenti versione-taggati, **rimuovili nello stesso commit**. Vale anche per i commit message.

## Performance / aspettative

| Operazione | Cold | Warm |
|---|---|---|
| `launch_codesys` | ~120s | istantaneo (adopt con keep-alive) |
| `open_project` (primo) | 60-180s | <5s |
| `get_all_pou_code` (medio) | 5-15s | 5-15s |
| `get_object_code` | <5s | <5s |
| `compile_project` (vuoto) | ~10s | ~5s |
| `compile_project` (reale) | dipende dal progetto | più veloce |
| `search_code` (medio) | <5s | <5s |

**Timeout su `open_project`**: aspetta ~30s e richiama lo stesso comando (warm → istantaneo). Non è un fallimento: il watcher sta lavorando.

## Troubleshooting

| Sintomo | Causa | Azione |
|---|---|---|
| `Watcher did not signal ready within Xms` | AB più lenta del `--ready-timeout-ms` configurato | `shutdown_codesys` → `launch_codesys`. Se ricorre: bumpare il flag nella registrazione MCP. |
| `Command ... timed out after Xms` | Operazione più lenta del `--timeout` IPC | Richiama lo stesso comando: il watcher ha completato, ora è warm. Se ricorre su comandi specifici: bumpare `--timeout`. |
| `launch_codesys` dice "successful" ma poi `state: launching`, PID N/A | Adozione di una session dir stale (watcher crashato, o GUI lanciata a mano in chiusura: lascia `ready.signal` ma non risponde) | Fissato: ora c'è un live-probe prima di adottare e il launch verifica `ready` prima di dichiarare successo. Se persiste: `force_reset_watcher`. |
| `selected project is currently in use by 'X' on 'Y'` | Lock conflict: un'altra AB (utente o altro agente) tiene quel progetto | Chiudere quella AB, o lavorare su un progetto diverso. Vedi "Istanza condivisa". |
| State `stalled`, heartbeat vecchio | Watcher worker morto o primary thread deadlockato (raro dopo il prompt-handling guard) | `diagnose_mcp_state` per confermare → `force_reset_watcher` (~10-30s). |
| MCP "locked" ma AB visivamente attiva, nessun dialog | Spesso AB è **occupata**, non morta (classico: una sessione online interattiva monopolizza il primary thread) | Il soft-probe ri-lancia il timeout invece di killare AB sotto l'utente. Aspettare, non forzare. |
| AB "si chiude da sola" su recycle sessione | Lifetime accoppiata al processo MCP | Usare `--keep-alive`. Diagnosi: `get_server_log` → cercare `cause=`. Nessun marker = kill del job-object OS (non intercettabile) → su Premium usare attach mode. |
| `Mode: headless` dopo un launch "successful" | Fallback auto-launch nascosto | `shutdown_codesys` → `launch_codesys`. |
| `Parent object not found for path: X` | Path non risolto | Vedi "Path conventions". Se ambiguo l'errore lo dice; altrimenti `inspect_project_tree` per il path esatto. |
| AB resta zombie dopo un errore | Spawn detached senza cleanup | `Stop-Process -Name AutomationBuilder -Force` **solo** se confermato orfano via `get_codesys_status`. |
| `Cannot add an object because it affects a device you are currently logged into` | Una sessione online attiva blocca le modifiche strutturali | Chiedere all'utente `Online → Logout` dall'AB UI. **Non** aspettarsi che `disconnect_from_device` funzioni sulle sessioni aperte dalla UI. |
| `disconnect_from_device` ritorna OK ma AB è ancora online | La sessione online creata dalla UI non è raggiungibile via scripting | Chiedere sempre `Online → Logout` all'utente. Il tool è affidabile **solo** se il login era stato fatto via `connect_to_device`. |
| `ERR_ONLINE_STACK_EMPTY` | Vedi la sezione "Online / runtime" | Non ritentare a caso: o il fix portato funziona su questa build, o si usa il workaround mixed-mode. |
| `compile_project` ritorna `0 error(s)` ma l'UI mostra errori syntax-level (`C0046 Identifier not defined`) | **CODESYS non analizza i POU fuori dal call graph.** Un typo in una `FUNCTION` leaf mai invocata dà "Build complete -- 0 errors". L'UI mostra l'errore col linter live, che è un canale separato. | Non è un bug dell'MCP. Per testare il path-errore, iniettare il typo in **codice raggiungibile** da `PLC_PRG`. `get_pou_dependency_graph(rootPOU='PLC_PRG')` mostra il dead code. Verifica in `%TEMP%\codesys-mcp-compile-debug.txt`. |
| `ERR_WRITE_DID_NOT_STICK` / `ERR_RESET_DID_NOT_STICK` / `ERR_RENAME_DID_NOT_STICK` | Il read-back ha rilevato che la scrittura non ha attaccato | **È il sistema che funziona**: prima questi casi passavano silenziosamente e si scoprivano sul PLC. Il messaggio riporta valore atteso vs letto. |

### Diagnostica `compile_project` su disco

Lo script di compile mirrora ogni `print()` in `%TEMP%\codesys-mcp-compile-debug.txt` (riscritto a ogni run). Contiene: lista delle categorie di message scansionate, istogramma severity per categoria, output testuale del compilatore (`Build complete -- N errors, M warnings`), eventuali WARN. Quando un compile dà risultati strani, quel file dà il quadro completo senza restart dell'MCP.

## CmpCrypto — RSA signature verify (AC500, HW-validated)

RSASSA-PKCS#1 v1.5 + SHA-256 su AC500 (CmpCrypto 3.5.18.0). Tre trappole (return code: `20` = algoritmo grezzo, `1` = chiave grezza, `0` = OK):

1. **L'algoritmo è lo SCHEMA, non la primitiva**: `CryptoGetAlgorithmById(RtsCryptoID.RSA_PKCS1_V15_SHA256, 0)`. Lo schema hasha e padda internamente. Passare `RtsCryptoID.RSA` grezzo → `code=20`.
2. **La chiave va IMPORTATA**: `CryptoImportAsymmetricKey(data := bsDerKey (SPKI DER), xBase64 := FALSE, xPrivateKey := FALSE, pKey := ADR(ck))`. Passare il DER grezzo in un `byteString` → `code=1`.
3. **Il dato è il MESSAGGIO grezzo, non il digest**: `CryptoSignatureVerify(hAlgo, ADR(bsMessage), ck, ADR(bsSig))` → `0` = OK. Argomenti **posizionali**: la forma con argomenti nominati rompe il parser su SP19.

base64url → mappare `-_` → `+/` e ri-paddare prima di `FC_Base64Decode`.

**Doc ufficiale su disco** (leggerla PRIMA di indovinare le firme): `C:\ProgramData\AutomationBuilder\AB_LibDoc_2.9\System\<Lib>\<ver>\en\`.

## ABB AC500 V3 — hardware FBs (libreria `Pm`)

Il target `PLC_AC500_V3` espone una libreria nativa **`Pm`** (vendor ABB, versione corrente `1.2.11.4`) per parlare con i servizi firmware del PLC fisico. Si aggiunge con `add_library` usando il nome qualificato **`Pm, 1.2.11.4 (ABB)`**.

**Quirk namespace**: la libreria NON dichiara un namespace `Pm.` — gli FB sono esposti direttamente nello scope globale. Si scrive `PmRealtimeClockDT`, **non** `Pm.PmRealtimeClockDT` (il prefisso dà `Unknown type` al compile). Solo gli FB di MQTT Client SL hanno un vero namespace `MQTT.`.

Doc su disco: `C:\ProgramData\AutomationBuilder\AB_LibDoc_2.9\ABB\Pm\1.2.11.4\Default\...\pmrealtimeclock.html`.

### FB principali (testati end-to-end su AB 2.9 / AC500 V3 SP19, PM5650)

| Elemento | Tipo | Cosa fa |
|---|---|---|
| `PmRealtimeClockDT` | FUNCTION_BLOCK EXTENDS `AbbLConC3` | RTC del PLC in formato `DATE_AND_TIME`. Input `Enable`, `Set`, `DTSet`. Output `Busy`, `Error`, `ErrorID`, **`DTAct : DATE_AND_TIME`**. Chiamala ogni scan con `Enable := TRUE, Set := FALSE` e leggi `DTAct`. Non bloccante. |
| `PmRealtimeClock` | FUNCTION_BLOCK | Stessa cosa ma con campi separati `HourAct`, `MinAct`, `SecAct`, `YearAct (WORD)`, `MonAct`, `DayAct`, `WDayAct`. Usalo quando ti servono solo gli orari e non vuoi spendere un `DT_TO_STRING`. Per **scrivere** l'RTC serve un fronte su `Set` — vedi il caveat sotto. |
| `PmProdRead` | FUNCTION_BLOCK EXTENDS `AbbETrig3` | Legge i factory data del PLC. Input `Execute` (fronte di salita). Output `Done/Busy/Error/ErrorID` + `IdentNum`, `IndexNum`, `CpuType`, **`ManuFactDate : STRING(4)`** (formato YWWY), `BaInst`, `FactoryId`, **`ManuFactYear : STRING(2)`**, **`SerialNum : STRING(8)`**, `Mac0`/`Mac1`, `ProductId`. Sostituisce serial/model hardcoded in qualunque struct di configurazione. |
| `PmVersion` | FUNCTION : STRING(255) | Versioni firmware multi-linea (display FW, update FW, boot FW, preproduction FW, system FW, flash FW). Delimiter di riga `$R$N`. |
| `PmSysTime` | FUNCTION : DWORD | System tick (ms). Per timing sub-secondo e delta. |

### ⚠️ Caveat — i Pm FB sono edge-triggered

Tutti i Pm FB che compiono un'**azione** richiedono un **fronte di salita** sul trigger (`Set`/`Execute`) con `Enable` TRUE. Un trigger costantemente TRUE **non ri-arma**. E disabilitare nella stessa scan in cui vedi `NOT Busy` **aborta** l'operazione.

**Anti-pattern** (sembra corretto, il write RTC non avviene mai):
```iec
IF GVL_Status.xRtcSetRequested THEN
    fbRtcSet(Enable := TRUE, Set := TRUE, ...);   // BAD: mai un edge pulito
    IF NOT fbRtcSet.Busy THEN
        fbRtcSet(Enable := FALSE, Set := FALSE);  // ABORT prematuro
    END_IF;
END_IF;
```

**Pattern corretto** — state machine multi-scan:
`IDLE → PRIME (Enable=TRUE, Set=FALSE, 1 scan) → TRIGGER (Set=TRUE, edge pulito) → WAIT_BUSY (tieni Set=TRUE, dwell ≥3 scan + watchdog 3s) → FINISH (cleanup ordinato) → IDLE`.

Razionale: il PRIME garantisce l'edge FALSE→TRUE; il dwell di 3 scan difende dal completamento single-scan (`Busy` 0→1→0 invisibile); `Enable := FALSE` solo in FINISH perché alcuni driver valutano `Enable` prima dell'edge-detect.

**HW finding (PM5650)**: i flag `Busy`/`Error` di `PmRealtimeClock` sono **inaffidabili sul set** — lo `Set` committa ma `Busy` può non scendere, o `Error` alzarsi spurio. **Decidi il successo RILEGGENDO il clock** (`PmRealtimeClockDT.DTAct` sopra una soglia plausibile), non dai flag.

### Pattern: timestamp UTC reale (ISO-8601)

Sequenza canonica per stampare datapoint con tempo reale (sostituisce placeholder tipo `1970-01-01T00:00:00.000Z`):

```iec
// 1) In un FB chiamato ogni scan:
VAR
    fbRtc : PmRealtimeClockDT;
END_VAR

// 2) Body, PRIMA di qualsiasi short-circuit/RETURN:
fbRtc(Enable := TRUE, Set := FALSE);
IF NOT fbRtc.Error THEN
    GVL_AppTime.dtNow := fbRtc.DTAct;
    IF fbRtc.DTAct > DT#2024-01-01-00:00:00 THEN
        GVL_AppTime.xRtcValid := TRUE;  // gate anti-1970
    END_IF;
END_IF;

// 3) In una function tipo FC_FormatTimestamp:
sRaw  := DT_TO_STRING(GVL_AppTime.dtNow);         // 'DT#YYYY-MM-DD-HH:MM:SS'
sDate := MID(STR := sRaw, LEN := 10, POS := 4);   // 'YYYY-MM-DD'
sTime := MID(STR := sRaw, LEN := 8,  POS := 15);  // 'HH:MM:SS'
sOut  := CONCAT(sDate, 'T');
sOut  := CONCAT(sOut, sTime);
sOut  := CONCAT(sOut, '.000Z');
```

**CAVEAT**: `PmRealtimeClockDT.DTAct` legge l'RTC hardware. Se la batteria CMOS è morta o l'RTC non è mai stato settato in factory, esce `DT#1970-01-01-00:00:00`. Soluzioni: settarlo da AB UI (`Device → Files → Set Clock`) oppure configurare SNTP a runtime (la libreria `Pm` ha una cartella `SNTP Diagnosis`; il device node ha anche un tab `NTP` per server e offset TZ). Marcare `xRtcValid := TRUE` **solo** dopo aver visto un DT plausibile (> 2024), per non spedire a valle orari del 1970.

### Pattern: identità factory dal PLC (kill hardcoded values)

Wrap di `PmProdRead` (async, `Execute` su fronte) + `PmVersion` (function sincrona) in un FB che espone tutto come output latchati:

```iec
FUNCTION_BLOCK FB_PlcIdentity
VAR_OUTPUT
    xReady           : BOOL := FALSE;
    sSerialNumber    : STRING(8);
    sModel           : STRING(14);
    sManufactureDate : STRING(4);   // YWWY: decade + week + year-in-decade
    sFirmwareVersion : STRING(16);  // parsato dalla riga "System FW:"
    sMacAddress      : STRING(17);
    sFirmwareFull    : STRING(255); // blob PmVersion grezzo, per debug/audit
END_VAR
VAR
    fbProd : PmProdRead;
    iState : INT := 0;
END_VAR

CASE iState OF
0: fbProd(Execute := TRUE); iState := 1;
1:
    fbProd(Execute := TRUE);
    IF fbProd.Done THEN
        sSerialNumber    := fbProd.SerialNum;
        sModel           := fbProd.CpuType;
        sManufactureDate := fbProd.ManuFactDate;
        sMacAddress      := fbProd.Mac0;
        sFirmwareFull    := PmVersion(Enable := TRUE);
        sFirmwareVersion := ExtractSystemFw(sFull := sFirmwareFull);
        xReady := TRUE;
        fbProd(Execute := FALSE);
        iState := 2;
    ELSIF fbProd.Error THEN
        iState := 99;
    END_IF;
2: ;  // latched
END_CASE;
END_FUNCTION_BLOCK
```

**Caller pattern** (in `PLC_PRG`):
```iec
fbId();
IF NOT fbId.xReady THEN
    RETURN;  // PmProdRead è async: aspetta la prossima scan
END_IF;
stMachineConfig.sSerialNumber    := fbId.sSerialNumber;
stMachineConfig.sModel           := fbId.sModel;
stMachineConfig.sManufactureDate := fbId.sManufactureDate;
stMachineConfig.sFirmwareVersion := fbId.sFirmwareVersion;
```

**ExtractSystemFw** — parsing per estrarre la versione "System FW" dal blob multi-linea di `PmVersion`:
```iec
METHOD PRIVATE ExtractSystemFw : STRING(16)
VAR_INPUT
    sFull : STRING(255);
END_VAR
VAR
    uiPos, uiCrlfPos : INT;
    sTail : STRING(64);
END_VAR
uiPos := FIND(STR1 := sFull, STR2 := 'System FW:');
IF uiPos = 0 THEN RETURN; END_IF;
sTail := MID(STR := sFull, LEN := 64, POS := uiPos + 11);  // oltre 'System FW: '
uiCrlfPos := FIND(STR1 := sTail, STR2 := '$R');
IF uiCrlfPos > 0 THEN
    ExtractSystemFw := LEFT(STR := sTail, SIZE := uiCrlfPos - 1);
ELSE
    ExtractSystemFw := sTail;  // nessun CR trovato
END_IF;
END_METHOD
```

`'$R'` è l'escape IEC 61131-3 per CR (0x0D), `'$N'` per LF (0x0A). `FIND` opera byte per byte, quindi trova il carattere letterale.

Formato `ManuFactDate` ABB = **YWWY**: decade-digit + WW (01-53) + year-in-decade. Es. `'2325'` = decade 2 (`202x`), settimana 32, anno 5 → 2025 W32.

### Lib `Pm` correlate non ancora testate

`Boot project`, `Data storage`, `Device State`, `Display`, `EcoResetFRAM`, `LED control`, `Reboot`, `SNTP Diagnosis` — FB target-specific utili (reset PLC, retain su FRAM, diagnostica NTP) non ancora coperti. Documentare qui quando vengono usati.

## Quando NON usare questa skill

- Lettura puramente statica di un `.project` per parsing dati → meglio export PLCopen XML + parser locale (più veloce, no AB).
- CI build server senza display → potenzialmente serve `--mode headless` (UX peggiore ma adatto).
- Task generici di programmazione (Python, web, ecc.) — non pertinenti.

## Setup macchina

Setup completo, troubleshooting esteso e sync con upstream: **`ONBOARDING.md` nel repo**. In sintesi, MCP registrato a user scope:

```
codesys-persistent: codesys-mcp-persistent
  --codesys-path "C:\Program Files\ABB\AB2.9\AutomationBuilder\Common\AutomationBuilder.exe"
  --codesys-profile "Automation Builder 2.9"
  --mode persistent
  --no-auto-launch
  --keep-alive                 # AB sopravvive ai recycle del server MCP
  --ready-timeout-ms 600000    # default 60s: troppo poco, AB cold-boota in ~120s
  --timeout 600000             # default 60s: troppo poco per il primo open_project
  --backup-retention 5
  --log-file <path>            # marker di lifecycle, leggibili via get_server_log
```

Source: fork `babos1908/ab-mcp-toolkit` (pubblico), `main` contiene tutte le patch. La lista autoritativa delle patch attive è `get_mcp_version()` a runtime, o il manifest `MCP_PATCHES` in `src/server.ts`.

Replica su un'altra macchina:
```powershell
git clone https://github.com/babos1908/ab-mcp-toolkit.git $env:USERPROFILE\Documents\GitHub\ab-mcp-toolkit
cd $env:USERPROFILE\Documents\GitHub\ab-mcp-toolkit
powershell -ExecutionPolicy Bypass -File .\setup-codesys-mcp.ps1
```
(lo script auto-detecta il path di AB, fa install/build/link, registra l'MCP a user scope e installa questa skill). Dopo: riavviare Claude Code — gli schema dei tool si fissano all'avvio.

Modifiche ai soli script IronPython in `src/scripts/` sono **template-side**: attive dopo `npm run build`, senza restart. Tool nuovi o parametri nuovi richiedono il restart.

## Estensione con pattern di progetto

Questa SKILL.md (la versione nel repo) contiene pattern **generici** ABB AC500 / CODESYS. Per pattern specifici di un progetto (struct, GVL, naming privati) aggiungi una sezione `## Project-specific patterns` in coda al **tuo** `~/.claude/skills/codesys-ab/SKILL.md` locale. Quel file resta sulla tua macchina, non viene committato e non viene sovrascritto da `setup-codesys-mcp.ps1` (lo script copia solo se il file locale non esiste).

## Convenzioni di interazione

- **Lingua**: l'utente preferisce italiano. Risposte in italiano salvo richiesta diversa.
- **Verbosity**: messaggi di stato concisi. Su comandi lunghi (es. `launch_codesys` cold) avvisare che ci vorranno ~2 min.
- **Azione vs domanda**: in modalità auto, eseguire. Chiedere conferma SOLO su operazioni irreversibili o ambigue (`delete_object` su nodo non-test, modifiche a progetto di produzione, `download_to_device` su PLC reale).
- **Mai aprire AB manualmente** in nome dell'utente in launch mode. Sempre via `launch_codesys`.
- **Mai chiudere AB con `Stop-Process`** se non c'è un orfano effettivo (verificato con `get_codesys_status`).
- **Istanza condivisa**: se un altro agente o un'altra sessione sta usando AB sulla stessa macchina (`list_ab_sessions` per vederlo), NON contendere lo stesso `.project` e non killare processi AB non propri. Su Premium, attach mode è la modalità più sicura in questo scenario.

---
name: codesys-ab
description: Use when working with ABB Automation Builder 2.9 (CODESYS V3.5 SP19) PLC projects. Triggered by mentions of "automation builder", "AB 2.9", "codesys", ".project file", "POU" (Program/FunctionBlock/Function), "GVL", "DUT", "ladder/ST/FBD", "compile project", "PLC code", "AC500", "IEC 61131", or by paths under AutomationBuilder/Projects. Use also when the user asks to open/edit/create/build a CODESYS project, read POU code, search IEC code, manage libraries, or interact with the AC500 device tree. Do NOT use for unrelated topics (web dev, generic Python, etc.).
---

# CODESYS / Automation Builder 2.9 — Workflow Skill

Skill operativa per pilotare AB 2.9 / CODESYS V3.5 SP19 dall'MCP server `codesys-persistent` (fork `ab-mcp-toolkit` con patch ABB-specific). Dà per scontato che la macchina sia già configurata (vedi sezione "Setup macchina" in fondo); copre 100% del workflow utente: aprire/leggere/editare/compilare progetti.

## ⚠️ Marker di attivazione (OBBLIGATORIO)

**La PRIMA volta che questa skill viene attivata in una sessione**, devi aprire la tua risposta con la riga esatta:

```
📡 codesys-ab skill attiva — workflow AB 2.9.
```

Una sola volta per sessione (o dopo `shutdown_codesys`). Serve all'utente per verificare a colpo d'occhio che la skill sia stata effettivamente caricata. Non ripetere il marker nelle risposte successive della stessa sessione.

## Stato note importanti

- **Edition**: AB 2.9 **Standard**. NON Premium → `Tools → Scripting → Execute Script File…` non esiste, quindi `attach_codesys` (modalità "tu apri AB, io mi attacco") **non è praticabile**.
- **Conseguenza**: si usa SEMPRE `launch_codesys` (MCP spawna AB visibile).
- **NON aprire AB manualmente prima del MCP**: il watcher headless non riesce ad acquisire il lock se la GUI utente lo tiene.
- **Cold start AB**: ~2 minuti (CPU + cache .NET + plugin ABB). È normale, non è un bug.
- **Tutti i tool MCP** hanno prefisso `mcp__codesys-persistent__`. Caricare schema via `ToolSearch select:` solo on-demand.

## Workflow base (sempre questo ordine)

1. **Status check** — `get_codesys_status`. Se già `state: ready`, salta al punto 3.
2. **Launch** — `launch_codesys`. Blocca ~2 min al primo avvio della giornata, poi è warm. Se ritorna error/fallback `Mode: headless`: `shutdown_codesys` → ri-`launch_codesys`.
3. **Open project** — `open_project(filePath)`. Path assoluto. Prima volta su un progetto può eccedere il timeout client (la patch locale lo porta a 600s ma 60s era il default in alcune build); se vedi `Command timed out after 60000ms` significa che il watcher ce la sta facendo da solo: **richiamare `open_project`** una seconda volta — sarà istantanea perché AB l'ha caricato in memoria.
4. **Operate** — read/edit/create/compile/search.
5. **Save** — la maggior parte dei tool che modificano salvano da soli; `save_project` per sicurezza prima di chiusura.
6. **End** — `shutdown_codesys` se l'utente lo chiede o se vuoi liberare risorse. Altrimenti AB resta su tra interazioni della stessa sessione Claude.

## Tool catalog (40 tool, raggruppati)

### Lifecycle / status
- `launch_codesys()` → spawna AB visibile + watcher, persistent mode.
- `shutdown_codesys()` → chiude AB controllatamente.
- `get_codesys_status()` → state (`stopped` | `launching` | `ready` | `error`), mode, pid.
- `attach_codesys(confirm?)` → **NON utilizzabile su Standard**. Premium-only.

### Project
- `open_project(filePath)` → apre `.project` esistente.
- `create_project(filePath)` → da template Standard.project. ⚠️ Path template hardcoded può non funzionare su AB; preferire copia di un template manuale + `open_project`.
- `save_project(projectFilePath)` → salva.
- `create_project_archive(projectFilePath, archivePath?, ...)` → archive `.projectarchive`.

### Read / Search
- `get_all_pou_code(projectFilePath)` → bulk dump declaration+implementation di **tutti** POU/Method/Property/DUT/GVL. **Primo strumento di esplorazione**.
- `search_code(projectFilePath, pattern, regex?, caseSensitive?, ...)` → regex/literal across tutti corpi testuali; ritorna `path:line:col`.
- `find_references(projectFilePath, symbol, ...)` → riferimenti a un simbolo.
- Resource template: `codesys://project/{path}/structure` per albero gerarchico.
- Resource template: `codesys://project/{path}/pou/{pou_path}/code` per leggere POU singola.

### CRUD POU / Code units
- `create_pou(projectFilePath, name, type, language, parentPath, returnType?)`
  - `type`: `Program` | `FunctionBlock` | `Function` | `Interface`
  - **Function richiede `returnType`** (es. `"BOOL"`, `"STRING"`, `"INT"`). Senza, errore handler-level.
  - **`Interface`** crea un contratto OOP astratto (solo signature). Niente implementazione. I metodi si aggiungono dopo via `create_method`. Su build CODESYS senza `PouType.Interface` esposto, il tool ritorna un errore descrittivo.
- `set_pou_code(projectFilePath, pouPath, declaration?, implementation?)` → modifica codice.
- `create_method(projectFilePath, parentPouPath, name, returnType?, ...)`.
- `create_property(projectFilePath, parentPouPath, name, propertyType, ...)`.
- `create_dut(projectFilePath, name, parentPath, ...)`.
- `create_gvl(projectFilePath, name, parentPath, ...)`.
- `create_folder(projectFilePath, name, parentPath)`.
- `delete_object(projectFilePath, objectPath)`.
- `rename_object(projectFilePath, objectPath, newName)`.
- `rename_symbol(projectFilePath, oldName, newName, ...)` → refactor.

### Build
- `compile_project(projectFilePath)` → sincrono, ritorna `N error(s), M warning(s)`. Supporta sia **`.project`** standard (compila l'Application via `clean()` + `build()` + `generate_code()`) sia **`.library`** (Pool Objects via `check_all_pool_objects()` o fallback iterativo su `get_children`).
- `get_compile_messages(projectFilePath)` → ultimi messaggi cached (no nuovo build).

### Libraries
- `list_project_libraries(projectFilePath)` → riferimenti correnti.
- `add_library(projectFilePath, libraryName, version?, ...)`.

### Device tree (AC500 / drives / IO)
- `list_device_repository()` → device installabili.
- `inspect_device_node(projectFilePath, nodePath)` → dettagli nodo.
- `add_device(projectFilePath, parentPath, deviceName, deviceType, ...)`.
- `set_device_parameter(projectFilePath, devicePath, parameterName, value)`.
- `map_io_channel(projectFilePath, channelPath, variableName, ...)`.

### Online / runtime (richiede PLC raggiungibile)
- `connect_to_device(projectFilePath, devicePath, ...)`.
- `set_credentials`, `set_simulation_mode`.
- `disconnect_from_device`, `get_application_state`.
- `read_variable`, `write_variable`, `monitor_variables`.
- `download_to_device`, `start_stop_application`.

## Pattern ricorrenti

### Esplorare un progetto sconosciuto
```
1. open_project(path)
2. get_all_pou_code(path)         # capire architettura SW
3. list_project_libraries(path)   # capire dipendenze
4. (se serve) search_code(...)    # trovare punti specifici
```

### Function POU che ritorna stringa
```
create_pou(name="GetMsg", type="Function", language="ST",
           parentPath="Application", returnType="STRING")
set_pou_code(pouPath="Application/GetMsg",
             implementation="GetMsg := 'value';")
```

### Workaround se Function non funziona (versione npm pubblica con bug)
Sintomo: `ValueError: ... Parameter name: return_type`. Vuol dire che il MCP installato è la versione npm pubblica senza la patch locale. Fallback semantico:
```
create_pou(name="GetMsgFB", type="FunctionBlock", language="ST", parentPath="Application")
set_pou_code(pouPath="Application/GetMsgFB",
  declaration="FUNCTION_BLOCK GetMsgFB\nVAR_OUTPUT\n  result : STRING;\nEND_VAR",
  implementation="result := 'value';"
)
# uso: instanzia, chiama, leggi .result
```

### Compilazione + diagnosi errori
```
result = compile_project(path)
# ritorno: "Compilation complete... N error(s), M warning(s)"
if N > 0:
    msgs = get_compile_messages(path)   # dettaglio per debug
```

### Path conventions
- `parentPath: "Application"` → fuzzy-match interno tenta `Application`, `<projectName>.Application`, `<projectName>/Application`, `PLCWinNT/Plc Logic/Application`, `PLC_AC500_V3/Plc Logic/Application`. Funziona nella stragrande maggioranza dei casi.
- Se la fuzzy-match fallisce: usa il path esatto visto in `get_all_pou_code` output (es. `PLC_AC500_V3/Plc Logic/Application`).
- `pouPath` (per `set_pou_code`, `delete_object`, ecc.) usa `/` come separatore: `Application/MyFB/MyMethod`.

### Naming consigliato
- POU programmi: `<Modulo>_PRG`
- FunctionBlock: `<Nome>FB` o senza suffisso
- Function: `<Verbo><Oggetto>` (es. `GetMsg`, `CalcChecksum`)
- GVL: `GVL_<scope>` (es. `GVL_IO`, `GVL_Recipe`)
- DUT: `T_<Nome>` o `<Nome>_t`

## Performance / aspettative

| Operazione | Cold | Warm |
|---|---|---|
| `launch_codesys` | ~120s | n/a (already running) |
| `open_project` (primo) | 60-180s | <5s |
| `get_all_pou_code` (medio) | 5-15s | 5-15s |
| `compile_project` (vuoto) | ~10s | ~5s |
| `compile_project` (reale) | dipende dal progetto | dipende |
| `search_code` (medio) | <5s | <5s |

**Importante**: il primo `open_project` di una sessione può scadere il client a 60s anche se la patch locale lo porta a 600s — perché la versione attiva del MCP è quella partita all'avvio Claude Code, e quindi se è la npm pubblica il default rimane 60s. **Risposta giusta a un timeout su `open_project`**: aspettare 30s poi richiamare lo stesso `open_project` (warm cache → istantaneo).

## Troubleshooting

| Sintomo | Causa | Azione |
|---|---|---|
| `State: error, Last Error: Watcher did not signal ready within Xms` | AB più lenta del `--ready-timeout-ms` configurato | `shutdown_codesys` → riprova `launch_codesys`. Se ricorre: bumpare `--ready-timeout-ms` nella registrazione MCP. |
| `Command ... timed out after 60000ms waiting for result` | Operazione + lenta del IPC `--timeout` | Richiama lo stesso comando: il watcher avrà completato e l'operazione (es. open_project) è ora warm. Se ricorre su comandi specifici: bumpare `--timeout` nella registrazione. |
| `selected project is currently in use by 'X' on 'Y'` | Lock conflict (utente ha aperto AB manualmente) | Chiudi quella AB. Usa SOLO `launch_codesys`. |
| `Specified argument was out of the range of valid values. Parameter name: return_type` (su Function) | Versione npm pubblica senza patch locale | Workaround FB con VAR_OUTPUT, oppure verificare che il MCP punti al fork patchato. |
| `Mode: headless` dopo `launch_codesys` "successful" | Auto-launch fallback nascosto | `shutdown_codesys` → `launch_codesys`. |
| `Parent object not found for path: X` | Fuzzy-match ha fallito | Eseguire `get_all_pou_code` e usare il path esatto stampato. |
| AB resta zombie dopo errore | Detached spawn senza cleanup | `Stop-Process -Name AutomationBuilder -Force` (o Task Manager). |
| `Cannot add an object because it affects a device you are currently logged into` (su `create_pou`/`set_pou_code`/`create_method`/`delete_object` o `compile_project`) | Una sessione online attiva blocca le modifiche structural alla configurazione device | Chiedi all'utente di fare `Online → Logout` dall'AB UI. **Non chiamare `disconnect_from_device` aspettandoti che funzioni** — vedi sotto. |
| `disconnect_from_device` ritorna OK ma AB è ancora online | Limite **inherent** della scripting API di CODESYS V3.5 SP19 Standard edition (la sessione online creata dall'UI non è raggiungibile via `script_engine.online.create_online_application`, e `system.commands` non espone il menu `Online.Logout` su Standard) | Chiedi sempre all'utente di fare `Online → Logout` dall'AB UI prima di operazioni che richiedono PLC offline. Il tool MCP è un no-op affidabile **solo** quando già si era loggati via `connect_to_device` MCP. |
| `compile_project` ritorna `0 error(s)` ma AB UI mostra errori syntax-level (es. `C0046 Identifier 'X' not defined`) | **CODESYS non analizza POU non chiamati nel call graph.** Un typo in una `FUNCTION` leaf mai invocata produce "Build complete -- 0 errors" dal compilatore. L'UI mostra l'errore via il linter live (syntax-level, separato dal compile). Il MCP riporta correttamente quello che il compilatore dice. | Non è un bug del MCP. Per testare il path-errore, iniettare il typo in **codice raggiungibile** (PLC_PRG o un FB chiamato dall'application attiva). Verifica con `%TEMP%\codesys-mcp-compile-debug.txt` (mirror diagnostic): cerca la riga `Build complete -- N errors, M warnings`. |

### Diagnostica `compile_project` su disco

Lo script di compile mirroris ogni `print()` a `%TEMP%\codesys-mcp-compile-debug.txt` (overwritten ogni run). Contiene: lista delle 6 categorie di message scansionate, istogramma severity per categoria, output testuale del compilatore (`Build complete -- N errors, M warnings`), eventuali WARN. Quando un compile sembra dare risultati strani, leggere quel file dà il quadro completo senza restart MCP né tornare al sorgente.

## ABB AC500 V3 — hardware FBs (`Pm` library)

Il target `PLC_AC500_V3` espone una libreria nativa **`Pm`** (vendor ABB, versione corrente `1.2.11.4`) per parlare con i servizi firmware del PLC fisico. La aggiungi al progetto con `add_library` usando il nome qualificato **`Pm, 1.2.11.4 (ABB)`** (formato fully-qualified, come per `MQTT Client SL`).

**Quirk namespace**: la libreria NON dichiara un namespace `Pm.` — gli FB sono esposti direttamente nello scope globale. Quindi si scrive `PmRealtimeClockDT` e non `Pm.PmRealtimeClockDT`. Provare il prefisso prima dà `ERROR: Unknown type: 'Pm.PmRealtimeClockDT'` al compile. Solo i FB della libreria MQTT Client SL hanno un vero namespace `MQTT.`.

### FB principali (testati end-to-end su AB 2.9 / AC500 V3 SP19)

| Elemento | Tipo | Cosa fa |
|---|---|---|
| `PmRealtimeClockDT` | FUNCTION_BLOCK EXTENDS `AbbLConC3` | RTC del PLC in formato `DATE_AND_TIME`. Input `Enable`, `Set`, `DTSet`. Output `Busy`, `Error`, `ErrorID`, **`DTAct : DATE_AND_TIME`**. Chiamala ogni scan con `Enable := TRUE, Set := FALSE` e leggi `DTAct`. È non-bloccante. |
| `PmRealtimeClock` | FUNCTION_BLOCK | Stessa cosa ma con campi separati `HourAct`, `MinAct`, `SecAct`, `YearAct (WORD)`, `MonAct`, `DayAct`, `WDayAct`. Usalo quando ti servono solo orari (es. operatori in UI) e non vuoi spendere `DT_TO_STRING`. |
| `PmProdRead` | FUNCTION_BLOCK EXTENDS `AbbETrig3` | Legge factory data del PLC. Input `Execute` (rising edge). Output `Done/Busy/Error/ErrorID` + `IdentNum`, `IndexNum`, `CpuType`, **`ManuFactDate : STRING(4)`** (formato YWWY), `BaInst`, `FactoryId`, **`ManuFactYear : STRING(2)`**, **`SerialNum : STRING(8)`**, `Mac0`/`Mac1`, `ProductId`. Sostituisce hardcoded serial/model in qualunque struct di configurazione. |
| `PmVersion` | FUNCTION : STRING(255) | Firmware version multi-line (display FW, update FW, boot FW, preproduction FW, system FW, flash FW). Line delimiter `$R$N`. |
| `PmSysTime` | FUNCTION : DWORD | System ticks (ms). Per timing sub-secondo / deltas. |

### Pattern: timestamp UTC reale (ISO-8601)

Sequenza canonica per stampare datapoint con tempo reale (sostituisce eventuali placeholder come `1970-01-01T00:00:00.000Z`):

```iec
// 1) In un FB chiamato ogni scan, instance:
VAR
    fbRtc : PmRealtimeClockDT;
END_VAR

// 2) Body, BEFORE qualsiasi short-circuit/RETURN:
fbRtc(Enable := TRUE, Set := FALSE);
IF NOT fbRtc.Error THEN
    GVL_AppTime.dtNow := fbRtc.DTAct;
    IF fbRtc.DTAct > DT#2024-01-01-00:00:00 THEN
        GVL_AppTime.xRtcValid := TRUE;  // gate per fallback epoch
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

**CAVEAT importante**: `PmRealtimeClockDT.DTAct` legge l'hardware RTC del PLC. Se la CMOS-battery è morta o non è mai stata settata in factory, il DT esce `DT#1970-01-01-00:00:00` → niente di reale. Soluzioni:
1. Settare l'RTC manualmente da AB UI: `Device → Files → Set Clock`, o
2. Configurare SNTP a runtime (libreria `Pm` ha cartella `SNTP Diagnosis`; il device IDE node ha anche un tab `NTP` per server NTP + offset TZ).

Mark `xRtcValid := TRUE` solo dopo aver visto un DT plausibile (es. > 2024) per non spedire al downstream orari del 1970 che lo confondono.

### Pattern: identità factory dal PLC (kill hardcoded values)

Wrap `PmProdRead` (async, rising-edge Execute) + `PmVersion` (sync function) in un FB che espone tutto come outputs latchati. Pattern di riferimento:

```iec
FUNCTION_BLOCK FB_PlcIdentity
VAR_OUTPUT
    xReady           : BOOL := FALSE;
    sSerialNumber    : STRING(8);
    sModel           : STRING(14);
    sManufactureDate : STRING(4);   // YWWY: decade + week + year-in-decade
    sFirmwareVersion : STRING(16);  // parsed from "System FW:" line
    sMacAddress      : STRING(17);
    sFirmwareFull    : STRING(255); // raw PmVersion blob for debug/audit
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

**Caller pattern** (in PLC_PRG):

```iec
fbId();
IF NOT fbId.xReady THEN
    RETURN;  // PmProdRead is async; wait for next scan
END_IF;
// Now safe to copy into your config struct and enable the client
stMachineConfig.sSerialNumber    := fbId.sSerialNumber;
stMachineConfig.sModel           := fbId.sModel;
stMachineConfig.sManufactureDate := fbId.sManufactureDate;
stMachineConfig.sFirmwareVersion := fbId.sFirmwareVersion;
```

**ExtractSystemFw** — parsing trick per estrarre la versione "System FW" dal blob multi-linea di `PmVersion`:

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
sTail := MID(STR := sFull, LEN := 64, POS := uiPos + 11);  // skip past 'System FW: '
uiCrlfPos := FIND(STR1 := sTail, STR2 := '$R');
IF uiCrlfPos > 0 THEN
    ExtractSystemFw := LEFT(STR := sTail, SIZE := uiCrlfPos - 1);
ELSE
    ExtractSystemFw := sTail;  // no CR found
END_IF;
END_METHOD
```

Nota: `'$R'` è l'escape IEC 61131-3 per CR (0x0D); `'$N'` per LF (0x0A). `FIND` opera byte-per-byte, quindi trova il carattere letterale.

Format `ManuFactDate` ABB = **YWWY**: decade-digit + WW(01-53) + year-in-decade. Es. `'2325'` = decade 2 (`202x`), week 32, year 5 → 2025 W32.

### Lib trovate ma non ancora testate

`Boot project`, `Data storage`, `Device State`, `Display`, `EcoResetFRAM`, `LED control`, `Reboot`, `SNTP Diagnosis` — useful target-specific FBs (reset PLC, FRAM retain, NTP diag) non ancora coperti in questa skill. Documenta quando li wirerete.

## Quando NON usare questa skill

- Lettura puramente statica di un `.project` per parsing dati → meglio export PLCopen XML + parser locale (più veloce, no AB).
- CI build server senza display → potenzialmente serve `--mode headless` (UX peggio ma adatto). Documentazione separata.
- Tasks generici di programmazione (Python, web, ecc.) — non pertinenti.

## Setup macchina

MCP server registrato user-scope:
```
codesys-persistent: codesys-mcp-persistent
  --codesys-path "C:\Program Files\ABB\AB2.9\AutomationBuilder\Common\AutomationBuilder.exe"
  --codesys-profile "Automation Builder 2.9"
  --mode persistent
  --no-auto-launch
  --ready-timeout-ms 600000
  --timeout 600000
```

Source: fork `ab-mcp-toolkit` con patch ABB-specific. Patch incluse in `main`:
1. `--ready-timeout-ms` configurabile (CLI → LauncherConfig.readyTimeoutMs)
2. `attach_codesys` tool per Premium edition (non utilizzato su Standard)
3. `create_pou` Function `returnType` parameter
4. `--timeout` wirato a IpcClient.commandTimeoutMs
5. `compile_project` reale via `generate_code()` + clear_messages + filtro categoria/severity (vecchio script ritornava sempre 0 errori)

Per replicare su altra macchina, usare lo script `setup-codesys-mcp.ps1` nel repo:
```powershell
git clone https://github.com/babos1908/ab-mcp-toolkit.git C:\Users\<user>\Documents\GitHub\ab-mcp-toolkit
cd C:\Users\<user>\Documents\GitHub\ab-mcp-toolkit
powershell -File .\setup-codesys-mcp.ps1
# (lo script auto-detecta AB path, fa install/build/link, registra MCP user-scope, copia questa skill)
```

## Estensione con pattern di progetto

Questa SKILL.md (la versione nel repo `ab-mcp-toolkit`) contiene solo pattern **generici** ABB AC500 / CODESYS. Per pattern specifici del tuo progetto (struct, GVL, naming convention private), aggiungi una sezione `## Project-specific patterns` in coda al **tuo** `~/.claude/skills/codesys-ab/SKILL.md` locale. Quel file resta sulla tua macchina, non viene committato, non viene sovrascritto dal `setup-codesys-mcp.ps1` (lo script copia solo se il file locale non esiste).

## Convenzioni di interazione

- **Lingua**: l'utente preferisce italiano. Risposte in italiano salvo specifica richiesta.
- **Verbosity**: messaggi di stato concisi. Su comandi lunghi (es. `launch_codesys` cold), avvisare l'utente che ci vorranno ~2 min.
- **Azione vs domanda**: in modalità auto, eseguire. Chiedere conferma SOLO su operazioni irreversibili o ambigue (es. `delete_object` su nodo non-test, modifiche a progetto produzione, `download_to_device` reale).
- **Mai aprire AB manualmente** in nome dell'utente. Sempre via `launch_codesys`.
- **Mai chiudere AB con `Stop-Process`** se non c'è un orfano effettivo (verificato con `get_codesys_status`).

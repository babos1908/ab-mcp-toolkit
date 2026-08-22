# Onboarding — `ab-mcp-toolkit` (ABB Automation Builder MCP)

Setup e workflow di **`ab-mcp-toolkit`**, MCP server che permette a Claude Code (Anthropic) di pilotare ABB Automation Builder 2.9 / CODESYS V3.5 SP19. Fork con patch ABB-specific di [`luke-harriman/Codesys-MCP`](https://github.com/luke-harriman/Codesys-MCP) (binary upstream: `codesys-mcp-persistent`, mantenuto invariato per facilità di sync futuro).

Ultimo aggiornamento: 2026-07-02.

## TL;DR

- **Cosa fa**: 75 tool MCP per aprire `.project`/`.library`, leggere/creare/modificare POU, compilare, cercare nel codice, gestire library repository e release, device tree AC500, task configuration, static analysis, boot application, e (con riserva, vedi sotto) online ops verso il PLC.
- **Edition richiesta**: AB 2.9 **Standard** o superiore. Alcuni tool sono **Premium-only** (`attach_codesys`, `run_static_analysis`) — vedi tabella edition.
- **Architettura**: persistent UI — il MCP spawna AB visibile e ci comunica via file-based IPC (`.command.json` + script IronPython). Con `--keep-alive` AB sopravvive ai recycle del server MCP.
- **Trigger automatico**: la skill Claude Code `codesys-ab` si attiva su menzioni di "automation builder", "codesys", "POU", "compile", "AC500", ecc.

## Setup nuova macchina

**Prerequisiti**: Windows + AB 2.9 Standard (o superiore) installato e licenziato + Node.js 18+ + git + Claude Code installato (`claude` su PATH).

Il repo è **pubblico**: non serve autenticazione GitHub né `gh` CLI per clonare.

```powershell
# 1. Clone (main include tutte le patch)
git clone https://github.com/babos1908/ab-mcp-toolkit.git $env:USERPROFILE\Documents\GitHub\ab-mcp-toolkit
cd $env:USERPROFILE\Documents\GitHub\ab-mcp-toolkit

# 2. Setup one-shot (install + build + link + registra MCP + installa la skill)
powershell -ExecutionPolicy Bypass -File .\setup-codesys-mcp.ps1
```

Lo script: verifica prerequisiti → auto-detecta `AutomationBuilder.exe` → `npm install` + `npm run build` + `npm link` → registra l'MCP a **user scope** → copia `skills/codesys-ab/SKILL.md` in `~/.claude/skills/codesys-ab/` (**non sovrascrive** se già presente).

Se AB è in un path non standard, o il profilo ha un nome diverso (AB → `Tools → Profiles`):

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-codesys-mcp.ps1 -CodesysPath "D:\ABB\AB2.9\AutomationBuilder\Common\AutomationBuilder.exe" -CodesysProfile "Automation Builder 2.9"
```

### Verifica

```powershell
claude mcp list      # deve mostrare "codesys-persistent: ✓ Connected"
```

Poi **riavviare Claude Code** — gli schema dei tool si fissano all'avvio, quindi prima del restart i tool non compaiono. Test finale: prompt tipo *"apri Test.project e leggimi i POU"* → la prima risposta deve iniziare con `📡 codesys-ab skill attiva — workflow AB 2.9.`

### Registrazione manuale (se non usi lo script)

```powershell
claude mcp add -s user codesys-persistent -- codesys-mcp-persistent `
  --codesys-path "C:\Program Files\ABB\AB2.9\AutomationBuilder\Common\AutomationBuilder.exe" `
  --codesys-profile "Automation Builder 2.9" `
  --mode persistent `
  --no-auto-launch `
  --keep-alive `
  --ready-timeout-ms 600000 `
  --timeout 600000 `
  --backup-retention 5 `
  --log-file "$env:TEMP\codesys-mcp-server.log"
```

Flag che contano davvero:

| Flag | Perché |
|---|---|
| `--ready-timeout-ms 600000` | il default upstream è 60s; AB 2.9 cold-boot impiega ~120s → timeout prematuro |
| `--timeout 600000` | default 60s troppo stretto per il primo `open_project` di progetti pesanti |
| `--keep-alive` | AB sopravvive ai recycle/compact della sessione Claude Code; il `launch_codesys` successivo **adotta** l'istanza viva invece di fare cold start |
| `--no-auto-launch` | non spawnare AB all'avvio del server, solo su `launch_codesys` esplicito |
| `--backup-retention 5` | i tool distruttivi fanno snapshot `<file>.backup-<TS>Z`; senza retention si accumulano |
| `--log-file <path>` | i marker di lifecycle (`detachKeepAlive`/`Force-killing`/`cause=`) non sopravvivono su stderr sotto Claude Code CLI. Serve per diagnosticare "AB si è chiusa da sola". Leggibile via il tool `get_server_log`. |

## Daily usage

1. Apri Claude Code in una cartella di progetto AB
2. Prompt che menziona `.project`, `POU`, `compile`, `AC500`… → **la skill triggera**
3. Workflow standard:
   - `get_codesys_status` → se già `ready`, salta il launch
   - `launch_codesys` → AB visibile (cold ~2 min, adopt istantaneo con keep-alive)
   - `open_project` → carica il `.project` (se va in timeout: **richiamalo**, il watcher ha finito, ora è warm)
   - operazione (read/edit/compile/search/release)
   - `save_project` (molti tool salvano da soli)

## Tool disponibili

**75 tool**, prefisso `mcp__codesys-persistent__`. L'elenco completo con descrizioni è **auto-generato** in [`docs/TOOL-CATALOG.md`](docs/TOOL-CATALOG.md) a ogni `npm run build` — non può andare stale. Categorie:

- **Lifecycle**: `launch_codesys`, `attach_codesys`, `shutdown_codesys`, `get_codesys_status`, `force_reset_watcher`, `diagnose_mcp_state`, `get_mcp_version`, `get_server_log`, `list_ab_sessions`
- **Project**: `open_project`, `close_project`, `create_project`, `create_ac500_project`, `list_project_templates`, `save_project`, `clean_project`, `create_project_archive`, `inspect_project_tree`, `get_project_info`, `set_project_info`, `cleanup_backups`
- **Read/Search**: `get_object_code` (singolo oggetto — preferiscilo), `get_all_pou_code`, `search_code`, `find_references`, `get_pou_dependency_graph`, varianti `*_offline`, `export_project_to_plcopen_xml`
- **CRUD POU**: `create_pou`, `set_pou_code`, `create_method`, `create_property`, `create_dut`, `create_gvl`, `create_folder`, `delete_object`, `rename_object`, `rename_symbol`
- **Build**: `compile_project`, `get_compile_messages`, `run_static_analysis` (Premium), `create_boot_application`
- **Libraries**: `list_project_libraries`, `add_library`, `remove_library`, `install_library_to_repository`, `list_library_repository`, `uninstall_library_from_repository`, parametri (`get`/`set`/`reset`/`export`/`import`), `set_library_reference_version`, `rebuild_library`, `release_library_version`, `diff_library_versions`, `diff_libraries_via_export`
- **Task config (AC500)**: `get_task_configuration`, `set_task_parameter`
- **Device tree**: `list_device_repository`, `inspect_device_node`, `add_device`, `set_device_parameter`, `map_io_channel`
- **Online/runtime**: `connect_to_device`, `disconnect_from_device`, `get_application_state`, `read_variable`, `write_variable`, `monitor_variables`, `download_to_device`, `start_stop_application`, `set_credentials`, `set_simulation_mode` — ⚠️ vedi sotto

### Cosa richiede Premium

| Funzione | Standard | Premium |
|---|---|---|
| Tutti i tool offline (project/POU/compile/library/device) | ✅ | ✅ |
| `attach_codesys` (tu apri AB, l'MCP si attacca) | ❌ manca `Tools → Scripting → Execute Script File…` | ✅ **modalità raccomandata su macchina condivisa** |
| `run_static_analysis` | ❌ add-on Code Analysis assente | ✅ (findings reali solo se un rule set SA è configurato in Project Settings) |
| Online ops via scripting | ⚠️ vedi sotto | ⚠️ identico a Standard |

### ⚠️ Stato online ops (leggere prima di usarli)

Storicamente **tutti** gli online ops via scripting fallivano con `ERR_ONLINE_STACK_EMPTY` su AB 2.9/SP19, **indipendentemente dall'edition** (confermato empiricamente su Standard 2026-05-27 e su Premium in attach mode 2026-05-30): `se.online.create_online_application` dà `RuntimeError: Stack empty.` perché lo stack di selezione dell'IDE non è popolato da un contesto script, e non esiste nessun accessor per riusare una sessione UI Login.

**2026-06-29**: portato un fix da upstream (`a063aad`) che usa reflection sul campo privato `_executor` di `se.online` per invocare `ExecuteSource()` e popolare quello stack. Upstream l'ha verificato su **CODESYS V3 SP16 Patch 5, hardware ifm** — vendor e service pack diversi dai nostri. **Su AB 2.9/SP19/AC500 NON è ancora verificato.**

- Se la reflection non funziona su questa build → degrada a chiamata diretta = **identico comportamento di prima**, nessuna regressione possibile.
- Se funziona → gli online tool potrebbero funzionare per la prima volta.
- `write_variable` ora usa `set_prepared_value` + `force_prepared_values`: **forza** la variabile (resta forzata finché non la sforzi). Non usarlo su variabili critiche senza saperlo.

Finché non c'è una verifica su PLC reale, il **workaround mixed-mode resta lo standard**: MCP per prep/compile/library release, AB UI per Online→Login/Download/Watch, e protocollo applicativo del PLC (MQTT/OPC UA/Modbus/HTTP) per smoke test automatizzati.

## Patch nel fork (rispetto a luke-harriman upstream)

**73 patch** in `main`. L'elenco autoritativo con descrizione, root cause e data di validazione è nel manifest `MCP_PATCHES` in [`src/server.ts`](src/server.ts) ed è interrogabile a runtime:

```
get_mcp_version()   → mcpVersion + buildSha + lista completa delle patch attive
```

Usalo **prima** di assumere che serva un workaround per un bug: potrebbe essere già fissato.

Macro-aree delle patch:
- **Lifecycle/robustezza**: keep-alive + adoption, live-probe prima di adottare (niente adozione di sessioni morte), soft-probe prima del force-reset (non killare AB che è solo *occupata*), prompt-handling guard (i dialog modali non deadlockano più il watcher), teardown markers + `--log-file`, owner-guard multi-istanza.
- **"Lying success" eliminati**: 8 setter fanno read-back e falliscono forte se la scrittura non attacca (`set_pou_code`, `create_gvl`, `set_library_parameter`, `reset_library_parameter`, `map_io_channel`, `set_library_reference_version`, `rename_object`, `set_project_info`).
- **Fix AC500-specific validati sul campo**: task `interval` come literal IEC TIME (`t#100ms`, non TimeSpan), `get_project_info`/`list_project_libraries` via accessor callable, `remove_library` via `get_libraries(recursive)`, DeviceID resolution + swap device in-place, `map_io_channel` su host_parameters.
- **Compile reale**: `generate_code()` + `clear_messages` + merge forzato delle categorie Build/Precompile/Additional code checks (il vecchio script ritornava sempre `0 error(s)`).
- **Tooling**: catalogo tool auto-generato, error-code taxonomy, backup con retention+dedup.

### Rapporti con upstream

- **PR #3 mergiata upstream.** Il progetto è attivo, non abbandonato.
- I due branch storici (`feat/configurable-ready-timeout`, `fix/compile-project-generate-code-and-categories`) sono stati **cancellati il 2026-07-02**: il loro contenuto è in `main` da tempo e i branch erano solo rumore. `main` è l'unico branch del fork.
- Il 2026-06-29 sono stati integrati selettivamente 4 commit upstream (fix online executor, probing device repository, `create_project` dual-mode, `list_project_templates`). **Non** è stato portato `eval_python` (esecuzione IronPython arbitraria) — decisione esplicita: è espansione di capability, non un bug fix.

## Aggiornamenti / sync

**Su un clone fresco**, `origin` = `babos1908/ab-mcp-toolkit`. Per seguire anche l'upstream serve aggiungerlo:

```powershell
git remote add upstream https://github.com/luke-harriman/Codesys-MCP.git
git fetch upstream
git log --oneline main..upstream/main     # cosa c'è di nuovo da loro
```

Integrazione: **non** fare merge cieco. Il fork è molto divergente e diversi commit upstream sono ifm-specific o rimuovono i nostri error code. Valutare commit per commit e fare cherry-pick/porting manuale, ri-aggiungendo i marker `SCRIPT_ERROR_CODE:` dove il diff upstream li toglie.

Dopo qualsiasi modifica locale:

```powershell
npm run build     # rigenera dist/ e docs/TOOL-CATALOG.md
```

`npm link` resta valido dopo un rebuild — non serve rifarlo. **Serve però riavviare Claude Code** se sono cambiati gli schema dei tool (tool nuovi/rinominati/parametri nuovi). Le modifiche ai soli script IronPython in `src/scripts/` sono **template-side**: attive subito dopo il build, senza restart.

> Nota sulla macchina di sviluppo originale: lì i remote sono invertiti per ragioni storiche — `fork` = babos1908, `origin` = luke-harriman. Su un clone nuovo vale la convenzione normale descritta sopra.

## Macchina condivisa / più agenti

Se più sessioni Claude Code (o più persone) usano AB sulla stessa macchina:

- `list_ab_sessions` mostra tutte le sessioni AB vive: pid, heartbeat age, progetto aperto, `isMine`.
- `launch_codesys(projectFilePath)` attiva l'**owner-guard**: adotta solo una sessione che ha aperto quel progetto (o nessuno), mai l'istanza di un altro agente su un progetto diverso.
- **Non contendere lo stesso `.project`** da due sessioni: chi arriva secondo prende `selected project is currently in use by 'X' on 'Y'`.
- **Non killare processi AB non propri** (`Stop-Process` solo su orfano confermato via `get_codesys_status`).
- Su Premium, `attach_codesys` è la modalità più sicura in questo scenario: l'utente guida la propria GUI, `force_reset_watcher` non gliela ammazza.

## Troubleshooting

| Sintomo | Causa | Azione |
|---|---|---|
| `Watcher did not signal ready within Xms` | AB più lenta di `--ready-timeout-ms` | `shutdown_codesys` → `launch_codesys`. Se ricorre: bumpare il flag. |
| `Command timed out after Xms` | Operazione (es. cold `open_project`) supera l'IPC timeout | Richiamare lo stesso comando: il watcher ha completato, ora è warm. |
| `launch_codesys` dice "successful" ma poi `state: launching`, PID N/A | Adozione di una session dir stale — **fissato**: ora c'è un live-probe e il launch verifica `ready` prima di dichiarare successo | Aggiornare all'ultima `main`. Se persiste: `force_reset_watcher`. |
| `selected project is currently in use by 'X' on 'Y'` | Lock: un'altra AB (utente o altro agente) tiene quel progetto | Chiudere quella AB, o lavorare su un progetto diverso. Vedi "Macchina condivisa". |
| State `stalled`, heartbeat vecchio | Watcher worker morto o primary thread deadlockato (raro dopo il prompt-handling guard) | `diagnose_mcp_state` per confermare → `force_reset_watcher` (~10-30s). |
| MCP "locked" ma AB visivamente attiva e senza dialog | Spesso è AB **occupata**, non morta (es. sessione online interattiva che monopolizza il primary thread) | Il soft-probe ora ri-lancia il timeout invece di killare AB. Aspettare, non forzare. |
| AB "si chiude da sola" su recycle sessione | Lifetime accoppiata al processo MCP | Usare `--keep-alive`. Diagnosi con `--log-file` + `get_server_log`: cercare `cause=`. Nessun marker = kill del job-object OS (non intercettabile) → su Premium usare attach mode. |
| `Mode: headless` dopo un launch "successful" | Fallback auto-launch nascosto | `shutdown_codesys` → `launch_codesys`. |
| `Parent object not found for path: X` | Path non risolto | I tool accettano full-from-root (`Application/MyPOU`), folder/leaf (`MyLib/Function Blocks/FB_X`) e leaf univoco (`FB_X`). Se ambiguo, l'errore lo dice. Altrimenti `inspect_project_tree` / `get_all_pou_code` per il path esatto. |
| `compile_project` ritorna `0 error(s)` ma l'UI mostra errori di sintassi | CODESYS non analizza POU fuori dal call graph. Il MCP riporta fedelmente ciò che dice il compilatore; l'UI ha un linter live syntax-level. | Non è un bug. Per testare il path-errore mettere il typo in **codice raggiungibile** da `PLC_PRG`. Diagnostica completa in `%TEMP%\codesys-mcp-compile-debug.txt`. Usare `get_pou_dependency_graph(rootPOU='PLC_PRG')` per vedere il dead code. |
| `Cannot add an object because it affects a device you are currently logged into` | Sessione online attiva blocca le modifiche strutturali | Chiedere all'utente `Online → Logout` dall'AB UI. `disconnect_from_device` **non** raggiunge le sessioni aperte dalla UI. |
| `ERR_ONLINE_STACK_EMPTY` | Vedi "Stato online ops" sopra | Non ritentare a caso: o il fix portato funziona su questa build, o si usa il workaround mixed-mode. |
| `ERR_WRITE_DID_NOT_STICK` / `ERR_RESET_DID_NOT_STICK` / `ERR_RENAME_DID_NOT_STICK` | Il read-back ha rilevato che la scrittura non ha attaccato | **È il sistema che funziona**, non un bug: prima questi casi passavano silenziosamente e si scoprivano sul PLC. Leggere il messaggio: dice valore atteso vs letto. |

## File chiave

| Cosa | Dove |
|---|---|
| Fork sorgente (pubblico) | https://github.com/babos1908/ab-mcp-toolkit |
| Clone locale (convenzione) | `%USERPROFILE%\Documents\GitHub\ab-mcp-toolkit` |
| Build artifacts | `<clone>\dist\` (rigenerato da `npm run build`) |
| Catalogo tool (auto-generato) | `<clone>\docs\TOOL-CATALOG.md` |
| Manifest patch | `MCP_PATCHES` in `<clone>\src\server.ts` — o `get_mcp_version()` a runtime |
| Skill workflow (source, pubblica) | `<clone>\skills\codesys-ab\SKILL.md` |
| Skill workflow (installata) | `~/.claude/skills/codesys-ab/SKILL.md` — può contenere estensioni private, **non** sovrascritta dal setup |
| MCP config | `%USERPROFILE%\.claude.json` (entry `codesys-persistent`) |
| Log server (se `--log-file`) | il path che hai passato — o `get_server_log()` |
| Watcher logs runtime | `%TEMP%\codesys-mcp-persistent\<sessionId>\watcher.log` |
| Diagnostica compile | `%TEMP%\codesys-mcp-compile-debug.txt` (riscritto a ogni compile) |
| Doc librerie ABB su disco | `C:\ProgramData\AutomationBuilder\AB_LibDoc_2.9\` — leggerla prima di indovinare le firme dei FB |
| Scripting docs CODESYS | https://content.helpme-codesys.com/en/CODESYS%20Scripting/ |

## La skill: pubblica vs personale

Due file distinti, stesso nome:

- **`<clone>\skills\codesys-ab\SKILL.md`** — versionata nel repo pubblico. Contiene pattern **generici** ABB/CODESYS. È quella che il setup script installa.
- **`~/.claude/skills/codesys-ab/SKILL.md`** — quella che Claude Code carica davvero. Il setup **non la sovrascrive** se esiste già, proprio perché può contenere estensioni tue.

Per pattern specifici del tuo progetto (struct, GVL, naming, findings hardware), aggiungi una sezione in coda al file locale. Per allineare la parte generica alla versione del repo dopo un `git pull`:

```powershell
Compare-Object (Get-Content "$env:USERPROFILE\.claude\skills\codesys-ab\SKILL.md") (Get-Content .\skills\codesys-ab\SKILL.md)
```

## Storia / contesto

Setup iniziale provò `@codesys/mcp-toolkit` (johannesPettersson80) — abbandonato da maggio 2025, nessuna risposta a issue/PR. Pivot su `luke-harriman/Codesys-MCP` (attivo). Riscontrate lacune ABB-specific, patchate nel fork; PR #3 accettata upstream. Da lì il fork è cresciuto molto oltre la base (75 tool, 73 patch), con la maggior parte del valore aggiunto in robustezza lifecycle, eliminazione dei falsi successi, e supporto AC500 V3 validato sul campo.

## Backup minimo se perdi tutto

1. Account GitHub + clone del fork (pubblico, nessuna credenziale necessaria)
2. Path AB su Windows (default `C:\Program Files\ABB\AB2.9\AutomationBuilder\Common\AutomationBuilder.exe`)
3. Profilo AB (default `Automation Builder 2.9`)

Tutto il resto è in questo file, in `SKILL.md`, in `docs/TOOL-CATALOG.md` e nel manifest `MCP_PATCHES`.

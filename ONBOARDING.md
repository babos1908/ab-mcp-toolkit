# Onboarding — codesys-persistent MCP per ABB Automation Builder 2.9

Setup e workflow del MCP server che permette a Claude Code (Anthropic) di pilotare ABB Automation Builder 2.9 / CODESYS V3.5 SP19. Fork con patch di [`luke-harriman/Codesys-MCP`](https://github.com/luke-harriman/Codesys-MCP).

## TL;DR

- **Cosa fa**: tool MCP per aprire `.project`, leggere/creare/modificare POU, compilare, cercare nel codice, gestire device tree AC500, scaricare al PLC, ecc.
- **Edition richiesta**: AB 2.9 **Standard** o superiore (lo scripting engine è disponibile da Standard in su).
- **Architettura**: persistent UI — il MCP spawna AB visibile e ci comunica via file-based IPC. UN'unica istanza AB, nessun lock conflict.
- **Trigger automatico**: la skill Claude Code `codesys-ab` si attiva su menzioni di "automation builder", "codesys", "POU", "compile", "AC500", ecc.

## Setup nuova macchina

**Prerequisiti**: Windows + AB 2.9 Standard installato + Node.js 18+ + git + GitHub CLI autenticato + Claude Code installato.

```powershell
# 1. Clone fork (main include già tutti i patch)
git clone https://github.com/babos1908/Codesys-MCP.git C:\Users\Admin\Documents\GitHub\Codesys-MCP
cd C:\Users\Admin\Documents\GitHub\Codesys-MCP

# 2. Install + build + link globale
npm install
npm run build
npm link

# 3. Registra MCP a livello user (vale per ogni progetto)
claude mcp add -s user codesys-persistent -- codesys-mcp-persistent `
  --codesys-path "C:\Program Files\ABB\AB2.9\AutomationBuilder\Common\AutomationBuilder.exe" `
  --codesys-profile "Automation Builder 2.9" `
  --mode persistent `
  --no-auto-launch `
  --ready-timeout-ms 600000 `
  --timeout 600000

# 4. Skill Claude Code (workflow knowledge)
# Copia il file ~/.claude/skills/codesys-ab/SKILL.md dalla macchina primaria,
# oppure recuperalo dal repo team se viene pubblicato.

# 5. Verifica
claude mcp list   # deve mostrare "codesys-persistent: ✓ Connected"
```

Adatta path AB se installato altrove. Profilo: in AB → `Tools → Profiles` per nome esatto.

## Daily usage

1. Apri Claude Code in qualunque cartella di progetto AB
2. Scrivi un prompt che menzioni `.project`, `POU`, `compile`, ecc. → **la skill `codesys-ab` triggera automaticamente**
3. Verifica trigger: la prima risposta inizia con `📡 codesys-ab skill attiva — workflow AB 2.9.`
4. Workflow standard:
   - `launch_codesys` → AB si apre visibile (cold start ~2 min, warm <30s)
   - `open_project` → carica il `.project`
   - operazione richiesta (read/edit/compile/search)
   - `save_project` (opzionale, molti tool salvano da soli)

Esempi di prompt che funzionano bene:
- *"Apri Test.project e leggimi tutti i POU"*
- *"Compila e dammi gli errori strutturati"*
- *"Cerca dove viene usato il flag IO_ALARM"*
- *"Crea FunctionBlock NuovoModulo con questi VAR_INPUT…"*
- *"Aggiungi libreria OSCAT 3.3.5"*

## Tool disponibili (40)

Prefisso: `mcp__codesys-persistent__`. Categorie:

- **Lifecycle**: `launch_codesys`, `shutdown_codesys`, `get_codesys_status`, `attach_codesys` (Premium-only)
- **Project**: `open_project`, `create_project`, `save_project`, `create_project_archive`
- **Read/Search**: `get_all_pou_code`, `search_code`, `find_references`
- **CRUD POU**: `create_pou`, `set_pou_code`, `create_method`, `create_property`, `create_dut`, `create_gvl`, `create_folder`, `delete_object`, `rename_object`, `rename_symbol`
- **Build**: `compile_project`, `get_compile_messages`
- **Libraries**: `list_project_libraries`, `add_library`
- **Device tree (AC500)**: `list_device_repository`, `inspect_device_node`, `add_device`, `set_device_parameter`, `map_io_channel`
- **Online/runtime**: `connect_to_device`, `set_credentials`, `set_simulation_mode`, `disconnect_from_device`, `get_application_state`, `read_variable`, `write_variable`, `download_to_device`, `start_stop_application`, `monitor_variables`

## Patch nel fork (rispetto a luke-harriman upstream)

Branch `main` contiene 4 commit di differenza, tutti su `feat/configurable-ready-timeout`:

1. **`--ready-timeout-ms` configurabile** — default era 60s hardcoded. AB 2.9 cold-boot impiega ~120s; senza patch il launcher dava timeout prematuro.
2. **`attach_codesys` tool** — modalità per Premium edition (utente lancia AB e fa "Tools → Scripting → Execute Script File…"). Non utilizzabile su Standard ma incluso per completezza.
3. **`create_pou Function returnType`** — fix bug: il template non passava `return_type` allo scripting API, ogni Function POU falliva con `ValueError`.
4. **`--timeout` wirato a IpcClient** — il flag esisteva ma era ignorato; ora regola il timeout per-comando IPC (default 60s troppo stretto per cold open di project pesanti).

PR upstream: **non ancora inviata** (decisione utente). Branch `feat/configurable-ready-timeout` resta separato per facilitarla quando serve:
```powershell
gh pr create --repo luke-harriman/Codesys-MCP --base main --head babos1908:feat/configurable-ready-timeout
```

## Troubleshooting

| Sintomo | Causa | Azione |
|---|---|---|
| `Watcher did not signal ready within Xms` | AB più lento del `--ready-timeout-ms` | `shutdown_codesys` → `launch_codesys`. Se persiste: bumpare `--ready-timeout-ms` nel registration. |
| `Command timed out after 60000ms` | Operazione (es. cold `open_project`) supera IPC timeout | Richiamare lo stesso comando: il watcher avrà completato, la cache è ora warm. |
| `selected project is currently in use by 'X' on 'Y'` | Lock: AB aperta manualmente dall'utente in parallelo | Chiudere quella AB. Usare SOLO `launch_codesys` (Standard non permette attach). |
| `Specified argument was out of the range of valid values. Parameter name: return_type` | Versione npm pubblica senza patch (questo fork ha il fix) | Usare il fork patchato. Workaround: `FunctionBlock` con `VAR_OUTPUT result : STRING`. |
| `State: ready, Mode: headless` dopo launch | Auto-launch fallback nascosto | `shutdown_codesys` → `launch_codesys`. |
| `Parent object not found for path: X` | Fuzzy-match path fallita | `get_all_pou_code` per vedere la struttura esatta, usare quel path. |
| AB zombie / non risponde | Detached spawn senza cleanup | `Stop-Process -Name AutomationBuilder -Force` (PowerShell) o Task Manager. |

## File chiave

| Cosa | Dove |
|---|---|
| Fork sorgente | https://github.com/babos1908/Codesys-MCP |
| Clone locale | `C:\Users\Admin\Documents\GitHub\Codesys-MCP` |
| Build artifacts | `<clone>\dist\` (rigenerato da `npm run build`) |
| Skill workflow | `C:\Users\Admin\.claude\skills\codesys-ab\SKILL.md` |
| MCP config | `C:\Users\Admin\.claude.json` (entry `codesys-persistent`) |
| Watcher logs runtime | `%TEMP%\codesys-mcp-persistent\<sessionId>\watcher.log` |
| Scripting docs CODESYS | https://content.helpme-codesys.com/en/CODESYS%20Scripting/ |

## Aggiornamenti / sync

- **Patch nuove** sul tuo fork: lavorare su un branch separato (`feat/<nome>`), commit, push, eventualmente merge in `main`. La macchina dev pulla con `git pull && npm run build` e `npm link` resta valido.
- **Sync da upstream luke-harriman**:
  ```powershell
  git fetch origin
  git checkout main
  git merge origin/main      # incorpora novità upstream
  git push fork main         # aggiorna il tuo fork
  ```
  Se ci sono conflitti coi nostri patch: risolvi a mano (è il prezzo del fork).
- **Skill update**: modifica `SKILL.md` direttamente, salva. Niente restart Claude Code richiesto.

## Replicare il setup su un nuovo dev/PC del team

1. Esegui i 5 step di "Setup nuova macchina" sopra
2. Copia anche `~/.claude/skills/codesys-ab/SKILL.md` (oppure se in futuro pubblichiamo skills su un repo team, clone quello)
3. Verifica con un prompt tipo "apri Test.project e leggi i POU"

## Storia / contesto

Setup iniziale provò `@codesys/mcp-toolkit` (johannesPettersson80) — abbandonato da maggio 2025, no risposta a issue/PR. Pivoted a `luke-harriman/Codesys-MCP` (attivo, commit del 2026-05-08). Riscontrate 4 lacune ABB-specific, patchate localmente. PR #8 al toolkit vecchio chiusa con commento di rispetto.

## Backup minimo se perdi tutto

Per ricostruire da zero serve solo:
1. Account GitHub + clone fork
2. Path AB su Windows (default `C:\Program Files\ABB\AB2.9\AutomationBuilder\Common\AutomationBuilder.exe`)
3. Profilo AB (default `Automation Builder 2.9`)

Tutti gli altri dettagli sono in questo file e in `SKILL.md`.

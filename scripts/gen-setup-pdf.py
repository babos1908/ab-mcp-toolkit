#!/usr/bin/env python3
"""Generate docs/SETUP.pdf -- the hand-to-a-new-colleague setup guide.

The PDF is committed so someone can be handed a single file, but it is
generated from this script so it never becomes an unmaintainable binary:
edit the CONTENT list below and re-run

    python scripts/gen-setup-pdf.py

Requires reportlab (pip install reportlab). Not wired into `npm run build`
on purpose -- reportlab is a Python dep and the build must stay Node-only.
"""

import os
import re
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------- palette ---

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5b5b5b")
ACCENT = colors.HexColor("#b3341a")       # ABB-ish red, used sparingly
RULE = colors.HexColor("#d8d8d8")
CODE_BG = colors.HexColor("#f4f4f2")
CODE_BORDER = colors.HexColor("#e0e0dc")
WARN_BG = colors.HexColor("#fdf3ef")
WARN_BORDER = colors.HexColor("#e8c4b8")

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm

# ----------------------------------------------------------------- styles ---

_ss = getSampleStyleSheet()

S_TITLE = ParagraphStyle(
    "AbTitle", parent=_ss["Title"], fontName="Helvetica-Bold",
    fontSize=22, leading=26, textColor=INK, alignment=TA_LEFT, spaceAfter=2,
)
S_SUBTITLE = ParagraphStyle(
    "AbSubtitle", parent=_ss["Normal"], fontName="Helvetica",
    fontSize=10.5, leading=15, textColor=MUTED, spaceAfter=14,
)
S_H1 = ParagraphStyle(
    "AbH1", parent=_ss["Heading1"], fontName="Helvetica-Bold",
    fontSize=13.5, leading=17, textColor=ACCENT, spaceBefore=16, spaceAfter=6,
)
S_H2 = ParagraphStyle(
    "AbH2", parent=_ss["Heading2"], fontName="Helvetica-Bold",
    fontSize=11, leading=14, textColor=INK, spaceBefore=11, spaceAfter=4,
)
S_BODY = ParagraphStyle(
    "AbBody", parent=_ss["Normal"], fontName="Helvetica",
    fontSize=9.7, leading=14.2, textColor=INK, spaceAfter=6,
)
S_BULLET = ParagraphStyle(
    "AbBullet", parent=S_BODY, leftIndent=11, bulletIndent=2, spaceAfter=3,
)
S_CODE = ParagraphStyle(
    "AbCode", parent=_ss["Code"], fontName="Courier",
    fontSize=8.4, leading=12.4, textColor=INK,
)
S_CELL = ParagraphStyle(
    "AbCell", parent=S_BODY, fontSize=8.8, leading=12, spaceAfter=0,
)
S_CELL_CODE = ParagraphStyle(
    "AbCellCode", parent=S_CELL, fontName="Courier", fontSize=8.0, leading=11.5,
)

CONTENT_W = PAGE_W - 2 * MARGIN


def esc(text):
    """Escape for reportlab's mini-XML, then honour **bold** and `code`."""
    out = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(
        r"`(.+?)`",
        r'<font face="Courier" size="8.8">\1</font>',
        out,
    )
    return out


# ------------------------------------------------------------- flowables ---

def para(text, style=S_BODY):
    return Paragraph(esc(text), style)


def bullets(items):
    return [Paragraph(esc(i), S_BULLET, bulletText="\u2022") for i in items]


def code(lines, comment=None):
    """A shaded code block. `lines` is a list of literal command lines."""
    body = "<br/>".join(
        l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
         .replace(" ", "&nbsp;") or "&nbsp;"
        for l in lines
    )
    cell = Paragraph(body, S_CODE)
    t = Table([[cell]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, CODE_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    out = [t, Spacer(1, 4)]
    if comment:
        out.append(para(comment))
    return out


def callout(title, text):
    inner = Paragraph(
        "<b>%s</b><br/>%s" % (esc(title), esc(text)), S_CELL
    )
    t = Table([[inner]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, WARN_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [t, Spacer(1, 8)]


def table(header, rows, widths, code_cols=()):
    data = [[Paragraph("<b>%s</b>" % esc(h), S_CELL) for h in header]]
    for r in rows:
        data.append([
            Paragraph(esc(c), S_CELL_CODE if i in code_cols else S_CELL)
            for i, c in enumerate(r)
        ])
    t = Table(data, colWidths=[w * CONTENT_W for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efefec")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("INNERGRID", (0, 1), (-1, -1), 0.35, RULE),
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [t, Spacer(1, 8)]


# --------------------------------------------------------------- content ---

REPO = "https://github.com/babos1908/ab-mcp-toolkit"


def build_story():
    s = []

    s.append(para("Setup ab-mcp-toolkit", S_TITLE))
    s.append(para(
        "Guida rapida per configurare da zero il controllo di ABB Automation Builder 2.9 "
        "(CODESYS V3.5 SP19) da Claude Code. Dal clone al primo progetto aperto: circa 15 minuti, "
        "di cui 10 di attesa.", S_SUBTITLE))

    # --- 1
    s.append(para("1. Cosa ottieni", S_H1))
    s.append(para(
        "Un server MCP che espone 75 tool con cui Claude Code pilota Automation Builder: aprire "
        "progetti, leggere e scrivere POU, compilare con errori strutturati, cercare nel codice IEC, "
        "gestire library e repository, manipolare il device tree AC500, configurare i task."))
    s.append(para(
        "Piu' una skill (`codesys-ab`) che si attiva da sola quando parli di Automation Builder, "
        "CODESYS, POU, AC500: contiene il workflow corretto, i caveat della piattaforma e i pattern "
        "hardware gia' validati sul campo, cosi' non li devi riscoprire."))
    s.extend(callout(
        "Due pezzi separati, servono entrambi",
        "Il server MCP fornisce i tool; la skill dice a Claude come usarli. Clonare il repo non "
        "installa ne' l'uno ne' l'altra: serve lo script di setup del passo 3, che li registra "
        "tutti e due."))

    # --- 2
    s.append(para("2. Prerequisiti", S_H1))
    s.extend(table(
        ["Cosa", "Note"],
        [
            ["Windows", "Automation Builder gira solo su Windows."],
            ["ABB Automation Builder 2.9, edizione Standard o superiore",
             "Sotto Standard manca lo scripting engine e non funziona nulla. Alcuni tool "
             "(attach_codesys, run_static_analysis) richiedono Premium."],
            ["Node.js 18 o superiore", "Verifica: node --version"],
            ["git", "Il repo e' pubblico: nessun account o token necessario."],
            ["Claude Code installato", "Il comando claude deve rispondere dal terminale."],
        ],
        [0.34, 0.66]))

    # --- 3
    s.append(para("3. Installazione", S_H1))
    s.append(para("Tre comandi in PowerShell. Il repo e' pubblico, il clone non chiede credenziali."))
    s.extend(code([
        "git clone %s.git $env:USERPROFILE\\Documents\\GitHub\\ab-mcp-toolkit" % REPO,
        "",
        "cd $env:USERPROFILE\\Documents\\GitHub\\ab-mcp-toolkit",
        "",
        "powershell -ExecutionPolicy Bypass -File .\\setup-codesys-mcp.ps1",
    ]))
    s.append(para("Lo script fa tutto da solo:"))
    s.extend(bullets([
        "verifica i prerequisiti e si ferma con un messaggio chiaro se ne manca uno;",
        "trova da solo AutomationBuilder.exe nei percorsi standard;",
        "esegue npm install, npm run build e npm link;",
        "registra il server MCP a livello utente (vale per tutti i tuoi progetti);",
        "installa la skill in ~/.claude/skills/codesys-ab/, senza sovrascriverla se esiste gia'.",
    ]))
    s.append(Spacer(1, 4))
    s.append(para(
        "Se Automation Builder e' installato altrove, o il profilo ha un nome diverso "
        "(lo leggi in AB da Tools > Profiles), passa i parametri:"))
    s.extend(code([
        "powershell -ExecutionPolicy Bypass -File .\\setup-codesys-mcp.ps1 `",
        "  -CodesysPath \"D:\\ABB\\AB2.9\\AutomationBuilder\\Common\\AutomationBuilder.exe\" `",
        "  -CodesysProfile \"Automation Builder 2.9\"",
    ]))

    # --- 4
    s.append(para("4. Verifica", S_H1))
    s.append(para("Primo controllo, il server deve risultare connesso:"))
    s.extend(code(["claude mcp list"],
                  "Deve comparire  codesys-persistent: Connected."))
    s.extend(callout(
        "Riavvia Claude Code prima di provare",
        "Gli schema dei tool vengono fissati all'avvio: finche' non riavvii, i tool non compaiono "
        "anche se il server e' registrato correttamente. Vale ogni volta che aggiorni il toolkit "
        "con tool nuovi."))
    s.append(para(
        "Poi apri Claude Code in una cartella qualsiasi e prova un prompt come "
        "\"apri Test.project e leggimi i POU\". Se la skill si e' agganciata, la prima risposta "
        "si apre con una riga di conferma, preceduta da una piccola icona a forma di antenna:"))
    s.extend(code(["codesys-ab skill attiva -- workflow AB 2.9."],
                  "Se quella riga non compare, la skill non si e' caricata: controlla che esista "
                  "il file ~/.claude/skills/codesys-ab/SKILL.md."))

    # --- 5
    s.append(para("5. Come si lavora", S_H1))
    s.append(para(
        "Non serve chiamare i tool a mano: descrivi cosa vuoi e la skill guida Claude nella "
        "sequenza giusta. Il flusso tipico e'"))
    s.extend(bullets([
        "launch_codesys apre Automation Builder visibile (lo vedi partire);",
        "open_project carica il .project;",
        "l'operazione richiesta: leggere, modificare, compilare, cercare;",
        "il salvataggio, che quasi tutti i tool fanno da soli.",
    ]))
    s.append(Spacer(1, 4))
    s.append(para("Esempi di richieste che funzionano bene:"))
    s.extend(bullets([
        "\"Apri PIOPO.project e dimmi come e' strutturata l'applicazione\"",
        "\"Compila e dammi solo gli errori, raggruppati per POU\"",
        "\"Cerca dove viene usato il flag xAlarmActive\"",
        "\"Crea un FunctionBlock FB_Diagnostica con questi VAR_INPUT ...\"",
        "\"Aggiungi la libreria Pm, 1.2.11.4 (ABB) e mostrami i parametri\"",
    ]))

    # --- 6
    s.append(para("6. Tempi da aspettarsi", S_H1))
    s.append(para(
        "Automation Builder e' pesante: la lentezza del primo avvio e' normale, non e' un blocco."))
    s.extend(table(
        ["Operazione", "Primo avvio", "Successivi"],
        [
            ["Avvio di Automation Builder", "circa 2 minuti", "immediato"],
            ["Apertura di un progetto", "da 1 a 3 minuti", "meno di 5 secondi"],
            ["Lettura del codice", "5-15 secondi", "5-15 secondi"],
            ["Compilazione", "dipende dal progetto", "piu' veloce"],
        ],
        [0.44, 0.28, 0.28]))
    s.extend(callout(
        "Se l'apertura del progetto va in timeout",
        "Non e' un errore: Automation Builder sta ancora caricando e finira'. Aspetta una "
        "trentina di secondi e richiedi la stessa operazione: la seconda volta e' istantanea."))

    # --- 7
    s.append(para("7. Problemi comuni", S_H1))
    s.extend(table(
        ["Sintomo", "Cosa fare"],
        [
            ["Il progetto risulta gia' in uso da un altro utente o macchina",
             "Un'altra istanza di Automation Builder tiene quel file. Chiudila, oppure lavora su "
             "un progetto diverso. Su una macchina condivisa, list_ab_sessions mostra chi sta usando cosa."],
            ["Automation Builder si chiude da sola durante la sessione",
             "Il setup registra --keep-alive proprio per evitarlo. Se succede lo stesso, chiedi a "
             "Claude di leggere get_server_log: i marker cause= dicono chi l'ha chiusa."],
            ["I comandi vanno in timeout ma Automation Builder sembra attiva",
             "Spesso e' occupata, non bloccata (tipico durante una sessione online verso il PLC). "
             "Aspetta invece di forzare. Se persiste, diagnose_mcp_state e poi force_reset_watcher."],
            ["La compilazione dice zero errori ma l'interfaccia ne mostra",
             "Non e' un difetto: CODESYS non analizza i POU che nessuno chiama. L'errore e' in "
             "codice morto. Chiedi il grafo delle dipendenze da PLC_PRG per individuarlo."],
            ["Un tool nuovo non compare",
             "Riavvia Claude Code: gli schema si fissano all'avvio."],
        ],
        [0.36, 0.64]))

    # --- 8
    s.append(para("8. Operazioni online verso il PLC: leggi prima", S_H1))
    s.extend(callout(
        "Stato non ancora verificato su questa piattaforma",
        "I tool che parlano col PLC in esecuzione (connessione, lettura e scrittura variabili, "
        "download, start/stop) storicamente non funzionavano via scripting su AB 2.9 / SP19. "
        "A giugno 2026 e' stato integrato un fix che potrebbe sbloccarli, ma e' stato validato "
        "da altri su un service pack e un hardware diversi dai nostri: su AC500 non e' ancora "
        "provato. Se non funziona, il comportamento e' identico a prima -- non puo' peggiorare nulla."))
    s.append(para(
        "In pratica, finche' non c'e' una verifica su PLC reale: usa il toolkit per preparare, "
        "compilare e rilasciare, e l'interfaccia di Automation Builder per Login, Download e "
        "osservazione runtime. Per i test automatici, parla col PLC dal suo protocollo "
        "applicativo (MQTT, OPC UA, Modbus, HTTP)."))
    s.extend(callout(
        "Attenzione alla scrittura di variabili",
        "write_variable ora forza il valore: la variabile resta forzata finche' non la sforzi "
        "esplicitamente. Non usarlo su variabili critiche di un impianto in produzione."))

    # --- 9
    s.append(para("9. Dove approfondire", S_H1))
    s.extend(table(
        ["Cosa", "Dove"],
        [
            ["Setup completo, troubleshooting esteso, sync con upstream", "ONBOARDING.md nel repo"],
            ["Workflow, caveat della piattaforma, pattern hardware AC500",
             "skills/codesys-ab/SKILL.md nel repo (e' la skill stessa: si legge come documento)"],
            ["Elenco completo dei 75 tool con descrizione", "docs/TOOL-CATALOG.md (auto-generato)"],
            ["Quali fix sono attivi nella tua installazione",
             "chiedi a Claude di chiamare get_mcp_version"],
            ["Documentazione delle librerie ABB, gia' sul tuo disco",
             "C:\\ProgramData\\AutomationBuilder\\AB_LibDoc_2.9\\"],
            ["Repository", REPO],
        ],
        [0.42, 0.58]))
    s.append(Spacer(1, 6))
    s.append(para(
        "Per pattern specifici di un tuo progetto (struct, GVL, convenzioni interne), aggiungili "
        "in coda al file locale ~/.claude/skills/codesys-ab/SKILL.md: resta sulla tua macchina "
        "e lo script di setup non lo sovrascrive."))

    return s


# ------------------------------------------------------------ page frame ---

def decorate(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, MARGIN - 5 * mm, PAGE_W - MARGIN, MARGIN - 5 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, MARGIN - 9.5 * mm, "ab-mcp-toolkit - guida al setup")
    canvas.drawRightString(PAGE_W - MARGIN, MARGIN - 9.5 * mm, "pag. %d" % doc.page)
    canvas.restoreState()


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(here, "docs", "SETUP.pdf")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    doc = BaseDocTemplate(
        out, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN + 6 * mm,
        title="Setup ab-mcp-toolkit",
        subject="Configurazione di ABB Automation Builder 2.9 con Claude Code",
        author="ab-mcp-toolkit",
    )
    frame = Frame(
        MARGIN, MARGIN + 6 * mm,
        PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN - 6 * mm,
        id="body", showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="std", frames=[frame], onPage=decorate)])
    doc.build(build_story())

    size = os.path.getsize(out)
    print("gen-setup-pdf: wrote %s (%.1f KB)" % (out, size / 1024.0))


if __name__ == "__main__":
    sys.exit(main())

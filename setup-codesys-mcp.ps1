# setup-codesys-mcp.ps1 — One-shot setup for the codesys-persistent MCP server (ABB Automation Builder fork).
#
# Run from any directory after cloning this repo:
#     cd <where-you-cloned>
#     pwsh -File .\setup-codesys-mcp.ps1
#
# Prerequisites (the script verifies and stops if any is missing):
#   - Windows
#   - Node.js 18+
#   - git
#   - Claude Code CLI (`claude` on PATH)
#   - ABB Automation Builder 2.9 Standard (or higher) installed
#
# What it does:
#   1. Validates prerequisites.
#   2. Auto-detects the AutomationBuilder.exe path (overridable via -CodesysPath).
#   3. Runs `npm install`, `npm run build`, `npm link` from the repo root.
#   4. Registers the MCP server at user scope (`claude mcp add -s user codesys-persistent ...`)
#      with sensible defaults for AB 2.9: `--mode persistent --no-auto-launch
#      --ready-timeout-ms 600000 --timeout 600000`.
#   5. Verifies registration with `claude mcp list`.
#
# Re-run safe: if codesys-persistent is already registered it is removed and re-added
# with the latest flags. `npm link` is also re-applied so the global binary points
# to the current checkout.

[CmdletBinding()]
param(
    [string]$CodesysPath = '',
    [string]$CodesysProfile = 'Automation Builder 2.9',
    [int]$ReadyTimeoutMs = 600000,
    [int]$CommandTimeoutMs = 600000,
    [string]$McpName = 'codesys-persistent'
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Fail([string]$msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

# ── 1. Prerequisites ──────────────────────────────────────────────────────────

Write-Step 'Checking prerequisites...'

if (-not $IsWindows -and $PSVersionTable.Platform -ne 'Win32NT' -and $env:OS -notmatch 'Windows') {
    Fail 'This script targets Windows (ABB Automation Builder runs on Windows only).'
}

foreach ($cmd in @('node', 'npm', 'git', 'claude')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Fail "$cmd is not on PATH."
    }
}

$nodeMajor = (& node --version) -replace '^v(\d+)\..*', '$1'
if ([int]$nodeMajor -lt 18) {
    Fail "Node.js >= 18 required, found $nodeMajor."
}

$repoRoot = $PSScriptRoot
if (-not (Test-Path (Join-Path $repoRoot 'package.json'))) {
    Fail "package.json not found at $repoRoot. Run this script from inside the cloned repo."
}

Write-Host "Repo root: $repoRoot"

# ── 2. Locate AutomationBuilder.exe ───────────────────────────────────────────

Write-Step 'Locating AutomationBuilder.exe...'

if (-not $CodesysPath) {
    $candidates = @(
        'C:\Program Files\ABB\AB2.9\AutomationBuilder\Common\AutomationBuilder.exe',
        'C:\Program Files (x86)\ABB\AB2.9\AutomationBuilder\Common\AutomationBuilder.exe'
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $CodesysPath = $c; break }
    }
}

if (-not $CodesysPath -or -not (Test-Path $CodesysPath)) {
    Fail "AutomationBuilder.exe not found. Pass -CodesysPath '<full path>' explicitly."
}

Write-Host "AB path:    $CodesysPath"
Write-Host "AB profile: $CodesysProfile"

# ── 3. npm install / build / link ─────────────────────────────────────────────

Write-Step 'Running npm install...'
Push-Location $repoRoot
try {
    npm install
    if ($LASTEXITCODE -ne 0) { Fail 'npm install failed.' }

    Write-Step 'Running npm run build...'
    npm run build
    if ($LASTEXITCODE -ne 0) { Fail 'npm run build failed.' }

    Write-Step 'Linking the package globally...'
    npm link
    if ($LASTEXITCODE -ne 0) { Fail 'npm link failed.' }
}
finally {
    Pop-Location
}

# ── 4. Register MCP server ────────────────────────────────────────────────────

Write-Step 'Registering MCP server at user scope...'

# Remove any pre-existing registration so the new flags take effect.
claude mcp remove $McpName 2>&1 | Out-Null

claude mcp add -s user $McpName -- codesys-mcp-persistent `
    --codesys-path $CodesysPath `
    --codesys-profile $CodesysProfile `
    --mode persistent `
    --no-auto-launch `
    --ready-timeout-ms $ReadyTimeoutMs `
    --timeout $CommandTimeoutMs

if ($LASTEXITCODE -ne 0) { Fail 'claude mcp add failed.' }

# ── 5. Install Claude Code skill (no-overwrite) ───────────────────────────────

Write-Step 'Installing Claude Code skill (codesys-ab)...'

$skillSrc    = Join-Path $repoRoot 'skills\codesys-ab\SKILL.md'
$skillDstDir = Join-Path $env:USERPROFILE '.claude\skills\codesys-ab'
$skillDst    = Join-Path $skillDstDir 'SKILL.md'

if (-not (Test-Path $skillSrc)) {
    Write-Host "WARN: source skill not found at $skillSrc - skipping." -ForegroundColor Yellow
} elseif (Test-Path $skillDst) {
    Write-Host "Skill already present at $skillDst - NOT overwriting." -ForegroundColor Yellow
    Write-Host "      The local file may contain project-specific extensions you want to keep."
    Write-Host "      To pull the latest public version manually, diff:"
    Write-Host "        Compare-Object (Get-Content '$skillDst') (Get-Content '$skillSrc')"
} else {
    New-Item -ItemType Directory -Path $skillDstDir -Force | Out-Null
    Copy-Item -Path $skillSrc -Destination $skillDst -Force
    Write-Host "Installed: $skillDst" -ForegroundColor Green
}

# ── 6. Verify ─────────────────────────────────────────────────────────────────

Write-Step 'Verifying...'
claude mcp list | Select-String $McpName

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  - Open Claude Code in a project folder, mention 'automation builder' / 'codesys' / 'POU' and the skill will trigger."
Write-Host "  - First tool call invoking AB will spawn it visibly (cold-start ~2 min, warm <30s)."
Write-Host "  - To add project-specific patterns (private structs/GVLs/conventions), append a"
Write-Host "    '## Project-specific patterns' section to the installed skill file. It will not be"
Write-Host "    overwritten on subsequent setup runs."
Write-Host ""

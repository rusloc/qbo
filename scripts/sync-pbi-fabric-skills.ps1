<#
.SYNOPSIS
  Sync Power BI + Fabric agent skills from microsoft/skills-for-fabric into this repo.
.NOTES
  Run from the repo root. Safe to re-run: pulls the latest version and replaces the local copies.
  .claude/common is managed by this script; don't keep your own files there.
  Exit codes: 0 = OK, 2 = one or more skills not found upstream.
#>
param(
  [string]$Source    = (Join-Path $HOME "skills-for-fabric"),
  [string]$SkillsDir = ".claude\skills"
)
$ErrorActionPreference = "Stop"
$CommonDir = Join-Path (Split-Path $SkillsDir -Parent) "common"

$Keep = @(
  # Local report build & design
  "semantic-model-authoring",
  # powerbi-report-cli replaces powerbi-report-planning / -design / -authoring / -management,
  # which upstream main merged into this one skill (2026-09-24, agreed with the user)
  "powerbi-report-cli",
  # Cloud: reports, data stores, discovery, governance
  "sqldw-cli",
  "spark-cli",
  "sqldb-cli",
  "search-consumption-cli",
  "onelake-catalog-govern-cli"
)
$Drop = @(
  "dataflows-cli",
  "deployment-pipelines-authoring-cli",
  "git-integration-operations-cli",
  "variable-library-cli"
)

# 1. Get or update the upstream repo
if (Test-Path (Join-Path $Source ".git")) {
  git -C $Source pull --quiet
} else {
  git clone --quiet https://github.com/microsoft/skills-for-fabric.git $Source
}
if ($LASTEXITCODE -ne 0) { throw "git failed (exit $LASTEXITCODE)" }

New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null

# 2. Remove skills that are no longer wanted
foreach ($s in $Drop) {
  $p = Join-Path $SkillsDir $s
  if (Test-Path $p) { Remove-Item $p -Recurse -Force; Write-Host "removed  $s" }
}

# 3. Copy wanted skills (root skills/ first, plugin folder as fallback)
$missing = @()
foreach ($s in $Keep) {
  $from = @(
    (Join-Path $Source "skills\$s"),
    (Join-Path $Source "plugins\powerbi-authoring\skills\$s")
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($from) {
    $to = Join-Path $SkillsDir $s
    if (Test-Path $to) { Remove-Item $to -Recurse -Force }
    Copy-Item $from $SkillsDir -Recurse -Force
    Write-Host "copied   $s"
  } else {
    $missing += $s
    Write-Warning "MISSING  $s"
  }
}

# 4. Shared files the skills reference via ../../common/
$upCommon = Join-Path $Source "common"
if (Test-Path $upCommon) {
  if (Test-Path $CommonDir) { Remove-Item $CommonDir -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $CommonDir | Out-Null
  Copy-Item (Join-Path $upCommon "*") $CommonDir -Recurse -Force
  Write-Host "copied   common/"
} else {
  Write-Warning "Upstream common/ folder not found"
}

# 5. Power Query M reference for the user's pbip-editor skill (optional)
$pbipDir = Join-Path $SkillsDir "pbip-editor"
$m = Get-ChildItem $Source -Recurse -Filter "m-language.md" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($m -and (Test-Path $pbipDir)) {
  $refs = Join-Path $pbipDir "references"
  New-Item -ItemType Directory -Force -Path $refs | Out-Null
  Copy-Item $m.FullName $refs -Force
  Write-Host "copied   m-language.md -> pbip-editor/references"
} else {
  Write-Host "skipped  m-language.md (not found upstream, or no pbip-editor skill)"
}

if ($missing.Count -gt 0) {
  Write-Warning ("Not found upstream: " + ($missing -join ", ") +
    ". List current names with: Get-ChildItem '$Source\skills' | Select-Object Name")
  exit 2
}
Write-Host "Done."

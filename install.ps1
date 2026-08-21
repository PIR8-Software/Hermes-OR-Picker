#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:USERPROFILE ".hermes" }
$DesktopRoot = Join-Path $env:LOCALAPPDATA "hermes"

function Copy-File {
    param([string]$Src, [string]$Dest)
    $dir = Split-Path -Parent $Dest
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Copy-Item -Force $Src $Dest
}

# Desktop app loads plugins from %LOCALAPPDATA%\hermes on Windows.
Copy-File `
    (Join-Path $Root "src\desktop-plugin\plugin.js") `
    (Join-Path $DesktopRoot "desktop-plugins\openrouter-picker\plugin.js")

# Gateway/API + provider: only if this machine also has a Hermes home.
if (Test-Path $HermesHome) {
    Copy-File `
        (Join-Path $Root "src\backend-api\plugin.yaml") `
        (Join-Path $HermesHome "plugins\openrouter-picker\plugin.yaml")
    Copy-File `
        (Join-Path $Root "src\backend-api\__init__.py") `
        (Join-Path $HermesHome "plugins\openrouter-picker\__init__.py")
    Copy-File `
        (Join-Path $Root "src\backend-api\manifest.json") `
        (Join-Path $HermesHome "plugins\openrouter-picker\dashboard\manifest.json")
    Copy-File `
        (Join-Path $Root "src\backend-api\plugin_api.py") `
        (Join-Path $HermesHome "plugins\openrouter-picker\dashboard\plugin_api.py")
    $dashInit = Join-Path $HermesHome "plugins\openrouter-picker\dashboard\__init__.py"
    if (-not (Test-Path (Split-Path $dashInit))) {
        New-Item -ItemType Directory -Path (Split-Path $dashInit) -Force | Out-Null
    }
    if (-not (Test-Path $dashInit)) {
        New-Item -ItemType File -Path $dashInit -Force | Out-Null
    }
    Copy-File `
        (Join-Path $Root "src\model-provider\__init__.py") `
        (Join-Path $HermesHome "plugins\model-providers\or-picker\__init__.py")
    Copy-File `
        (Join-Path $Root "src\model-provider\plugin.yaml") `
        (Join-Path $HermesHome "plugins\model-providers\or-picker\plugin.yaml")

    $jsonDest = Join-Path $HermesHome "openrouter-supplemental-models.json"
    $jsonItem = Get-Item -LiteralPath $jsonDest -ErrorAction SilentlyContinue
    if ($jsonItem -and $jsonItem.LinkType) {
        Write-Host "Refusing to overwrite symlink $jsonDest (unlink it first so a git pull cannot wipe your list)"
    } elseif (-not $jsonItem) {
        Copy-Item (Join-Path $Root "openrouter-supplemental-models.json") $jsonDest
        Write-Host "Wrote empty starter $jsonDest"
    } else {
        Write-Host "Left existing $jsonDest in place"
    }
    Write-Host "Installed API/provider into $HermesHome"
} else {
    Write-Host "No $HermesHome — installed desktop plugin only."
    Write-Host "Run install.sh on the gateway host for the API + provider."
}

Write-Host "Desktop plugin: $DesktopRoot\desktop-plugins\openrouter-picker\plugin.js"
Write-Host "Enable on the gateway: hermes plugins enable openrouter-picker --no-allow-tool-override"
Write-Host "Then: Ctrl+K → Reload desktop plugins"

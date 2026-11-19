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
    (Join-Path $Root "catalog\desktop\plugin.js") `
    (Join-Path $DesktopRoot "desktop-plugins\openrouter-picker\plugin.js")

function Ensure-ProviderLink {
    # Make $LinkPath discoverable as a model-provider dir (symlink to $TargetPath,
    # falling back to a real copy of the provider files when symlinks are not permitted).
    param([string]$LinkPath, [string]$TargetPath)
    if (Test-Path (Join-Path $LinkPath "__init__.py")) { return }
    if (Test-Path -LiteralPath $LinkPath) {
        $item = Get-Item -LiteralPath $LinkPath -Force
        if ($item.LinkType) {
            Remove-Item -Force -LiteralPath $LinkPath
        } else {
            Remove-Item -Recurse -Force -LiteralPath $LinkPath
        }
    }
    $parent = Split-Path -Parent $LinkPath
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    try {
        New-Item -ItemType SymbolicLink -Path $LinkPath -Target $TargetPath -ErrorAction Stop | Out-Null
    } catch {
        New-Item -ItemType Directory -Path $LinkPath -Force | Out-Null
        Copy-Item -Force (Join-Path $TargetPath "__init__.py") $LinkPath
        Copy-Item -Force (Join-Path $TargetPath "plugin.yaml") $LinkPath
    }
}

# Gateway/API + provider: only if this machine also has a Hermes home.
if (Test-Path $HermesHome) {
    Copy-File `
        (Join-Path $Root "catalog\plugin.yaml") `
        (Join-Path $HermesHome "plugins\openrouter-picker\plugin.yaml")
    Copy-File `
        (Join-Path $Root "catalog\__init__.py") `
        (Join-Path $HermesHome "plugins\openrouter-picker\__init__.py")
    Copy-File `
        (Join-Path $Root "catalog\dashboard\manifest.json") `
        (Join-Path $HermesHome "plugins\openrouter-picker\dashboard\manifest.json")
    Copy-File `
        (Join-Path $Root "catalog\dashboard\plugin_api.py") `
        (Join-Path $HermesHome "plugins\openrouter-picker\dashboard\plugin_api.py")
    $dashInit = Join-Path $HermesHome "plugins\openrouter-picker\dashboard\__init__.py"
    if (-not (Test-Path (Split-Path $dashInit))) {
        New-Item -ItemType Directory -Path (Split-Path $dashInit) -Force | Out-Null
    }
    if (-not (Test-Path $dashInit)) {
        New-Item -ItemType File -Path $dashInit -Force | Out-Null
    }

    # Provider share point + per-profile wiring (see install.sh): provider discovery is
    # per-home, and secondary profiles' plugins\model-providers\or-picker links target here.
    $oneTree = Join-Path $HermesHome "plugins\openrouter-picker"
    $sharePoint = Join-Path $HermesHome "plugins\model-providers\or-picker"
    Ensure-ProviderLink -LinkPath $sharePoint -TargetPath $oneTree
    $profilesDir = Join-Path $HermesHome "profiles"
    foreach ($profHome in (Get-ChildItem -Directory -Path $profilesDir -ErrorAction SilentlyContinue)) {
        Ensure-ProviderLink `
            -LinkPath (Join-Path $profHome.FullName "plugins\model-providers\or-picker") `
            -TargetPath $oneTree
    }

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
    Write-Host "Installed API and provider into $HermesHome"
} else {
    Write-Host "No $HermesHome — installed desktop plugin only."
    Write-Host "Run install.sh on the gateway host for the API and provider."
}

Write-Host "Desktop plugin: $DesktopRoot\desktop-plugins\openrouter-picker\plugin.js"
Write-Host "Enable on the gateway: hermes plugins enable openrouter-picker --no-allow-tool-override"
Write-Host "Then: Ctrl+K → Reload desktop plugins"

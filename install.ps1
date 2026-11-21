#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$INSTALL_ROOT = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:USERPROFILE ".hermes" }
$DesktopRoot = Join-Path $env:LOCALAPPDATA "hermes"

# Detect if $INSTALL_ROOT is profile-scoped (<root>/profiles/<name>).
# Path-component normalization: covers both supported separators, doubled
# separators and trailing separators; when the path ends with profiles/<name>
# (a single path component) the install root is the prefix above it.
$normPath = $INSTALL_ROOT.TrimEnd('\', '/')
$sep = if ($normPath.Contains('\')) { '\' } else { '/' }
$lead = ''
if ($normPath.StartsWith('\\')) { $lead = '\\' } elseif ($normPath.StartsWith('/')) { $lead = '/' }
$components = @($normPath -split '[\\/]+' | Where-Object { $_ -ne '' })
if ($components.Count -ge 3 -and $components[$components.Count - 2] -eq 'profiles') {
    $components = @($components[0..($components.Count - 3)])
}
if ($components.Count -ge 1) {
    $INSTALL_ROOT = $lead + ($components -join $sep)
} else {
    $INSTALL_ROOT = $sep
}

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

# ---------------------------------------------------------------------------
# Provider-copy ownership. Real dirs at managed provider paths (Windows-fallback
# or manual copies) are classified BEFORE any destructive action:
#   * receipt-verified installer-owned copies    -> refreshed A->B in place
#   * known legacy bytes (exact historical pair) -> migrated in place
#   * bytes identical to the current one tree    -> adopted (receipt written)
#   * anything else (custom overrides, incomplete dirs) -> preserved + WARNING
# Unrelated files inside a copy are never deleted; the two managed files
# (__init__.py, plugin.yaml) are only rewritten when ownership is established.
# ---------------------------------------------------------------------------
$ReceiptName = "or-picker-install-receipt.txt"

function Get-Sha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
}

function Write-ProviderReceipt {
    param([string]$Dir, [string]$InitSha, [string]$PlugSha)
    $txt = "owner=openrouter-picker-installer`nschema=1`ninit_sha256=$InitSha`nplugin_sha256=$PlugSha"
    Set-Content -LiteralPath (Join-Path $Dir $ReceiptName) -Value $txt -Encoding ascii
}

function Get-ReceiptHash {
    param([string]$ReceiptPath, [string]$Key)
    foreach ($line in (Get-Content -LiteralPath $ReceiptPath)) {
        if ($line.StartsWith("$Key=")) {
            return $line.Substring($Key.Length + 1).Trim().ToLower()
        }
    }
    return $null
}

function Test-KnownLegacyPair {
    # Exact (init, plugin) pairs shipped by historical installers; see
    # install/known-legacy-pairs.txt (generated from the repository's history).
    param([string]$InitSha, [string]$PlugSha)
    $reg = Join-Path (Join-Path $Root "install") "known-legacy-pairs.txt"
    if (-not (Test-Path -LiteralPath $reg)) { return $false }
    foreach ($line in (Get-Content -LiteralPath $reg)) {
        if (-not $line -or $line.TrimStart().StartsWith('#')) { continue }
        $parts = @($line.Trim() -split '\s+')
        if ($parts.Count -ge 2 -and $parts[0].ToLower() -eq $InitSha -and $parts[1].ToLower() -eq $PlugSha) {
            return $true
        }
    }
    return $false
}

function Bump-RescanSignal {
    # A running gateway's per-home discovery re-scans a home's plugins ONLY when
    # the plugins/model-providers dir mtime changes, so bump it on every pass.
    param([string]$Dir)
    if ($Dir -and (Test-Path -LiteralPath $Dir)) {
        (Get-Item -LiteralPath $Dir).LastWriteTime = Get-Date
    }
}

function Ensure-ProviderLink {
    # Make $LinkPath discoverable as a model-provider dir (symlink to $TargetPath,
    # falling back to an installer-owned real copy when symlinks are not permitted).
    # Real copies are refreshed only when ownership is established (receipt or
    # known legacy bytes); anything ambiguous is preserved with a visible warning.
    param([string]$LinkPath, [string]$TargetPath, [string]$OneTree)
    $parent = Split-Path -Parent $LinkPath
    $srcInit = Join-Path $OneTree "__init__.py"
    $srcPlug = Join-Path $OneTree "plugin.yaml"
    $srcInitSha = Get-Sha256 $srcInit
    $srcPlugSha = Get-Sha256 $srcPlug

    $item = Get-Item -LiteralPath $LinkPath -Force -ErrorAction SilentlyContinue
    if ($item -and $item.LinkType) {
        if (Test-Path -LiteralPath $LinkPath) {
            Bump-RescanSignal $parent
            return   # working symlinked provider
        }
        Remove-Item -Force -LiteralPath $LinkPath   # dangling link only
        $item = $null
    }
    if ($item) {
        if (-not $item.PSIsContainer) {
            Write-Host "WARNING: preserving $LinkPath (exists but is not a directory); left unchanged"
            Bump-RescanSignal $parent
            return
        }
        # Real directory: classify by ownership before touching anything.
        $initF = Join-Path $LinkPath "__init__.py"
        $plugF = Join-Path $LinkPath "plugin.yaml"
        $rcpt = Join-Path $LinkPath $ReceiptName
        $initSha = $null
        $plugSha = $null
        if (Test-Path -LiteralPath $initF) { $initSha = Get-Sha256 $initF }
        if (Test-Path -LiteralPath $plugF) { $plugSha = Get-Sha256 $plugF }
        if (Test-Path -LiteralPath $rcpt) {
            $rInit = Get-ReceiptHash $rcpt "init_sha256"
            $rPlug = Get-ReceiptHash $rcpt "plugin_sha256"
            if ($initSha -and $plugSha -and ($initSha -eq $rInit) -and ($plugSha -eq $rPlug)) {
                # Installer-owned copy: the receipt verifies these are our bytes.
                if (($initSha -ne $srcInitSha) -or ($plugSha -ne $srcPlugSha)) {
                    Copy-Item -Force $srcInit $initF
                    Copy-Item -Force $srcPlug $plugF
                    Write-ProviderReceipt $LinkPath $srcInitSha $srcPlugSha
                    Write-Host "Refreshed installer-owned provider copy $LinkPath (version A -> B)"
                }
                Bump-RescanSignal $parent
                return
            }
            $initOk = (-not $initSha) -or ($initSha -eq $rInit)
            $plugOk = (-not $plugSha) -or ($plugSha -eq $rPlug)
            if ($initOk -and $plugOk -and ($initSha -or $plugSha)) {
                # Every present managed file still matches the receipt: restore.
                Copy-Item -Force $srcInit $initF
                Copy-Item -Force $srcPlug $plugF
                Write-ProviderReceipt $LinkPath $srcInitSha $srcPlugSha
                Write-Host "Restored installer-owned provider copy $LinkPath (missing or stale managed files)"
                Bump-RescanSignal $parent
                return
            }
            Write-Host "WARNING: preserving custom provider copy $LinkPath (files changed since the installer wrote them); left unchanged"
            Bump-RescanSignal $parent
            return
        }
        # No receipt: recognize imported current bytes or known legacy bytes.
        if ($initSha -and $plugSha -and ($initSha -eq $srcInitSha) -and ($plugSha -eq $srcPlugSha)) {
            Write-ProviderReceipt $LinkPath $srcInitSha $srcPlugSha
            Write-Host "Adopted matching provider copy $LinkPath (wrote ownership receipt)"
        } elseif ($initSha -and $plugSha -and (Test-KnownLegacyPair $initSha $plugSha)) {
            Copy-Item -Force $srcInit $initF
            Copy-Item -Force $srcPlug $plugF
            Write-ProviderReceipt $LinkPath $srcInitSha $srcPlugSha
            Write-Host "Migrated known legacy provider copy $LinkPath to the current one-tree files"
        } elseif ((-not $initSha) -or (-not $plugSha)) {
            Write-Host "WARNING: preserving provider dir $LinkPath (missing __init__.py or plugin.yaml and not installer-owned); left unchanged"
        } else {
            Write-Host "WARNING: preserving custom provider copy $LinkPath (not installer-owned); left unchanged"
        }
        Bump-RescanSignal $parent
        return
    }

    # Missing or dangling: create the canonical symlink, falling back to an
    # installer-owned real copy (with receipt) when symlinks are not permitted.
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    try {
        New-Item -ItemType SymbolicLink -Path $LinkPath -Target $TargetPath -ErrorAction Stop | Out-Null
    } catch {
        New-Item -ItemType Directory -Path $LinkPath -Force | Out-Null
        Copy-Item -Force $srcInit $LinkPath
        Copy-Item -Force $srcPlug $LinkPath
        Write-ProviderReceipt $LinkPath $srcInitSha $srcPlugSha
        Write-Host "Symlinks unavailable here; created installer-owned provider copy $LinkPath"
    }
    Bump-RescanSignal $parent
}

# Gateway/API + provider: only if this machine also has a Hermes home.
if (Test-Path $INSTALL_ROOT) {
    Copy-File `
        (Join-Path $Root "catalog\plugin.yaml") `
        (Join-Path $INSTALL_ROOT "plugins\openrouter-picker\plugin.yaml")
    Copy-File `
        (Join-Path $Root "catalog\__init__.py") `
        (Join-Path $INSTALL_ROOT "plugins\openrouter-picker\__init__.py")
    Copy-File `
        (Join-Path $Root "catalog\dashboard\manifest.json") `
        (Join-Path $INSTALL_ROOT "plugins\openrouter-picker\dashboard\manifest.json")
    Copy-File `
        (Join-Path $Root "catalog\dashboard\plugin_api.py") `
        (Join-Path $INSTALL_ROOT "plugins\openrouter-picker\dashboard\plugin_api.py")
    $dashInit = Join-Path $INSTALL_ROOT "plugins\openrouter-picker\dashboard\__init__.py"
    if (-not (Test-Path (Split-Path $dashInit))) {
        New-Item -ItemType Directory -Path (Split-Path $dashInit) -Force | Out-Null
    }
    if (-not (Test-Path $dashInit)) {
        New-Item -ItemType File -Path $dashInit -Force | Out-Null
    }

    # Provider share point + per-profile wiring (see install.sh): provider discovery is
    # per-home, and secondary profiles' plugins\model-providers\or-picker links target here.
    $oneTree = Join-Path $INSTALL_ROOT "plugins\openrouter-picker"
    $sharePoint = Join-Path $INSTALL_ROOT "plugins\model-providers\or-picker"
    Ensure-ProviderLink -LinkPath $sharePoint -TargetPath $oneTree -OneTree $oneTree
    $profilesDir = Join-Path $INSTALL_ROOT "profiles"
    foreach ($profHome in (Get-ChildItem -Directory -Path $profilesDir -ErrorAction SilentlyContinue)) {
        Ensure-ProviderLink `
            -LinkPath (Join-Path $profHome.FullName "plugins\model-providers\or-picker") `
            -TargetPath $sharePoint `
            -OneTree $oneTree
    }

    $jsonDest = Join-Path $INSTALL_ROOT "openrouter-supplemental-models.json"
    $jsonItem = Get-Item -LiteralPath $jsonDest -ErrorAction SilentlyContinue
    if ($jsonItem -and $jsonItem.LinkType) {
        Write-Host "Refusing to overwrite symlink $jsonDest (unlink it first so a git pull cannot wipe your list)"
    } elseif (-not $jsonItem) {
        Copy-Item (Join-Path $Root "openrouter-supplemental-models.json") $jsonDest
        Write-Host "Wrote empty starter $jsonDest"
    } else {
        Write-Host "Left existing $jsonDest in place"
    }
    Write-Host "Installed API and provider into $INSTALL_ROOT"
} else {
    Write-Host "No $INSTALL_ROOT — installed desktop plugin only."
    Write-Host "Run install.sh on the gateway host for the API and provider."
}

Write-Host "Desktop plugin: $DesktopRoot\desktop-plugins\openrouter-picker\plugin.js"
Write-Host "Enable on the gateway: hermes plugins enable openrouter-picker --no-allow-tool-override"
Write-Host "Then: Ctrl+K → Reload desktop plugins"

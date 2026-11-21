#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

# Detect if HERMES_HOME is profile-scoped (<root>/profiles/<name>).
# Normalize trailing separators first so a scoped root with a trailing slash is
# still recognized, then strip the /profiles/<name> suffix to find the install root.
while [ "$HERMES_HOME" != "/" ] && [ "${HERMES_HOME%/}" != "$HERMES_HOME" ]; do
  HERMES_HOME="${HERMES_HOME%/}"
done
if [[ "$HERMES_HOME" =~ ^(.+)/profiles/[^/]+$ ]]; then
  INSTALL_ROOT="${HERMES_HOME%/profiles/*}"
  [ -n "$INSTALL_ROOT" ] || INSTALL_ROOT="/"
else
  INSTALL_ROOT="$HERMES_HOME"
fi

copy_file() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
}

if command -v sha256sum >/dev/null 2>&1; then
  sha256_of() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null 2>&1; then
  sha256_of() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
  sha256_of() { openssl dgst -sha256 "$1" | awk '{print $NF}'; }
fi

# ---------------------------------------------------------------------------
# Provider-copy ownership. Real dirs at managed provider paths (Windows-fallback
# or manual copies) are classified BEFORE any destructive action:
#   * receipt-verified installer-owned copies  -> refreshed A->B in place
#   * known legacy bytes (exact historical pair) -> migrated in place
#   * bytes identical to the current one tree -> adopted (receipt written)
#   * anything else (custom overrides, incomplete dirs) -> preserved + WARNING
# Unrelated files inside a copy are never deleted; the two managed files
# (__init__.py, plugin.yaml) are only rewritten when ownership is established.
# ---------------------------------------------------------------------------
RECEIPT_NAME="or-picker-install-receipt.txt"
LEGACY_PAIRS="$ROOT/install/known-legacy-pairs.txt"

write_receipt() {
  # write_receipt <dir> <init_sha> <plugin_sha>
  printf 'owner=openrouter-picker-installer\nschema=1\ninit_sha256=%s\nplugin_sha256=%s\n' \
    "$2" "$3" > "$1/$RECEIPT_NAME"
}

receipt_hash() {
  # receipt_hash <receipt> <key> -> value (possibly empty); CR-safe
  sed -n "s/^$2=//p" "$1" | head -n 1 | tr -d '\r'
}

known_legacy_pair() {
  # known_legacy_pair <init_sha> <plugin_sha> -> 0 when the exact pair was
  # shipped by a historical installer (see install/known-legacy-pairs.txt)
  [ -f "$LEGACY_PAIRS" ] || return 1
  local line ih ph rest
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    ih="${line%% *}"
    rest="${line#* }"
    ph="${rest%% *}"
    if [ "$ih" = "$1" ] && [ "$ph" = "$2" ]; then
      return 0
    fi
  done < "$LEGACY_PAIRS"
  return 1
}

wire_provider_dir() {
  # wire_provider_dir <target> <symlink_dest> <one_tree> <model-providers dir>
  # Makes <target> discoverable as a model-provider dir and bumps <model-providers
  # dir>'s mtime (the re-scan signal a running gateway's per-home discovery needs).
  local target="$1" link_dest="$2" one="$3" mp_parent="$4"
  local src_init="$one/__init__.py" src_plug="$one/plugin.yaml"
  local sih sph
  sih=$(sha256_of "$src_init")
  sph=$(sha256_of "$src_plug")

  if [ -L "$target" ]; then
    if [ -e "$target" ]; then
      touch "$mp_parent" 2>/dev/null || true
      return 0   # working symlinked provider
    fi
    rm -f "$target"   # dangling link only (rm never follows a bare symlink arg)
  elif [ -e "$target" ] && [ ! -d "$target" ]; then
    echo "WARNING: preserving $target (exists but is not a directory); left unchanged"
    touch "$mp_parent" 2>/dev/null || true
    return 0
  fi

  if [ ! -e "$target" ]; then
    mkdir -p "$(dirname "$target")" "$mp_parent"
    ln -s "$link_dest" "$target"
    touch "$mp_parent" 2>/dev/null || true
    return 0
  fi

  # Real directory: classify by ownership before touching anything.
  local init_f="$target/__init__.py" plug_f="$target/plugin.yaml" rcpt="$target/$RECEIPT_NAME"
  local ih="" ph="" rh rp
  [ -f "$init_f" ] && ih=$(sha256_of "$init_f")
  [ -f "$plug_f" ] && ph=$(sha256_of "$plug_f")

  if [ -f "$rcpt" ]; then
    rh=$(receipt_hash "$rcpt" init_sha256)
    rp=$(receipt_hash "$rcpt" plugin_sha256)
    if [ -n "$ih" ] && [ -n "$ph" ] && [ "$ih" = "$rh" ] && [ "$ph" = "$rp" ]; then
      # Installer-owned copy: the receipt verifies these are our bytes (version A).
      if [ "$ih" != "$sih" ] || [ "$ph" != "$sph" ]; then
        cp "$src_init" "$init_f"
        cp "$src_plug" "$plug_f"
        write_receipt "$target" "$sih" "$sph"
        echo "Refreshed installer-owned provider copy $target (version A -> B)"
      fi
      touch "$mp_parent" 2>/dev/null || true
      return 0
    fi
    if { [ -n "$ih" ] || [ -n "$ph" ]; } && { [ -z "$ih" ] || [ "$ih" = "$rh" ]; } && { [ -z "$ph" ] || [ "$ph" = "$rp" ]; }; then
      # Every present managed file still matches the receipt: restore/refresh.
      cp "$src_init" "$init_f"
      cp "$src_plug" "$plug_f"
      write_receipt "$target" "$sih" "$sph"
      echo "Restored installer-owned provider copy $target (missing or stale managed files)"
      touch "$mp_parent" 2>/dev/null || true
      return 0
    fi
    echo "WARNING: preserving custom provider copy $target (files changed since the installer wrote them); left unchanged"
    touch "$mp_parent" 2>/dev/null || true
    return 0
  fi

  # No receipt: recognize imported current bytes or known legacy bytes.
  if [ -n "$ih" ] && [ -n "$ph" ] && [ "$ih" = "$sih" ] && [ "$ph" = "$sph" ]; then
    write_receipt "$target" "$sih" "$sph"
    echo "Adopted matching provider copy $target (wrote ownership receipt)"
    touch "$mp_parent" 2>/dev/null || true
    return 0
  fi
  if [ -n "$ih" ] && [ -n "$ph" ] && known_legacy_pair "$ih" "$ph"; then
    cp "$src_init" "$init_f"
    cp "$src_plug" "$plug_f"
    write_receipt "$target" "$sih" "$sph"
    echo "Migrated known legacy provider copy $target to the current one-tree files"
    touch "$mp_parent" 2>/dev/null || true
    return 0
  fi
  if [ -z "$ih" ] || [ -z "$ph" ]; then
    echo "WARNING: preserving provider dir $target (missing __init__.py or plugin.yaml and not installer-owned); left unchanged"
  else
    echo "WARNING: preserving custom provider copy $target (not installer-owned); left unchanged"
  fi
  touch "$mp_parent" 2>/dev/null || true
  return 0
}

copy_file "$ROOT/catalog/desktop/plugin.js" \
  "$INSTALL_ROOT/desktop-plugins/openrouter-picker/plugin.js"

copy_file "$ROOT/catalog/plugin.yaml" \
  "$INSTALL_ROOT/plugins/openrouter-picker/plugin.yaml"
copy_file "$ROOT/catalog/__init__.py" \
  "$INSTALL_ROOT/plugins/openrouter-picker/__init__.py"

mkdir -p "$INSTALL_ROOT/plugins/openrouter-picker/dashboard"
copy_file "$ROOT/catalog/dashboard/manifest.json" \
  "$INSTALL_ROOT/plugins/openrouter-picker/dashboard/manifest.json"
copy_file "$ROOT/catalog/dashboard/plugin_api.py" \
  "$INSTALL_ROOT/plugins/openrouter-picker/dashboard/plugin_api.py"
: > "$INSTALL_ROOT/plugins/openrouter-picker/dashboard/__init__.py"

# Provider share point. Hermes discovers model-provider plugins PER HOME
# ($INSTALL_ROOT/plugins/model-providers/<name>/), so one flat install registers OR Picker
# for the default profile only. Secondary profile homes' `plugins/model-providers/or-picker`
# links target this path; older installs kept a split provider copy here and the one-plugin
# restructure removed it, leaving those links dangling — non-default profiles then lost the
# provider and their model picker asked for the API key. Point the legacy path at the one tree.
share_point="$INSTALL_ROOT/plugins/model-providers/or-picker"
one_tree="$INSTALL_ROOT/plugins/openrouter-picker"
wire_provider_dir "$share_point" "$one_tree" "$one_tree" "$INSTALL_ROOT/plugins/model-providers"

# Wire every profile home to the share point (missing or dangling -> create/repair;
# real copies -> ownership-classified refresh or preserved override).
for prof_home in "$INSTALL_ROOT/profiles"/*/; do
  [ -d "$prof_home" ] || continue
  wire_provider_dir "${prof_home}plugins/model-providers/or-picker" \
    "$share_point" "$one_tree" "${prof_home}plugins/model-providers"
done

json_dest="$INSTALL_ROOT/openrouter-supplemental-models.json"
if [ -L "$json_dest" ]; then
  echo "Refusing to overwrite symlink $json_dest (unlink it first so a git pull cannot wipe your list)"
elif [ ! -e "$json_dest" ]; then
  cp "$ROOT/openrouter-supplemental-models.json" "$json_dest"
  echo "Wrote empty starter $json_dest"
else
  echo "Left existing $json_dest in place"
fi

echo "Installed into $INSTALL_ROOT"
echo "Enable: hermes plugins enable openrouter-picker --no-allow-tool-override"
echo "Then: Ctrl/Cmd+K → Reload desktop plugins"
echo "Composer provider name stays OR Picker. If the desktop app is on another machine, copy catalog/desktop/plugin.js there (see README)."

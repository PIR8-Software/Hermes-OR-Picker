#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

copy_file() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
}

copy_file "$ROOT/catalog/desktop/plugin.js" \
  "$HERMES_HOME/desktop-plugins/openrouter-picker/plugin.js"

copy_file "$ROOT/catalog/plugin.yaml" \
  "$HERMES_HOME/plugins/openrouter-picker/plugin.yaml"
copy_file "$ROOT/catalog/__init__.py" \
  "$HERMES_HOME/plugins/openrouter-picker/__init__.py"

mkdir -p "$HERMES_HOME/plugins/openrouter-picker/dashboard"
copy_file "$ROOT/catalog/dashboard/manifest.json" \
  "$HERMES_HOME/plugins/openrouter-picker/dashboard/manifest.json"
copy_file "$ROOT/catalog/dashboard/plugin_api.py" \
  "$HERMES_HOME/plugins/openrouter-picker/dashboard/plugin_api.py"
: > "$HERMES_HOME/plugins/openrouter-picker/dashboard/__init__.py"

# Provider share point. Hermes discovers model-provider plugins PER HOME
# ($HERMES_HOME/plugins/model-providers/<name>/), so one flat install registers OR Picker
# for the default profile only. Secondary profile homes' `plugins/model-providers/or-picker`
# links target this path; older installs kept a split provider copy here and the one-plugin
# restructure removed it, leaving those links dangling — non-default profiles then lost the
# provider and their model picker asked for the API key. Point the legacy path at the one tree.
share_point="$HERMES_HOME/plugins/model-providers/or-picker"
one_tree="$HERMES_HOME/plugins/openrouter-picker"
if [ -L "$share_point" ]; then
  rm -f "$share_point"
elif [ -e "$share_point" ]; then
  rm -rf "$share_point"   # stale split copy, superseded by the one tree
fi
mkdir -p "$HERMES_HOME/plugins/model-providers"
ln -s "$one_tree" "$share_point"

# Wire every profile home to the share point (missing or dangling -> create/repair).
for prof_home in "$HERMES_HOME"/profiles/*/; do
  [ -d "$prof_home" ] || continue
  link="${prof_home}plugins/model-providers/or-picker"
  if [ -f "$link/__init__.py" ]; then
    # Link already resolves (real copy or share-point link). Still bump the parent
    # model-providers dir mtime: a running gateway's per-home discovery re-scans on a
    # dir-mtime change ONLY. A share-point-only repair resolves these links without
    # touching this dir's mtime, so a live backend never re-scans and OR Picker stays
    # unregistered ("Set up OR Picker") until a restart. Touching the dir makes the next
    # lookup re-scan and register it — no restart needed. The link itself is left alone.
    touch "${prof_home}plugins/model-providers" 2>/dev/null || true
    continue   # working provider dir (real copy or resolving link): leave it
  fi
  rm -rf "$link"   # dangling link or stale remains (rm never follows a bare symlink arg)
  mkdir -p "${prof_home}plugins/model-providers"
  ln -s "$share_point" "$link"
done

json_dest="$HERMES_HOME/openrouter-supplemental-models.json"
if [ -L "$json_dest" ]; then
  echo "Refusing to overwrite symlink $json_dest (unlink it first so a git pull cannot wipe your list)"
elif [ ! -e "$json_dest" ]; then
  cp "$ROOT/openrouter-supplemental-models.json" "$json_dest"
  echo "Wrote empty starter $json_dest"
else
  echo "Left existing $json_dest in place"
fi

echo "Installed into $HERMES_HOME"
echo "Enable: hermes plugins enable openrouter-picker --no-allow-tool-override"
echo "Then: Ctrl/Cmd+K → Reload desktop plugins"
echo "Composer provider name stays OR Picker. If the desktop app is on another machine, copy catalog/desktop/plugin.js there (see README)."

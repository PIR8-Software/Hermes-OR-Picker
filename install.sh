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

copy_file "$ROOT/src/desktop-plugin/plugin.js" \
  "$HERMES_HOME/desktop-plugins/openrouter-picker/plugin.js"

copy_file "$ROOT/src/backend-api/plugin.yaml" \
  "$HERMES_HOME/plugins/openrouter-picker/plugin.yaml"
copy_file "$ROOT/src/backend-api/__init__.py" \
  "$HERMES_HOME/plugins/openrouter-picker/__init__.py"

mkdir -p "$HERMES_HOME/plugins/openrouter-picker/dashboard"
copy_file "$ROOT/src/backend-api/manifest.json" \
  "$HERMES_HOME/plugins/openrouter-picker/dashboard/manifest.json"
copy_file "$ROOT/src/backend-api/plugin_api.py" \
  "$HERMES_HOME/plugins/openrouter-picker/dashboard/plugin_api.py"
: > "$HERMES_HOME/plugins/openrouter-picker/dashboard/__init__.py"

copy_file "$ROOT/src/model-provider/__init__.py" \
  "$HERMES_HOME/plugins/model-providers/or-picker/__init__.py"
copy_file "$ROOT/src/model-provider/plugin.yaml" \
  "$HERMES_HOME/plugins/model-providers/or-picker/plugin.yaml"

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
echo "If the desktop app is on another machine, copy plugin.js there (see README)."

# Hermes OR Picker

A Hermes Agent plugin: browse the full OpenRouter catalog, check the models you want, and use them as a **separate** composer provider named **OR Picker**.

Stock **OpenRouter** stays the official auto catalog. OR Picker is only your checked list.

Do **not** set `model_catalog.providers.openrouter.url` — that replaces the official OpenRouter tab.

## Requirements

- [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) with the desktop app
- An OpenRouter key already configured in Hermes (`OPENROUTER_API_KEY`)

## Install

```bash
git clone https://github.com/croycrabtree/Hermes-OR-Picker.git
cd Hermes-OR-Picker
./install.sh
hermes plugins enable openrouter-picker --no-allow-tool-override
```

Then in the desktop app: **Ctrl/Cmd+K → Reload desktop plugins**.

`install.sh` copies:

| Source | Destination |
|--------|-------------|
| `src/desktop-plugin/plugin.js` | `$HERMES_HOME/desktop-plugins/openrouter-picker/` |
| `src/backend-api/` | `$HERMES_HOME/plugins/openrouter-picker/` (+ `dashboard/`) |
| `src/model-provider/` | `$HERMES_HOME/plugins/model-providers/or-picker/` |
| `openrouter-supplemental-models.json` | `$HERMES_HOME/openrouter-supplemental-models.json` (skipped if already present) |

`$HERMES_HOME` defaults to `~/.hermes`.

### Split desktop / gateway

If Hermes Desktop runs on a different machine than the gateway:

1. Run `install.sh` on the **gateway** host (API + provider + JSON).
2. Copy `src/desktop-plugin/plugin.js` to the **desktop** machine:

```text
%LOCALAPPDATA%\hermes\desktop-plugins\openrouter-picker\plugin.js
```

(or `$HERMES_HOME/desktop-plugins/openrouter-picker/plugin.js` on Linux/macOS).

Python API changes need a dashboard remount on the gateway host. Do not restart the gateway from inside a live gateway chat.

## Use

1. Open the sidebar **OR Picker** page (or command palette → “Open OpenRouter Picker”).
2. Check models. Uncheck to remove them.
3. In the composer model picker, choose provider **OR Picker**.

Or:

```bash
hermes config set model.provider or-picker
hermes config set model.default xiaomi/mimo-v2.5
hermes config set model.base_url https://openrouter.ai/api/v1
```

New sessions pick this up.

## Architecture

```
Desktop UI  $HERMES_HOME/desktop-plugins/openrouter-picker/plugin.js
        ↓  /api/plugins/openrouter-picker/
Backend     $HERMES_HOME/plugins/openrouter-picker/dashboard/plugin_api.py
        ↓ writes
JSON        $HERMES_HOME/openrouter-supplemental-models.json
        ↓ read by
Provider    $HERMES_HOME/plugins/model-providers/or-picker/
            name: or-picker
            display: OR Picker
            base_url: https://openrouter.ai/api/v1
            auth: OPENROUTER_API_KEY
        ↓
hermes model picker → provider "OR Picker" (separate from OpenRouter)
```

## Files

| Path | Role |
|------|------|
| `openrouter-supplemental-models.json` | Starter curated list |
| `src/desktop-plugin/plugin.js` | Desktop UI |
| `src/backend-api/` | Dashboard FastAPI plugin |
| `src/model-provider/` | Hermes provider `or-picker` |
| `install.sh` | Copy into `$HERMES_HOME` |
| `AGENT_HANDOFF.md` | Agent pitfalls and deploy notes |

## Tests

```bash
uv run --with pytest pytest -q
```

## License

MIT

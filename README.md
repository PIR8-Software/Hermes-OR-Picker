# OpenRouter Picker

A Hermes Agent desktop plugin for managing your curated OpenRouter model list.

## What it does

- Shows your hand-picked OpenRouter models in a sidebar pane
- Add models manually or search the OpenRouter API
- Edit descriptions inline
- Remove models you no longer want
- Changes write directly to the supplemental models JSON that Hermes reads

## Architecture

```
~/.hermes/openrouter-supplemental-models.json  ← symlink to project
    ↑ read by hermes_cli/model_catalog.py (provider override)
    ↑ read/written by ~/.hermes/plugins/openrouter-picker/dashboard/plugin_api.py
    ↑ UI at ~/.hermes/desktop-plugins/openrouter-picker/plugin.js
```

## The supplemental models file

The model catalog config (`hermes config get model_catalog`) points to this file:

```yaml
model_catalog:
  providers:
    openrouter:
      url: file:///home/roy/.hermes/openrouter-supplemental-models.json
```

When set, this **replaces** the upstream curated list with your custom list.

## Files

| File | Purpose |
|------|---------|
| `openrouter-supplemental-models.json` | The model list (symlinked to `~/.hermes/`) |
| `~/.hermes/desktop-plugins/openrouter-picker/plugin.js` | Desktop UI pane |
| `~/.hermes/plugins/openrouter-picker/dashboard/plugin_api.py` | Backend API (FastAPI router) |
| `~/.hermes/plugins/openrouter-picker/plugin.yaml` | Plugin metadata |
| `~/.hermes/plugins/openrouter-picker/dashboard/manifest.json` | Dashboard manifest |

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/models` | List current models |
| POST | `/models` | Add a model `{id, description}` |
| PUT | `/models/{id}` | Update description |
| DELETE | `/models/{id}` | Remove a model |
| POST | `/search` | Search OpenRouter API `{q}` |
| POST | `/reorder` | Reorder models `{order: [...]}` |
| GET | `/config` | Show file path and symlink status |

## Setup

1. The supplemental JSON is symlinked from the project to `~/.hermes/`
2. Desktop plugin is in `~/.hermes/desktop-plugins/openrouter-picker/`
3. Backend plugin is in `~/.hermes/plugins/openrouter-picker/`
4. Plugin is registered in `plugins.enabled` in config.yaml
5. Reload desktop plugins from ⌘K in the Hermes desktop app

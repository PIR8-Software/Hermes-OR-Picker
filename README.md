# OpenRouter Picker

Desktop plugin + separate Hermes provider for Roy's curated OpenRouter models.

## Behavior

- **OpenRouter** in `hermes model` is the **default auto-populated** Hermes catalog again (42 curated models, refreshes from the docs manifest).
- **OR Picker** is a **separate provider**. It only lists models you select in the desktop plugin.
- Selecting a model in the plugin writes `openrouter-supplemental-models.json`. That file is what `or-picker` shows. Check/uncheck also busts `provider_models_cache.json` and invalidates the desktop `model-options` query so the composer list updates without restarting Hermes.exe.

The old `model_catalog.providers.openrouter.url` override (which **replaced** the whole OpenRouter list) is removed.

## Architecture

```
Desktop UI  ~/.hermes/desktop-plugins/openrouter-picker/plugin.js
        ↓  /api/plugins/openrouter-picker/
Backend     ~/.hermes/plugins/openrouter-picker/dashboard/plugin_api.py
        ↓ writes
JSON        ~/projects/openrouter-picker/openrouter-supplemental-models.json
            (symlinked to ~/.hermes/openrouter-supplemental-models.json)
        ↓ read by
Provider    ~/.hermes/plugins/model-providers/or-picker/
            name: or-picker
            display: OR Picker
            base_url: https://openrouter.ai/api/v1
            auth: OPENROUTER_API_KEY
        ↓
hermes model picker → provider "OR Picker" (separate from OpenRouter)
```

## Switch to a curated model

In the model picker choose provider **OR Picker**, then a selected model.

Or:

```bash
hermes config set model.provider or-picker
hermes config set model.default xiaomi/mimo-v2.5
hermes config set model.base_url https://openrouter.ai/api/v1
```

New sessions pick this up. Do not restart the gateway from inside a live gateway chat.

## Files

| Path | Role |
|------|------|
| `openrouter-supplemental-models.json` | Curated list |
| `src/desktop-plugin/plugin.js` | Desktop UI |
| `src/backend-api/` | Dashboard FastAPI plugin |
| `src/model-provider/` | Hermes provider `or-picker` |

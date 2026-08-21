# Agent Handoff — OpenRouter Picker

**Status:** Working. Sidebar catalog editor + composer provider **OR Picker** (separate from stock OpenRouter). Check/uncheck updates the composer list without restarting the desktop app.

Do not restart the Hermes gateway from inside a live gateway session.

---

## Goal (done)

Desktop plugin to browse the full OpenRouter catalog, check models into a curated list, and expose that list as a **separate** Hermes provider.

- **OpenRouter** = official auto catalog (~40 models).
- **OR Picker** = the user's checked list only.

Do **not** set `model_catalog.providers.openrouter.url` — that **replaces** the official OpenRouter tab.

---

## Install paths

| What | Path |
|------|------|
| Git | this repo (`main`) |
| Starter JSON (git) | `openrouter-supplemental-models.json` (**empty** — do not put personal picks here) |
| JSON (live) | `$HERMES_HOME/openrouter-supplemental-models.json` (**real file**, never a symlink to git) |
| Desktop UI | `$HERMES_HOME/desktop-plugins/openrouter-picker/plugin.js` |
| Desktop UI (Windows) | `%LOCALAPPDATA%\hermes\desktop-plugins\openrouter-picker\plugin.js` |
| Dashboard API | `$HERMES_HOME/plugins/openrouter-picker/` |
| Provider | `$HERMES_HOME/plugins/model-providers/or-picker/` |

`$HERMES_HOME` is `~/.hermes` unless a profile is active.

If the desktop app and the gateway run on different machines, copy `plugin.js` to the desktop machine. The API and provider stay on the gateway host.

---

## Architecture

```
OpenRouter GET /api/v1/models
        ↓
dashboard plugin_api.py  /api/plugins/openrouter-picker/
  GET  /catalog
  GET  /models
  POST /models          add  (JSON body {id, description})
  POST /remove          remove (JSON body {id})  ← slashes + ~ aliases
  PUT/DELETE /models/{id:path}
        ↓ writes via Path.resolve() (keep symlink)
openrouter-supplemental-models.json
        ↓ also clears ~/.hermes/provider_models_cache.json["or-picker"]
        ↓
or-picker ProviderProfile.fetch_models() + live fallback_models
        ↓
composer provider tab "OR Picker"
```

Desktop plugin:

- `ctx.rest` (never raw `fetch`)
- `defaultEnabled: true`
- Hermes `Select` / `Checkbox` from `@hermes/plugin-sdk`
- After check/uncheck: `queryClient.invalidateQueries({ queryKey: ['model-options'] })`

---

## What works

- Sidebar **OR Picker** loads catalog, filters, details.
- Check/uncheck writes JSON.
- `~provider/...-latest` aliases are valid IDs.
- Composer shows **OpenRouter** (stock) and **OR Picker** (curated).
- Check/uncheck refreshes the composer list **without** quitting the desktop app (disk cache bust + React Query invalidate).

---

## Pitfalls

- **Two enables:** `plugins.enabled` is the Python dashboard plugin. Desktop enable is `defaultEnabled` + Electron localStorage. Gateway list ≠ sidebar.
- **`ctx.rest` body must be an object**, not `JSON.stringify` (double-encode 422).
- **`~` IDs:** OpenRouter latest aliases. `_valid_id` allows optional leading `~`.
- **Composer cache:** `$HERMES_HOME/provider_models_cache.json` key `or-picker`, 1h TTL / 7d SWR. Writes must `clear_provider_models_cache("or-picker")`. Snapshotting `fallback_models` at import blocks removes — `ORPickerProfile.__getattribute__('fallback_models')` reads the JSON live.
- **Write through the symlink:** `tmp.replace(MODELS_PATH.resolve())`. `rename` onto the symlink path turns it into a regular file.
- **Python API changes** need a dashboard remount (`systemctl --user restart hermes-dashboard.service` from a **separate** shell, or equivalent). Do not bounce the gateway from a live gateway chat. Dashboard restart blinks desktop sessions.
- Relays are unrelated. Do not kill `hermes relay` to debug the picker.

---

## Deploy checklist after code change

1. Copy `src/` into the live `$HERMES_HOME/` trees (desktop-plugin, dashboard plugin, model-provider), or re-run `./install.sh`.
2. If desktop is on another machine, copy `plugin.js` there.
3. Dashboard remount only if `plugin_api.py` or `or-picker/__init__.py` changed.
4. Desktop JS: file-watch or Ctrl/Cmd+K → Reload desktop plugins.

---

## Next (optional)

- Tighten ID regex if you care about `../` style false positives (catalog IDs only come from OpenRouter).
- Do not merge the curated list into stock OpenRouter unless the user asks.

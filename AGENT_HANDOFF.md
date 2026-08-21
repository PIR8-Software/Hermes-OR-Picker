# Agent Handoff — OpenRouter Picker

**Date:** 2026-08-21
**Session:** @session:default/20260821_022219_6ca62b
**Status:** Working. Sidebar catalog editor + composer provider **OR Picker** (separate from stock OpenRouter). Check/uncheck updates the composer list without restarting Hermes.exe.

Do not restart the Hermes gateway from inside a live gateway session.

---

## Goal (done)

Desktop plugin to browse the full OpenRouter catalog, check models into a curated list, and expose that list as a **separate** Hermes provider.

- **OpenRouter** = official auto catalog (~40 models).
- **OR Picker** = Roy’s checked list only.

Do **not** set `model_catalog.providers.openrouter.url` — that **replaces** the official OpenRouter tab.

---

## Live paths

| What | Path |
|------|------|
| Git | `/home/roy/projects/openrouter-picker` (`main`) |
| Curated JSON | `openrouter-supplemental-models.json` |
| Symlink | `~/.hermes/openrouter-supplemental-models.json` → project file |
| Desktop UI (VM) | `~/.hermes/desktop-plugins/openrouter-picker/plugin.js` |
| Desktop UI (Surface) | `C:\Users\<user>\AppData\Local\hermes\desktop-plugins\openrouter-picker\plugin.js` |
| Dashboard API | `~/.hermes/plugins/openrouter-picker/` |
| Provider | `~/.hermes/plugins/model-providers/or-picker/` |

Roy’s desktop is **Windows desktop** (`<desktop-host>`). After editing `plugin.js`, copy to Surface:

```bash
scp plugin.js <user>@<desktop-host>:C:/Users/<user>/Downloads/openrouter-picker-plugin.js
ssh <user>@<desktop-host> 'powershell -NoProfile -Command "Copy-Item -Force C:\Users\<user>\Downloads\openrouter-picker-plugin.js C:\Users\<user>\AppData\Local\hermes\desktop-plugins\openrouter-picker\plugin.js"'
```

SSH: `ssh <user>@<desktop-host>`

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

## What works (verified with Roy)

- Sidebar **OR Picker** loads catalog, filters, details.
- Check/uncheck writes JSON.
- `~provider/...-latest` aliases are valid IDs.
- Composer shows **OpenRouter** (stock) and **OR Picker** (curated).
- Check/uncheck refreshes the composer list **without** quitting Hermes.exe (disk cache bust + React Query invalidate).

---

## Pitfalls

- **Two enables:** `plugins.enabled` is the Python dashboard plugin. Desktop enable is `defaultEnabled` + Electron localStorage. Gateway list ≠ sidebar.
- **`ctx.rest` body must be an object**, not `JSON.stringify` (double-encode 422).
- **`~` IDs:** OpenRouter latest aliases. `_valid_id` allows optional leading `~`.
- **Composer cache:** `~/.hermes/provider_models_cache.json` key `or-picker`, 1h TTL / 7d SWR. Writes must `clear_provider_models_cache("or-picker")`. Snapshotting `fallback_models` at import blocks removes — `ORPickerProfile.__getattribute__('fallback_models')` reads the JSON live.
- **Write through the symlink:** `tmp.replace(MODELS_PATH.resolve())`. `rename` onto the symlink path turns it into a regular file.
- **Python API changes** need `hermes-dashboard.service` remount. Do not bounce the gateway from this chat. Dashboard restart blinks desktop sessions.
- **Surface vs VM:** UI lives on Surface; API lives on the VM dashboard `:9119`.
- Relays are unrelated. Do not kill `hermes relay` to debug the picker. `hermes-relay` systemd units were disabled this session because core `hermes relay` is invalid unless that plugin is enabled. Restore only from a non-gateway shell.

---

## Deploy checklist after code change

1. Copy `src/` into the live `~/.hermes/` trees (desktop-plugin, dashboard plugin, model-provider).
2. `scp` `plugin.js` to Surface (path above).
3. Dashboard remount only if `plugin_api.py` or `or-picker/__init__.py` changed: `systemctl --user restart hermes-dashboard.service` from a **separate** shell.
4. Desktop JS: file-watch or Ctrl+K → Reload desktop plugins.

---

## Next (optional)

- Tighten ID regex if you care about `../` style false positives (catalog IDs only come from OpenRouter).
- Restore hermes-relay from a non-gateway shell if mobile pairing is needed.
- Do not merge curated list into stock OpenRouter unless Roy asks.

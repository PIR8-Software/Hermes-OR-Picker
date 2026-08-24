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

## Features

- **Model Catalog** — browse 400+ OpenRouter models with filters (sort, modality, context, provider, free-only)
- **Model Badges** — NEW (last 2 weeks), DEFAULT (in Hermes default list), FREE, BATCH, tools 🔧, vision 👁, audio 🎤, image generation 🖼, agent, reasoning, long-ctx
- **Credits Balance** — live balance in header (green ≥$5, red <$5)
- **Analytics Page** — key info, balance, credits usage, BYOK usage, per-model breakdown with time periods (today/week/month/all), monthly forecast, price drop alerts
- **News Page** — OpenRouter blog posts from RSS feed with NEW badge
- **Changelog** — tracks new models, removed models, price changes since last check
- **Model Comparison** — select 2-5 models, side-by-side table with pricing, context, capabilities, benchmarks
- **Export/Import** — export/import curated list as JSON
- **Design Arena** — ELO rankings and win rates in expanded model details
- **Context Window Bar** — visual progress bar in expanded details
- **Provider Health** — uptime %, latency, throughput per provider (fetched on expand)
- **Cost Calculator** — enter input/output tokens, see estimated cost
- **Quick Test** — send a test prompt to any model from expanded details
- **Batch Variant Link** — click to search for `:batch` variant
- **Auto-categorize** — agent (tools+vision), reasoning, long-ctx badges
- **Management Key** — optional key for per-model analytics (stored in localStorage)

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
| Changelog snapshot | `$HERMES_HOME/openrouter-picker-changelog.json` |
| Price alerts snapshot | `$HERMES_HOME/openrouter-picker-price-alerts.json` |

`$HERMES_HOME` is `~/.hermes` unless a profile is active.

If the desktop app and the gateway run on different machines, copy `plugin.js` to the desktop machine. The API and provider stay on the gateway host.

---

## Architecture

```
OpenRouter GET /api/v1/models
        ↓
dashboard plugin_api.py  /api/plugins/openrouter-picker/
  GET  /catalog          full model catalog with filters
  GET  /models           curated list
  POST /models           add model (JSON body {id, description})
  POST /remove           remove model (JSON body {id})
  PUT/DELETE /models/{id:path}
  GET  /credits          account balance from /api/v1/credits
  GET  /blog             RSS feed from openrouter.ai/blog/feed.xml
  GET  /default-models   Hermes built-in OpenRouter model IDs
  GET  /analytics        key info, usage, BYOK from /api/v1/key
  GET  /activity         per-model usage from /api/v1/activity (management key)
  GET  /changelog        model changes since last snapshot
  GET  /price-alerts     price drops in curated models
  POST /test             send test prompt to model via /api/v1/chat/completions
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
- **Credits balance** in header (green ≥$5, red <$5).
- **Analytics page** with key info, balance, usage breakdowns, per-model activity, forecast, price alerts.
- **News page** with blog posts from RSS feed, NEW badge on new posts.
- **Changelog** tracks added/removed/price-changed models.
- **Model comparison** side-by-side table (up to 5 models).
- **Export/import** curated list as JSON.
- **Model badges**: NEW (2 weeks), DEFAULT, FREE, BATCH, tools, vision, audio, image gen, agent, reasoning, long-ctx.
- **Design Arena** benchmarks in expanded model details.
- **Context window bar** in expanded details.
- **Provider health** (uptime, latency, throughput) on expand.
- **Cost calculator** in expanded details.
- **Quick test** — send prompt to model from expanded details.
- **Batch variant link** — searches for `:batch` variant.

---

## Pitfalls

- **Two enables:** `plugins.enabled` is the Python dashboard plugin. Desktop enable is `defaultEnabled` + Electron localStorage. Gateway list ≠ sidebar.
- **`ctx.rest` body must be an object**, not `JSON.stringify` (double-encode 422).
- **`~` IDs:** OpenRouter latest aliases. `_valid_id` allows optional leading `~`.
- **Composer cache:** `$HERMES_HOME/provider_models_cache.json` key `or-picker`, 1h TTL / 7d SWR. Writes must `clear_provider_models_cache("or-picker")`. Snapshotting `fallback_models` at import blocks removes — `ORPickerProfile.__getattribute__('fallback_models')` reads the JSON live.
- **Write through the symlink:** `tmp.replace(MODELS_PATH.resolve())`. `rename` onto the symlink path turns it into a regular file.
- **Python API changes** need a dashboard remount (`systemctl --user restart hermes-dashboard.service` from a **separate** shell, or equivalent). Do not bounce the gateway from a live gateway chat. Dashboard restart blinks desktop sessions.
- Relays are unrelated. Do not kill `hermes relay` to debug the picker.
- **Desktop plugin path on Windows:** `%LOCALAPPDATA%\hermes\` (NOT `~\.hermes\`). The app reads from AppData, not the home directory.
- **Management key** for per-model analytics is stored in localStorage (`or-picker-mgmt-key`). Create at [openrouter.ai/settings/management-keys](https://openrouter.ai/settings/management-keys).
- **Blog NEW badge** uses localStorage (`or-picker-blog-last`). Clears when user opens the news view.
- **Changelog** saves snapshot to `$HERMES_HOME/openrouter-picker-changelog.json`. First run shows no changes.
- **Price alerts** saves snapshot to `$HERMES_HOME/openrouter-picker-price-alerts.json`. First run shows no alerts.
- **Quick test** uses the OpenRouter API key from Hermes secret store. Some models return "no endpoints" if unavailable.
- **Activity endpoint** requires a management key. Regular API key returns 0 items.
- **Endpoints API** (`/models/{id}/endpoints`) returns null for latency/throughput on some models. Provider health skips those.

---

## Deploy checklist after code change

1. Copy `src/` into the live `$HERMES_HOME/` trees (desktop-plugin, dashboard plugin, model-provider), or re-run `./install.sh`.
2. If desktop is on another machine, copy `plugin.js` to `%LOCALAPPDATA%\hermes\desktop-plugins\openrouter-picker\`.
3. Dashboard remount only if `plugin_api.py` or `or-picker/__init__.py` changed.
4. Desktop JS: file-watch or Ctrl/Cmd+K → Reload desktop plugins.

---

## Next (optional)

- Tighten ID regex if you care about `../` style false positives (catalog IDs only come from OpenRouter).
- Do not merge the curated list into stock OpenRouter unless the user asks.
- Add Analytics API (`/api/v1/analytics/query`) for richer time-series data.
- Add per-request logs if OpenRouter exposes them.

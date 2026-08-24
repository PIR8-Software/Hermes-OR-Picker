# Hermes OR Picker

A Hermes Agent plugin: browse the full OpenRouter catalog, check the models you want, and use them as a **separate** composer provider named **OR Picker**.

Stock **OpenRouter** stays the official auto catalog. OR Picker is only your checked list.

Do **not** set `model_catalog.providers.openrouter.url` — that replaces the official OpenRouter tab.

## Features

### Model Catalog
- Browse 400+ OpenRouter models with filters (sort, modality, context, provider, free-only)
- **Model Badges** — NEW (last 2 weeks), DEFAULT (in Hermes default list), FREE, BATCH, tools 🔧, vision 👁, audio 🎤, image generation 🖼
- **Auto-categorize** — agent (tools+vision), reasoning, long-ctx badges
- **Design Arena** — ELO rankings and win rates in expanded model details
- **Context window bar** — visual progress bar showing context length relative to 2M max
- **Provider health** — uptime %, latency, throughput per provider (fetched on expand)
- **Cost calculator** — enter input/output tokens, see estimated cost per model
- **Quick test** — send a test prompt to any model right from the picker
- **Batch variant link** — click to search for `:batch` variant (lower cost, slower)
- **View on OpenRouter** — link to full model page with complete description

### Model Comparison
- Click ⚖ on 2-5 models, then "⚖ Compare" button in header
- Side-by-side table: pricing, context, max output, tools, vision, reasoning, intelligence/coding/agentic scores, provider, batch, moderated

### Analytics Page (📊 button)
- **API Key info** — label, tier, BYOK in limit
- **🔑 Change Management Key** — input/save management key for per-model data
- **Balance** — remaining credits (green ≥$5, red <$5), limit, reset schedule
- **Account Credits** — total credits, total used, remaining (all keys)
- **Per-Key Usage** — today, this week, this month, all time (this key only)
- **BYOK Usage** — same breakdowns
- **Total Spend** — today, this week, this month, all time (from activity API)
- **Monthly Forecast** — projections from daily avg, weekly avg, current month pace
- **Price Drop Alerts** — notifies when curated models get cheaper
- **Usage by Model** — per-model cost, requests, tokens with time breakdowns (requires management key)

### News Page (📰 button)
- OpenRouter blog posts from RSS feed
- Title, description, date for each post
- Green **NEW** badge on new posts (auto-dismisses after viewing)

### Changelog (📋 button)
- Tracks new models, removed models, and price changes
- Saves a snapshot on each check, diffs against previous

### Export/Import
- 📤 button — export curated list as JSON
- 📥 button — import curated list from JSON

### Credits Balance
- Live balance in picker header (green ≥$5, red <$5)

## Requirements

- [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) with the desktop app
- An OpenRouter key already configured in Hermes (`OPENROUTER_API_KEY`)
- (Optional) Management key for per-model analytics — create at [openrouter.ai/settings/management-keys](https://openrouter.ai/settings/management-keys)

## Install

**Linux / macOS (gateway host):**

```bash
git clone https://github.com/PIR8-Software/Hermes-OR-Picker.git
cd Hermes-OR-Picker
./install.sh
hermes plugins enable openrouter-picker --no-allow-tool-override
```

**Windows (desktop app):**

```powershell
git clone https://github.com/PIR8-Software/Hermes-OR-Picker.git
cd Hermes-OR-Picker
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Then in the desktop app: **Ctrl/Cmd+K → Reload desktop plugins**.

The repo ships an **empty** curated list. Your picks are stored in `$HERMES_HOME/openrouter-supplemental-models.json` and are not overwritten on reinstall. Do not symlink that file to the git checkout — a pull would wipe your list.

`install.sh` copies:

| Source | Destination |
|--------|-------------|
| `src/desktop-plugin/plugin.js` | `$HERMES_HOME/desktop-plugins/openrouter-picker/` |
| `src/backend-api/` | `$HERMES_HOME/plugins/openrouter-picker/` (+ `dashboard/`) |
| `src/model-provider/` | `$HERMES_HOME/plugins/model-providers/or-picker/` |
| `openrouter-supplemental-models.json` | `$HERMES_HOME/openrouter-supplemental-models.json` (skipped if already present) |

`$HERMES_HOME` defaults to `~/.hermes`. On Windows, `install.ps1` always writes `plugin.js` to `%LOCALAPPDATA%\hermes\desktop-plugins\openrouter-picker\` and installs the API/provider only if a Hermes home exists on that machine.

### Split desktop / gateway

1. Run `install.sh` on the **gateway** host (API + provider + JSON).
2. Run `install.ps1` on the **Windows desktop** (or copy `plugin.js` to `%LOCALAPPDATA%\hermes\desktop-plugins\openrouter-picker\`).

Python API changes need a dashboard remount on the gateway host. Do not restart the gateway from inside a live gateway chat.

## Use

1. Open the sidebar **OR Picker** page (or command palette → "Open OpenRouter Picker").
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
  GET  /catalog          full model catalog
  GET  /models           curated list
  POST /models           add model
  POST /remove           remove model
  GET  /credits          account balance
  GET  /blog             RSS feed
  GET  /default-models   Hermes built-in IDs
  GET  /analytics        key info + usage
  GET  /activity         per-model usage (management key)
  GET  /changelog        model changes since last check
  GET  /price-alerts     price drops in curated models
  POST /test             send test prompt to model
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
| `openrouter-supplemental-models.json` | Empty starter list (live picks live under `$HERMES_HOME`) |
| `src/desktop-plugin/plugin.js` | Desktop UI |
| `src/backend-api/` | Dashboard FastAPI plugin |
| `src/model-provider/` | Hermes provider `or-picker` |
| `install.sh` | Copy into `$HERMES_HOME` (Linux/macOS) |
| `install.ps1` | Copy into `%LOCALAPPDATA%\hermes` (Windows) |
| `AGENT_HANDOFF.md` | Agent pitfalls and deploy notes |

## Tests

```bash
uv run --with pytest pytest -q
```

## License

MIT

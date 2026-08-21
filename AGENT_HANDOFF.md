# Agent Handoff — OpenRouter Picker

**Date:** 2026-08-21  
**Session:** @session:default/20260821_003607_9d8be4  
**Status:** Plugin code is in place. Desktop UI still not confirmed visible. Relays were broken by this session and stopped.

Do not restart the Hermes gateway from inside a live gateway session. SIGTERM kills the agent.

---

## Goal

Roy wants a **desktop plugin** that manages his **custom OpenRouter model list**.

Intended behavior:

1. Pull the **full** OpenRouter catalog (`https://openrouter.ai/api/v1/models`).
2. Filter/sort like openrouter.ai/models (newest, popular, price, context, free, provider, modality, min context).
3. Click to **select/deselect** models into the curated list.
4. Show **full model details**: input/output/cache prices, context, benchmarks, tools/vision/reasoning, etc.
5. That curated list is what Hermes shows in the OpenRouter picker (it currently **replaces** the upstream curated catalog, it does not merge).

Primary model in this session drifted to `grok-4.6` via `xai-oauth`. Earlier intent was GPT-5.6 SOL via Codex + OpenRouter fallback. Do not silently change model/fallback unless Roy asks.

---

## Repos and live install paths

| What | Path |
|------|------|
| Git project | `/home/roy/projects/openrouter-picker` (branch `main`) |
| Curated JSON (source of truth) | `/home/roy/projects/openrouter-picker/openrouter-supplemental-models.json` |
| Hermes symlink | `~/.hermes/openrouter-supplemental-models.json` → project file |
| Desktop plugin (VM) | `~/.hermes/desktop-plugins/openrouter-picker/plugin.js` |
| Desktop plugin (Surface) | `C:\Users\<user>\AppData\Local\hermes\desktop-plugins\openrouter-picker\plugin.js` |
| Backend plugin (VM) | `~/.hermes/plugins/openrouter-picker/` |
| Catalog override | `hermes config get model_catalog` → `providers.openrouter.url: file:///home/roy/.hermes/openrouter-supplemental-models.json` |

**Important:** Roy’s Hermes desktop app runs on **Windows desktop** (`<desktop-host>`, Win11). Desktop plugins load from the **Surface** `desktop-plugins` folder, not the VM. After editing `plugin.js`, `scp` it to the Surface.

SSH works: `ssh <user>@<desktop-host>`

---

## Architecture

```
OpenRouter API  GET /api/v1/models
        ↓
~/.hermes/plugins/openrouter-picker/dashboard/plugin_api.py
        FastAPI router mounted at /api/plugins/openrouter-picker/
        GET  /catalog   full catalog + selected flags (5 min cache)
        GET  /models    curated list
        POST /models    add
        PUT  /models/{id}
        DELETE /models/{id}
        POST /reorder
        GET  /config
        ↓ writes
openrouter-supplemental-models.json
        ↓ read by
hermes_cli/model_catalog.py  (_fetch_provider_override)
        ↓
Hermes model picker OpenRouter tab  (REPLACES upstream list, does not merge)
```

Desktop UI: `plugin.js` registers:

- `ROUTES_AREA` path `/openrouter-picker`
- `SIDEBAR_NAV_AREA` label `OR Picker`
- `PALETTE_AREA` “Open OpenRouter Picker”

This matches the working **polymarket-dashboard** pattern (`ctx.registerMany`, `defaultEnabled: true`).

`__init__.py` has a no-op `register(ctx)` so the **gateway** plugin loader stops warning. This plugin is not a gateway tool plugin.

`plugin.yaml` now has `api: dashboard/plugin_api.py`.

---

## What was already working before this session

- Supplemental JSON with 10 models.
- `model_catalog.providers.openrouter.url` override (replaces Hermes default OpenRouter list).
- Project created, JSON moved, symlink in place.

## What this session built

1. Project + git at `~/projects/openrouter-picker`.
2. FastAPI backend with catalog fetch, filters, full pricing/benchmark enrichment.
3. Desktop UI: catalog browser, checkboxes, expand-for-details, sort/filter.
4. Plugin registered in `plugins.enabled`: `android-emulator`, `brain-graph`, `openrouter-picker`.
5. Copied `plugin.js` to Surface.
6. Codebase Memory index: **OpenRouter-Picker** — 108 nodes, 241 edges, 0 skipped, 0 parse-partial.

## What is still broken / unverified

### Desktop plugin visibility (primary remaining UI task)

Roy never saw **OR Picker** in the sidebar.

Root cause found late: `defaultEnabled: false`. Gateway `plugins.enabled` ≠ desktop plugin enable. Desktop enable lives in Electron localStorage `hermes.desktop.pluginDecisions.v2`.

**Latest Surface file has `defaultEnabled: true`.** Next check:

1. On Surface: Ctrl+K → **Reload desktop plugins**.
2. Look for **OR Picker** in the left sidebar (same place as Polymarket).
3. If missing: fully quit Hermes.exe and reopen.
4. If still missing: Settings → Plugins (desktop plugins page, not `hermes plugins list`) and confirm OpenRouter Picker status is `loaded` not `error`/`disabled`.

If status is `error`, the toast/message is the real failure. Do not restart the gateway to debug a desktop JS load error.

### Relays (this session caused this)

I killed the long-running relay processes:

- PID 1045 `hermes relay start --port 8767`
- PID 1049 `hermes relay start --port 8768 --no-ssl`

Those had been up since Aug 11. Current Hermes CLI **does not have** a `relay` subcommand unless the **hermes-relay plugin is enabled**. systemd units `/etc/systemd/system/hermes-relay-{dev,stable}.service` were crash-looping (600+ restarts) because `/home/roy/.local/bin/hermes relay` is invalid.

I **stopped and disabled** those systemd units so they would stop looping.

**Do not re-enable those units as-is.** To restore relays:

1. Add `hermes-relay` to `plugins.enabled` (it is currently only in `plugins.entries`, not enabled).
2. Restart gateway from a **separate shell outside the gateway** (`systemctl --user restart hermes-gateway.service`).
3. Then `hermes relay start --port 8767` and `hermes relay start --port 8768 --no-ssl` using the venv hermes, or fix the systemd ExecStart to the venv binary **after** the plugin is enabled.
4. Original start command was:  
   `/home/roy/.hermes/hermes-agent/venv/bin/python /home/roy/.hermes/hermes-agent/hermes relay start --port 8767`

Desktop chat itself talks to dashboard `:9119` / gateway `:8642`. Relays are for mobile/media pairing, not required for the picker UI to appear.

### Cron I added then removed

`* * * * * /tmp/restart-hermes.sh` was created to bounce gateway. **Removed.** Confirm `crontab -l` is empty for roy.

### Model/fallback drift (not picker-specific, but happened)

During this work:

- `model.provider` / default drifted around (OpenRouter MiMo, then xAI Grok 4.6).
- Cron job `fb-plex-support-post` / id `97915aa9416b` skipped due to inference drift (`openai-codex/gpt-5.6-sol` → `openrouter/xiaomi/mimo-v2.5`).
- Do not “fix” that unless Roy asks. Pin or restore only with explicit instruction.

---

## Codebase Memory

Indexed just now:

| Project | Root | Nodes | Edges | Coverage |
|---------|------|------:|------:|----------|
| OpenRouter-Picker | `/home/roy/projects/openrouter-picker` | 108 | 241 | skipped=0, parse_partial=0 |
| PIR8 | `/home/roy/projects/PIR8Sales` | 2374 | 10204 | already indexed |
| JuliesCleaning | `/home/roy/projects/JuliesCleaning` | 1006 | 3822 | already indexed |
| TV-Tenderr | `/home/roy/projects/movie-swipe` | 809 | 2832 | already indexed |
| Hermes-Android-Emulator | `/home/roy/projects/hermes-android-emulator` | 202 | 526 | already indexed |

Re-index OpenRouter-Picker after any substantial plugin.js / plugin_api.py change.

---

## Next agent: exact first actions

1. Confirm Surface `plugin.js` contains `defaultEnabled: true` and matches VM.
2. Ask Roy to Reload desktop plugins (or quit/reopen Hermes.exe). Do not restart gateway for this.
3. If it loads: test catalog fetch, select/deselect, confirm JSON write + picker list.
4. If it errors: read the desktop plugin error string; fix JS. Polymarket is the working reference.
5. Only after UI works: restore hermes-relay **from a non-gateway shell**, not from this chat.
6. Do not merge custom list with Hermes upstream catalog unless Roy asks — current config **replaces** it.

---

## Pitfalls

- `model_catalog.providers.openrouter.url` **replaces** the upstream list. It does not merge.
- Desktop plugins ≠ gateway plugins.
- Never `hermes gateway restart` from inside the gateway process.
- Surface is the desktop-plugin machine; VM is the backend/API machine.
- `hermes relay` only exists when `hermes-relay` plugin is enabled.
- Do not nuke layout/storage. Icon buttons have no text labels (Roy UI preference) — this picker currently uses text chips; tighten later if he complains.

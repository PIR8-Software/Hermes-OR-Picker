"""
OpenRouter Picker — backend API for managing the supplemental model list.

Mounted at /api/plugins/openrouter-picker/ by Hermes dashboard.
Exposes every field the OpenRouter /api/v1/models endpoint returns.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, Request
except Exception:
    class APIRouter:
        def get(self, *_a, **_kw):
            return lambda fn: fn
        def post(self, *_a, **_kw):
            return lambda fn: fn
        def delete(self, *_a, **_kw):
            return lambda fn: fn
        def put(self, *_a, **_kw):
            return lambda fn: fn
    class Request:  # pragma: no cover
        pass

router = APIRouter()

MODELS_PATH = Path(os.environ.get(
    "OPENROUTER_PICKER_MODELS",
    str(Path.home() / ".hermes" / "openrouter-supplemental-models.json"),
))

OPENROUTER_API = "https://openrouter.ai/api/v1/models"
OPENROUTER_BLOG_FEED = "https://openrouter.ai/blog/feed.xml"

# Cache: key = query params hash → (data, timestamp)
_CATALOG_CACHE: dict[str, tuple[list[dict], float]] = {}
CATALOG_TTL = 300  # 5 minutes

# Blog feed cache
_BLOG_CACHE: tuple[list[dict], float] | None = None
BLOG_TTL = 1800  # 30 minutes


def _read_models() -> dict[str, Any]:
    if not MODELS_PATH.exists():
        return _empty_manifest()
    try:
        return json.loads(MODELS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return _empty_manifest()


def _invalidate_or_picker_cache() -> None:
    """Composer picker caches or-picker ids for 1h in provider_models_cache.json."""
    try:
        from hermes_cli.models import clear_provider_models_cache
        clear_provider_models_cache("or-picker")
        return
    except Exception:
        pass
    try:
        from hermes_constants import get_hermes_home
        path = get_hermes_home() / "provider_models_cache.json"
    except Exception:
        path = Path.home() / ".hermes" / "provider_models_cache.json"
    if not path.exists():
        return
    try:
        cache = json.loads(path.read_text())
        if isinstance(cache, dict) and "or-picker" in cache:
            del cache["or-picker"]
            path.write_text(json.dumps(cache))
    except Exception:
        pass


def _write_models(data: dict[str, Any]) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    target = MODELS_PATH.resolve() if MODELS_PATH.exists() else MODELS_PATH
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(target)
    _invalidate_or_picker_cache()


def _as_dict(body: Any) -> dict[str, Any]:
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return {}
    return body if isinstance(body, dict) else {}


def _valid_id(mid: str) -> bool:
    # OpenRouter "latest" aliases are ids like ~anthropic/claude-opus-latest
    return bool(re.match(r"^~?[A-Za-z0-9_.-]+/[A-Za-z0-9_.:/-]+$", mid))


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        raw = await request.json()
    except Exception:
        return {}
    return _as_dict(raw)


def _remove_id(mid: str) -> dict[str, Any]:
    data = _read_models()
    models = _get_models_list(data)
    before = len(models)
    models[:] = [m for m in models if m["id"] != mid]
    if len(models) == before:
        return {"error": f"Model {mid} not found"}
    _write_models(data)
    return {"ok": True, "removed": mid, "count": len(models)}


def _empty_manifest() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"source": "Supplemental OpenRouter picker models"},
        "providers": {
            "openrouter": {
                "metadata": {"display_name": "Supplemental OpenRouter models"},
                "models": [],
            }
        },
    }


def _get_models_list(data: dict) -> list[dict]:
    return data.setdefault("providers", {}).setdefault("openrouter", {}).setdefault("models", [])


def _parse_price(pricing: dict, key: str) -> float:
    """Parse a price string to per-million-tokens float."""
    try:
        return float(pricing.get(key, "0")) * 1_000_000
    except (ValueError, TypeError):
        return 0


def _enrich_model(m: dict, curated_ids: set[str]) -> dict[str, Any]:
    """Enrich a raw OpenRouter model with all display-friendly fields."""
    mid = m.get("id", "")
    pricing = m.get("pricing", {})
    arch = m.get("architecture", {})
    top = m.get("top_provider", {})
    bench = m.get("benchmarks", {})
    aa = bench.get("artificial_analysis", {}) if isinstance(bench, dict) else {}
    reasoning = m.get("reasoning", {})

    provider = mid.split("/")[0] if "/" in mid else ""

    variant = ""
    if mid.endswith(":free"):
        variant = "free"
    elif mid.endswith(":batch"):
        variant = "batch"

    created_ts = m.get("created", 0)
    created_str = ""
    if created_ts:
        try:
            created_str = datetime.fromtimestamp(created_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            pass

    return {
        # ── Identity ──
        "id": mid,
        "name": m.get("name", mid),
        "description": (m.get("description") or "")[:500],
        "canonical_slug": m.get("canonical_slug", ""),
        "huggingface_id": m.get("hugging_face_id"),
        "provider": provider,
        "variant": variant,
        "created": created_str,
        "created_ts": created_ts,
        "selected": mid in curated_ids,

        # ── Context & Limits ──
        "context_length": m.get("context_length", 0),
        "max_completion_tokens": top.get("max_completion_tokens", 0),
        "is_moderated": top.get("is_moderated", False),

        # ── Architecture ──
        "modality": arch.get("modality", ""),
        "input_modalities": arch.get("input_modalities", []) if isinstance(arch, dict) else [],
        "output_modalities": arch.get("output_modalities", []) if isinstance(arch, dict) else [],
        "tokenizer": arch.get("tokenizer", ""),
        "instruct_type": arch.get("instruct_type"),

        # ── Pricing (per million tokens) ──
        "prompt_price": _parse_price(pricing, "prompt"),
        "completion_price": _parse_price(pricing, "completion"),
        "image_price": _parse_price(pricing, "image"),
        "audio_price": _parse_price(pricing, "audio"),
        "cache_read_price": _parse_price(pricing, "input_cache_read"),
        "cache_write_price": _parse_price(pricing, "input_cache_write"),
        "web_search_price": pricing.get("web_search", ""),
        "reasoning_price": _parse_price(pricing, "internal_reasoning"),

        # ── Benchmarks ──
        "intelligence_index": aa.get("intelligence_index"),
        "coding_index": aa.get("coding_index"),
        "agentic_index": aa.get("agentic_index"),
        "design_arena": bench.get("design_arena", []) if isinstance(bench, dict) else [],

        # ── Reasoning ──
        "reasoning_enabled": reasoning.get("default_enabled", False) if isinstance(reasoning, dict) else False,
        "reasoning_mandatory": reasoning.get("mandatory", False) if isinstance(reasoning, dict) else False,
        "reasoning_efforts": reasoning.get("supported_efforts", []) if isinstance(reasoning, dict) else [],
        "reasoning_default_effort": reasoning.get("default_effort") if isinstance(reasoning, dict) else None,

        # ── Capabilities ──
        "supported_parameters": m.get("supported_parameters", []),
        "has_tools": "tools" in (m.get("supported_parameters") or []),
        "has_vision": bool(arch.get("input_modalities", [])) and "image" in (arch.get("input_modalities") or []),
        "expiration_date": m.get("expiration_date"),
        "knowledge_cutoff": m.get("knowledge_cutoff"),
    }


def _fetch_catalog(
    sort: str = "",
    output_modalities: str = "",
    supported_parameters: str = "",
    min_context: int = 0,
    max_prompt_price: float = -1,
    max_completion_price: float = -1,
) -> list[dict[str, Any]]:
    """Fetch the full OpenRouter model list with server-side filtering + caching."""
    cache_key = json.dumps({
        "sort": sort,
        "output_modalities": output_modalities,
        "supported_parameters": supported_parameters,
        "min_context": min_context,
        "max_prompt_price": max_prompt_price,
        "max_completion_price": max_completion_price,
    }, sort_keys=True)

    now = time.time()
    if cache_key in _CATALOG_CACHE:
        cached, ts = _CATALOG_CACHE[cache_key]
        if (now - ts) < CATALOG_TTL:
            return cached

    params: list[str] = []
    if sort:
        params.append(f"sort={sort}")
    if output_modalities:
        params.append(f"output_modalities={output_modalities}")
    if supported_parameters:
        params.append(f"supported_parameters={supported_parameters}")
    if min_context > 0:
        params.append(f"min_context_length={min_context}")
    if max_prompt_price >= 0:
        params.append(f"max_prompt_price={max_prompt_price}")
    if max_completion_price >= 0:
        params.append(f"max_completion_price={max_completion_price}")

    url = OPENROUTER_API
    if params:
        url += "?" + "&".join(params)

    try:
        import httpx
        resp = httpx.get(url, timeout=20)
        resp.raise_for_status()
        raw = resp.json().get("data", [])
    except Exception:
        return []

    curated_ids = set()
    data = _read_models()
    for m in _get_models_list(data):
        curated_ids.add(m["id"])

    enriched = [_enrich_model(m, curated_ids) for m in raw if m.get("id")]
    _CATALOG_CACHE[cache_key] = (enriched, now)
    return enriched


# ── GET /models ──────────────────────────────────────────────────────
@router.get("/models")
def get_models():
    data = _read_models()
    models = _get_models_list(data)
    return {"models": models, "count": len(models)}


# ── GET /catalog ─────────────────────────────────────────────────────
@router.get("/catalog")
def get_catalog(
    sort: str = "",
    output_modalities: str = "",
    supported_parameters: str = "",
    min_context_length: int = 0,
    max_prompt_price: float = -1,
    max_completion_price: float = -1,
):
    """Return the full OpenRouter model list with server-side filtering."""
    catalog = _fetch_catalog(
        sort=sort,
        output_modalities=output_modalities,
        supported_parameters=supported_parameters,
        min_context=min_context_length,
        max_prompt_price=max_prompt_price,
        max_completion_price=max_completion_price,
    )

    providers = sorted({m["provider"] for m in catalog if m["provider"]})
    modality_set: set[str] = set()
    for m in catalog:
        modality_set.update(m.get("output_modalities", []))

    return {
        "models": catalog,
        "count": len(catalog),
        "providers": providers,
        "modalities": sorted(modality_set),
    }


# ── POST /models ─────────────────────────────────────────────────────
@router.post("/models")
async def add_model(request: Request):
    body = await _json_body(request)
    mid = (body.get("id") or "").strip()
    desc = (body.get("description") or "").strip()
    if not mid:
        return {"error": "id required"}
    if body.get("remove"):
        return _remove_id(mid)
    if not _valid_id(mid):
        return {"error": f"Invalid model ID format: {mid}"}

    data = _read_models()
    models = _get_models_list(data)
    existing = {m["id"] for m in models}
    if mid in existing:
        return {"error": f"Model {mid} already in list"}

    models.append({"id": mid, "description": desc or mid})
    _write_models(data)
    return {"ok": True, "added": mid, "count": len(models)}


# ── POST /remove ─────────────────────────────────────────────────────
@router.post("/remove")
async def remove_model(request: Request):
    body = await _json_body(request)
    mid = (body.get("id") or "").strip()
    if not mid:
        return {"error": "id required"}
    return _remove_id(mid)


# ── PUT /models/{model_id} ──────────────────────────────────────────
@router.put("/models/{model_id:path}")
def update_model(model_id: str, body: dict | None = None):
    if not body:
        return {"error": "body required"}

    data = _read_models()
    models = _get_models_list(data)
    for m in models:
        if m["id"] == model_id:
            if "description" in body:
                m["description"] = body["description"]
            _write_models(data)
            return {"ok": True, "updated": model_id}
    return {"error": f"Model {model_id} not found"}


# ── DELETE /models/{model_id} ───────────────────────────────────────
@router.delete("/models/{model_id:path}")
def delete_model(model_id: str):
    return _remove_id(model_id)


# ── POST /reorder ───────────────────────────────────────────────────
@router.post("/reorder")
def reorder_models(body: dict | None = None):
    if not body or "order" not in body:
        return {"error": "body with 'order' list required"}
    new_order = body["order"]

    data = _read_models()
    models = _get_models_list(data)
    by_id = {m["id"]: m for m in models}
    reordered = []
    for mid in new_order:
        if mid in by_id:
            reordered.append(by_id.pop(mid))
    reordered.extend(by_id.values())

    data["providers"]["openrouter"]["models"] = reordered
    _write_models(data)
    return {"ok": True, "count": len(reordered)}


# ── GET /config ─────────────────────────────────────────────────────
@router.get("/config")
def get_config():
    return {
        "models_path": str(MODELS_PATH),
        "exists": MODELS_PATH.exists(),
        "is_symlink": MODELS_PATH.is_symlink() if MODELS_PATH.exists() else False,
        "resolved": str(MODELS_PATH.resolve()) if MODELS_PATH.exists() else None,
    }


# ── GET /blog ──────────────────────────────────────────────────────
def _parse_rss_feed(xml_text: str) -> list[dict[str, str]]:
    """Parse RSS/XML into a flat list of {title, link, description, pubDate}."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict[str, str]] = []
    for item in root.iter("item"):
        entry: dict[str, str] = {}
        for child in item:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag in ("title", "link", "description", "pubDate"):
                entry[tag] = (child.text or "").strip()
        if entry.get("title") and entry.get("link"):
            items.append(entry)
    return items


def _fetch_blog() -> list[dict[str, str]]:
    global _BLOG_CACHE
    now = time.time()
    if _BLOG_CACHE is not None:
        cached, ts = _BLOG_CACHE
        if (now - ts) < BLOG_TTL:
            return cached
    try:
        import httpx
        resp = httpx.get(OPENROUTER_BLOG_FEED, timeout=15)
        resp.raise_for_status()
        items = _parse_rss_feed(resp.text)
    except Exception:
        items = []
    _BLOG_CACHE = (items, now)
    return items


@router.get("/blog")
def get_blog(limit: int = 15):
    items = _fetch_blog()
    return {"posts": items[:limit], "count": min(len(items), limit)}


# ── GET /credits ───────────────────────────────────────────────────
_CREDITS_CACHE: tuple[dict, float] | None = None
CREDITS_TTL = 60  # 1 minute


def _get_openrouter_key() -> str:
    """Get OpenRouter API key from environment or Hermes secret store."""
    import os
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    try:
        from agent.secret_scope import get_secret
        return get_secret("OPENROUTER_API_KEY") or ""
    except Exception:
        pass
    try:
        from hermes_constants import get_hermes_home
        env_path = get_hermes_home() / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _fetch_credits() -> dict:
    global _CREDITS_CACHE
    now = time.time()
    if _CREDITS_CACHE is not None:
        cached, ts = _CREDITS_CACHE
        if (now - ts) < CREDITS_TTL:
            return cached
    key = _get_openrouter_key()
    if not key:
        return {"error": "No OpenRouter API key configured"}
    try:
        import httpx
        resp = httpx.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        result = {
            "total_credits": data.get("total_credits", 0),
            "total_usage": data.get("total_usage", 0),
            "remaining": (data.get("total_credits", 0) or 0) - (data.get("total_usage", 0) or 0),
        }
    except Exception as e:
        result = {"error": str(e)}
    _CREDITS_CACHE = (result, now)
    return result


@router.get("/credits")
def get_credits():
    return _fetch_credits()


# ── GET /default-models ────────────────────────────────────────────
@router.get("/default-models")
def get_default_models():
    """Return model IDs from Hermes' built-in OpenRouter catalog."""
    try:
        from hermes_cli.models import OPENROUTER_MODELS
        return {"ids": [mid for mid, _ in OPENROUTER_MODELS]}
    except Exception:
        return {"ids": [], "error": "Could not load default models"}


# ── GET /analytics ─────────────────────────────────────────────────
_ANALYTICS_CACHE: tuple[dict, float] | None = None
ANALYTICS_TTL = 60  # 1 minute


def _fetch_analytics() -> dict:
    global _ANALYTICS_CACHE
    now = time.time()
    if _ANALYTICS_CACHE is not None:
        cached, ts = _ANALYTICS_CACHE
        if (now - ts) < ANALYTICS_TTL:
            return cached
    key = _get_openrouter_key()
    if not key:
        return {"error": "No OpenRouter API key configured"}
    try:
        import httpx
        resp = httpx.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        result = {
            "label": data.get("label", ""),
            "limit": data.get("limit"),
            "limit_remaining": data.get("limit_remaining"),
            "limit_reset": data.get("limit_reset"),
            "include_byok_in_limit": data.get("include_byok_in_limit", False),
            "usage": data.get("usage", 0),
            "usage_daily": data.get("usage_daily", 0),
            "usage_weekly": data.get("usage_weekly", 0),
            "usage_monthly": data.get("usage_monthly", 0),
            "byok_usage": data.get("byok_usage", 0),
            "byok_usage_daily": data.get("byok_usage_daily", 0),
            "byok_usage_weekly": data.get("byok_usage_weekly", 0),
            "byok_usage_monthly": data.get("byok_usage_monthly", 0),
            "is_free_tier": data.get("is_free_tier", False),
        }
    except Exception as e:
        result = {"error": str(e)}
    _ANALYTICS_CACHE = (result, now)
    return result


@router.get("/analytics")
def get_analytics():
    return _fetch_analytics()


# ── GET /activity ──────────────────────────────────────────────────
_ACTIVITY_CACHE: tuple[list, float] | None = None
ACTIVITY_TTL = 300  # 5 minutes


def _fetch_activity(mgmt_key: str = "") -> list:
    global _ACTIVITY_CACHE
    now = time.time()
    if _ACTIVITY_CACHE is not None:
        cached, ts = _ACTIVITY_CACHE
        if (now - ts) < ACTIVITY_TTL:
            return cached
    key = mgmt_key or _get_openrouter_key()
    if not key:
        return []
    try:
        import httpx
        from datetime import datetime, timedelta, timezone
        
        resp = httpx.get(
            "https://openrouter.ai/api/v1/activity",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        
        # Calculate date boundaries (UTC)
        today = datetime.now(timezone.utc).date()
        week_start = today - timedelta(days=today.weekday())  # Monday
        month_start = today.replace(day=1)
        
        # Aggregate by model with time breakdowns
        by_model: dict[str, dict] = {}
        totals = {"today": 0, "week": 0, "month": 0, "all": 0}
        
        for item in data:
            if not isinstance(item, dict):
                continue
            model = item.get("model", "")
            if not model:
                continue
            
            # Parse date
            date_str = item.get("date", "")
            item_date = None
            if date_str:
                try:
                    item_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass
            if item_date is None:
                # Default to today if no date
                item_date = today
            
            usage = item.get("usage", 0) or 0
            requests = item.get("requests", 0) or 0
            prompt_tok = item.get("prompt_tokens", 0) or 0
            completion_tok = item.get("completion_tokens", 0) or 0
            
            # Update totals
            if item_date == today:
                totals["today"] += usage
            if item_date >= week_start:
                totals["week"] += usage
            if item_date >= month_start:
                totals["month"] += usage
            totals["all"] += usage
            
            if model not in by_model:
                by_model[model] = {
                    "model": model,
                    "provider": item.get("provider_name", ""),
                    "cost_today": 0, "cost_week": 0, "cost_month": 0, "cost_all": 0,
                    "requests_today": 0, "requests_week": 0, "requests_month": 0, "requests_all": 0,
                    "tokens_today": 0, "tokens_week": 0, "tokens_month": 0, "tokens_all": 0,
                }
            entry = by_model[model]
            
            entry["cost_all"] += usage
            entry["requests_all"] += requests
            entry["tokens_all"] += prompt_tok + completion_tok
            
            if item_date == today:
                entry["cost_today"] += usage
                entry["requests_today"] += requests
                entry["tokens_today"] += prompt_tok + completion_tok
            if item_date >= week_start:
                entry["cost_week"] += usage
                entry["requests_week"] += requests
                entry["tokens_week"] += prompt_tok + completion_tok
            if item_date >= month_start:
                entry["cost_month"] += usage
                entry["requests_month"] += requests
                entry["tokens_month"] += prompt_tok + completion_tok
        
        models = sorted(by_model.values(), key=lambda x: x["cost_all"], reverse=True)
        result = {"models": models, "totals": totals}
    except Exception:
        result = {"models": [], "totals": {"today": 0, "week": 0, "month": 0, "all": 0}}
    _ACTIVITY_CACHE = (result, now)
    return result


@router.get("/activity")
def get_activity(mgmt_key: str = ""):
    return _fetch_activity(mgmt_key)

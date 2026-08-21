"""
OpenRouter Picker — backend API for managing the supplemental model list.

Mounted at /api/plugins/openrouter-picker/ by Hermes dashboard.
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
    from fastapi import APIRouter
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

router = APIRouter()

# The supplemental JSON file — symlinked from ~/.hermes/
MODELS_PATH = Path(os.environ.get(
    "OPENROUTER_PICKER_MODELS",
    str(Path.home() / ".hermes" / "openrouter-supplemental-models.json"),
))

OPENROUTER_API = "https://openrouter.ai/api/v1/models"

# Cache the full catalog for 5 minutes so repeated pane loads don't hammer the API
_CATALOG_CACHE: dict[str, Any] | None = None
_CATALOG_CACHE_AT: float = 0
CATALOG_TTL = 300


def _fetch_catalog() -> list[dict[str, Any]]:
    """Fetch the full OpenRouter model list with in-memory caching."""
    global _CATALOG_CACHE, _CATALOG_CACHE_AT
    now = time.time()
    if _CATALOG_CACHE is not None and (now - _CATALOG_CACHE_AT) < CATALOG_TTL:
        return _CATALOG_CACHE  # type: ignore[return-value]
    try:
        import httpx
        resp = httpx.get(OPENROUTER_API, timeout=20)
        resp.raise_for_status()
        raw = resp.json().get("data", [])
    except Exception:
        return _CATALOG_CACHE or []  # type: ignore[return-value]

    curated_ids = set()
    data = _read_models()
    for m in _get_models_list(data):
        curated_ids.add(m["id"])

    enriched: list[dict[str, Any]] = []
    for m in raw:
        mid = m.get("id", "")
        if not mid:
            continue
        pricing = m.get("pricing", {})
        ctx = m.get("context_length", 0)
        prompt_price = pricing.get("prompt", "0")
        comp_price = pricing.get("completion", "0")
        desc_parts: list[str] = []
        if ctx:
            desc_parts.append(f"{ctx // 1024}K ctx")
        try:
            pp = float(prompt_price) * 1_000_000
            cp = float(comp_price) * 1_000_000
            if pp or cp:
                desc_parts.append(f"${pp:.2f}/${cp:.2f}/M")
        except (ValueError, TypeError):
            pass
        enriched.append({
            "id": mid,
            "name": m.get("name", mid),
            "description": " — ".join(desc_parts) if desc_parts else "",
            "context_length": ctx,
            "selected": mid in curated_ids,
        })

    _CATALOG_CACHE = enriched
    _CATALOG_CACHE_AT = now
    return enriched


def _read_models() -> dict[str, Any]:
    if not MODELS_PATH.exists():
        return _empty_manifest()
    try:
        return json.loads(MODELS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return _empty_manifest()


def _write_models(data: dict[str, Any]) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = MODELS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.rename(MODELS_PATH)


def _empty_manifest() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"source": "Roy's supplemental OpenRouter picker models"},
        "providers": {
            "openrouter": {
                "metadata": {"display_name": "Roy supplemental OpenRouter models"},
                "models": [],
            }
        },
    }


def _get_models_list(data: dict) -> list[dict]:
    return data.setdefault("providers", {}).setdefault("openrouter", {}).setdefault("models", [])


# ── GET /models ──────────────────────────────────────────────────────
@router.get("/models")
def get_models():
    data = _read_models()
    models = _get_models_list(data)
    return {"models": models, "count": len(models)}


# ── GET /catalog ─────────────────────────────────────────────────────
@router.get("/catalog")
def get_catalog():
    """Return the full OpenRouter model list, each tagged with selected status."""
    catalog = _fetch_catalog()
    return {"models": catalog, "count": len(catalog)}


# ── POST /models ─────────────────────────────────────────────────────
@router.post("/models")
def add_model(body: dict | None = None):
    if not body:
        return {"error": "body required"}
    mid = (body.get("id") or "").strip()
    desc = (body.get("description") or "").strip()
    if not mid:
        return {"error": "id required"}

    if not re.match(r"^[a-z0-9_-]+/[a-z0-9._:-]+$", mid):
        return {"error": f"Invalid model ID format: {mid}"}

    data = _read_models()
    models = _get_models_list(data)
    existing = {m["id"] for m in models}
    if mid in existing:
        return {"error": f"Model {mid} already in list"}

    models.append({"id": mid, "description": desc or mid})
    _write_models(data)
    return {"ok": True, "added": mid, "count": len(models)}


# ── PUT /models/{model_id} ──────────────────────────────────────────
@router.put("/models/{model_id}")
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
@router.delete("/models/{model_id}")
def delete_model(model_id: str):
    data = _read_models()
    models = _get_models_list(data)
    before = len(models)
    models[:] = [m for m in models if m["id"] != model_id]
    if len(models) == before:
        return {"error": f"Model {model_id} not found"}
    _write_models(data)
    return {"ok": True, "removed": model_id, "count": len(models)}


# ── POST /search ────────────────────────────────────────────────────
@router.post("/search")
def search_openrouter(body: dict | None = None):
    q = (body or {}).get("q", "")
    if not q:
        return {"error": "q parameter required"}

    try:
        import httpx
        resp = httpx.get(OPENROUTER_API, timeout=15)
        resp.raise_for_status()
        all_models = resp.json().get("data", [])
    except Exception as e:
        return {"error": f"OpenRouter API error: {e}"}

    q_lower = q.lower()
    matches = []
    for m in all_models:
        mid = m.get("id", "")
        name = m.get("name", "")
        if q_lower in mid.lower() or q_lower in name.lower():
            pricing = m.get("pricing", {})
            ctx = m.get("context_length", 0)
            prompt_price = pricing.get("prompt", "0")
            comp_price = pricing.get("completion", "0")
            desc = name
            if ctx:
                desc += f" — {ctx // 1024}K ctx"
            try:
                pp = float(prompt_price) * 1_000_000
                cp = float(comp_price) * 1_000_000
                if pp or cp:
                    desc += f" — ${pp:.2f}/${cp:.2f}/M"
            except (ValueError, TypeError):
                pass
            matches.append({"id": mid, "description": desc, "context_length": ctx})

    return {"matches": matches[:30], "total": len(matches)}


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

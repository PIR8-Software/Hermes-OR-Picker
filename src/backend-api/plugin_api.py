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

MODELS_PATH = Path(os.environ.get(
    "OPENROUTER_PICKER_MODELS",
    str(Path.home() / ".hermes" / "openrouter-supplemental-models.json"),
))

OPENROUTER_API = "https://openrouter.ai/api/v1/models"

# Cache: key = query params hash → (data, timestamp)
_CATALOG_CACHE: dict[str, tuple[list[dict], float]] = {}
CATALOG_TTL = 300  # 5 minutes


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


def _enrich_model(m: dict, curated_ids: set[str]) -> dict[str, Any]:
    """Enrich a raw OpenRouter model with display-friendly fields."""
    mid = m.get("id", "")
    pricing = m.get("pricing", {})
    ctx = m.get("context_length", 0)
    prompt_price = pricing.get("prompt", "0")
    comp_price = pricing.get("completion", "0")

    # Extract provider from ID (before the /)
    provider = mid.split("/")[0] if "/" in mid else ""

    # Detect variant from ID suffix
    variant = ""
    if mid.endswith(":free"):
        variant = "free"
    elif mid.endswith(":batch"):
        variant = "batch"

    # Detect output modalities from architecture
    arch = m.get("architecture", {})
    output_mods = arch.get("output_modalities", []) if isinstance(arch, dict) else []
    input_mods = arch.get("input_modalities", []) if isinstance(arch, dict) else []

    # Parse prices
    try:
        pp = float(prompt_price) * 1_000_000
    except (ValueError, TypeError):
        pp = 0
    try:
        cp = float(comp_price) * 1_000_000
    except (ValueError, TypeError):
        cp = 0

    return {
        "id": mid,
        "name": m.get("name", mid),
        "provider": provider,
        "variant": variant,
        "context_length": ctx,
        "prompt_price": pp,
        "completion_price": cp,
        "output_modalities": output_mods,
        "input_modalities": input_mods,
        "selected": mid in curated_ids,
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

    # Build query params
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
        # Return empty on failure (cache miss)
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

    # Also return available filter options for the UI
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

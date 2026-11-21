"""
OpenRouter Picker — backend API for managing the supplemental model list.

Mounted at /api/plugins/openrouter-picker/ by Hermes dashboard.
Exposes every field the OpenRouter /api/v1/models endpoint returns.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
from datetime import UTC, datetime
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

# ── Curated-JSON path resolution ──────────────────────────────────────
# KEEP IN SYNC with catalog/__init__.py — the dashboard writer
# and the provider reader must agree on one file (contract tests:
# tests/test_path_resolution.py).


def _hermes_home() -> Path:
    """Active Hermes home (profile-scoped when Settings scopes HERMES_HOME)."""
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        pass
    env = os.environ.get("HERMES_HOME", "").strip()
    return Path(env) if env else Path.home() / ".hermes"


def _hermes_root() -> Path:
    """Install-wide root: ``<root>`` when the home is ``<root>/profiles/<name>``."""
    try:
        from hermes_constants import get_default_hermes_root
        return Path(get_default_hermes_root())
    except Exception:
        pass
    home = _hermes_home()
    return home.parent.parent if home.parent.name == "profiles" else home


def _shared_models_path() -> Path:
    return _hermes_root() / "openrouter-supplemental-models.json"


def _scoped_models_path() -> Path:
    return _hermes_home() / "openrouter-supplemental-models.json"


def _resolve_models_path() -> Path:
    """One curated-JSON path for the writer AND the reader.

    Order: explicit env overrides (both historical names) → install-wide
    shared file → profile-scoped file if one exists → shared (creation
    target). The shared file is the documented canonical store, so it wins
    over a stray scoped copy instead of splitting reads from writes.
    """
    for var in ("OPENROUTER_MODELS_PATH", "OPENROUTER_PICKER_MODELS"):
        val = os.environ.get(var, "").strip()
        if val:
            return Path(val)
    shared = _shared_models_path()
    if shared.is_file():
        return shared
    scoped = _scoped_models_path()
    if scoped.is_file():
        return scoped
    return shared


def _snapshot_path(name: str) -> Path:
    """Plugin snapshots (changelog, price alerts) live at the Hermes root."""
    return _hermes_root() / name


# -- Path override slots -------------------------------------------------
# Tests/tools pin the storage location by assigning these module attributes;
# when left at None the effective path is resolved fresh for every operation
# (never captured at import) so late HERMES_HOME / env / profile changes take
# effect immediately and the dashboard writer stays on the provider reader's
# path (F-06; contract tests: tests/test_path_resolution.py).

MODELS_PATH: Path | None = None
CHANGELOG_PATH: Path | None = None
PRICE_ALERTS_PATH: Path | None = None


def _models_path() -> Path:
    override = MODELS_PATH
    return Path(override) if override is not None else _resolve_models_path()


def _changelog_path() -> Path:
    override = CHANGELOG_PATH
    return Path(override) if override is not None else _snapshot_path(
        "openrouter-picker-changelog.json"
    )


def _price_alerts_path() -> Path:
    override = PRICE_ALERTS_PATH
    return Path(override) if override is not None else _snapshot_path(
        "openrouter-picker-price-alerts.json"
    )

OPENROUTER_API = "https://openrouter.ai/api/v1/models"
OPENROUTER_BLOG_FEED = "https://openrouter.ai/blog/feed.xml"

# Cache: key = query params hash → (data, timestamp). Bounded (F-7).
_CATALOG_CACHE: dict[str, tuple[list[dict], float]] = {}
CATALOG_TTL = 300  # 5 minutes
CATALOG_CACHE_MAX = 8

# Blog feed cache
_BLOG_CACHE: tuple[list[dict], float] | None = None
BLOG_TTL = 1800  # 30 minutes


def _entry_id(entry: Any) -> str | None:
    """Model id of a manifest entry, or None for malformed entries.

    Malformed non-dict / missing-id entries are preserved verbatim across
    mutations (F-04: never silently erased) but skipped in lookups.
    """
    if isinstance(entry, dict):
        mid = entry.get("id")
        if isinstance(mid, str) and mid:
            return mid
    return None


class ManifestEncodingError(ValueError):
    """The manifest exists but its bytes are not valid UTF-8 (F-04).

    Distinct type so API boundaries can reject the operation with a clean,
    truthful storage-validation error without any catch-all (unrelated bugs
    still propagate). Subclasses ValueError for compatibility with existing
    ``except ValueError`` handling. The undecodable original is never rewritten
    and never normalized to an empty manifest — a corrupt file must not appear
    empty or successful.
    """


def _load_manifest(path: Path) -> tuple[dict[str, Any], bytes | None]:
    """Read and normalize the curated manifest.

    Returns ``(data, malformed_raw_bytes)``. ``malformed_raw_bytes`` is the
    verbatim file content when the file exists but does not parse to the
    expected schema, so a later write can preserve the original instead of
    silently erasing it (F-04). Entry-level junk inside a valid ``models``
    list is kept as-is.

    FAIL CLOSED: if the file exists but cannot be read (e.g. chmod 000), raise
    to block mutation; distinguish missing file (OK → empty) from unreadable.
    Undecodable bytes raise ManifestEncodingError: the original is retained
    byte-for-byte and every caller must surface a clean storage-validation
    error instead of rewriting it or reporting empty success.
    """
    if not path.exists():
        return _empty_manifest(), None
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise OSError(f"cannot read manifest {path}") from exc
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ManifestEncodingError(
            f"storage validation failed: manifest {path} is not valid UTF-8"
        ) from exc
    except (json.JSONDecodeError, ValueError):
        return _empty_manifest(), raw_bytes
    if not isinstance(data, dict):
        return _empty_manifest(), raw_bytes
    providers = data.setdefault("providers", {})
    if not isinstance(providers, dict):
        return _empty_manifest(), raw_bytes
    orpicker = providers.setdefault("openrouter", {})
    if not isinstance(orpicker, dict):
        return _empty_manifest(), raw_bytes
    models = orpicker.setdefault("models", [])
    if not isinstance(models, list):
        return _empty_manifest(), raw_bytes
    return data, None


def _read_models(path: Path | None = None) -> dict[str, Any]:
    return _load_manifest(_models_path() if path is None else path)[0]


# ── Concurrency + atomic persistence ──────────────────────────────────
# In-process: a reentrant lock around every read-modify-write. Cross-process:
# an advisory exclusive lock on a "<file>.lock" sidecar (fcntl on POSIX,
# msvcrt on Windows) that FAILS CLOSED: if the lock cannot be acquired the
# operation aborts with a clean error instead of proceeding unlocked (F-12).
# The sidecar is deliberately retained after release (never unlinked): a
# waiter may already hold the file handle, so removing it races (F-12).
# Writes are tmp + rename, so a crash can never leave a half-written JSON file.

_IO_LOCK = threading.RLock()
_LOCK_WAIT_SECONDS = 10.0


class LockUnavailableError(RuntimeError):
    """The cross-process storage lock could not be acquired."""


def _ensure_parent(path: Path) -> None:
    """Create the parent directory of *path* on first write (F-07)."""
    parent = Path(path).parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def _file_lock(target: Path):
    resolved = Path(target).resolve()  # one sidecar even via symlinked paths
    lock_path = Path(str(resolved) + ".lock")
    _ensure_parent(lock_path)
    fh = open(lock_path, "a+")  # OSError propagates: fail closed
    backend = ""
    locked = False
    try:
        try:
            import fcntl
            backend = "fcntl"
        except ImportError:
            fcntl = None  # type: ignore[assignment]
            try:
                import msvcrt
                backend = "msvcrt"
            except ImportError:
                msvcrt = None  # type: ignore[assignment]
                raise LockUnavailableError("no fcntl/msvcrt locking available") from None
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        while True:
            try:
                if backend == "fcntl":
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise LockUnavailableError(
                        f"could not acquire cross-process lock {lock_path}"
                    ) from exc
                time.sleep(0.05)
        yield
    finally:
        if locked:
            try:
                if backend == "fcntl":
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                else:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass  # teardown unlock is best effort; close releases anyway
        try:
            fh.close()
        except Exception:
            pass


def _write_json_atomic(path: Path, data: Any, indent: int | None = None) -> None:
    """Write JSON via tmp + rename, keeping a symlink at *path* intact.

    ``resolve()`` is non-strict so a dangling symlink is written *through* to
    its target (the link survives and becomes valid) instead of being replaced
    (F-07). Missing parent directories are created (F-07).
    """
    target = Path(path).resolve()
    _ensure_parent(target)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n")
    tmp.replace(target)


def _preserve_malformed_original(target: Path, raw_bytes: bytes) -> None:
    """Keep verbatim bytes of a malformed manifest beside the file (F-04).

    Write exact bytes to sidecar; no universal-newline translation, no encoding
    normalization. Called with the raw bytes read via read_bytes().
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    sidecar = target.with_name(f"{target.name}.corrupt-{stamp}")
    sidecar.write_bytes(raw_bytes)


def _mutate_models(mutator):
    """Read-modify-write the manifest under lock; persists when mutator says ok.

    One effective storage path is resolved at operation start and used for the
    lock, the read and the write alike (F-06). Lock/write failures fail closed
    with a clean error dict and never touch the file (F-12).

    _load_manifest now returns (data, raw_bytes) for malformed entries (F-04).
    """
    path = _models_path()
    try:
        _ensure_parent(path)
        with _IO_LOCK, _file_lock(path):
            data, malformed_raw_bytes = _load_manifest(path)
            result = mutator(data)
            if isinstance(result, dict) and result.get("ok"):
                _write_models(data, path, preserve_raw_bytes=malformed_raw_bytes)
            return result
    except ManifestEncodingError as exc:
        # F-04: undecodable storage fails closed with a clean, truthful error —
        # no rewrite of the original and no empty/success masquerade. Only this
        # narrow encoding error is translated here; unrelated bugs propagate.
        return {"error": str(exc)}
    except (LockUnavailableError, OSError) as exc:
        return {"error": f"storage write failed: {exc}"}


def _provider_models_cache_path() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home()) / "provider_models_cache.json"
    except Exception:
        return Path.home() / ".hermes" / "provider_models_cache.json"


def _invalidate_or_picker_cache() -> None:
    """Composer picker caches or-picker ids for 1h in provider_models_cache.json."""
    try:
        from hermes_cli.models import clear_provider_models_cache
        clear_provider_models_cache("or-picker")
        return
    except Exception:
        pass
    # Fallback when hermes_cli is unavailable: drop the row ourselves, guarded
    # by the same cross-process lock and an atomic write (F-12). The cache is
    # disposable — upkeep failures never fail the mutation that triggered them.
    path = _provider_models_cache_path()
    if not path.exists():
        return
    try:
        _ensure_parent(path)
        with _file_lock(path):
            cache = json.loads(path.read_text())
            if isinstance(cache, dict) and "or-picker" in cache:
                del cache["or-picker"]
                _write_json_atomic(path, cache)
    except (OSError, LockUnavailableError, ValueError):
        pass


def _write_models(data: dict[str, Any], path: Path | None = None, preserve_raw_bytes: bytes | None = None) -> None:
    target = _models_path() if path is None else path
    if preserve_raw_bytes is not None:
        # F-04: a malformed original is preserved verbatim beside the file
        # before the rewrite; if preservation fails the write is aborted.
        _preserve_malformed_original(Path(target).resolve(), preserve_raw_bytes)
    data["updated_at"] = datetime.now(UTC).isoformat()
    _write_json_atomic(target, data, indent=2)
    _invalidate_or_picker_cache()


def _as_dict(body: Any) -> dict[str, Any]:
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return {}
    return body if isinstance(body, dict) else {}


def _valid_id(mid: str) -> bool:
    # OpenRouter "latest" aliases are ids like ~anthropic/claude-opus-latest.
    # ".." and "//" are rejected: ids are interpolated into upstream API paths.
    if ".." in mid or "//" in mid:
        return False
    return bool(re.match(r"^~?[A-Za-z0-9_.-]+/[A-Za-z0-9_.:/-]+$", mid))


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        raw = await request.json()
    except Exception:
        return {}
    return _as_dict(raw)


def _remove_id(mid: str) -> dict[str, Any]:
    def mutator(data: dict[str, Any]) -> dict[str, Any]:
        models = _get_models_list(data)
        # Malformed entries have no matching id and are kept verbatim (F-04).
        kept = [m for m in models if _entry_id(m) != mid]
        if len(kept) == len(models):
            return {"error": f"Model {mid} not found"}
        models[:] = kept
        return {"ok": True, "removed": mid, "count": len(models)}

    return _mutate_models(mutator)


def _add_id(mid: str, desc: str | None = None) -> dict[str, Any]:
    if not isinstance(mid, str):
        return {"error": "id must be a string"}
    if desc is not None and not isinstance(desc, str):
        return {"error": "description must be a string"}
    mid = mid.strip()
    if not mid:
        return {"error": "id required"}
    if not _valid_id(mid):
        return {"error": f"Invalid model ID format: {mid}"}

    def mutator(data: dict[str, Any]) -> dict[str, Any]:
        models = _get_models_list(data)
        # Lookups skip malformed entries; they are never erased by an add (F-04).
        if any(_entry_id(m) == mid for m in models):
            return {"error": f"Model {mid} already in list"}
        # F-10 lossless (review 2810): explicit description strings — including
        # empty and whitespace — are stored byte-for-byte; only an omitted
        # description keeps the legacy fallback to the model id.
        models.append({"id": mid, "description": mid if desc is None else desc})
        return {"ok": True, "added": mid, "count": len(models)}

    return _mutate_models(mutator)


def _empty_manifest() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
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
            created_str = datetime.fromtimestamp(created_ts, tz=UTC).strftime("%Y-%m-%d")
        except Exception:
            pass

    return {
        # ── Identity ──
        "id": mid,
        "name": m.get("name", mid),
        "description": m.get("description") or "",
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


class UpstreamUnavailableError(RuntimeError):
    """The upstream fetch failed transiently (F-08: never zero-success)."""


def _curated_id_set() -> set[str]:
    return {
        mid
        for m in _get_models_list(_read_models())
        if (mid := _entry_id(m)) is not None
    }


def _with_fresh_selected(models: list[dict]) -> list[dict]:
    """Recompute curated membership on every return (F-05).

    The cache holds immutable upstream enrichment only; ``selected`` must
    reflect the live manifest right now, not the moment of the fetch.
    """
    curated = _curated_id_set()
    for m in models:
        if isinstance(m, dict) and "id" in m:
            m["selected"] = m.get("id") in curated
    return models


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
            return _with_fresh_selected(cached)

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
    except Exception as exc:
        # F-08: a transient failure is never cached and never reported as an
        # empty catalog; callers surface a truthful error.
        raise UpstreamUnavailableError(str(exc)) from exc

    # Malformed manifest entries are skipped here (F-04); membership is
    # refreshed on every return via _with_fresh_selected (F-05).
    curated_ids = _curated_id_set()
    enriched = [
        _enrich_model(m, curated_ids) for m in raw if isinstance(m, dict) and m.get("id")
    ]
    _CATALOG_CACHE[cache_key] = (enriched, now)
    while len(_CATALOG_CACHE) > CATALOG_CACHE_MAX:
        _CATALOG_CACHE.pop(next(iter(_CATALOG_CACHE)))
    return _with_fresh_selected(enriched)


# ── GET /models ──────────────────────────────────────────────────────
@router.get("/models")
def get_models():
    try:
        data = _read_models()
    except ManifestEncodingError as exc:
        # F-04: undecodable storage must read back as a clean, truthful
        # storage-validation error — never an empty list masquerade.
        return {"error": str(exc)}
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
    try:
        catalog = _fetch_catalog(
            sort=sort,
            output_modalities=output_modalities,
            supported_parameters=supported_parameters,
            min_context=min_context_length,
            max_prompt_price=max_prompt_price,
            max_completion_price=max_completion_price,
        )
    except ManifestEncodingError as exc:
        # F-04: curated-membership reads (fresh fetch AND cache-hit re-selection)
        # must surface a clean, truthful storage-validation error — never an
        # all-unselected catalog that hides the corrupt file.
        return {"error": str(exc)}
    except UpstreamUnavailableError as exc:
        return {"error": f"OpenRouter catalog unavailable: {exc}"}

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
    mid_raw = body.get("id")
    desc_raw = body.get("description")
    if not isinstance(mid_raw, str):
        return {"error": "id must be a string"}
    if not isinstance(desc_raw, str) and desc_raw is not None:
        return {"error": "description must be a string or omitted"}
    mid = mid_raw.strip()
    if not mid:
        return {"error": "id required"}
    if body.get("remove"):
        return _remove_id(mid)
    # explicit strings (incl. empty) are preserved verbatim; None/omitted
    # keeps the legacy id fallback (review 2810 finding 5)
    desc = desc_raw if isinstance(desc_raw, str) else None
    return _add_id(mid, desc)


# ── POST /remove ─────────────────────────────────────────────────────
@router.post("/remove")
async def remove_model(request: Request):
    body = await _json_body(request)
    mid_raw = body.get("id")
    if not isinstance(mid_raw, str):
        return {"error": "id must be a string"}
    mid = mid_raw.strip()
    if not mid:
        return {"error": "id required"}
    return _remove_id(mid)


# ── PUT /models/{model_id} ──────────────────────────────────────────
@router.put("/models/{model_id:path}")
def update_model(model_id: str, body: dict | None = None):
    if not body:
        return {"error": "body required"}

    def mutator(data: dict[str, Any]) -> dict[str, Any]:
        models = _get_models_list(data)
        for m in models:
            if _entry_id(m) == model_id:
                if "description" in body:
                    if not isinstance(body["description"], str):
                        return {"error": "description must be a string"}
                    m["description"] = body["description"]
                return {"ok": True, "updated": model_id}
        return {"error": f"Model {model_id} not found"}

    return _mutate_models(mutator)


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
    if not isinstance(new_order, list) or not all(
        isinstance(mid, str) and mid for mid in new_order
    ):
        return {"error": "body 'order' must be a non-empty list of model ids"}

    def mutator(data: dict[str, Any]) -> dict[str, Any]:
        models = _get_models_list(data)
        # Stable lossless reorder: known ids first (in the requested order),
        # every other entry — including malformed ones — kept after in original
        # relative order (F-04).
        index: dict[str, int] = {}
        for mid in new_order:
            if mid not in index:
                index[mid] = len(index)
        matched = [m for m in models if _entry_id(m) in index]
        rest = [m for m in models if _entry_id(m) not in index]
        matched.sort(key=lambda m: index[_entry_id(m) or ""])
        data["providers"]["openrouter"]["models"] = matched + rest
        return {"ok": True, "count": len(matched) + len(rest)}

    return _mutate_models(mutator)


# ── GET /config ─────────────────────────────────────────────────────
@router.get("/config")
def get_config():
    models_path = _models_path()
    return {
        "models_path": str(models_path),
        "exists": models_path.exists(),
        "is_symlink": models_path.is_symlink() if models_path.exists() else False,
        "resolved": str(models_path.resolve()) if models_path.exists() else None,
    }


# ── GET /endpoints/{model_id} ───────────────────────────────────────
@router.get("/endpoints/{model_id:path}")
def get_model_endpoints(model_id: str):
    """Provider-health endpoints, proxied so the UI never raw-fetches (F-10)."""
    mid = (model_id or "").strip()
    if not mid or not _valid_id(mid):
        return {"error": f"Invalid model ID format: {mid}"}
    try:
        import httpx
        resp = httpx.get(
            f"https://openrouter.ai/api/v1/models/{mid}/endpoints",
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {}) or {}
        return {"endpoints": data.get("endpoints", [])}
    except Exception as e:
        return {"error": str(e)}


# ── GET /blog ──────────────────────────────────────────────────────
RSS_MAX_BYTES = 1_000_000


def _parse_rss_feed(xml_text: str) -> list[dict[str, str]]:
    """Parse RSS/XML into a flat list of {title, link, description, pubDate}.

    Defensive parse (N-2): size-capped and DTD/entity declarations are
    rejected outright before the XML parser sees the document.
    """
    import xml.etree.ElementTree as ET
    if not xml_text or len(xml_text) > RSS_MAX_BYTES:
        return []
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        return []
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
    except Exception as exc:
        # F-08: a fetch failure is neither cached nor reported as an empty feed.
        raise UpstreamUnavailableError(str(exc)) from exc
    _BLOG_CACHE = (items, now)
    return items


@router.get("/blog")
def get_blog(limit: int = 15):
    try:
        items = _fetch_blog()
    except UpstreamUnavailableError as exc:
        return {"posts": [], "count": 0, "error": f"blog feed unavailable: {exc}"}
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
    if "error" not in result:
        # F-08: error results are never cached — a retry recovers immediately.
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
    if "error" not in result:
        # F-08: error results are never cached — a retry recovers immediately.
        _ANALYTICS_CACHE = (result, now)
    return result


@router.get("/analytics")
def get_analytics():
    return _fetch_analytics()


# ── GET/POST /activity ──────────────────────────────────────────────
# Per-key cache: hashed management key → (result, timestamp). Bounded.
_ACTIVITY_CACHE: dict[str, tuple[dict, float]] = {}
ACTIVITY_TTL = 300  # 5 minutes
ACTIVITY_CACHE_MAX = 8


def _activity_cache_key(mgmt_key: str) -> str:
    import hashlib
    return hashlib.sha256((mgmt_key or "").encode()).hexdigest()[:16]


def _fetch_activity(mgmt_key: str = "") -> dict:
    cache_key = _activity_cache_key(mgmt_key)
    now = time.time()
    cached = _ACTIVITY_CACHE.get(cache_key)
    if cached is not None and (now - cached[1]) < ACTIVITY_TTL:
        return cached[0]
    key = mgmt_key or _get_openrouter_key()
    if not key:
        return {"models": [], "totals": {"today": 0, "week": 0, "month": 0, "all": 0}}
    try:
        from datetime import datetime, timedelta

        import httpx

        resp = httpx.get(
            "https://openrouter.ai/api/v1/activity",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

        # Calculate date boundaries (UTC)
        today = datetime.now(UTC).date()
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
    except Exception as e:
        # F-08: a transient failure is truthful (not zero usage) and is not
        # cached, so an immediate retry recovers.
        return {"error": f"activity fetch failed: {e}"}
    _ACTIVITY_CACHE[cache_key] = (result, now)
    while len(_ACTIVITY_CACHE) > ACTIVITY_CACHE_MAX:
        _ACTIVITY_CACHE.pop(next(iter(_ACTIVITY_CACHE)))
    return result


@router.post("/activity")
async def activity_post(request: Request):
    """Per-model usage. The management key travels in the JSON body (F-2)."""
    body = await _json_body(request)
    return _fetch_activity((body.get("mgmt_key") or "").strip())


@router.get("/activity")
def get_activity(request: Request):
    """Per-model usage. Management key via X-OR-Management-Key header only —
    never a query parameter (URLs leak into logs/history)."""
    key = ""
    try:
        key = (request.headers.get("x-or-management-key") or "").strip()
    except Exception:
        key = ""
    return _fetch_activity(key)


# ── GET /changelog ─────────────────────────────────────────────────
@router.get("/changelog")
def get_changelog():
    """Compare current catalog against saved snapshot, return changes and history."""
    try:
        # Get current catalog (just id, name, prices) — no lock held over network
        catalog = _fetch_catalog()
        current = {}
        for m in catalog:
            current[m["id"]] = {
                "name": m.get("name", ""),
                "prompt_price": m.get("prompt_price", 0),
                "completion_price": m.get("completion_price", 0),
            }

        changelog_path = _changelog_path()  # one effective path per operation (F-06)
        with _IO_LOCK, _file_lock(changelog_path):
            # Load previous data (snapshot + history); recover from corruption
            data = {}
            if changelog_path.exists():
                try:
                    data = json.loads(changelog_path.read_text())
                except (json.JSONDecodeError, OSError):
                    data = {}
            if not isinstance(data, dict):
                data = {}
            snapshot = data.get("snapshot", {}) or {}
            history = data.get("history", []) or []

            # Find changes
            added = []
            removed = []
            price_changed = []

            for mid, mdata in current.items():
                if mid not in snapshot:
                    added.append({"id": mid, "name": mdata["name"]})
                else:
                    old = snapshot[mid]
                    if (old.get("prompt_price") != mdata["prompt_price"] or
                        old.get("completion_price") != mdata["completion_price"]):
                        price_changed.append({
                            "id": mid,
                            "name": mdata["name"],
                            "old_prompt": old.get("prompt_price", 0),
                            "new_prompt": mdata["prompt_price"],
                            "old_completion": old.get("completion_price", 0),
                            "new_completion": mdata["completion_price"],
                        })

            for mid, mdata in snapshot.items():
                if mid not in current:
                    removed.append({"id": mid, "name": mdata.get("name", "")})

            # Save to history if there are changes
            has_changes = added or removed or price_changed
            if has_changes:
                history.append({
                    "date": datetime.now(UTC).isoformat(),
                    "added": added,
                    "removed": removed,
                    "price_changed": price_changed,
                    "total_added": len(added),
                    "total_removed": len(removed),
                    "total_price_changed": len(price_changed),
                })
                # Keep last 50 entries
                history = history[-50:]

            # Save new snapshot + history (atomic)
            _write_json_atomic(changelog_path, {"snapshot": current, "history": history})

        return {
            "added": added,
            "removed": removed,
            "price_changed": price_changed,
            "total_added": len(added),
            "total_removed": len(removed),
            "total_price_changed": len(price_changed),
            "snapshot_size": len(current),
            "history": history,
            "history_count": len(history),
        }
    except Exception as e:
        return {"error": str(e)}


# ── POST /test ─────────────────────────────────────────────────────
@router.post("/test")
def test_model(body: dict):
    """Send a test prompt to a model."""
    model_id = body.get("model", "")
    prompt = body.get("prompt", "Say hello in one sentence.")
    if not model_id:
        return {"error": "No model specified"}
    key = _get_openrouter_key()
    if not key:
        return {"error": "No OpenRouter API key configured"}
    try:
        import httpx
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model_id, "messages": [{"role": "user", "content": prompt}], "max_tokens": 100},
            timeout=30,
        )
        data = resp.json()
        if data.get("choices"):
            return {"response": data["choices"][0]["message"]["content"], "usage": data.get("usage", {})}
        elif "error" in data:
            return {"error": data["error"].get("message", str(data["error"]))}
        else:
            return {"error": "Unexpected response", "raw": data}
    except Exception as e:
        return {"error": str(e)}


# ── GET /price-alerts ──────────────────────────────────────────────

@router.get("/price-alerts")
def get_price_alerts():
    """Check for price drops in curated models."""
    try:
        # Get current catalog — no lock held over network
        catalog = _fetch_catalog()

        # Get curated models (malformed entries skipped, F-04)
        curated_ids = _curated_id_set()

        # Check for price changes in curated models
        alerts = []
        current_prices = {}

        alerts_path = _price_alerts_path()  # one effective path per operation (F-06)
        with _IO_LOCK, _file_lock(alerts_path):
            # Load previous prices; recover from corruption
            prev_prices = {}
            if alerts_path.exists():
                try:
                    prev_prices = json.loads(alerts_path.read_text())
                except (json.JSONDecodeError, OSError):
                    prev_prices = {}
            if not isinstance(prev_prices, dict):
                prev_prices = {}

            for m in catalog:
                if not isinstance(m, dict):
                    continue
                mid = m.get("id")
                if not mid:
                    continue
                current_prices[mid] = {
                    "prompt_price": m.get("prompt_price", 0),
                    "completion_price": m.get("completion_price", 0),
                }

                if mid in curated_ids and mid in prev_prices:
                    old = prev_prices[mid]
                    new_prompt = m.get("prompt_price", 0)
                    new_comp = m.get("completion_price", 0)
                    old_prompt = old.get("prompt_price", 0)
                    old_comp = old.get("completion_price", 0)

                    if new_prompt < old_prompt or new_comp < old_comp:
                        alerts.append({
                            "id": mid,
                            "name": m.get("name", ""),
                            "old_prompt": old_prompt,
                            "new_prompt": new_prompt,
                            "old_completion": old_comp,
                            "new_completion": new_comp,
                            "prompt_drop": old_prompt - new_prompt,
                            "completion_drop": old_comp - new_comp,
                        })

            # Save current prices (atomic)
            _write_json_atomic(alerts_path, current_prices)

        return {
            "alerts": alerts,
            "total_alerts": len(alerts),
            "tracked_models": len(curated_ids),
        }
    except Exception as e:
        return {"error": str(e)}

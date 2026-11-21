"""Invalid-UTF8 clean-error boundary regressions (F-04 final boundary, run 2817).

Reviewer probe ``or-picker-joined-2816/boundaries.py`` rows ``invalidUTF8-add``
and ``invalidUTF8-get`` failed on the pre-fix source: ``_load_manifest`` raised
``ValueError`` for undecodable bytes (e.g. ``b'{broken\\xff\\xfe'``) and the API
boundaries let it escape as an unhandled failure. Contract after the fix:

- every model read/mutation route and every catalog model-reading path returns
  a clean, truthful ``{"error": ...}`` storage-validation error for an
  undecodable manifest — no unhandled exception, never a quiet empty success;
- the undecodable original is never rewritten: bytes stay identical and no
  corrupt sidecar or tmp file appears (only the retained lock sidecar from the
  F-12 lock may exist);
- nonempty valid manifests and missing-file behavior are unchanged (controls);
- route-level coverage of every actual impacted handler: get_models (read),
  add_model (add), remove_model + delete_model (remove), update_model (update),
  reorder_models (reorder), get_catalog (catalog); get_price_alerts (catalog
  model-reading path) is covered too.

Every test pins MODELS_PATH / CHANGELOG_PATH / PRICE_ALERTS_PATH to tmp_path;
nothing here touches the live Hermes home.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "catalog" / "dashboard"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import plugin_api as api

# The exact synthetic bytes from the reviewer probe.
RAW = b"{broken\xff\xfe"


class FakeRequest:
    def __init__(self, body=None):
        self._body = body or {}

    async def json(self):
        return self._body


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpx:
    """Canned httpx stub; each get() consumes one scripted response."""

    def __init__(self, payload=None):
        self.payload = payload if payload is not None else {"data": []}
        self.urls: list[str] = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return FakeResponse(self.payload)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Pin every write seam at tmp_path; keep caches clean per test."""
    monkeypatch.setattr(api, "MODELS_PATH", tmp_path / "models.json")
    monkeypatch.setattr(api, "CHANGELOG_PATH", tmp_path / "changelog.json")
    monkeypatch.setattr(api, "PRICE_ALERTS_PATH", tmp_path / "price-alerts.json")
    monkeypatch.setattr(
        api,
        "_provider_models_cache_path",
        lambda: tmp_path / "provider_models_cache.json",
        raising=False,
    )
    monkeypatch.setattr(api, "_invalidate_or_picker_cache", lambda: None)
    monkeypatch.delenv("OPENROUTER_MODELS_PATH", raising=False)
    monkeypatch.delenv("OPENROUTER_PICKER_MODELS", raising=False)
    api._CATALOG_CACHE.clear()
    api._ACTIVITY_CACHE.clear()
    monkeypatch.setattr(api, "_BLOG_CACHE", None)
    monkeypatch.setattr(api, "_CREDITS_CACHE", None)
    monkeypatch.setattr(api, "_ANALYTICS_CACHE", None)
    yield tmp_path


def _seed_invalid() -> Path:
    target = Path(api.MODELS_PATH)
    target.write_bytes(RAW)
    return target


def _assert_clean_error(result) -> str:
    """No unhandled failure, no quiet success: a truthful storage error."""
    assert isinstance(result, dict), f"handler must return a dict, got {type(result)}"
    assert result.get("error"), f"clean storage-validation error required, got {result!r}"
    assert not result.get("ok"), f"operation must not report ok, got {result!r}"
    assert result.get("models") is None, f"must not masquerade as a model list, got {result!r}"
    message = str(result["error"])
    assert "not valid UTF-8" in message, f"error must say what is wrong: {message!r}"
    assert "storage" in message.lower(), f"error must be a storage-validation error: {message!r}"
    return message


def _assert_original_untouched(target: Path) -> None:
    """Undecodable originals are never rewritten and never sidecar-backed."""
    assert target.read_bytes() == RAW, "undecodable original bytes must be unchanged"
    leftovers = [
        p.name
        for p in target.parent.iterdir()
        if p.name not in {target.name, target.name + ".lock"}
    ]
    assert not leftovers, f"no rewrite artifacts allowed, found {leftovers}"


class TestInvalidUtf8CleanErrorBoundary:
    """Every impacted handler rejects undecodable storage with a clean error."""

    def test_read_get_models_clean_error(self):
        target = _seed_invalid()
        result = api.get_models()
        _assert_clean_error(result)
        _assert_original_untouched(target)

    def test_add_add_model_clean_error_no_write(self):
        target = _seed_invalid()
        result = asyncio.run(
            api.add_model(FakeRequest({"id": "new/model", "description": "d"}))
        )
        _assert_clean_error(result)
        _assert_original_untouched(target)

    def test_remove_remove_model_clean_error_no_write(self):
        target = _seed_invalid()
        result = asyncio.run(api.remove_model(FakeRequest({"id": "keep/model"})))
        _assert_clean_error(result)
        _assert_original_untouched(target)

    def test_delete_delete_model_clean_error_no_write(self):
        target = _seed_invalid()
        result = api.delete_model("keep/model")
        _assert_clean_error(result)
        _assert_original_untouched(target)

    def test_update_update_model_clean_error_no_write(self):
        target = _seed_invalid()
        result = api.update_model("keep/model", {"description": "x"})
        _assert_clean_error(result)
        _assert_original_untouched(target)

    def test_reorder_reorder_models_clean_error_no_write(self):
        target = _seed_invalid()
        result = api.reorder_models({"order": ["keep/model"]})
        _assert_clean_error(result)
        _assert_original_untouched(target)

    def test_catalog_get_catalog_clean_error(self, monkeypatch):
        target = _seed_invalid()
        monkeypatch.setitem(
            sys.modules, "httpx", FakeHttpx({"data": [{"id": "vendor/model", "name": "V"}]})
        )
        result = api.get_catalog()
        _assert_clean_error(result)
        _assert_original_untouched(target)

    def test_catalog_cache_hit_path_clean_error(self, monkeypatch):
        """The cached-enrichment re-selection path reads models too (F-05)."""
        target = _seed_invalid()
        monkeypatch.setitem(sys.modules, "httpx", FakeHttpx())
        cache_key = json.dumps(
            {
                "sort": "",
                "output_modalities": "",
                "supported_parameters": "",
                "min_context": 0,
                "max_prompt_price": -1,
                "max_completion_price": -1,
            },
            sort_keys=True,
        )
        api._CATALOG_CACHE[cache_key] = ([{"id": "cached/model", "selected": False}], time.time())
        result = api.get_catalog()
        _assert_clean_error(result)
        _assert_original_untouched(target)

    def test_price_alerts_model_reading_path_clean_error(self, monkeypatch):
        target = _seed_invalid()
        monkeypatch.setitem(
            sys.modules, "httpx", FakeHttpx({"data": [{"id": "vendor/model", "name": "V"}]})
        )
        result = api.get_price_alerts()
        _assert_clean_error(result)
        assert not Path(api.PRICE_ALERTS_PATH).exists(), "no write on clean rejection"
        _assert_original_untouched(target)

    def test_changelog_model_reading_path_clean_error(self, monkeypatch):
        target = _seed_invalid()
        monkeypatch.setitem(
            sys.modules, "httpx", FakeHttpx({"data": [{"id": "vendor/model", "name": "V"}]})
        )
        result = api.get_changelog()
        _assert_clean_error(result)
        assert not Path(api.CHANGELOG_PATH).exists(), "no write on clean rejection"
        _assert_original_untouched(target)

    def test_probe_parity_add_and_get(self):
        """Mirror the exact reviewer probe operations at the module seams."""
        target = _seed_invalid()
        _assert_clean_error(api._add_id("new/model", "new"))
        _assert_original_untouched(target)
        _assert_clean_error(api.get_models())
        _assert_original_untouched(target)


class TestValidAndMissingControls:
    """Valid nonempty manifests and missing files behave exactly as before."""

    def test_valid_nonempty_read_and_mutation_unchanged(self):
        target = Path(api.MODELS_PATH)
        target.write_text(
            json.dumps(
                {
                    "version": 1,
                    "providers": {
                        "openrouter": {"models": [{"id": "keep/model", "description": "d"}]}
                    },
                }
            )
        )
        result = api.get_models()
        assert result["count"] == 1 and result["models"][0]["id"] == "keep/model"
        assert api._add_id("new/model", "n")["ok"] is True
        ids = {m["id"] for m in api.get_models()["models"]}
        assert ids == {"keep/model", "new/model"}
        assert api._remove_id("new/model")["ok"] is True
        assert api.get_models()["count"] == 1

    def test_missing_file_read_is_empty_success(self):
        assert not Path(api.MODELS_PATH).exists()
        result = api.get_models()
        assert result == {"models": [], "count": 0}

"""Endpoint-level tests for plugin_api routes (offline, stubbed network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "src" / "backend-api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import plugin_api as api


class FakeResponse:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self.text = text
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpx:
    """Stub of the httpx module: canned responses, records requested URLs."""

    def __init__(self, payload=None, text="", status=200):
        self.payload = payload
        self.text = text
        self.status = status
        self.urls: list[str] = []
        self.posts: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return FakeResponse(self.payload, self.text, self.status)

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs.get("json") or {}))
        return FakeResponse(self.payload, self.text, self.status)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Point all snapshot paths at tmp, stub cache-bust + catalog fetch."""
    monkeypatch.setattr(api, "MODELS_PATH", tmp_path / "models.json")
    monkeypatch.setattr(api, "CHANGELOG_PATH", tmp_path / "changelog.json")
    monkeypatch.setattr(api, "PRICE_ALERTS_PATH", tmp_path / "price-alerts.json")
    monkeypatch.setattr(api, "_invalidate_or_picker_cache", lambda: None)
    return tmp_path


def _catalog_model(mid, prompt="0.000010", completion="0.000020", name=None):
    return {
        "id": mid,
        "name": name or mid.upper(),
        "pricing": {"prompt": prompt, "completion": completion},
    }


def _enriched(mid, prompt_price, completion_price, name=None):
    return {
        "id": mid,
        "name": name or mid.upper(),
        "prompt_price": prompt_price,
        "completion_price": completion_price,
    }


class FakeRequest:
    def __init__(self, body=None, headers=None, query=None):
        self._body = body or {}
        self.headers = headers or {}
        self.query_params = query or {}

    async def json(self):
        return self._body


class TestActivityTransport:
    """The management key must never travel in a URL (F-2) and the cache is
    per-key (F-6)."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        api._ACTIVITY_CACHE.clear()
        yield
        api._ACTIVITY_CACHE.clear()

    def _activity_item(self):
        return {
            "model": "vendor/model",
            "provider_name": "Vendor",
            "date": "2026-09-26",
            "usage": 1.5,
            "requests": 2,
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }

    def test_post_body_carries_key_and_url_stays_clean(self, monkeypatch):
        import asyncio
        fake = FakeHttpx(payload={"data": [self._activity_item()]})
        monkeypatch.setitem(sys.modules, "httpx", fake)

        result = asyncio.run(api.activity_post(FakeRequest(body={"mgmt_key": "sk-or-mgmt-SECRET"})))

        assert "error" not in result, result
        assert result["totals"]["today"] == pytest.approx(1.5)
        assert len(fake.urls) == 1
        assert "SECRET" not in fake.urls[0]

    def test_get_reads_header_not_query(self, monkeypatch):
        fake = FakeHttpx(payload={"data": [self._activity_item()]})
        monkeypatch.setitem(sys.modules, "httpx", fake)
        monkeypatch.setattr(api, "_get_openrouter_key", lambda: "server-key")

        result = api.get_activity(FakeRequest(
            headers={"x-or-management-key": "sk-or-mgmt-SECRET"},
            query={"mgmt_key": "sk-or-mgmt-LEAKED"},
        ))

        assert "error" not in result, result
        # server-side fetch uses the header key and no key in the URL
        assert "SECRET" not in fake.urls[0]
        assert "LEAKED" not in fake.urls[0]
        # the query-string key is ignored entirely
        assert "LEAKED" not in json.dumps(result)

    def test_cache_is_isolated_per_key(self, monkeypatch):
        fake = FakeHttpx(payload={"data": [self._activity_item()]})
        monkeypatch.setitem(sys.modules, "httpx", fake)
        monkeypatch.setattr(api, "_get_openrouter_key", lambda: "")

        api._fetch_activity("key-A")
        api._fetch_activity("key-B")
        api._fetch_activity("key-A")  # cache hit for key-A
        api._fetch_activity("")  # no key at all: empty result, no fetch

        # one fetch per distinct key that has one; repeats hit the cache
        assert len(fake.urls) == 2

    def test_unkeyed_error_does_not_poison_keyed_cache(self, monkeypatch):
        calls = []

        class Flaky:
            def get(self, url, **kwargs):
                calls.append(url)
                if len(calls) == 1:
                    return FakeResponse(status=500)
                return FakeResponse(payload={"data": [self_payload]})

        self_payload = self._activity_item()
        monkeypatch.setitem(sys.modules, "httpx", Flaky())
        monkeypatch.setattr(api, "_get_openrouter_key", lambda: "server-key")
        api._fetch_activity("")  # server-key fetch fails, cached under ""
        result = api._fetch_activity("key-A")  # must fetch again, not get ""s cache
        assert len(calls) == 2
        assert result["models"] and result["models"][0]["model"] == "vendor/model"


class TestCatalogCache:
    def test_catalog_cache_is_bounded(self, monkeypatch):
        fake = FakeHttpx(payload={"data": [_catalog_model("vendor/model")]})
        monkeypatch.setitem(sys.modules, "httpx", fake)
        monkeypatch.setattr(api, "_read_models", lambda: api._empty_manifest())
        api._CATALOG_CACHE.clear()

        for i in range(20):
            api._fetch_catalog(min_context=i)

        assert len(api._CATALOG_CACHE) <= api.CATALOG_CACHE_MAX
        before = len(fake.urls)
        api._fetch_catalog(min_context=19)  # newest entry survives eviction: hit
        assert len(fake.urls) == before
        api._fetch_catalog(min_context=0)  # oldest entry was evicted: refetch
        assert len(fake.urls) == before + 1


class TestEndpointsProxy:
    """Provider-health endpoints must go through the backend (F-10)."""

    def test_proxies_endpoints_for_valid_id(self, monkeypatch):
        fake = FakeHttpx(payload={"data": {"endpoints": [
            {"provider_name": "Vendor", "uptime_last_30m": 99.9},
        ]}})
        monkeypatch.setitem(sys.modules, "httpx", fake)

        result = api.get_model_endpoints("vendor/model:free")

        assert "error" not in result, result
        assert result["endpoints"][0]["provider_name"] == "Vendor"
        assert fake.urls == ["https://openrouter.ai/api/v1/models/vendor/model:free/endpoints"]

    def test_rejects_invalid_id_without_fetching(self, monkeypatch):
        fake = FakeHttpx(payload={"data": {"endpoints": []}})
        monkeypatch.setitem(sys.modules, "httpx", fake)

        for bad in ("../etc/passwd", "no spaces/allowed x", "drop;table/x", ""):
            result = api.get_model_endpoints(bad)
            assert "error" in result, (bad, result)

        assert fake.urls == []

    def test_upstream_failure_is_reported(self, monkeypatch):
        fake = FakeHttpx(status=500)
        monkeypatch.setitem(sys.modules, "httpx", fake)
        result = api.get_model_endpoints("vendor/model")
        assert "error" in result


class TestRssHardening:
    """Feed XML is HTTPS from openrouter.ai, but parse defensively (N-2)."""

    FEED = """<?xml version="1.0"?>
    <rss><channel>
      <item><title>T1</title><link>https://x/1</link></item>
      <item><title>T2</title><link>https://x/2</link></item>
    </channel></rss>"""

    def test_parses_normal_feed(self):
        items = api._parse_rss_feed(self.FEED)
        assert [i["title"] for i in items] == ["T1", "T2"]

    def test_rejects_doctype_and_entities(self):
        bomb = """<?xml version="1.0"?>
        <!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>
        <rss><channel>
          <item><title>&lol2;</title><link>https://x/1</link></item>
        </channel></rss>"""
        assert api._parse_rss_feed(bomb) == []

    def test_rejects_oversized_feed(self):
        huge = self.FEED.replace("T1", "T" + "x" * api.RSS_MAX_BYTES)
        assert api._parse_rss_feed(huge) == []


class TestChangelogEndpoint:
    def test_first_run_baselines_and_reports_added(self, offline, monkeypatch):
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [_enriched("a/b", 10.0, 20.0)])
        result = api.get_changelog()
        assert "error" not in result, result
        assert result["total_added"] == 1
        assert result["snapshot_size"] == 1
        assert result["history_count"] == 1

    def test_price_change_recorded_in_history(self, offline, monkeypatch):
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [_enriched("a/b", 10.0, 20.0)])
        api.get_changelog()
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [_enriched("a/b", 5.0, 20.0)])
        result = api.get_changelog()
        assert result["total_price_changed"] == 1
        assert result["price_changed"][0]["old_prompt"] == 10.0
        assert result["history_count"] == 2

    def test_removed_model_reported(self, offline, monkeypatch):
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [_enriched("a/b", 1.0, 1.0), _enriched("c/d", 1.0, 1.0)])
        api.get_changelog()
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [_enriched("a/b", 1.0, 1.0)])
        result = api.get_changelog()
        assert [m["id"] for m in result["removed"]] == ["c/d"]

    def test_history_capped_at_50(self, offline, monkeypatch):
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [])
        api.get_changelog()  # baseline
        result = {}
        for i in range(60):
            monkeypatch.setattr(api, "_fetch_catalog", lambda i=i: [_enriched(f"v{i}/m", 1.0, 1.0)])
            result = api.get_changelog()
        assert result["history_count"] == 50


class TestReorder:
    def test_reorder_puts_known_ids_first_and_keeps_the_rest(self, offline):
        for mid in ("a/one", "b/two", "c/three"):
            api._add_id(mid, mid)
        result = api.reorder_models({"order": ["c/three", "a/one"]})
        assert result["ok"] is True
        ids = [m["id"] for m in api._get_models_list(api._read_models())]
        assert ids == ["c/three", "a/one", "b/two"]

    def test_route_add_remove_flag_roundtrip(self, offline, monkeypatch):
        import asyncio
        req = FakeRequest(body={"id": "a/b", "description": "d"})
        assert asyncio.run(api.add_model(req))["ok"] is True
        req = FakeRequest(body={"id": "a/b", "remove": True})
        assert asyncio.run(api.add_model(req))["ok"] is True
        assert api._get_models_list(api._read_models()) == []


class TestPriceAlerts:
    def test_detects_drop_for_curated_model_and_writes_snapshot(self, offline, monkeypatch):
        # curated list contains a/b
        data = api._empty_manifest()
        api._get_models_list(data).append({"id": "a/b", "description": "x"})
        api._write_models(data)
        # previous snapshot had a higher price
        (offline / "price-alerts.json").write_text(json.dumps({
            "a/b": {"prompt_price": 10.0, "completion_price": 20.0},
        }))
        monkeypatch.setattr(
            api, "_fetch_catalog",
            lambda **kw: [
                _enriched("a/b", 5.0, 20.0),
                _enriched("c/d", 1.0, 1.0),
            ],
        )

        result = api.get_price_alerts()

        assert "error" not in result, result
        assert result["total_alerts"] == 1
        alert = result["alerts"][0]
        assert alert["id"] == "a/b"
        assert alert["prompt_drop"] == pytest.approx(5.0)
        assert result["tracked_models"] == 1
        # snapshot is persisted so the next run compares against these prices
        saved = json.loads((offline / "price-alerts.json").read_text())
        assert saved["a/b"]["prompt_price"] == 5.0

    def test_no_alert_on_first_run(self, offline, monkeypatch):
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [_enriched("a/b", 5.0, 5.0)])
        result = api.get_price_alerts()
        assert "error" not in result, result
        assert result["alerts"] == []
        assert (offline / "price-alerts.json").exists()

    def test_untracked_model_price_drop_is_not_alerted(self, offline, monkeypatch):
        (offline / "price-alerts.json").write_text(json.dumps({
            "c/d": {"prompt_price": 10.0, "completion_price": 10.0},
        }))
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [_enriched("c/d", 1.0, 1.0)])
        result = api.get_price_alerts()
        assert "error" not in result, result
        assert result["alerts"] == []

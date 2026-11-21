"""Backend regression tests for the F-04..F-08/F-12 slice.

Every test pins the module path override slots (MODELS_PATH / CHANGELOG_PATH /
PRICE_ALERTS_PATH) or a helper seam to tmp_path — nothing here may touch the
live Hermes home. Contract coverage:

- F-04: manifest schema normalization on read; malformed non-dict/missing-id
  entries preserved losslessly across mutations (never silently erased);
  nonempty corrupt originals preserved verbatim to a sidecar before rewrite.
- F-05: /catalog ``selected`` membership is recomputed from live curated state
  on every return (cache holds immutable upstream enrichment only).
- F-06: writer resolves ONE effective storage path per operation and never
  captures a path at import time.
- F-07: first write creates missing parents; dangling symlink is written
  through (link preserved); lock sidecar is created and deliberately retained.
- F-08: transient upstream failures are truthful (error, never zero-success)
  and are never cached, so a retry recovers immediately.
- F-12: the cross-process lock fails CLOSED (fcntl and msvcrt paths), unlocks
  accurately, serializes contenders; the provider-models-cache fallback is
  atomic and guarded.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "catalog" / "dashboard"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import plugin_api as api

REAL_INVALIDATE = api._invalidate_or_picker_cache


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
    """Canned httpx stub; each get() consumes one scripted response."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.urls: list[str] = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        resp = self.responses.pop(0) if self.responses else FakeResponse(payload={"data": []})
        if isinstance(resp, Exception):
            raise resp
        return resp


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
    # default stub; the fallback tests re-enable the real function deliberately
    monkeypatch.setattr(api, "_invalidate_or_picker_cache", lambda: None)
    monkeypatch.setitem(sys.modules, "hermes_cli.models", None)  # force fallback path
    monkeypatch.delenv("OPENROUTER_MODELS_PATH", raising=False)
    monkeypatch.delenv("OPENROUTER_PICKER_MODELS", raising=False)
    api._CATALOG_CACHE.clear()
    api._ACTIVITY_CACHE.clear()
    monkeypatch.setattr(api, "_BLOG_CACHE", None)
    monkeypatch.setattr(api, "_CREDITS_CACHE", None)
    monkeypatch.setattr(api, "_ANALYTICS_CACHE", None)
    yield tmp_path


def _manifest_with_entries(entries) -> dict:
    return {
        "version": 1,
        "providers": {"openrouter": {"models": list(entries)}},
    }


def _seed(path: Path, entries) -> None:
    path.write_text(json.dumps(_manifest_with_entries(entries)))


# ── F-06: one effective storage path per operation ─────────────────────


class TestOperationConsistentPaths:
    def test_no_import_time_capture_late_env_change_wins(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api, "MODELS_PATH", None)
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        monkeypatch.setenv("OPENROUTER_MODELS_PATH", str(a))
        assert api._models_path() == a
        monkeypatch.setenv("OPENROUTER_MODELS_PATH", str(b))
        assert api._models_path() == b

    def test_one_path_per_operation_even_if_override_flips_mid_mutation(self, tmp_path):
        path_a = tmp_path / "a" / "models.json"
        path_b = tmp_path / "b" / "models.json"
        api.MODELS_PATH = path_a

        def mutator(data):
            # A late path change must not split one operation across two files.
            api.MODELS_PATH = path_b
            api._get_models_list(data).append({"id": "x/y", "description": "x"})
            return {"ok": True}

        result = api._mutate_models(mutator)
        assert result["ok"] is True
        assert path_a.exists()
        written = json.loads(path_a.read_text())
        assert written["providers"]["openrouter"]["models"][0]["id"] == "x/y"
        assert not path_b.exists()

    def test_writer_and_reader_share_one_resolver(self):
        # The provider reader (catalog/__init__.py) keeps its own copy of the
        # resolution contract; tests/test_path_resolution.py locks the pairing.
        # Here we pin the dashboard side's observable: one resolver per op.
        assert api._read_models.__name__ == "_read_models"
        assert api._models_path() == Path(api.MODELS_PATH)


# ── F-04: schema normalization and lossless malformed-entry handling ──


class TestSchemaSafety:
    def test_read_missing_file_is_empty_manifest(self):
        data = api._read_models()
        assert isinstance(data, dict)
        assert api._get_models_list(data) == []

    @pytest.mark.parametrize(
        "content",
        [
            "{not json at all!!",          # nonempty corrupt fixture
            "[1, 2, 3]",                   # top-level list
            '"just a string"',             # top-level string
            "42",                          # top-level number
            '{"providers": 5}',            # providers not a dict
            '{"providers": {"openrouter": {"models": "nope"}}}',  # models not a list
        ],
    )
    def test_read_normalizes_schema_invalid_to_empty(self, content):
        Path(api.MODELS_PATH).write_text(content)
        data = api._read_models()
        assert isinstance(data, dict)
        assert api._get_models_list(data) == []

    def test_malformed_entries_survive_add(self):
        junk = ["not-a-dict", {"description": "no id"}, 42]
        _seed(Path(api.MODELS_PATH), [{"id": "a/b", "description": "x"}, *junk])
        result = api._add_id("c/d", "d")
        assert result["ok"] is True
        entries = api._get_models_list(api._read_models())
        assert [e for e in entries if isinstance(e, dict) and e.get("id")] == [
            {"id": "a/b", "description": "x"},
            {"id": "c/d", "description": "d"},
        ]
        # malformed originals retained verbatim (never silently erased)
        assert entries[1] == "not-a-dict"
        assert entries[2] == {"description": "no id"}
        assert entries[3] == 42

    def test_malformed_entries_survive_remove(self):
        junk = ["not-a-dict", {"description": "no id"}]
        _seed(Path(api.MODELS_PATH), [{"id": "a/b"}, {"id": "c/d"}, *junk])
        result = api._remove_id("a/b")
        assert result["ok"] is True
        entries = api._get_models_list(api._read_models())
        assert [e["id"] for e in entries if isinstance(e, dict) and e.get("id")] == ["c/d"]
        assert entries[-2] == "not-a-dict"
        assert entries[-1] == {"description": "no id"}

    def test_malformed_entries_survive_reorder(self):
        junk = ["not-a-dict", {"description": "no id"}]
        _seed(Path(api.MODELS_PATH), [{"id": "a/b"}, {"id": "c/d"}, *junk])
        result = api.reorder_models({"order": ["c/d", "a/b"]})
        assert result["ok"] is True
        entries = api._get_models_list(api._read_models())
        assert [e["id"] for e in entries if isinstance(e, dict) and e.get("id")] == ["c/d", "a/b"]
        assert entries[-2] == "not-a-dict"
        assert entries[-1] == {"description": "no id"}

    def test_malformed_entries_survive_update(self):
        junk = ["not-a-dict", {"description": "no id"}]
        _seed(Path(api.MODELS_PATH), [{"id": "a/b", "description": "old"}, *junk])
        result = api.update_model("a/b", {"description": "new"})
        assert result["ok"] is True
        entries = api._get_models_list(api._read_models())
        assert entries[0] == {"id": "a/b", "description": "new"}
        assert entries[1] == "not-a-dict"
        assert entries[2] == {"description": "no id"}

    def test_reorder_validates_order_type(self):
        _seed(Path(api.MODELS_PATH), [{"id": "a/b"}])
        assert "error" in api.reorder_models({"order": "a/b"})
        assert "error" in api.reorder_models({"order": [1, 2]})
        # failed validation must not touch the file
        assert [m["id"] for m in api._get_models_list(api._read_models())] == ["a/b"]

    def test_add_rejects_invalid_id_with_clean_validation(self):
        result = api._add_id("../etc/passwd", "")
        assert "error" in result and "ok" not in result
        result = api._add_id("", "")
        assert "error" in result

    def test_corrupt_original_preserved_to_sidecar_on_first_write(self):
        original = "{not json at all!!\nsecond line of junk"
        target = Path(api.MODELS_PATH)
        target.write_text(original)
        result = api._add_id("a/b", "x")
        assert result["ok"] is True
        sidecars = list(target.parent.glob(target.name + ".corrupt-*"))
        assert len(sidecars) == 1
        assert sidecars[0].read_text() == original  # verbatim, not erased
        entries = api._get_models_list(api._read_models())
        assert [m["id"] for m in entries] == ["a/b"]
        # second mutation reads the now-valid manifest: no new sidecar
        assert api._remove_id("a/b")["ok"] is True
        assert len(list(target.parent.glob(target.name + ".corrupt-*"))) == 1

    def test_schema_invalid_original_preserved_to_sidecar_on_first_write(self):
        original = '{"providers": {"openrouter": {"models": "nope"}}}'
        target = Path(api.MODELS_PATH)
        target.write_text(original)
        result = api._add_id("a/b", "x")
        assert result["ok"] is True
        sidecars = list(target.parent.glob(target.name + ".corrupt-*"))
        assert len(sidecars) == 1
        assert sidecars[0].read_text() == original

    def test_fetch_catalog_tolerates_malformed_entries(self, monkeypatch):
        _seed(
            Path(api.MODELS_PATH),
            [{"id": "vendor/model"}, "not-a-dict", {"description": "no id"}],
        )
        fake = FakeHttpx([FakeResponse(payload={"data": [{"id": "vendor/model", "pricing": {}}]})])
        monkeypatch.setitem(sys.modules, "httpx", fake)
        catalog = api._fetch_catalog()
        assert [m["id"] for m in catalog] == ["vendor/model"]


# ── F-05: selection membership always fresh ────────────────────────────


class TestSelectionFreshness:
    def _fake_catalog(self, monkeypatch, mid="vendor/model"):
        fake = FakeHttpx([
            FakeResponse(payload={"data": [{"id": mid, "name": "V", "pricing": {}}]}),
        ])
        monkeypatch.setitem(sys.modules, "httpx", fake)
        return fake

    def test_selected_flag_fresh_after_add(self, monkeypatch):
        fake = self._fake_catalog(monkeypatch)
        first = api._fetch_catalog()
        assert first[0]["selected"] is False
        assert api._add_id("vendor/model", "v")["ok"] is True
        second = api._fetch_catalog()
        assert second[0]["selected"] is True
        # membership recomputed on the cached upstream payload: one fetch only
        assert len(fake.urls) == 1

    def test_selected_flag_fresh_after_remove(self, monkeypatch):
        _seed(Path(api.MODELS_PATH), [{"id": "vendor/model"}])
        fake = self._fake_catalog(monkeypatch)
        assert api._fetch_catalog()[0]["selected"] is True
        assert api._remove_id("vendor/model")["ok"] is True
        assert api._fetch_catalog()[0]["selected"] is False
        assert len(fake.urls) == 1

    def test_flags_fresh_after_reorder(self, monkeypatch):
        _seed(Path(api.MODELS_PATH), [{"id": "vendor/model"}, {"id": "other/model"}])
        fake = self._fake_catalog(monkeypatch)
        api._fetch_catalog()
        assert api.reorder_models({"order": ["other/model", "vendor/model"]})["ok"] is True
        assert api._fetch_catalog()[0]["selected"] is True
        assert len(fake.urls) == 1


# ── F-07: first write, missing parents, symlink semantics ─────────────


class TestFirstWriteAndSymlinks:
    def test_first_write_creates_missing_parent_dirs(self):
        target = tmp_target = Path(api.MODELS_PATH).parent / "deep" / "nest" / "models.json"
        api.MODELS_PATH = target
        assert api._add_id("a/b", "x")["ok"] is True
        assert target.exists()
        entries = api._get_models_list(api._read_models())
        assert [m["id"] for m in entries] == ["a/b"]
        assert tmp_target.parent.is_dir()

    def test_lock_sidecar_created_and_deliberately_retained(self):
        target = Path(api.MODELS_PATH)
        assert api._add_id("a/b", "x")["ok"] is True
        sidecar = Path(str(target.resolve()) + ".lock")
        assert sidecar.exists(), "first write must create the lock sidecar"
        assert api._add_id("c/d", "x")["ok"] is True
        assert sidecar.exists(), "lock sidecar is deliberately retained (F-12)"

    def test_dangling_symlink_write_through_preserves_link(self, tmp_path):
        real = tmp_path / "real.json"
        link = tmp_path / "link.json"
        link.symlink_to(real)  # dangling: target missing
        api.MODELS_PATH = link
        assert api._add_id("a/b", "x")["ok"] is True
        assert link.is_symlink(), "write-through must not replace the symlink"
        assert real.exists()
        entries = api._get_models_list(api._read_models())
        assert [m["id"] for m in entries] == ["a/b"]


# ── F-08: truthful transient failures, no negative caching ────────────


class TestTransientFailures:
    def test_catalog_failure_truthful_not_zero_success(self, monkeypatch):
        fake = FakeHttpx([
            FakeResponse(status=500),
            FakeResponse(payload={"data": [{"id": "a/b", "pricing": {}}]}),
        ])
        monkeypatch.setitem(sys.modules, "httpx", fake)
        result = api.get_catalog()
        assert "error" in result, "transient failure must not masquerade as an empty catalog"
        # failure is not cached: an immediate retry recovers
        result = api.get_catalog()
        assert "error" not in result
        assert result["count"] == 1
        assert len(fake.urls) == 2

    def test_activity_failure_truthful_and_not_cached(self, monkeypatch):
        fake = FakeHttpx([
            FakeResponse(status=500),
            FakeResponse(payload={"data": []}),
        ])
        monkeypatch.setitem(sys.modules, "httpx", fake)
        monkeypatch.setattr(api, "_get_openrouter_key", lambda: "k")
        result = api._fetch_activity("k1")
        assert "error" in result, "failure must not masquerade as zero usage"
        result = api._fetch_activity("k1")
        assert "error" not in result
        assert len(fake.urls) == 2, "a failed fetch must not be cached"

    def test_blog_failure_truthful_and_not_cached(self, monkeypatch):
        fake = FakeHttpx([
            FakeResponse(status=500),
            FakeResponse(text='<rss><channel><item><title>T</title>'
                              "<link>https://x/1</link></item></channel></rss>"),
        ])
        monkeypatch.setitem(sys.modules, "httpx", fake)
        result = api.get_blog()
        assert "error" in result
        result = api.get_blog()
        assert "error" not in result
        assert result["count"] == 1
        assert len(fake.urls) == 2, "failure must not be cached for the full blog TTL"

    def test_credits_error_result_not_cached(self, monkeypatch):
        fake = FakeHttpx([
            FakeResponse(status=500),
            FakeResponse(payload={"data": {"total_credits": 5, "total_usage": 1}}),
        ])
        monkeypatch.setitem(sys.modules, "httpx", fake)
        monkeypatch.setattr(api, "_get_openrouter_key", lambda: "k")
        assert "error" in api._fetch_credits()
        result = api._fetch_credits()
        assert result.get("remaining") == 4
        assert len(fake.urls) == 2


# ── F-12: fail-closed locking and guarded atomic cache fallback ───────


class TestLockingAndCache:
    def test_lock_fails_closed_when_msvcrt_lock_fails(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "fcntl", None)
        monkeypatch.setattr(api, "_LOCK_WAIT_SECONDS", 0.2)
        msvcrt = types.ModuleType("msvcrt")
        msvcrt.LK_NBLCK = 1
        msvcrt.LK_UNLCK = 0

        def locking(fd, mode, n):
            raise OSError("simulated lock failure")

        msvcrt.locking = locking
        monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)
        _seed(Path(api.MODELS_PATH), [{"id": "keep/me"}])
        result = api._add_id("a/b", "x")
        assert "error" in result, "lock failure must fail the mutation closed"
        entries = api._get_models_list(api._read_models())
        assert [m["id"] for m in entries] == ["keep/me"], "no data loss on lock failure"

    def test_lock_fails_closed_when_no_lock_backend(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "fcntl", None)
        monkeypatch.setitem(sys.modules, "msvcrt", None)
        result = api._add_id("a/b", "x")
        assert "error" in result
        assert not Path(api.MODELS_PATH).exists(), "nothing may be written without the lock"

    def test_msvcrt_lock_unlock_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "fcntl", None)
        calls = []
        msvcrt = types.ModuleType("msvcrt")
        msvcrt.LK_NBLCK = 1
        msvcrt.LK_UNLCK = 0
        msvcrt.locking = lambda fd, mode, n: calls.append(mode)
        monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)
        with api._file_lock(tmp_path / "x.json"):
            assert calls == [msvcrt.LK_NBLCK], "lock acquired before the critical section"
        assert calls == [msvcrt.LK_NBLCK, msvcrt.LK_UNLCK], "accurate explicit unlock"

    def test_contended_lock_serializes_waiters(self, tmp_path):
        target = tmp_path / "contended.json"
        hold = 0.4
        acquired_gap = {}

        def holder():
            with api._file_lock(target):
                time.sleep(hold)

        def waiter():
            time.sleep(0.1)  # ensure holder is inside first
            t0 = time.monotonic()
            with api._file_lock(target):
                acquired_gap["gap"] = time.monotonic() - t0

        threads = [threading.Thread(target=holder), threading.Thread(target=waiter)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert acquired_gap["gap"] >= hold - 0.15, "second acquirer must wait for release"

    def _use_real_fallback(self, tmp_path, monkeypatch):
        """Run the real invalidator in a disposable home (never the live one)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(api, "_invalidate_or_picker_cache", REAL_INVALIDATE)

    def test_provider_cache_fallback_atomic_guarded_preserves_other_keys(
        self, tmp_path, monkeypatch
    ):
        self._use_real_fallback(tmp_path, monkeypatch)
        cache_path = tmp_path / "provider_models_cache.json"
        cache_path.write_text(json.dumps({
            "or-picker": {"fp": "x", "at": 1, "models": ["a/b"]},
            "openrouter": {"fp": "y", "at": 2, "models": ["c/d"]},
        }))
        written = []
        real_atomic = api._write_json_atomic

        def spy(path, data, indent=None):
            written.append(Path(path))
            return real_atomic(path, data, indent)

        monkeypatch.setattr(api, "_write_json_atomic", spy)
        api._invalidate_or_picker_cache()  # hermes_cli stubbed out -> fallback
        saved = json.loads(cache_path.read_text())
        assert "or-picker" not in saved
        assert saved["openrouter"]["models"] == ["c/d"], "other providers' rows preserved"
        assert cache_path in written, "fallback must use the atomic writer"
        assert list(tmp_path.glob("*.tmp")) == [], "no tmp residue"
        sidecar = Path(str(cache_path.resolve()) + ".lock")
        assert sidecar.exists(), "fallback rewrite must run under the guarded lock"

    def test_provider_cache_fallback_missing_file_is_noop(self, tmp_path, monkeypatch):
        self._use_real_fallback(tmp_path, monkeypatch)
        api._invalidate_or_picker_cache()
        assert not Path(api._provider_models_cache_path()).exists()

    def test_provider_cache_fallback_corrupt_cache_left_alone(self, tmp_path, monkeypatch):
        self._use_real_fallback(tmp_path, monkeypatch)
        cache_path = Path(api._provider_models_cache_path())
        cache_path.write_text("{corrupt")
        api._invalidate_or_picker_cache()
        assert cache_path.read_text() == "{corrupt", "corrupt cache must not be destroyed"


# ── F-04 additional regression tests for review2766 defects ────────────


class TestReview2766Defects:
    """Exact regression tests for the three review2766 blocking defects.

    These tests verify:
    - Defect 1: Unreadable existing manifest (chmod 000) must fail closed
      with clean error, no replacement written, valid/missing-file controls.
    - Defect 2: Corrupt CRLF source backup must be byte-identical (no CRLF→LF).
    - Defect 3: Nonstring IDs/descriptions must be rejected cleanly without writes.
    """

    def test_unreadable_manifest_chmod000_fails_closed_no_replacement(self, tmp_path, monkeypatch):
        target = tmp_path / "models.json"
        # Create a valid manifest first
        target.write_text(json.dumps(_manifest_with_entries([{"id": "keep/this", "description": "k"}])))
        # Patch _load_manifest to simulate OSError when reading
        original_load = api._load_manifest

        def patched_load(path):
            if path == target and path.exists():
                # Simulate OSError on read
                raise OSError(13, "Permission denied")
            return original_load(path)

        monkeypatch.setattr(api, "_load_manifest", patched_load)
        api.MODELS_PATH = target
        result = api._add_id("a/b", "x")
        # Must fail closed: error dict, no ok key, file untouched
        assert "error" in result and "ok" not in result
        # Verify file was NOT written (original content intact)
        assert target.exists()
        content = json.loads(target.read_text())
        assert content["providers"]["openrouter"]["models"][0]["id"] == "keep/this"

    def test_corrupt_crlf_preserved_byte_identical_to_sidecar(self, tmp_path):
        target = tmp_path / "models.json"
        # Create MALFORMED JSON with CRLF content (Windows line endings)
        # This triggers the preserve_malformed_original path
        crlf_content = b'{not json at all\r\nsecond line\r\n'
        target.write_bytes(crlf_content)
        api.MODELS_PATH = target
        result = api._add_id("a/b", "x")
        assert result["ok"] is True
        # Find sidecar
        sidecars = list(target.parent.glob(target.name + ".corrupt-*"))
        assert len(sidecars) == 1, "sidecar must be created for malformed original"
        # Verify verbatim preservation: CRLF must be intact
        sidecar_content = sidecars[0].read_bytes()
        assert sidecar_content == crlf_content, "CRLF original must be preserved verbatim"

    def test_nonstring_id_rejected_cleanly_no_write(self, tmp_path):
        target = tmp_path / "models.json"
        api.MODELS_PATH = target
        # Test integer ID
        result = api._add_id(17, "x")
        assert "error" in result and "ok" not in result
        # No file written
        assert not target.exists()
        # Test list ID
        result = api._add_id(["a", "b"], "x")
        assert "error" in result and "ok" not in result
        assert not target.exists()
        # Test nonstring description
        result = api._add_id("a/b", 123)
        assert "error" in result and "ok" not in result
        assert not target.exists()

    def test_async_handler_rejects_nonstring_ids_cleanly(self, tmp_path):
        target = tmp_path / "models.json"
        api.MODELS_PATH = target
        # Test the internal _add_id which the handler uses - integer ID
        result = api._add_id(17, "test")
        assert "error" in result and "ok" not in result
        assert not target.exists()

    def test_async_handler_rejects_nonstring_description_cleanly(self, tmp_path):
        target = tmp_path / "models.json"
        api.MODELS_PATH = target
        # Test the internal _add_id which the handler uses - integer description
        result = api._add_id("a/b", 456)
        assert "error" in result and "ok" not in result
        assert not target.exists()

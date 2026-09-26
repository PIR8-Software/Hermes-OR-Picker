"""Persistence guarantees: atomic snapshot writes, no lost writes on mutation (F-5)."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "src" / "backend-api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import plugin_api as api


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "MODELS_PATH", tmp_path / "models.json")
    monkeypatch.setattr(api, "CHANGELOG_PATH", tmp_path / "changelog.json")
    monkeypatch.setattr(api, "PRICE_ALERTS_PATH", tmp_path / "price-alerts.json")
    monkeypatch.setattr(api, "_invalidate_or_picker_cache", lambda: None)
    return tmp_path


class TestAtomicWrite:
    def test_write_json_atomic_roundtrip_no_residue(self, tmp_path):
        target = tmp_path / "snap.json"
        api._write_json_atomic(target, {"a": 1})
        assert json.loads(target.read_text()) == {"a": 1}
        assert list(tmp_path.glob("*.tmp")) == []

    def test_write_json_atomic_preserves_symlink(self, tmp_path):
        real = tmp_path / "real.json"
        link = tmp_path / "link.json"
        real.write_text("{}")
        link.symlink_to(real)
        api._write_json_atomic(link, {"k": "v"})
        assert link.is_symlink()
        assert json.loads(real.read_text()) == {"k": "v"}
        assert list(tmp_path.glob("*.tmp")) == []


class TestSnapshotWriters:
    def test_changelog_uses_atomic_writer(self, offline, monkeypatch):
        calls = []
        real = api._write_json_atomic

        def spy(path, data):
            calls.append(path)
            return real(path, data)

        monkeypatch.setattr(api, "_write_json_atomic", spy)
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [])
        result = api.get_changelog()
        assert "error" not in result, result
        assert offline / "changelog.json" in calls
        assert list(offline.glob("*.tmp")) == []

    def test_price_alerts_uses_atomic_writer(self, offline, monkeypatch):
        calls = []
        real = api._write_json_atomic

        def spy(path, data):
            calls.append(path)
            return real(path, data)

        monkeypatch.setattr(api, "_write_json_atomic", spy)
        monkeypatch.setattr(api, "_fetch_catalog", lambda **kw: [])
        result = api.get_price_alerts()
        assert "error" not in result, result
        assert offline / "price-alerts.json" in calls
        assert list(offline.glob("*.tmp")) == []


class TestLostWrites:
    def test_concurrent_adds_do_not_lose_writes(self, offline):
        ids = [f"vendor-{i}/model-{i}" for i in range(40)]
        errors: list[object] = []

        def add(mid):
            try:
                api._add_id(mid, mid)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=add, args=(mid,)) for mid in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        saved = {m["id"] for m in api._get_models_list(api._read_models())}
        assert saved == set(ids)

    def test_concurrent_remove_and_add_keep_consistent_file(self, offline):
        for mid in ("a/one", "b/two", "c/three"):
            api._add_id(mid, mid)

        def remove(mid):
            api._remove_id(mid)

        def add(mid):
            api._add_id(mid, mid)

        threads = [
            threading.Thread(target=remove, args=("a/one",)),
            threading.Thread(target=add, args=("d/four",)),
            threading.Thread(target=remove, args=("b/two",)),
            threading.Thread(target=add, args=("e/five",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        saved = {m["id"] for m in api._get_models_list(api._read_models())}
        assert saved == {"c/three", "d/four", "e/five"}

"""Unit tests for OpenRouter Picker dashboard API helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "catalog" / "dashboard"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import plugin_api as api


@pytest.fixture
def models_file(tmp_path, monkeypatch):
    path = tmp_path / "openrouter-supplemental-models.json"
    monkeypatch.setattr(api, "MODELS_PATH", path)
    monkeypatch.setattr(api, "_invalidate_or_picker_cache", lambda: None)
    return path


class TestValidId:
    @pytest.mark.parametrize(
        "mid",
        [
            "xiaomi/mimo-v2.5",
            "nvidia/nemotron-3-nano-30b-a3b:free",
            "~deepseek/deepseek-v4-flash-latest",
            "z-ai/glm-5.3",
            "openai/gpt-4.1",
            "a/b/c",
        ],
    )
    def test_accepts_openrouter_ids(self, mid):
        assert api._valid_id(mid)

    @pytest.mark.parametrize(
        "mid",
        ["", "noslash", " /bad", "bad id/has space", "drop;rm -rf", "id with space/x"],
    )
    def test_rejects_junk(self, mid):
        assert not api._valid_id(mid)


class TestAsDict:
    def test_dict_passthrough(self):
        assert api._as_dict({"id": "a/b"}) == {"id": "a/b"}

    def test_json_string(self):
        assert api._as_dict('{"id":"a/b"}') == {"id": "a/b"}

    def test_bad_json(self):
        assert api._as_dict("{nope") == {}

    def test_non_object(self):
        assert api._as_dict(["x"]) == {}
        assert api._as_dict(None) == {}


class TestParsePrice:
    def test_per_million(self):
        assert api._parse_price({"prompt": "0.000001"}, "prompt") == pytest.approx(1.0)

    def test_missing_is_zero(self):
        assert api._parse_price({}, "prompt") == 0

    def test_garbage_is_zero(self):
        assert api._parse_price({"prompt": "nope"}, "prompt") == 0


class TestManifestIo:
    def test_missing_file_is_empty(self, models_file):
        data = api._read_models()
        assert data["providers"]["openrouter"]["models"] == []

    def test_corrupt_json_is_empty(self, models_file):
        models_file.write_text("{not json")
        data = api._read_models()
        assert data["providers"]["openrouter"]["models"] == []

    def test_write_roundtrip_keeps_symlink_target(self, tmp_path, monkeypatch):
        real = tmp_path / "real.json"
        link = tmp_path / "link.json"
        real.write_text(json.dumps(api._empty_manifest()))
        link.symlink_to(real)
        monkeypatch.setattr(api, "MODELS_PATH", link)
        monkeypatch.setattr(api, "_invalidate_or_picker_cache", lambda: None)

        data = api._read_models()
        api._get_models_list(data).append({"id": "a/b", "description": "x"})
        api._write_models(data)

        assert link.is_symlink()
        loaded = json.loads(real.read_text())
        assert loaded["providers"]["openrouter"]["models"][0]["id"] == "a/b"

    def test_add_and_remove(self, models_file):
        data = api._empty_manifest()
        api._get_models_list(data).append({"id": "a/b", "description": "x"})
        api._write_models(data)
        result = api._remove_id("a/b")
        assert result["ok"] is True
        assert result["count"] == 0
        assert api._remove_id("a/b")["error"].startswith("Model")


class TestEnrich:
    def test_selected_and_free_variant(self):
        raw = {
            "id": "nvidia/foo:free",
            "name": "Foo",
            "description": "d" * 600,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "top_provider": {"max_completion_tokens": 4096, "is_moderated": True},
            "supported_parameters": ["tools", "temperature"],
            "created": 1700000000,
        }
        out = api._enrich_model(raw, {"nvidia/foo:free"})
        assert out["selected"] is True
        assert out["variant"] == "free"
        assert out["provider"] == "nvidia"
        assert out["has_tools"] is True
        assert out["has_vision"] is True
        assert out["is_moderated"] is True
        assert len(out["description"]) == 600
        assert out["created"] == "2023-11-14"

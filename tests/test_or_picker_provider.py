"""Unit tests for the or-picker provider catalog reader."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_FILE = ROOT / "src" / "model-provider" / "__init__.py"


def _load_provider(models_path: Path):
    providers = types.ModuleType("providers")
    base = types.ModuleType("providers.base")

    class ProviderProfile:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                object.__setattr__(self, key, value)

        def __getattribute__(self, name):
            return object.__getattribute__(self, name)

    def register_provider(_profile):
        return None

    providers.register_provider = register_provider
    base.ProviderProfile = ProviderProfile
    sys.modules["providers"] = providers
    sys.modules["providers.base"] = base

    spec = importlib.util.spec_from_file_location("or_picker_provider", PROVIDER_FILE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod.os.environ["OPENROUTER_PICKER_MODELS"] = str(models_path)
    return mod


def _manifest(ids):
    return {
        "version": 1,
        "providers": {
            "openrouter": {
                "models": [{"id": mid, "description": mid} for mid in ids]
            }
        },
    }


class TestCuratedIds:
    def test_reads_unique_ids(self, tmp_path):
        path = tmp_path / "models.json"
        data = _manifest(["a/b", "a/b", "c/d"])
        data["providers"]["openrouter"]["models"].append({"id": "  "})
        data["providers"]["openrouter"]["models"].append("not-a-dict")
        path.write_text(json.dumps(data))
        mod = _load_provider(path)
        assert mod._curated_ids() == ["a/b", "c/d"]

    def test_missing_file(self, tmp_path):
        mod = _load_provider(tmp_path / "missing.json")
        assert mod._curated_ids() == []

    def test_corrupt_json(self, tmp_path):
        path = tmp_path / "models.json"
        path.write_text("{nope")
        mod = _load_provider(path)
        assert mod._curated_ids() == []

    def test_fallback_models_is_live(self, tmp_path):
        path = tmp_path / "models.json"
        path.write_text(json.dumps(_manifest(["one/a"])))
        mod = _load_provider(path)
        profile = mod.ORPickerProfile(
            name="or-picker",
            aliases=(),
            env_vars=("OPENROUTER_API_KEY",),
            display_name="OR Picker",
            description="test",
            signup_url="",
            base_url="https://openrouter.ai/api/v1",
            auth_type="api_key",
            fallback_models=("stale",),
        )
        assert profile.fallback_models == ("one/a",)
        path.write_text(json.dumps(_manifest(["two/b"])))
        assert profile.fallback_models == ("two/b",)
        assert profile.fetch_models() == ["two/b"]
        assert profile.name == "or-picker"

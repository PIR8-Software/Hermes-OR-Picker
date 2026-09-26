"""Backend and provider must resolve the curated-JSON path identically (F-4).

Contract (both modules implement it the same way):
  1. OPENROUTER_MODELS_PATH env override
  2. OPENROUTER_PICKER_MODELS env override (legacy provider name)
  3. install-wide shared file under the Hermes root
  4. profile-scoped file under get_hermes_home(), when one exists there
  5. shared file (creation target)
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "src" / "backend-api"
PROVIDER_FILE = ROOT / "src" / "model-provider" / "__init__.py"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import plugin_api as api

FILENAME = "openrouter-supplemental-models.json"


def _load_provider():
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

    spec = importlib.util.spec_from_file_location("or_picker_provider_paths", PROVIDER_FILE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def both(tmp_path, monkeypatch):
    """Both modules under one fake Hermes root with a profile-scoped home."""
    root = tmp_path
    profile_home = root / "profiles" / "betty"
    profile_home.mkdir(parents=True)

    monkeypatch.delenv("OPENROUTER_MODELS_PATH", raising=False)
    monkeypatch.delenv("OPENROUTER_PICKER_MODELS", raising=False)

    class _Constants(types.ModuleType):
        @staticmethod
        def get_hermes_home():
            return profile_home

        @staticmethod
        def get_default_hermes_root():
            return root

    monkeypatch.setitem(sys.modules, "hermes_constants", _Constants("hermes_constants"))
    prov = _load_provider()
    return api, prov, root, profile_home


def _put(path: Path, ids=("x/y",)):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": 1,
        "providers": {"openrouter": {"models": [{"id": i, "description": i} for i in ids]}},
    }))


class TestOverrides:
    def test_backend_env_var_honored_by_both(self, both, monkeypatch):
        api, prov, root, _profile_home = both
        target = root / "elsewhere.json"
        monkeypatch.setenv("OPENROUTER_MODELS_PATH", str(target))
        assert api._resolve_models_path() == target
        assert prov._resolve_models_path() == target

    def test_provider_env_var_honored_by_both(self, both, monkeypatch):
        api, prov, root, _profile_home = both
        target = root / "other.json"
        monkeypatch.setenv("OPENROUTER_PICKER_MODELS", str(target))
        assert api._resolve_models_path() == target
        assert prov._resolve_models_path() == target


class TestFileResolution:
    def test_shared_and_scoped_both_exist_return_shared(self, both):
        # Regression: the writer used shared while the reader used scoped (F-4c).
        api, prov, root, profile_home = both
        _put(root / FILENAME, ("shared/model",))
        _put(profile_home / FILENAME, ("scoped/model",))
        assert api._resolve_models_path() == root / FILENAME
        assert prov._resolve_models_path() == root / FILENAME

    def test_scoped_only_is_used_by_both(self, both):
        api, prov, _root, profile_home = both
        _put(profile_home / FILENAME, ("scoped/model",))
        assert api._resolve_models_path() == profile_home / FILENAME
        assert prov._resolve_models_path() == profile_home / FILENAME

    def test_nothing_exists_defaults_to_shared(self, both):
        api, prov, root, _profile_home = both
        assert api._resolve_models_path() == root / FILENAME
        assert prov._resolve_models_path() == root / FILENAME

    def test_custom_hermes_home_is_honored(self, tmp_path, monkeypatch):
        # HERMES_HOME points at a plain root (the install.sh custom-root case).
        custom = tmp_path / "custom-home"
        custom.mkdir()
        monkeypatch.delenv("OPENROUTER_MODELS_PATH", raising=False)
        monkeypatch.delenv("OPENROUTER_PICKER_MODELS", raising=False)
        monkeypatch.setenv("HERMES_HOME", str(custom))
        monkeypatch.setitem(sys.modules, "hermes_constants", None)
        _put(custom / FILENAME, ("custom/model",))
        prov = _load_provider()
        assert api._resolve_models_path() == custom / FILENAME
        assert prov._resolve_models_path() == custom / FILENAME


class TestSnapshotPaths:
    def test_snapshots_live_at_hermes_root_not_profile_home(self, both):
        api, _prov, root, _profile_home = both
        assert api._snapshot_path("openrouter-picker-changelog.json") == root / "openrouter-picker-changelog.json"

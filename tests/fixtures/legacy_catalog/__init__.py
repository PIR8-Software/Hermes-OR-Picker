"""OR Picker — separate OpenRouter provider showing only the curated picker list.

Uses the same OpenRouter API key and endpoint as the built-in OpenRouter
provider. The live catalog is the supplemental JSON managed by the
openrouter-picker desktop plugin, not Hermes's auto-refreshed curated list.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from providers import register_provider
from providers.base import ProviderProfile

# ── Curated-JSON path resolution ──────────────────────────────────
# KEEP IN SYNC with dashboard/plugin_api.py — the provider reader
# and the dashboard writer must agree on one file (contract tests:
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
    """One curated-JSON path for the reader AND the writer.

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


def _curated_ids() -> list[str]:
    path = _resolve_models_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    models = (
        data.get("providers", {})
        .get("openrouter", {})
        .get("models", [])
    )
    out: list[str] = []
    seen: set[str] = set()
    for m in models:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "").strip()
        if mid and mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


class ORPickerProfile(ProviderProfile):
    """OpenRouter transport, curated model list from the picker JSON."""

    def __getattribute__(self, name: str):
        # Never pin fallback_models at import — that list is what the
        # composer picker merges against, so a snapshot blocks removes.
        if name == "fallback_models":
            ids = _curated_ids()
            return tuple(ids) if ids else ()
        return super().__getattribute__(name)

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        ids = _curated_ids()
        return ids or None


or_picker = ORPickerProfile(
    name="or-picker",
    aliases=("roy-openrouter", "orpicker"),
    env_vars=("OPENROUTER_API_KEY",),
    display_name="OR Picker",
    description="Curated OpenRouter list (separate from default OpenRouter)",
    signup_url="https://openrouter.ai/keys",
    base_url="https://openrouter.ai/api/v1",
    auth_type="api_key",
    fallback_models=(),
)

register_provider(or_picker)

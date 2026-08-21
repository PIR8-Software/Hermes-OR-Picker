"""OR Picker — separate OpenRouter provider showing only Roy's curated models.

Uses the same OpenRouter API key and endpoint as the built-in OpenRouter
provider. The live catalog is the supplemental JSON managed by the
openrouter-picker desktop plugin, not Hermes's auto-refreshed curated list.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


def _models_path() -> Path:
    override = os.environ.get("OPENROUTER_PICKER_MODELS", "").strip()
    if override:
        return Path(override)
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home() / "openrouter-supplemental-models.json"
    except Exception:
        return Path.home() / ".hermes" / "openrouter-supplemental-models.json"


def _curated_ids() -> list[str]:
    path = _models_path()
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
    description="Roy's curated OpenRouter list (separate from default OpenRouter)",
    signup_url="https://openrouter.ai/keys",
    base_url="https://openrouter.ai/api/v1",
    auth_type="api_key",
    fallback_models=(),
)

register_provider(or_picker)

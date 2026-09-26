"""Sanity checks that do not import Hermes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src" / "desktop-plugin" / "plugin.js"


def test_plugin_js_syntax():
    result = subprocess.run(
        ["node", "--check", str(JS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_manifests_parse():
    json.loads((ROOT / "openrouter-supplemental-models.json").read_text())
    json.loads((ROOT / "src" / "backend-api" / "manifest.json").read_text())


def test_starter_list_is_empty():
    data = json.loads((ROOT / "openrouter-supplemental-models.json").read_text())
    models = data["providers"]["openrouter"]["models"]
    assert models == []


def test_starter_ids_match_valid_id_regex():
    """Starter-list ids must survive _valid_id, parametrized over real id
    shapes (the old loop over the intentionally empty starter list could
    never fail)."""
    sys.path.insert(0, str(ROOT / "src" / "backend-api"))
    import plugin_api as api

    data = json.loads((ROOT / "openrouter-supplemental-models.json").read_text())
    ids = [m["id"] for m in data["providers"]["openrouter"]["models"]]
    for mid in ids:
        assert api._valid_id(mid), mid
    # real OpenRouter id shapes are accepted even when the starter list is empty
    for mid in (
        "openai/gpt-4.1",
        "nvidia/nemotron-3-nano-30b-a3b:free",
        "meta/llama-3.3-70b-instruct:floor",
        "anthropic/claude-3.5-sonnet:batch",
        "~deepseek/deepseek-v4-flash-latest",
        "a/b/c",
    ):
        assert api._valid_id(mid), mid
    # traversal and junk shapes are rejected
    for bad in ("a/../b", "../x", "x//y", "noslash", "bad id/x", "x/", "/x", ""):
        assert not api._valid_id(bad), bad


class TestPluginJsHygiene:
    """Static regression gates for the desktop plugin (F-2/F-9/F-10/F-11)."""

    def test_no_raw_fetch_left_in_plugin(self):
        # ctx.rest only (AGENT_HANDOFF rule) — endpoints go through the proxy
        src = JS.read_text()
        assert "fetch(" not in src, "raw fetch() found in plugin.js"

    def test_mgmt_key_never_travels_in_url(self):
        src = JS.read_text()
        assert "mgmt_key=" not in src, "mgmt key sent as query string"
        assert "?mgmt_key" not in src

    def test_icon_controls_have_accessible_names(self):
        src = JS.read_text().replace("'", '"')
        for label in (
            '"aria-label": "Expand model details"',
            '"aria-label": "Add to compare"',
            '"aria-label": "Export list"',
            '"aria-label": "Import list"',
        ):
            assert label in src, label

    def test_forecast_labels_are_honest(self):
        src = JS.read_text()
        for honest in ("Today × 30", "This week × 4.3", "Month to date"):
            assert honest in src, honest
        for misleading in ("From daily avg", "From weekly avg", "Current month pace"):
            assert misleading not in src, misleading

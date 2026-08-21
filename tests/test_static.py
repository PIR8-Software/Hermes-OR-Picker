"""Sanity checks that do not import Hermes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_js_syntax():
    js = ROOT / "src" / "desktop-plugin" / "plugin.js"
    result = subprocess.run(
        ["node", "--check", str(js)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_manifests_parse():
    json.loads((ROOT / "openrouter-supplemental-models.json").read_text())
    json.loads((ROOT / "src" / "backend-api" / "manifest.json").read_text())


def test_starter_list_is_empty():
    data = json.loads((ROOT / "openrouter-supplemental-models.json").read_text())
    models = data["providers"]["openrouter"]["models"]
    assert models == []


def test_curated_ids_match_valid_id_regex():
    import sys

    sys.path.insert(0, str(ROOT / "src" / "backend-api"))
    import plugin_api as api

    data = json.loads((ROOT / "openrouter-supplemental-models.json").read_text())
    for m in data["providers"]["openrouter"]["models"]:
        assert api._valid_id(m["id"]), m["id"]

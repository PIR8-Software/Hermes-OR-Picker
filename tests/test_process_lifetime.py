"""Process-lifetime regression: a long-lived gateway registers OR Picker only when the
repair bumps the profile home's ``model-providers`` dir mtime (the re-scan signal).

This reproduces the live discovery bug. The running gateway's per-home provider
discovery (``providers._refresh_home_layer``) re-scans a home's plugins ONLY when
``_plugin_dir_stamps(home)`` — the mtimes of ``home/plugins`` and
``home/plugins/model-providers`` — changes. An earlier repair fixed the *share point* (root),
which made the old per-profile symlinks resolve again WITHOUT bumping those profile
homes' dir mtimes. So a long-lived process that had scanned the home while the link was
dangling never re-scanned, leaving ``or-picker`` unregistered → the desktop showed
"Set up OR Picker" even after a desktop reboot (the stale cache is in the GATEWAY, not the
desktop). A fresh process re-scans unconditionally and registers it — which is why offline
fresh-process probes passed.

``tests/_lifetime_driver.py`` runs the transition in ONE long-lived process
(absent → repaired → next lookup) against the real ``providers`` discovery layer. The
hermetic companion ``test_running_process_rescan_signal_bumped`` asserts the installer
bumps that dir mtime even when the link already resolves.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "_lifetime_driver.py"
INSTALL_SH = ROOT / "install.sh"


def _hermes_agent_python() -> Path | None:
    cand = os.environ.get("HERMES_AGENT_PYTHON")
    if cand and Path(cand).is_file():
        return Path(cand)
    default = Path.home() / ".hermes" / "hermes-agent" / ".venv" / "bin" / "python"
    return default if default.is_file() else None


# Required tier (CI's `integration` job sets this): these tests must RUN and must FAIL
# when the hermes-agent runtime is missing — never skip. The hermetic tier leaves it
# unset and skips cleanly when no runtime is available. The silent CI skip of these
# tests was finding F-09; the required tier is the fix.
_REQUIRED_TIER = os.environ.get("OR_PICKER_REQUIRE_HERMES_AGENT", "").strip().lower() in {"1", "true", "yes"}
_PY = _hermes_agent_python()


def _run_driver(mode: str) -> dict:
    py = _PY
    assert py is not None, "hermes-agent interpreter required to run the discovery driver"
    out = subprocess.run(
        [str(py), str(DRIVER), str(INSTALL_SH), mode],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.integration
@pytest.mark.skipif(
    not _REQUIRED_TIER and _PY is None,
    reason="hermes-agent interpreter not available (hermetic tier; the required tier runs these)",
)
class TestProcessLifetimeHotDiscovery:
    def test_installer_repair_registers_provider_in_long_lived_process(self):
        # The fix: install.sh's repair bumps the profile model-providers dir mtime, so
        # the running gateway's natural stamp check re-scans and registers OR Picker on
        # the next lookup. Before the fix this returned registered=False (stale gateway cache).
        res = _run_driver("install_sh")
        assert res["dir_mtime_bumped"] is True, (
            "the installer must bump the profile model-providers dir mtime (the re-scan signal)")
        assert res["registered"] is True, (
            "after the installer repair a long-lived process must register OR Picker on the next lookup")

    def test_share_point_only_repair_leaves_process_stale(self):
        # Documents the root cause: repairing ONLY the share point (so the link resolves)
        # does NOT bump the profile dir mtime, so a long-lived process never re-scans and
        # the provider stays unregistered. This is the observed failure boundary.
        res = _run_driver("sharepoint_only")
        assert res["dir_mtime_bumped"] is False
        assert res["registered"] is False, (
            "a share-point-only repair must NOT register the provider in a long-lived process")

"""Installers must wire every profile home's model-provider discovery to the one plugin tree.

Hermes discovers model-provider plugins PER HOME: ``$HERMES_HOME/plugins/model-providers/<name>/``
(child dir with ``__init__.py``) or a flat ``$HERMES_HOME/plugins/<name>/`` declaring
``kind: model-provider``. The combined plugin installs flat into ONE home, so a single
``./install.sh`` registers OR Picker for the DEFAULT profile only. Secondary profile homes share
the provider through ``plugins/model-providers/or-picker`` links at the install-wide tree; when
that share point vanished (the one-plugin restructure's cleanup removed the old split copy), those
links dangled, discovery skipped them, and every non-default profile's default-model picker asked
for the API key even with OPENROUTER_API_KEY in its own ``.env``.

Contract asserted here (offline, hermetic — bash installer against a throwaway HERMES_HOME):
  1. ``plugins/model-providers/or-picker`` exists as the share point and resolves to the one
     plugin tree (``plugins/openrouter-picker``).
  2. Every profile home's ``plugins/model-providers/or-picker`` satisfies the discovery
     predicate ``is_dir()`` + ``__init__.py`` after install — including a pre-seeded DANGLING
     link (the incident state) and a home with no scaffolding at all.
  3. What discovery would import is byte-identical to ``catalog/__init__.py`` (one tree).
  4. An existing curated list (``openrouter-supplemental-models.json``) is never clobbered.
  5. install.ps1 (static check) declares the same wiring.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"
INSTALL_PS1 = ROOT / "install.ps1"


def _run_install(home: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}
    env["HERMES_HOME"] = str(home)
    return subprocess.run(
        ["bash", str(INSTALL_SH)], env=env, capture_output=True, text=True, check=True
    )


def _discovery_ok(link: Path) -> bool:
    """The exact predicate `providers._scan_home_layer` applies to `plugins/model-providers/`
    children: a directory (symlinks followed) containing `__init__.py`."""
    return link.is_dir() and (link / "__init__.py").is_file()


@pytest.fixture()
def hermes_home(tmp_path: Path) -> Path:
    home = tmp_path / ".hermes"
    home.mkdir()
    return home


class TestSharePoint:
    def test_legacy_share_point_resolves_to_one_tree(self, hermes_home: Path):
        _run_install(hermes_home)
        share = hermes_home / "plugins" / "model-providers" / "or-picker"
        one_tree = hermes_home / "plugins" / "openrouter-picker"
        assert share.is_symlink(), "legacy share point must be a link at the one plugin tree"
        assert share.resolve() == one_tree.resolve()
        assert _discovery_ok(share)

    def test_flat_install_unchanged(self, hermes_home: Path):
        _run_install(hermes_home)
        one_tree = hermes_home / "plugins" / "openrouter-picker"
        assert (one_tree / "__init__.py").is_file()
        assert "kind: model-provider" in (one_tree / "plugin.yaml").read_text()


class TestProfileWiring:
    def test_repairs_dangling_profile_link(self, hermes_home: Path):
        # The incident state: every non-default home's share link pointed at the
        # install-wide path the one-plugin cleanup had removed.
        dangling = hermes_home / "profiles" / "betty" / "plugins" / "model-providers"
        dangling.mkdir(parents=True)
        link = dangling / "or-picker"
        link.symlink_to(hermes_home / "plugins" / "model-providers" / "or-picker")
        assert not link.exists(), "precondition: link must start dangling"

        _run_install(hermes_home)

        assert _discovery_ok(link), "dangling profile link must resolve to a provider dir"
        assert (link / "__init__.py").read_bytes() == (
            ROOT / "catalog" / "__init__.py"
        ).read_bytes(), "discovery must import the one tree, not a stale copy"

    def test_wires_profile_home_without_scaffolding(self, hermes_home: Path):
        (hermes_home / "profiles" / "crafty").mkdir(parents=True)
        _run_install(hermes_home)
        link = (
            hermes_home / "profiles" / "crafty" / "plugins" / "model-providers" / "or-picker"
        )
        assert _discovery_ok(link), "a profile home with no scaffolding must be wired too"

    def test_wired_link_carries_model_provider_manifest(self, hermes_home: Path):
        (hermes_home / "profiles" / "oompah").mkdir(parents=True)
        _run_install(hermes_home)
        link = (
            hermes_home / "profiles" / "oompah" / "plugins" / "model-providers" / "or-picker"
        )
        assert _discovery_ok(link)
        assert "kind: model-provider" in (link / "plugin.yaml").read_text()

    def test_existing_real_copy_matches_source_unchanged(self, hermes_home: Path):
        # A REAL copy (not a symlink - the old test silently ended up writing through
        # a freshly linked dir into the one tree) whose bytes match the source stays
        # unchanged. Ownership/migration semantics live in test_install_ownership.py.
        _run_install(hermes_home)  # create the one tree first
        own = hermes_home / "profiles" / "statler" / "plugins" / "model-providers" / "or-picker"
        own.parent.mkdir(parents=True, exist_ok=True)
        if own.is_symlink():
            own.unlink()
        own.mkdir(parents=True, exist_ok=True)
        source_init = hermes_home / "plugins" / "openrouter-picker" / "__init__.py"
        source_plug = hermes_home / "plugins" / "openrouter-picker" / "plugin.yaml"
        (own / "__init__.py").write_bytes(source_init.read_bytes())
        (own / "plugin.yaml").write_bytes(source_plug.read_bytes())
        assert not own.is_symlink(), "precondition: real copy fixture, not a symlink"
        _run_install(hermes_home)
        assert not own.is_symlink(), "a real copy must stay a real copy (no symlink conversion)"
        assert (own / "__init__.py").read_bytes() == source_init.read_bytes()
        assert (own / "plugin.yaml").read_bytes() == source_plug.read_bytes()

    def test_custom_real_copy_preserved_not_refreshed(self, hermes_home: Path):
        # Arbitrary local bytes are a DELIBERATE OVERRIDE: the installer must preserve
        # them and warn (the old test asserted arbitrary-copy overwrite, which violates
        # the explicit preserve-overrides contract).
        _run_install(hermes_home)  # create the one tree first
        own = hermes_home / "profiles" / "statler" / "plugins" / "model-providers" / "or-picker"
        own.parent.mkdir(parents=True, exist_ok=True)
        if own.is_symlink():
            own.unlink()
        own.mkdir(parents=True, exist_ok=True)
        (own / "__init__.py").write_text("# profile-local copy v1\n")
        (own / "plugin.yaml").write_text("# local manifest\n")
        (own / "keep.txt").write_text("must survive")
        assert not own.is_symlink(), "precondition: real copy fixture, not a symlink"
        run = _run_install(hermes_home)
        assert not own.is_symlink()
        assert (own / "__init__.py").read_text() == "# profile-local copy v1\n"
        assert (own / "plugin.yaml").read_text() == "# local manifest\n"
        assert (own / "keep.txt").read_text() == "must survive"
        out = run.stdout + run.stderr
        assert "WARNING" in out and "preserv" in out.lower(), (
            "preserving a custom copy must be visible in installer output")

    def test_running_process_rescan_signal_bumped(self, hermes_home: Path):
        # A running gateway's per-home discovery re-scans a home's plugins ONLY when the
        # home's plugins/model-providers dir mtime changes (providers._plugin_dir_stamps).
        # A share-point-only repair resolves a profile link WITHOUT touching that dir, so
        # a live backend never re-scans and OR Picker stays unregistered ("Set up OR
        # Picker"). install.sh must bump that dir's mtime so the next lookup re-scans.
        (hermes_home / "profiles" / "betty").mkdir(parents=True)
        _run_install(hermes_home)  # creates the tree + a resolving share-point link
        mp_dir = hermes_home / "profiles" / "betty" / "plugins" / "model-providers"
        assert _discovery_ok(mp_dir / "or-picker")
        # Simulate "the running gateway last scanned this home long ago".
        old = 1_600_000_000
        os.utime(mp_dir, (old, old))
        before = mp_dir.stat().st_mtime_ns
        _run_install(hermes_home)  # the repair
        after = mp_dir.stat().st_mtime_ns
        assert after > before, (
            "install must bump the profile model-providers dir mtime (the re-scan signal "
            "a running gateway needs to register OR Picker without a restart)")


class TestSafety:
    def test_existing_curated_list_preserved(self, hermes_home: Path):
        curated = hermes_home / "openrouter-supplemental-models.json"
        curated.write_text('{"version": 1, "providers": {"openrouter": {"models": []}}}')
        _run_install(hermes_home)
        assert curated.read_text().startswith('{"version": 1'), "curated list must survive install"

    def test_no_unrelated_profile_files_touched(self, hermes_home: Path):
        prof = hermes_home / "profiles" / "warden"
        (prof / "plugins" / "model-providers").mkdir(parents=True)
        (prof / "plugins" / "model-providers" / "keepme.txt").write_text("keep")
        _run_install(hermes_home)
        assert (prof / "plugins" / "model-providers" / "keepme.txt").read_text() == "keep"


class TestWindowsInstallerParity:
    def test_install_ps1_declares_profile_wiring(self):
        # Static parity check: the PowerShell installer must carry the same share-point +
        # per-profile wiring (it cannot be executed on this host).
        text = INSTALL_PS1.read_text()
        assert "model-providers" in text and "or-picker" in text
        assert "profiles" in text, "install.ps1 must wire profile homes like install.sh"

    def test_install_ps1_bumps_rescan_signal(self):
        # install.ps1 must bump the profile model-providers dir mtime in its skip path,
        # matching install.sh: a running gateway re-scans on a dir-mtime change only, so
        # a share-point-only repair would otherwise leave OR Picker unregistered.
        text = INSTALL_PS1.read_text()
        assert "LastWriteTime" in text, (
            "install.ps1 must bump the model-providers dir mtime (LastWriteTime) so a "
            "running gateway re-scans and registers OR Picker without a restart")

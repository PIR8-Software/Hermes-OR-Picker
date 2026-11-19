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

    def test_existing_real_copy_left_alone(self, hermes_home: Path):
        # A profile that already carries its own working provider dir keeps it.
        own = hermes_home / "profiles" / "statler" / "plugins" / "model-providers" / "or-picker"
        own.mkdir(parents=True)
        (own / "__init__.py").write_text("# profile-local copy\n")
        _run_install(hermes_home)
        assert (own / "__init__.py").read_text() == "# profile-local copy\n"


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

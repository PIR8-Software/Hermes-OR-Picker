"""Installer ownership/migration contract — F01-F03 regression suite.

Real provider copies (Windows-fallback / manual copy state) at
``plugins/model-providers/or-picker`` (root share point or profile links) must be
classified by ownership, never blanket-overwritten:

  * installer-owned copy (``or-picker-install-receipt.txt`` verifies current files)
        -> refreshed A->B IN PLACE, unrelated files kept (F-01/F-02 fix)
  * known legacy bytes (exact pair listed in ``install/known-legacy-pairs.txt``)
        -> migrated A->B in place, unrelated files kept, receipt written
  * imported current bytes (byte-equal to ``catalog/`` right now)
        -> adopted: receipt written, files untouched
  * custom / ambiguous (override bytes, missing manifest, modified-after-receipt)
        -> PRESERVED with a visible WARNING, nothing written or deleted

Path contract (F-03): profile-scoped ``HERMES_HOME=<root>/profiles/<name>`` — with or
without trailing separator, in both separator styles — installs into ``<root>``.

All executable checks run REAL bash and REAL Linux pwsh (label: Linux pwsh, NOT a
Windows qualification) against disposable homes.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"
INSTALL_PS1 = ROOT / "install.ps1"
REGISTRY = ROOT / "install" / "known-legacy-pairs.txt"
RECEIPT_NAME = "or-picker-install-receipt.txt"
SHELLS = ["bash", "pwsh"]

LEGACY_SPLIT = ROOT / "tests" / "fixtures" / "legacy_split"  # A-split 29226bec bytes
LEGACY_CATALOG = ROOT / "tests" / "fixtures" / "legacy_catalog"  # B-catalog 5f360c80 bytes


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _receipt_for(init_bytes: bytes, plugin_bytes: bytes) -> str:
    """Exactly the receipt format the installers write (frozen by this test)."""
    return (
        "owner=openrouter-picker-installer\n"
        "schema=1\n"
        f"init_sha256={_sha(init_bytes)}\n"
        f"plugin_sha256={_sha(plugin_bytes)}\n"
    )


def _run(shell: str, selected: Path | str, base: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}
    env["HERMES_HOME"] = str(selected)  # keep trailing separators verbatim (str, not Path)
    env["HOME"] = str(base)
    env["USERPROFILE"] = str(base)
    env["LOCALAPPDATA"] = str(base / "localapp")
    cmd = (
        ["bash", str(INSTALL_SH)]
        if shell == "bash"
        else ["pwsh", "-NoProfile", "-File", str(INSTALL_PS1)]
    )
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


@pytest.fixture()
def home(tmp_path: Path):
    """Disposable home with profiles betty + alice and a nonempty curated list."""
    base = tmp_path
    h = base / "hermes"
    (h / "profiles" / "betty").mkdir(parents=True)
    (h / "profiles" / "alice").mkdir(parents=True)
    curated = h / "openrouter-supplemental-models.json"
    curated.write_text('{"user": "preserve this nonempty list"}')
    return base, h


def _seed_copy(link: Path, init_bytes: bytes, plugin_bytes: bytes | None, receipt: str | None, extra: bool = True):
    link.mkdir(parents=True)
    (link / "__init__.py").write_bytes(init_bytes)
    if plugin_bytes is not None:
        (link / "plugin.yaml").write_bytes(plugin_bytes)
    if receipt is not None:
        (link / RECEIPT_NAME).write_text(receipt)
    if extra:
        (link / "keep.txt").write_text("must survive")


def _betty_copy(h: Path) -> Path:
    return h / "profiles" / "betty" / "plugins" / "model-providers" / "or-picker"


def _curated_ok(h: Path) -> bool:
    return (h / "openrouter-supplemental-models.json").read_text() == (
        '{"user": "preserve this nonempty list"}'
    )


# ---------------------------------------------------------------------------
# F-03: root/profile normalization (both shells, both separators, trailing sep)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_scoped_profile_home_installs_into_root(shell, home):
    base, h = home
    run = _run(shell, h / "profiles" / "betty", base)
    assert run.returncode == 0, run.stderr
    assert (h / "plugins" / "openrouter-picker" / "__init__.py").is_file(), (
        "profile-scoped HERMES_HOME must install into <root>, not inside the profile"
    )
    alice = h / "profiles" / "alice" / "plugins" / "model-providers" / "or-picker"
    assert alice.is_dir() and (alice / "__init__.py").is_file(), (
        "sibling profile must be wired from a profile-scoped install"
    )
    assert not (h / "profiles" / "betty" / "openrouter-supplemental-models.json").exists(), (
        "starter JSON must not be written inside the profile home"
    )
    assert _curated_ok(h)


@pytest.mark.parametrize("shell", SHELLS)
def test_scoped_profile_home_trailing_separator_installs_into_root(shell, home):
    base, h = home
    selected = str(h / "profiles" / "betty") + os.sep
    run = _run(shell, selected, base)
    assert run.returncode == 0, run.stderr
    assert (h / "plugins" / "openrouter-picker" / "__init__.py").is_file(), (
        "a trailing separator must not defeat profile-scoped root detection"
    )
    alice = h / "profiles" / "alice" / "plugins" / "model-providers" / "or-picker"
    assert alice.is_dir() and (alice / "__init__.py").is_file()
    assert _curated_ok(h)


# ---------------------------------------------------------------------------
# Override preservation (rejection probes, executable)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_custom_override_preserved_with_warning(shell, home):
    """Review probe custom_override: custom __init__.py + current plugin.yaml + keep.txt."""
    base, h = home
    link = _betty_copy(h)
    _seed_copy(
        link,
        b"# deliberate profile-local override\n",
        (ROOT / "catalog" / "plugin.yaml").read_bytes(),
        receipt=None,
    )
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    out = run.stdout + run.stderr
    assert (link / "__init__.py").read_text() == "# deliberate profile-local override\n"
    assert (link / "keep.txt").read_text() == "must survive"
    assert "WARNING" in out and "preserv" in out.lower(), (
        "preserving a custom copy must be visible in installer output"
    )
    assert not link.is_symlink()
    assert _curated_ok(h)


@pytest.mark.parametrize("shell", SHELLS)
def test_missing_manifest_preserved_no_crash(shell, home):
    """Review probe copy_missing_manifest: __init__.py + keep.txt, NO plugin.yaml."""
    base, h = home
    link = _betty_copy(h)
    _seed_copy(link, b"# deliberate profile-local override\n", None, receipt=None)
    run = _run(shell, h, base)
    assert run.returncode == 0, f"installer must not crash on a missing manifest: {run.stderr}"
    out = run.stdout + run.stderr
    assert (link / "__init__.py").read_text() == "# deliberate profile-local override\n"
    assert (link / "keep.txt").read_text() == "must survive"
    assert "plugin.yaml" in out, "the diagnostic must name the missing manifest"
    assert not link.is_symlink()
    assert _curated_ok(h)


@pytest.mark.parametrize("shell", SHELLS)
def test_ambiguous_custom_bytes_preserved(shell, home):
    """Custom bytes on BOTH managed files are never redefined as stale."""
    base, h = home
    link = _betty_copy(h)
    _seed_copy(link, b"# custom init\n", b"name: custom\n", receipt=None)
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    assert (link / "__init__.py").read_bytes() == b"# custom init\n"
    assert (link / "plugin.yaml").read_bytes() == b"name: custom\n"
    assert (link / "keep.txt").exists()
    assert not link.is_symlink()


# ---------------------------------------------------------------------------
# Owned A->B migration (F-01/F-02 regression coverage)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_owned_copy_upgraded_in_place_preserves_extras(shell, home):
    """Receipt-verified copy of known versionA bytes refreshes to versionB (current
    catalog bytes) without deleting unrelated files (versionA->B fixture)."""
    base, h = home
    link = _betty_copy(h)
    a_init = (LEGACY_CATALOG / "__init__.py").read_bytes()
    a_plugin = (LEGACY_CATALOG / "plugin.yaml").read_bytes()
    _seed_copy(link, a_init, a_plugin, receipt=_receipt_for(a_init, a_plugin))
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    assert not link.is_symlink(), "real copies must stay real copies (no symlink conversion)"
    assert (link / "__init__.py").read_bytes() == (ROOT / "catalog" / "__init__.py").read_bytes()
    assert (link / "plugin.yaml").read_bytes() == (ROOT / "catalog" / "plugin.yaml").read_bytes()
    assert (link / "keep.txt").read_text() == "must survive", (
        "refreshing an owned copy must not delete unrelated files"
    )
    receipt = (link / RECEIPT_NAME).read_text()
    assert _sha((link / "__init__.py").read_bytes()) in receipt, "receipt must track the new bytes"
    assert _curated_ok(h)


@pytest.mark.parametrize("shell", SHELLS)
def test_known_legacy_copy_migrated_without_receipt(shell, home):
    """Split-era real copy (exact historical bytes, no receipt) is recognized as
    installer-owned legacy and migrated — not treated as an override."""
    base, h = home
    link = _betty_copy(h)
    _seed_copy(
        link,
        (LEGACY_SPLIT / "__init__.py").read_bytes(),
        (LEGACY_SPLIT / "plugin.yaml").read_bytes(),
        receipt=None,
    )
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    assert not link.is_symlink()
    assert (link / "__init__.py").read_bytes() == (ROOT / "catalog" / "__init__.py").read_bytes()
    assert (link / "plugin.yaml").read_bytes() == (ROOT / "catalog" / "plugin.yaml").read_bytes()
    assert (link / "keep.txt").read_text() == "must survive"
    assert (link / RECEIPT_NAME).is_file(), "migration must leave an ownership receipt"


@pytest.mark.parametrize("shell", SHELLS)
def test_imported_current_bytes_adopted(shell, home):
    """A receipt-less copy whose bytes equal the current catalog (imported bytes)
    is adopted, never destroyed or rewritten."""
    base, h = home
    link = _betty_copy(h)
    _seed_copy(
        link,
        (ROOT / "catalog" / "__init__.py").read_bytes(),
        (ROOT / "catalog" / "plugin.yaml").read_bytes(),
        receipt=None,
    )
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    assert not link.is_symlink()
    assert (link / "__init__.py").read_bytes() == (ROOT / "catalog" / "__init__.py").read_bytes()
    assert (link / "plugin.yaml").read_bytes() == (ROOT / "catalog" / "plugin.yaml").read_bytes()
    assert (link / "keep.txt").read_text() == "must survive"
    assert (link / RECEIPT_NAME).is_file(), "adoption must write an ownership receipt"


@pytest.mark.parametrize("shell", SHELLS)
def test_modified_after_receipt_is_preserved(shell, home):
    """A receipt whose files no longer match means the user took over: preserve."""
    base, h = home
    link = _betty_copy(h)
    a_init = (LEGACY_CATALOG / "__init__.py").read_bytes()
    a_plugin = (LEGACY_CATALOG / "plugin.yaml").read_bytes()
    _seed_copy(
        link,
        b"# user rewrote this after install\n",
        a_plugin,
        receipt=_receipt_for(a_init, a_plugin),
    )
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    assert (link / "__init__.py").read_bytes() == b"# user rewrote this after install\n"
    assert (link / "keep.txt").exists()


# ---------------------------------------------------------------------------
# Root share point: never unconditionally deleted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_share_point_real_dir_not_deleted(shell, home):
    base, h = home
    share = h / "plugins" / "model-providers" / "or-picker"
    _seed_copy(
        share,
        (LEGACY_SPLIT / "__init__.py").read_bytes(),
        (LEGACY_SPLIT / "plugin.yaml").read_bytes(),
        receipt=None,
    )
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    assert not share.is_symlink(), "an existing real copy is refreshed, not replaced"
    assert (share / "keep.txt").read_text() == "must survive", (
        "the share-point real dir must not be unconditionally deleted"
    )
    assert (share / "__init__.py").read_bytes() == (ROOT / "catalog" / "__init__.py").read_bytes()
    alice = h / "profiles" / "alice" / "plugins" / "model-providers" / "or-picker"
    assert alice.is_dir() and (alice / "__init__.py").is_file()


@pytest.mark.parametrize("shell", SHELLS)
def test_share_point_custom_dir_preserved(shell, home):
    base, h = home
    share = h / "plugins" / "model-providers" / "or-picker"
    _seed_copy(share, b"# custom root provider\n", None, receipt=None)
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    out = run.stdout + run.stderr
    assert (share / "__init__.py").read_bytes() == b"# custom root provider\n"
    assert (share / "keep.txt").exists()
    assert "WARNING" in out and "preserv" in out.lower()


# ---------------------------------------------------------------------------
# Discovery signal: strict mtime bump (both shells)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_discovery_mtime_strictly_bumped(shell, home):
    base, h = home
    (h / "profiles" / "betty").exists()
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    mp_dirs = [
        h / "plugins" / "model-providers",
        h / "profiles" / "betty" / "plugins" / "model-providers",
    ]
    old = 1_600_000_000
    for d in mp_dirs:
        os.utime(d, (old, old))
    before = [d.stat().st_mtime_ns for d in mp_dirs]
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    after = [d.stat().st_mtime_ns for d in mp_dirs]
    for b, a, d in zip(before, after, mp_dirs, strict=True):
        assert a > b, f"{d} mtime must strictly increase (gateway re-scan signal)"


# ---------------------------------------------------------------------------
# Curated data + registry sanity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_nonempty_curated_list_preserved(shell, home):
    base, h = home
    run = _run(shell, h, base)
    assert run.returncode == 0, run.stderr
    assert _curated_ok(h)


def test_registry_lists_version_a_fixture_pairs():
    reg = REGISTRY.read_text()
    for fixture in (LEGACY_SPLIT, LEGACY_CATALOG):
        pair = _sha((fixture / "__init__.py").read_bytes()) + " " + _sha((fixture / "plugin.yaml").read_bytes())
        assert pair in reg, f"{fixture.name} fixture pair must be a registered known-legacy pair"


# ---------------------------------------------------------------------------
# install.ps1 normalization block (verbatim extraction, Linux pwsh label)
# ---------------------------------------------------------------------------


def _run_normalization_block(install_root_literal: str) -> str:
    """Execute ONLY the extracted normalization block."""
    source = INSTALL_PS1.read_text()
    block = source[source.index("# Detect if") : source.index("function Copy-File")]
    command = f"$INSTALL_ROOT = '{install_root_literal}'\n{block}\nWrite-Output $INSTALL_ROOT"
    run = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
    return run.stdout.strip()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not available (Linux host)")
class TestPwshNormalization:
    def test_windows_style_double_separator_path(self):
        # Doubled separators, as a probe may build them.
        out = _run_normalization_block("C:\\\\Users\\\\Example\\\\.hermes\\\\profiles\\\\betty")
        assert out == "C:\\Users\\Example\\.hermes", out

    def test_windows_style_single_separator_path(self):
        out = _run_normalization_block("C:\\Users\\Example\\.hermes\\profiles\\betty")
        assert out == "C:\\Users\\Example\\.hermes", out

    def test_windows_style_trailing_separator(self):
        out = _run_normalization_block("C:\\Users\\Example\\.hermes\\profiles\\betty\\")
        assert out == "C:\\Users\\Example\\.hermes", out

    def test_posix_scoped_path(self):
        out = _run_normalization_block("/opt/hermes-fixture/profiles/betty")
        assert out == "/opt/hermes-fixture", out

    def test_posix_scoped_path_trailing_separator(self):
        out = _run_normalization_block("/opt/hermes-fixture/profiles/betty/")
        assert out == "/opt/hermes-fixture", out

    def test_posix_root_path_unchanged(self):
        out = _run_normalization_block("/opt/hermes-fixture")
        assert out == "/opt/hermes-fixture", out

    def test_windows_root_path_unchanged(self):
        out = _run_normalization_block("C:\\Users\\Example\\.hermes")
        assert out == "C:\\Users\\Example\\.hermes", out

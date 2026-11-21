"""CI/manifest hygiene regression tests (F-13) and the required-tier guarantee for the
process-lifetime integration tests (F-09).

Hermetic-suite members: no hermes runtime, no network, no live files touched. They
inspect the GitHub workflow contract (full-SHA action pins with provenance, least
privilege, finite timeouts, concurrency, required integration job path), the
``catalog/dashboard/manifest.json`` <-> ``catalog/plugin.yaml`` version coherence
contract, and behaviorally prove the required tier FAILS (never skips) when the
hermes-agent runtime is missing while the hermetic tier skips cleanly.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
MIN_DEPS = ROOT / ".ci" / "hermes-min-deps.txt"

# Full 40-hex action commit SHAs, verified read-only via `git ls-remote --tags` on
# 2026-11-20. Deliberate contract: updating an action means updating this table AND
# the provenance comment on the matching `uses:` line in the same change.
PINNED_ACTIONS = {
    "actions/checkout": {
        "sha": "11d5960a326750d5838078e36cf38b85af677262",  # v4.4.0 == moving tag v4
        "tag": "v4.4.0",
    },
    "actions/setup-node": {
        "sha": "49933ea5288caeca8642d1e84afbd3f7d6820020",  # v4.4.0 == moving tag v4
        "tag": "v4.4.0",
    },
    "astral-sh/setup-uv": {
        "sha": "d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86",  # v5.4.2 == moving tag v5 (peeled)
        "tag": "v5.4.2",
    },
}

# Tag v0.23.0 (peeled) of NousResearch/hermes-agent == the live discovery layer this
# repo's process-lifetime driver is validated against. Must match the `ref:` in the
# integration job and the pin documented in .ci/hermes-min-deps.txt.
PINNED_HERMES_COMMIT = "2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19"


def _workflow_text() -> str:
    return WORKFLOW.read_text()


def _uses_lines(text: str) -> list[tuple[str, str]]:
    """Return (action@ref, trailing comment) for every `uses:` entry."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^\s*-?\s*uses:\s*([^\s#]+)\s*(#\s*(.*))?$", line)
        if m:
            out.append((m.group(1), (m.group(3) or "").strip()))
    return out


def _job_sections(text: str) -> dict[str, str]:
    """Split the workflow body into {job_name: job_body} (2-space `jobs:` children)."""
    jobs: dict[str, str] = {}
    current = None
    in_jobs = False
    for line in text.splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if in_jobs and re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            current = line.strip().rstrip(":")
            jobs[current] = ""
        elif current is not None:
            jobs[current] += line + "\n"
    return jobs


class TestWorkflowActionPins:
    def test_every_action_is_full_sha_pinned_with_provenance(self):
        uses = _uses_lines(_workflow_text())
        assert uses, "workflow has no uses: entries"
        for target, comment in uses:
            action, _, ref = target.partition("@")
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{target}: must pin a full 40-hex commit SHA"
            assert action in PINNED_ACTIONS, f"{action}: unknown action - record provenance in this test"
            assert ref == PINNED_ACTIONS[action]["sha"], f"{action}: pin drifted from verified SHA"
            assert comment, f"{target}: missing provenance comment"
            assert "verified" in comment.lower(), f"{target}: provenance comment must say how it was verified"
            assert PINNED_ACTIONS[action]["tag"] in comment, f"{target}: comment must name the tagged release"

    def test_workflow_documents_pinned_hermes_commit(self):
        text = _workflow_text()
        assert PINNED_HERMES_COMMIT in text, "workflow must pin the authoritative hermes discovery commit"
        assert "repository: NousResearch/hermes-agent" in text, "hermes checkout must name the authoritative repo"


class TestWorkflowHardening:
    def test_least_privilege_permissions(self):
        text = _workflow_text()
        m = re.search(r"^permissions:\n((?:[ \t]+.*\n?)*)", text, re.M)
        assert m, "workflow must declare an explicit least-privilege permissions block"
        block = m.group(1)
        assert "contents: read" in block
        assert "write" not in block, "permissions must not grant write access"
        # jobs must not widen permissions on their own
        for name, body in _job_sections(text).items():
            assert "permissions:" not in body, f"job {name} overrides permissions"

    def test_finite_job_timeouts(self):
        text = _workflow_text()
        jobs = _job_sections(text)
        timeouts = [int(v) for v in re.findall(r"timeout-minutes:\s*(\d+)", text)]
        assert len(timeouts) == len(jobs) >= 1, "every job must declare timeout-minutes"
        for name, body in jobs.items():
            assert "timeout-minutes:" in body, f"job {name} has no timeout"
        assert all(1 <= t <= 60 for t in timeouts), f"timeouts must be finite and small: {timeouts}"

    def test_concurrency_group_with_cancel_in_progress(self):
        m = re.search(r"^concurrency:\n((?:[ \t]+.*\n?)*)", _workflow_text(), re.M)
        assert m, "workflow must declare a concurrency group"
        assert "cancel-in-progress: true" in m.group(1)


class TestRequiredIntegrationJob:
    def test_required_job_path_runs_process_lifetime_tests(self):
        jobs = _job_sections(_workflow_text())
        assert "integration" in jobs, "required integration job missing"
        integ = jobs["integration"]
        assert "tests/test_process_lifetime.py" in integ, "required job must run the process-lifetime path"
        assert 'OR_PICKER_REQUIRE_HERMES_AGENT: "1"' in integ, "required tier env var must be set"
        assert "HERMES_AGENT_PYTHON:" in integ and "HERMES_AGENT_SRC:" in integ
        assert ".ci/hermes-min-deps.txt" in integ, "required job must install the pinned minimal deps"

    def test_hermetic_job_excludes_integration_tests(self):
        jobs = _job_sections(_workflow_text())
        assert "hermetic" in jobs, "hermetic job missing"
        herm = jobs["hermetic"]
        assert '-m "not integration"' in herm, "hermetic suite must be separately labeled and exclude integration"
        assert "tests/test_process_lifetime.py" not in herm, "hermetic job must not run the integration path"
        assert "OR_PICKER_REQUIRE_HERMES_AGENT" not in herm

    def test_process_lifetime_file_defines_exactly_two_real_tests(self):
        text = (ROOT / "tests" / "test_process_lifetime.py").read_text()
        names = re.findall(r"^    def (test_\w+)\(", text, re.M)
        assert names == [
            "test_installer_repair_registers_provider_in_long_lived_process",
            "test_share_point_only_repair_leaves_process_stale",
        ], "the required tier's expected 2 tests must stay exactly these"


class TestRequiredTierNeverSkips:
    """Behavioral proof of the F-09 fix: in the required tier a missing runtime fails;
    in the hermetic tier it skips. Runs the real pytest entrypoints, no stubs."""

    def _inner(self, tmp_path: Path, required: bool) -> subprocess.CompletedProcess[str]:
        home = tmp_path / "home"
        home.mkdir()
        env = os.environ.copy()
        for key in ("PYTEST_ADDOPTS", "OR_PICKER_REQUIRE_HERMES_AGENT", "HERMES_AGENT_PYTHON", "HERMES_AGENT_SRC"):
            env.pop(key, None)
        env["HOME"] = str(home)
        env["HERMES_HOME"] = str(home / ".hermes")
        env["HERMES_AGENT_PYTHON"] = str(tmp_path / "no-such-hermes-python")
        if required:
            env["OR_PICKER_REQUIRE_HERMES_AGENT"] = "1"
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/test_process_lifetime.py"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
        )

    def test_required_tier_fails_when_runtime_missing(self, tmp_path):
        r = self._inner(tmp_path, required=True)
        assert r.returncode != 0, "required tier must FAIL without the runtime:\n" + r.stdout
        assert "2 failed" in r.stdout, r.stdout
        assert "skipped" not in r.stdout, "required tier must never skip:\n" + r.stdout

    def test_hermetic_tier_skips_when_runtime_missing(self, tmp_path):
        r = self._inner(tmp_path, required=False)
        assert r.returncode == 0, r.stdout
        assert "2 skipped" in r.stdout, r.stdout


class TestManifestContract:
    def test_dashboard_manifest_contract_and_version_coherence(self):
        manifest = json.loads((ROOT / "catalog" / "dashboard" / "manifest.json").read_text())
        for key in ("name", "label", "description", "version", "api"):
            assert key in manifest, f"manifest.json missing {key}"
        assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]), "manifest version must be semver"

        plugin_yaml = (ROOT / "catalog" / "plugin.yaml").read_text()
        name_m = re.search(r'^name:\s*"?([^"\n]+)"?\s*$', plugin_yaml, re.M)
        ver_m = re.search(r'^version:\s*"?([^"\n]+)"?\s*$', plugin_yaml, re.M)
        assert name_m and ver_m
        assert manifest["name"] == name_m.group(1), "manifest name must match plugin.yaml name"
        assert manifest["version"] == ver_m.group(1), (
            f"version drift: manifest.json says {manifest['version']!r} "
            f"plugin.yaml says {ver_m.group(1)!r} - one source of truth")
        assert (ROOT / "catalog" / "dashboard" / manifest["api"]).is_file(), "manifest api must name a real file"

    def test_hermes_min_deps_pin_matches_workflow_and_commit(self):
        assert MIN_DEPS.is_file()
        deps_text = MIN_DEPS.read_text()
        assert PINNED_HERMES_COMMIT in deps_text, "min-deps file must document the pinned hermes commit"
        reqs = [ln.strip() for ln in deps_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        assert reqs, "min-deps file must list requirements"
        for req in reqs:
            base = req.split(";", 1)[0].strip()
            assert re.fullmatch(r"[A-Za-z0-9_.\-]+==\S+", base), f"every dep must be exact-pinned: {req!r}"
        wf = _workflow_text()
        assert ".ci/hermes-min-deps.txt" in wf
        assert PINNED_HERMES_COMMIT in wf, "workflow hermes ref and min-deps pin must name the same commit"

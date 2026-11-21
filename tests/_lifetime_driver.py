#!/usr/bin/env python3
"""Driver: reproduce the OR Picker process-lifetime transition in ONE long-lived process.

Models the running gateway's PER-HOME provider discovery across a link repair:
    provider initially absent (dangling plugins/model-providers/or-picker),
    link repaired, NEXT LOOKUP -> is the provider registered (hot discovery)?

The per-home discovery target is the PROFILE home (profiles/<name>), which relies solely
on its model-providers/or-picker symlink. Stamps are backdated so they look SETTLED (a
long-running gateway): the ONLY re-scan trigger is the profile dir mtime changing.

repair_mode:
  "sharepoint_only"  -- recreate ONLY the share point (the earlier repair). The profile
                        home's model-providers dir mtime is left unchanged -> BUG: the
                        running process never re-scans, provider stays unregistered.
  "install_sh"       -- run the repo's install.sh (the fix). It must bump the profile
                        home's model-providers dir mtime so the running process re-scans.

Prints one JSON line: {"registered": bool, "mode": ..., "dir_mtime_bumped": bool}.

Run with the hermes-agent interpreter (needs `providers` + deps):
    python tests/_lifetime_driver.py <install_sh> <repair_mode>
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERMES_AGENT = Path(os.environ.get("HERMES_AGENT_SRC", str(Path.home() / ".hermes" / "hermes-agent")))
sys.path.insert(0, str(HERMES_AGENT))

SETTLED = 1_600_000_000  # fixed past epoch -> deterministic "settled" dir stamps


def _settle(path: Path) -> None:
    os.utime(path, (SETTLED, SETTLED))


def lookup_registered(profile_home: Path) -> bool:
    os.environ["HERMES_HOME"] = str(profile_home)
    import providers
    from hermes_cli.auth import PROVIDER_REGISTRY
    prof = providers.get_provider_profile("or-picker")
    return bool(prof is not None or "or-picker" in PROVIDER_REGISTRY)


def force_stamp_check_due(profile_home: Path) -> None:
    """Make the periodic stamp check due WITHOUT forcing a re-scan: registration must be
    driven by the dir-mtime change, exactly like the running gateway's natural check."""
    import providers
    from hermes_constants import hermes_home_key
    layer = providers._HOME_LAYERS.get(hermes_home_key(profile_home))
    if layer is not None:
        layer.stamp_checked_at = 0.0  # TTL elapsed -> next lookup re-stats the plugin dirs


def main() -> int:
    install_sh = Path(sys.argv[1]).resolve()
    mode = sys.argv[2] if len(sys.argv) > 2 else "install_sh"
    catalog = install_sh.parent / "catalog"
    tmp = Path(tempfile.mkdtemp(prefix="orpicker_lifetime_"))
    root = tmp / ".hermes"
    profile_home = root / "profiles" / "betty"
    try:
        # INCIDENT state: betty's model-providers/or-picker dangles at a share point that
        # does not exist yet. Discovery must see the provider as absent.
        share_dir = root / "plugins" / "model-providers"
        mp_dir = profile_home / "plugins" / "model-providers"
        mp_dir.mkdir(parents=True)
        share_dir.mkdir(parents=True)
        link = mp_dir / "or-picker"
        link.symlink_to(share_dir / "or-picker")  # dangling: share point not created yet
        # Settle every dir the stamp check reads so the ONLY re-scan signal is a later
        # mtime change (a long-running gateway's stamps are old, not "just created").
        for d in (profile_home / "plugins", mp_dir, root / "plugins", share_dir):
            _settle(d)

        # PHASE A: provider absent (dangling link); long-lived discovery caches the miss.
        assert lookup_registered(profile_home) is False, "precondition: dangling link must not register"
        mtime_before = mp_dir.stat().st_mtime_ns

        # REPAIR
        if mode == "sharepoint_only":
            one_tree = root / "plugins" / "openrouter-picker"
            shutil.copytree(catalog, one_tree)
            (share_dir / "or-picker").symlink_to(one_tree)  # betty's link now resolves
        else:
            env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}
            env["HERMES_HOME"] = str(root)
            subprocess.run(["bash", str(install_sh)], env=env, check=True, capture_output=True)

        mtime_after = mp_dir.stat().st_mtime_ns
        bumped = mtime_after != mtime_before

        # PHASE B: NEXT LOOKUP (same long-lived process). Registration must now happen iff
        # the dir-mtime change signaled a re-scan.
        force_stamp_check_due(profile_home)
        registered = lookup_registered(profile_home)

        print(json.dumps({"registered": registered, "mode": mode, "dir_mtime_bumped": bumped}))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

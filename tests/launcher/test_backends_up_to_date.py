"""The readiness ribbon and Dashboard > Service status list every backend, release after release.

Offline: every container a compose file runs is tracked by core/appliance_readiness.py,
and an optional backend is tracked only by the stacks that run it (its env var is set
for the simulator exactly when its container is defined), so no stack waits forever on
a backend it never starts. Nano: fixtures/nano-backends.json (generated from
core/nano_registry.py by wasm/build_cores.py) is current, and every store passes the live check the cards use
(nano_persist.health_registry), which must also catch a store that can't be read.

    python tests/launcher/test_backends_up_to_date.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core import appliance_readiness as R  # noqa: E402

COMPOSE = ["docker-compose.cloudlite.yml", "docker-compose.yml", "docker-compose.appliance.yml"]
ALIASES = {"gcs": "fake-gcs"}   # compose name (minus vyomi-/sql-) -> readiness key
NOT_BACKENDS = {"caddy": "the HTTPS front door for the console", "portal": "dev-only portal (docker-compose.yml)"}


def services(path: Path) -> list[str]:
    top = re.search(r"^services:\n(.*?)(?=^\S|\Z)", path.read_text(), re.S | re.M).group(1)
    return re.findall(r"^  ([a-zA-Z0-9_.-]+):\s*$", top, re.M)


def key(name: str) -> str:
    k = re.sub(r"^(vyomi|cloudlearn)-", "", name)
    k = re.sub(r"^sql-", "", k)
    return ALIASES.get(k, k)


def main() -> int:
    bad: list[str] = []
    tracked = {b[0] for b in R._BACKENDS}
    for f in COMPOSE:
        p = ROOT / f
        if not p.exists():
            continue
        text = p.read_text()
        ran = {key(s) for s in services(p)} - set(NOT_BACKENDS)
        for k in sorted(ran - tracked):
            bad.append(f"{f}: runs '{k}' but core/appliance_readiness.py doesn't track it")
        for k in sorted(getattr(R, "_OPTIONAL", ())):
            env = R._CANONICAL_ENV[k]
            sets = re.search(r"^\s+%s:" % re.escape(env), text, re.M) is not None
            if (k in ran) != sets:
                bad.append(f"{f}: '{k}' container {'defined' if k in ran else 'absent'} but "
                           f"{env} {'not ' if not sets else ''}set for the simulator")

    # Nano's list is generated from the registry (wasm/build_cores.py); it must be current.
    import json
    sys.path.insert(0, str(ROOT / "wasm"))
    import build_cores
    listed = json.load(open(ROOT / "wasm/fixtures/nano-backends.json"))
    if listed != build_cores.nano_backends():
        bad.append("wasm/fixtures/nano-backends.json is stale: run python3 wasm/build_cores.py")

    # Nano's live check (what the Service status cards show) passes on every store of
    # the shipped engines, and reports a store that can't be read.
    for m in [m for m in sys.modules if m == "core" or m.startswith("core.")]:
        del sys.modules[m]                     # use the vendored wasm/core, as Nano does
    from core import nano_persist as NP, nano_registry as NR
    health = NP.health_registry()
    for k, v in health.items():
        if not v["ok"]:
            bad.append(f"Nano engine store '{k}' ({v['engine']}) fails its live check: {v.get('error')}")
    saved = NR.get()["kms"]
    NR.get()["kms"] = None
    if NP.health_registry().get("kms", {}).get("ok"):
        bad.append("nano_persist.health_registry() reported a missing store as ok")
    NR.get()["kms"] = saved

    if bad:
        print("[FAIL] backend lists are behind the release:\n  " + "\n  ".join(bad))
        return 1
    print(f"[PASS] readiness tracks all {len(tracked)} offline backends; Nano lists all {len(listed)} backends; "
          f"all {len(health)} Nano engine stores pass the live check")
    return 0


if __name__ == "__main__":
    sys.exit(main())

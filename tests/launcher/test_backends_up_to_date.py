"""The readiness ribbon and Dashboard > Service status list every backend, release after release.

Offline: every container a compose file runs is tracked by core/appliance_readiness.py,
and an optional backend is tracked only by the stacks that run it (its env var is set
for the simulator exactly when its container is defined), so no stack waits forever on
a backend it never starts. Nano: every store in core/nano_registry.py belongs to an
engine in wasm/sw.js NANO_SERVICES.

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

    reg = (ROOT / "core/nano_registry.py").read_text()
    stores = set(re.findall(r'^\s+"([a-z0-9_]+)":\s', reg[reg.index("def get("):], re.M))
    sw = (ROOT / "wasm/sw.js").read_text()
    block = sw[sw.index("const NANO_SERVICES = ["):]
    block = block[:block.index("];") + 1]
    covered = {s for arr in re.findall(r"stores:\s*(\[[^\]]*\])", block) for s in ast.literal_eval(arr)}
    for s in sorted(stores - covered):
        bad.append(f"core/nano_registry.py store '{s}' has no engine in wasm/sw.js NANO_SERVICES")

    if bad:
        print("[FAIL] backend lists are behind the release:\n  " + "\n  ".join(bad))
        return 1
    print(f"[PASS] readiness tracks all {len(tracked)} offline backends; NANO_SERVICES covers {len(stores)} registry stores")
    return 0


if __name__ == "__main__":
    sys.exit(main())

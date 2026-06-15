"""Env-var alias bridge — Phase 8 of the v2.0.0 vyomi rebrand.

The appliance historically reads ``CLOUDLEARN_*`` env vars (~69 of them
spanning compose service URLs, license/tier knobs, instance config,
runtime bridge tokens, etc.). Starting v2.0.0 the canonical prefix is
``VYOMI_*`` — but we ship a runtime mirror so existing deployments,
user .env files, Dockerfiles, and CI configs keep working.

How it works
------------

Called once at module import time (server.py, scripts that use the
Python helpers, etc.). For every ``CLOUDLEARN_X`` key in ``os.environ``
we set ``VYOMI_X`` to the same value if it isn't already set, and
vice-versa. Existing code that reads ``os.environ.get("CLOUDLEARN_X")``
keeps working. New code can use ``VYOMI_X`` everywhere.

Idempotent. Conflict-safe: if both names are already set with different
values, neither is overwritten.

The bash launcher (``scripts/cloud-learn``) does the same at shell
level so non-Python paths (the launcher itself, ``docker compose``
invocations spawned by it) also see both names.

Slated for removal in v3.0 alongside the CLI shim, header alias
middleware, and other v2.0.0 back-compat layers.
"""
from __future__ import annotations

import os
from typing import Iterable

_OLD_PREFIX = "CLOUDLEARN_"
_NEW_PREFIX = "VYOMI_"


def mirror_env(env: dict | None = None) -> tuple[int, list[str]]:
    """Bidirectionally mirror CLOUDLEARN_* ↔ VYOMI_* in the given env
    dict (defaults to ``os.environ``). Returns (count, conflicts) where
    ``count`` is the number of aliases added and ``conflicts`` is the
    list of base names that already had BOTH variants set with different
    values (those are left untouched).

    Idempotent — running twice produces the same result on the second
    call (count=0 on second call, no conflicts re-flagged).
    """
    target = env if env is not None else os.environ
    snapshot: Iterable[tuple[str, str]] = list(target.items())
    added = 0
    conflict_set: set[str] = set()
    for key, value in snapshot:
        if key.startswith(_OLD_PREFIX):
            base = key[len(_OLD_PREFIX):]
            alias = _NEW_PREFIX + base
        elif key.startswith(_NEW_PREFIX):
            base = key[len(_NEW_PREFIX):]
            alias = _OLD_PREFIX + base
        else:
            continue
        if alias in target:
            if target[alias] != value:
                # Both keys flag the same conflict — dedup via set.
                conflict_set.add(base)
            continue
        target[alias] = value
        added += 1
    return added, sorted(conflict_set)


# Run on import. Most importers want this side-effect; opting out is
# possible by using mirror_env() directly with an empty dict (rare).
_count, _conflicts = mirror_env()
if _conflicts:
    # Don't crash — just emit a one-time stderr note. If both VYOMI_X
    # and CLOUDLEARN_X are set to different values, the deployer almost
    # certainly meant for the values to converge; let them know.
    import sys
    sys.stderr.write(
        "env_aliases: %d env var(s) have BOTH CLOUDLEARN_* and VYOMI_* set "
        "with different values (left untouched): %s\n" % (
            len(_conflicts), ", ".join(_conflicts[:10])
            + ("…" if len(_conflicts) > 10 else "")
        )
    )

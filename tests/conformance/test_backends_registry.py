"""Backends registry validation — the "How Vyomi runs this service" side-panel data.

core/capabilities/backends/<cloud>.json documents, per service, how Vyomi runs it on each
substrate (schema: docs/architecture/v4.0/BACKENDS-SCHEMA.md). This test checks that

  * every registry file core/capabilities/<cloud>/<service>.json has a key in the data file,
  * required fields are present and correctly typed,
  * `kind` values are valid, `summary` is non-empty,
  * nano.kind == "unavailable" carries explanatory notes.

A cloud whose data file does not exist yet is SKIPPED with a clear message, so this test can
land before the data. Set BACKENDS_DIR to validate a data directory other than the default.

Run:  PYTHONPATH=. python3 tests/conformance/test_backends_registry.py
  or  python3 -m pytest tests/conformance/test_backends_registry.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPS = ROOT / "core" / "capabilities"
BACKENDS = Path(os.environ.get("BACKENDS_DIR") or CAPS / "backends")
CLOUDS = ("aws", "gcp", "azure")
KINDS = {"opensource", "inhouse", "hybrid"}
NANO_KINDS = KINDS | {"unavailable"}
LIST_FIELDS = ("wire", "differs", "notInScope", "sources")


def service_ids(cloud: str) -> list[str]:
    return sorted(p.stem for p in (CAPS / cloud).glob("*.json"))


def _is_strs(x) -> bool:
    return isinstance(x, list) and all(isinstance(i, str) and i.strip() for i in x)


def validate_entry(sid: str, e) -> list[str]:
    """Problems with one service entry (empty list = valid)."""
    if not isinstance(e, dict):
        return [f"{sid}: entry must be an object"]
    errs: list[str] = []
    for f in ("title", "summary"):
        if not isinstance(e.get(f), str) or not e[f].strip():
            errs.append(f"{sid}: '{f}' must be a non-empty string")
    for f in LIST_FIELDS:
        if f not in e:
            errs.append(f"{sid}: missing '{f}'")
        elif not _is_strs(e[f]):
            errs.append(f"{sid}: '{f}' must be a list of non-empty strings")
    if isinstance(e.get("wire"), list) and not e["wire"]:
        errs.append(f"{sid}: 'wire' must not be empty")
    for side, kinds in (("offline", KINDS), ("nano", NANO_KINDS)):
        s = e.get(side)
        if not isinstance(s, dict):
            errs.append(f"{sid}: '{side}' must be an object")
            continue
        if s.get("kind") not in kinds:
            errs.append(f"{sid}: {side}.kind {s.get('kind')!r} not in {sorted(kinds)}")
        if not _is_strs(s.get("tech")):
            errs.append(f"{sid}: {side}.tech must be a list of non-empty strings")
        if not isinstance(s.get("notes"), str):
            errs.append(f"{sid}: {side}.notes must be a string")
        elif s.get("kind") == "unavailable" and not s["notes"].strip():
            errs.append(f"{sid}: {side}.kind 'unavailable' requires explanatory notes")
    return errs


def check_cloud(cloud: str):
    """(status, problems): status is 'skip' | 'ok' | 'fail'."""
    f = BACKENDS / f"{cloud}.json"
    if not f.is_file():
        return "skip", [f"{f} not present yet"]
    try:
        data = json.loads(f.read_text())
    except ValueError as exc:
        return "fail", [f"{f.name}: invalid JSON ({exc})"]
    if not isinstance(data, dict):
        return "fail", [f"{f.name}: top level must be an object"]
    errs = [f"service '{s}': no entry in {f.name}" for s in service_ids(cloud) if s not in data]
    for sid, e in data.items():
        if sid.startswith("$"):
            continue
        errs += validate_entry(sid, e)
    return "fail" if errs else "ok", errs


def _pytest_case(cloud: str) -> None:
    status, errs = check_cloud(cloud)
    if status == "skip":
        import pytest
        pytest.skip(f"[{cloud}] backends data file not present yet: {errs[0]}")
    assert not errs, "\n".join(errs)


def test_backends_aws(): _pytest_case("aws")
def test_backends_gcp(): _pytest_case("gcp")
def test_backends_azure(): _pytest_case("azure")


def main() -> int:
    bad = 0
    for cloud in CLOUDS:
        status, errs = check_cloud(cloud)
        if status == "skip":
            print(f"SKIP {cloud}: backends data file not present yet ({errs[0]})")
        elif status == "ok":
            print(f"ok   {cloud}: {len(service_ids(cloud))} registry files documented")
        else:
            bad += 1
            print(f"FAIL {cloud}: {len(errs)} problem(s)")
            for e in errs:
                print("     -", e)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

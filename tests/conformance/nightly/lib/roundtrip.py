"""Check 5: UI <-> SDK/CLI/API both ways, comparing DATA (names, ids, links, status), not presence.

A cloud script supplies a `RoundtripAdapter`. `run_roundtrip` then proves, for one resource:
  1. made in the UI  -> the client reads the same data
  2. made by client  -> the UI shows the same data after a reload
  3. deleted in the UI -> the client no longer finds it; deleted by client -> the UI no longer lists it
It prints PASS/FAIL lines (what run_suites.py scores) and returns the list of failures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


class RoundtripAdapter(Protocol):
    fields: tuple[str, ...]                       # data fields that must match, e.g. ("name", "location", "status")
    def ui_create(self, name: str) -> None: ...
    def client_create(self, name: str) -> None: ...
    def ui_read(self, name: str) -> dict | None: ...      # None = not shown (after a UI reload)
    def client_read(self, name: str) -> dict | None: ...  # None = not found
    def ui_delete(self, name: str) -> None: ...
    def client_delete(self, name: str) -> None: ...


@dataclass
class Failure:
    step: str
    detail: str


def diff(expected: dict | None, actual: dict | None, fields: tuple[str, ...]) -> str:
    """'' when equal on `fields`, else a human-readable difference."""
    if expected is None or actual is None:
        return "missing on one side"
    bad = [f"{f}: {expected.get(f)!r} != {actual.get(f)!r}" for f in fields if expected.get(f) != actual.get(f)]
    return "; ".join(bad)


def run_roundtrip(a: RoundtripAdapter, base: str, emit: Callable[[str], None] = print) -> list[Failure]:
    fails: list[Failure] = []

    def check(step: str, ok: bool, detail: str = "") -> None:
        emit(f"{'PASS' if ok else 'FAIL'}: {step}" + (f" ({detail})" if detail and not ok else ""))
        if not ok:
            fails.append(Failure(step, detail))

    for origin, create, other_read, other_label in (
        ("ui", a.ui_create, a.client_read, "client"),
        ("client", a.client_create, a.ui_read, "ui"),
    ):
        name = f"{base}-{origin}"
        try:
            create(name)
            own = a.ui_read(name) if origin == "ui" else a.client_read(name)
            theirs = other_read(name)
            d = "not created" if own is None else ("not visible to " + other_label if theirs is None else diff(own, theirs, a.fields))
            check(f"{origin}-created resource read identically by {other_label}", d == "", d)
        except Exception as e:  # a crash is a finding, never a skip
            check(f"{origin}-created resource read identically by {other_label}", False, f"{type(e).__name__}: {e}")
            continue
        try:
            (a.ui_delete if origin == "ui" else a.client_delete)(name)
            gone_other = other_read(name) is None
            check(f"{origin}-deleted resource gone for {other_label}", gone_other, "still visible")
        except Exception as e:
            check(f"{origin}-deleted resource gone for {other_label}", False, f"{type(e).__name__}: {e}")
    return fails

"""Check 6: the tunnel link comes back by itself, with no user action and no state loss.

A cloud/Mesh script provides callables; this module owns the sequence and the verdicts.
  link_ok()       -> True when the client reaches the simulator through the tunnel (e.g. GET /health via 127.0.0.1:9000)
  write_marker()  -> creates a resource through the link, returns its name
  marker_ok(name) -> True when that resource is still there through the link
  faults          -> {label: callable} each breaks the link (kill relay, drop ssh session, restart appliance)
Each fault: break it, then poll `link_ok` for up to `deadline` seconds; the marker must survive.
"""
from __future__ import annotations

import time
from typing import Callable


def run_recovery(link_ok: Callable[[], bool], write_marker: Callable[[], str], marker_ok: Callable[[str], bool],
                 faults: dict[str, Callable[[], None]], deadline: float = 120.0, poll: float = 2.0,
                 emit: Callable[[str], None] = print, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> list[str]:
    failures: list[str] = []

    def verdict(label: str, ok: bool, detail: str = "") -> None:
        emit(f"{'PASS' if ok else 'FAIL'}: {label}" + (f" ({detail})" if detail and not ok else ""))
        if not ok:
            failures.append(f"{label}: {detail}")

    if not link_ok():
        verdict("link is up before the faults", False, "cannot start")
        return failures
    verdict("link is up before the faults", True)
    marker = write_marker()
    for label, fault in faults.items():
        try:
            fault()
        except Exception as e:
            verdict(f"fault applied: {label}", False, f"{type(e).__name__}: {e}")
            continue
        start = clock()
        back = False
        while clock() - start < deadline:
            if link_ok():
                back = True
                break
            sleep(poll)
        verdict(f"link recovers by itself after: {label}", back, f"no link after {deadline:.0f}s")
        if back:
            verdict(f"state survives: {label}", marker_ok(marker), "marker resource lost")
    return failures

"""Lambda core: every invocation bumps a running total (the console shows it; only the last 20 rows are kept)."""
import json
import types

try:
    from core import lambda_core as lc
except ImportError:  # pragma: no cover
    import lambda_core as lc  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def run():
    fn = {"invocations": [], "memory_size": 128}
    for i in range(25):
        lc._record_invocation(fn, f"req-{i}", 1.5, False)
    _check("only the last %d rows are kept" % lc.RECENT_INVOCATIONS_KEPT, len(fn["invocations"]) == lc.RECENT_INVOCATIONS_KEPT)
    _check("running total counts all 25 invocations", fn["invocation_count"] == 25)
    lc._record_invocation(fn, "req-err", 1.5, True)
    _check("failed invocations count too", fn["invocation_count"] == 26)
    print("LAMBDA INVOCATION COUNT OK")


if __name__ == "__main__":
    run()

#!/usr/bin/env python3
"""run_checks.py <sdk|cli> <endpoint> <tfstate> <out.json>  -> {check_name: {ok, detail}}  (shared by sdk/run_sdk.py and cli/run_cli.py)"""
import json, sys, time, traceback
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import checks


def run(kind, ep, state, out):
    c = (checks.Sdk if kind == "sdk" else checks.Cli)(ep)
    S = checks.State(state)
    res = {}
    for name, fn in checks.CHECKS.items():
        t = time.time()
        try:
            d = fn(c, S); res[name] = {"ok": True, "detail": d or "", "s": round(time.time() - t, 1)}
        except Exception as e:  # noqa
            res[name] = {"ok": False, "detail": f"{type(e).__name__}: {e}"[:600], "s": round(time.time() - t, 1)}
        print(("PASS " if res[name]["ok"] else "FAIL ") + f"{kind} {name} {res[name]['detail'][:160]}", flush=True)
    json.dump(res, open(out, "w"), indent=1)
    return res


if __name__ == "__main__":
    run(*sys.argv[1:5])

"""Vendor the Pyodide runtime Nano needs into wasm/vendor/pyodide/ so Nano loads it from its
own origin instead of cdn.jsdelivr.net (a CDN stall leaves Nano stuck at "booting Pyodide").

The loaders (nano-boot.js, relay/relay-shared-worker.js, relay/nano-endpoint.html) use this
folder when it exists and fall back to the CDN otherwise. ~13 MB; git-ignored (the repo is
public and must not carry the binaries) — run it in the build/deploy step that publishes the
Nano bundle, or locally once.

    python3 wasm/fetch_pyodide.py            (idempotent; re-downloads only missing files)
"""
import json
import os
import sys
import urllib.request

VERSION = "0.26.2"
CDN = f"https://cdn.jsdelivr.net/pyodide/v{VERSION}/full/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "pyodide")
CORE = ["pyodide.mjs", "pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
PACKAGES = ["sqlite3"]          # loadPackage() calls in the relay


def fetch(name: str) -> None:
    dst = os.path.join(OUT, name)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return
    for attempt in range(4):
        try:
            with urllib.request.urlopen(CDN + name, timeout=60) as r, open(dst + ".part", "wb") as f:
                f.write(r.read())
            os.replace(dst + ".part", dst)
            print(f"  {name}  {os.path.getsize(dst) // 1024} KB")
            return
        except Exception as e:  # the CDN stalls intermittently — retry
            print(f"  {name}: retry {attempt + 1} ({e})", file=sys.stderr)
    raise SystemExit(f"could not fetch {name}")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for f in CORE:
        fetch(f)
    lock = json.load(open(os.path.join(OUT, "pyodide-lock.json")))["packages"]
    todo, seen = list(PACKAGES), set()
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        fetch(lock[n]["file_name"])
        todo += [d.lower() for d in lock[n].get("depends", [])]
    print(f"Pyodide {VERSION} vendored → {OUT}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Regenerate the route-pattern table inside wasm/nano-usage.js from the v4 console sources.

The view-dwell emitter keys every view by the console's own ROUTE PATTERN (e.g. `s3/buckets/:name`), never
by the real URL, so resource names can never leave the browser. The patterns are the `pattern: "/svc/..."`
entries under consoles/src/<cloud>/. Run after adding/renaming a console route:

    python3 scripts/gen_nano_usage_routes.py            # rewrite the block
    python3 scripts/gen_nano_usage_routes.py --check    # exit 1 if wasm/nano-usage.js is stale (CI/test)
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "wasm" / "nano-usage.js"
PAT = re.compile(r"""pattern:\s*["'`]([^"'`]+)["'`]""")
OK = re.compile(r"^/[a-z0-9_:./-]*$")
BEGIN, END = "/*ROUTES:BEGIN*/", "/*ROUTES:END*/"


def collect() -> dict:
    out = {}
    for cloud in ("aws", "gcp", "azure"):
        pats = set()
        for f in (ROOT / "consoles" / "src" / cloud).rglob("*"):
            if f.suffix not in (".jsx", ".js", ".tsx", ".ts") or not f.is_file():
                continue
            for m in PAT.finditer(f.read_text(encoding="utf-8", errors="ignore")):
                p = m.group(1).strip()
                if OK.match(p) and p != "/":
                    pats.add(p.lstrip("/"))
        out[cloud] = sorted(pats)
    return out


def block(data: dict) -> str:
    return f"{BEGIN}var ROUTES={json.dumps(data, separators=(',', ':'))};{END}"


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    a, b = src.index(BEGIN), src.index(END) + len(END)
    new = src[:a] + block(collect()) + src[b:]
    if "--check" in sys.argv:
        if new != src:
            print("wasm/nano-usage.js route table is stale: run scripts/gen_nano_usage_routes.py"); return 1
        print("nano-usage route table is current"); return 0
    TARGET.write_text(new, encoding="utf-8")
    print("wrote", sum(len(v) for v in collect().values()), "patterns")
    return 0


if __name__ == "__main__":
    sys.exit(main())

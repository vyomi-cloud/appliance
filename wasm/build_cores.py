"""Vendor the canonical conformance cores into the Nano bundle.

Nano serves the `wasm/` folder as its web root (the repo source is never
exposed), but the page-side backend (nano-boot.js) must fetch the SAME proven
core modules the conformance suite runs against. So we COPY — never fork — the
canonical files from `core/` into `wasm/core/`, where they're reachable from the
web root. The copies are generated artifacts (like `wasm/fixtures/`): re-run this
after changing any core to keep the bundle in lock-step with the proven source.

Cores vendored (each green on host CPython AND Pyodide via tests/conformance/):
  core/object_store.py     -> the S3 data-plane seam
  core/s3_object_core.py   -> the S3 handler logic (native wire)
  core/nosql_store.py      -> the DynamoDB data-plane seam
  core/dynamodb_core.py    -> the DynamoDB handler logic (native wire)

Run:  python3 wasm/build_cores.py   (part of the bundle build, with build_fixtures.py)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "core")
OUT = os.path.join(HERE, "core")

CORES = ["object_store.py", "s3_object_core.py", "nosql_store.py", "dynamodb_core.py"]

HEADER = ("# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.\n"
          "# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py\n")


def main():
    os.makedirs(OUT, exist_ok=True)
    # Make wasm/core an importable package mirror of the repo `core` package, so
    # the vendored modules' `from core.object_store import ...` resolve in Pyodide.
    with open(os.path.join(OUT, "__init__.py"), "w") as f:
        f.write(HEADER)
    for name in CORES:
        with open(os.path.join(SRC, name)) as f:
            src = f.read()
        with open(os.path.join(OUT, name), "w") as f:
            f.write(HEADER + src)
        print(f"core/{name:22} -> wasm/core/{name} ({len(src)} bytes)")


if __name__ == "__main__":
    main()

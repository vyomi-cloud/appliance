#!/usr/bin/env python3
"""Generate docs/architecture/v4.0/BACKENDS-<CLOUD>.md from core/capabilities/backends/<cloud>.json.

Usage: python3 scripts/gen_backends_doc.py aws|gcp|azure [--check]
Cloud-agnostic: only reads the backends JSON schema.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cell(v):
    if isinstance(v, list):
        v = "; ".join(str(x) for x in v)
    return (str(v) if v else "-").replace("|", "\\|").replace("\n", " ")


def side(b):
    if not b:
        return "-"
    tech = ", ".join(b.get("tech") or []) or "-"
    return f"**{b.get('kind', '?')}**: {tech}. {b.get('notes', '')}".strip()


def render(cloud, data):
    out = [f"# How Vyomi runs each {cloud.upper()} service\n",
           f"Generated from `core/capabilities/backends/{cloud}.json` by `scripts/gen_backends_doc.py`. Do not edit by hand.\n",
           "kind: opensource = a third-party open-source engine does the real work; inhouse = Vyomi's own implementation; hybrid = both.\n",
           f"Services: {len(data)}\n",
           "| Service | Wire | Offline backend | Nano backend | Differs from real cloud | Not in scope |",
           "|---|---|---|---|---|---|"]
    for sid in sorted(data):
        e = data[sid]
        out.append("| " + " | ".join([
            f"**{cell(e.get('title', sid))}** (`{sid}`)<br>{cell(e.get('summary'))}",
            cell(e.get("wire")), cell(side(e.get("offline"))), cell(side(e.get("nano"))),
            cell(e.get("differs")), cell(e.get("notInScope"))]) + " |")
    out.append("\n## Sources\n")
    for sid in sorted(data):
        out.append(f"- `{sid}`: " + ", ".join(f"`{s}`" for s in data[sid].get("sources", [])))
    return "\n".join(out) + "\n"


def main():
    cloud = sys.argv[1].lower()
    data = json.loads((ROOT / f"core/capabilities/backends/{cloud}.json").read_text())
    target = ROOT / f"docs/architecture/v4.0/BACKENDS-{cloud.upper()}.md"
    text = render(cloud, data)
    if "--check" in sys.argv:
        sys.exit(0 if target.exists() and target.read_text() == text else 1)
    target.write_text(text)
    print(f"wrote {target} ({len(data)} services)")


if __name__ == "__main__":
    main()

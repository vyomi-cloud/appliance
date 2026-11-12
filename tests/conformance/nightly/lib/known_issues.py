"""Read and update docs/architecture/v4.0/V4.0.0-KNOWN-ISSUES.md from the pipeline (stdlib only).

The file is the single issue register for the v4.0.x beta. Humans own the per-cloud sections (rows `AWS-n`, `AZ-n`, `GCP-n`, `GW-n`,
`CI-n`, `NANO-n`, `MESH-n`). The pipeline owns ONE section, `## Auto-detected (daily bi-directional)`, whose rows are
`AUTO-<cloud>-<key>` with an HTML marker so a re-run updates a row instead of duplicating it.

    python3 tests/conformance/nightly/lib/known_issues.py list   --cloud azure          # open rows for a cloud (JSON)
    python3 tests/conformance/nightly/lib/known_issues.py add    --cloud azure --key vm-power --impact S2 --what "..." --where "..."
    python3 tests/conformance/nightly/lib/known_issues.py resolve --id AZ-4 --by <commit> # move a row to "Resolved after the cut"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[4] / "docs/architecture/v4.0/V4.0.0-KNOWN-ISSUES.md"
AUTO_H = "## Auto-detected (daily bi-directional)"
RESOLVED_H = "## Resolved after the cut"
# which row-id prefixes belong to which cloud's fixer
PREFIX = {"azure": ("AZ-", "AUTO-azure-"), "aws": ("AWS-", "AUTO-aws-"),
          "gcp": ("GCP-", "GW-", "AUTO-gcp-")}
ROW = re.compile(r"^\|\s*([A-Z][A-Z0-9]*-[A-Za-z0-9_.-]+)\s*\|")


def _rows(text: str):
    """Yield (line_index, id, cells) for table rows whose first cell looks like an issue id."""
    for i, line in enumerate(text.splitlines()):
        m = ROW.match(line)
        if m and not set(m.group(1)) <= set("-"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            yield i, m.group(1), cells


def list_open(cloud: str | None = None, path: Path = DEFAULT):
    text = Path(path).read_text()
    out = []
    in_resolved = False
    for i, line in enumerate(text.splitlines()):
        if line.startswith("## "):
            in_resolved = line.strip() == RESOLVED_H
    for i, rid, cells in _rows(text):
        # rows after the Resolved heading are closed
        head = max((j for j, l in enumerate(text.splitlines()[: i + 1]) if l.startswith("## ")), default=-1)
        if text.splitlines()[head].strip() == RESOLVED_H:
            continue
        if cloud and not rid.startswith(PREFIX[cloud]):
            continue
        impact = cells[1] if len(cells) > 1 else ""
        out.append({"id": rid, "impact": impact, "what": cells[2] if len(cells) > 2 else "",
                    "workaround": cells[3] if len(cells) > 3 else "", "where": cells[4] if len(cells) > 4 else ""})
    return out


def _ensure_section(text: str, heading: str, header_row: str) -> str:
    if heading in text:
        return text
    return text.rstrip("\n") + f"\n\n{heading}\n\n{header_row}\n|---|---|---|---|---|\n"


def add_issue(cloud: str, key: str, impact: str, what: str, where: str, workaround: str = "None.", path: Path = DEFAULT) -> str:
    """Add (or refresh) an auto-detected row. Returns 'added' | 'updated'."""
    p = Path(path)
    text = _ensure_section(p.read_text(), AUTO_H, "| ID | Impact | What | Workaround | Where to start |")
    rid = f"AUTO-{cloud}-{key}"
    new = f"| {rid} | {impact} | {what.replace('|', '/')} | {workaround.replace('|', '/')} | {where.replace('|', '/')} |"
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"| {rid} |"):
            lines[i] = new
            p.write_text("\n".join(lines) + "\n")
            return "updated"
    # append at the end of the auto section's table (right after the last row/separator of that section)
    start = next(i for i, l in enumerate(lines) if l.strip() == AUTO_H)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    ins = end
    while ins > start and not lines[ins - 1].startswith("|"):
        ins -= 1
    lines.insert(ins, new)
    p.write_text("\n".join(lines) + "\n")
    return "added"


def resolve(rid: str, by: str, path: Path = DEFAULT) -> bool:
    """Remove the row and log it under 'Resolved after the cut'."""
    p = Path(path)
    lines = p.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"| {rid} |"):
            row = lines.pop(i)
            text = _ensure_section("\n".join(lines) + "\n", RESOLVED_H, "| ID | Impact | What | Workaround | Where to start |")
            text = text.rstrip("\n") + f"\n| {rid} | resolved by {by} | " + " ".join(row.split("|")[3:4]).strip()[:160] + " | | |\n"
            p.write_text(text)
            return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "add", "resolve"])
    ap.add_argument("--file", default=str(DEFAULT))
    ap.add_argument("--cloud", choices=list(PREFIX))
    ap.add_argument("--key"); ap.add_argument("--impact", default="S2"); ap.add_argument("--what"); ap.add_argument("--where", default="")
    ap.add_argument("--workaround", default="None."); ap.add_argument("--id"); ap.add_argument("--by", default="")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        print(json.dumps(list_open(a.cloud, a.file), indent=1)); return 0
    if a.cmd == "add":
        if not (a.cloud and a.key and a.what):
            ap.error("add needs --cloud --key --what")
        print(add_issue(a.cloud, a.key, a.impact, a.what, a.where, a.workaround, a.file)); return 0
    ok = resolve(a.id, a.by, a.file)
    print("resolved" if ok else "not found"); return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

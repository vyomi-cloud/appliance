#!/usr/bin/env python3
"""Draft UI-spec extractor for native cloud console captures.

Turns a console crawl (manifest.jsonl + per-page innerText .txt files) into one
draft spec per service, shaped by ui-spec/schema.json.  Stdlib only, Python 3.11+,
deterministic (same captures -> byte-identical output).

    python3 tools/ui_spec/extract.py --captures <crawl-dir> --out ui-spec/aws
    python3 tools/ui_spec/extract.py --captures <crawl-dir> --out /tmp/x --service s3

The output is a DRAFT. Heuristics read text layout only (no DOM), so field types,
section boundaries and option lists are guesses; anything uncertain carries
"confidence": "low".  Pilot services are hand-reviewed against screenshots.

Text facts only: labels, column names, option values and short helper strings.
Row data, long paragraphs and anything that looks like account data are dropped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

CLOUD = "aws"
MAX_HELP = 120

# ---------------------------------------------------------------- sanitising

MASKED_ACCOUNT = {"1234-5678-9012", "123456789012"}
RE_ACCOUNT_DASH = re.compile(r"\b\d{4}-\d{4}-\d{4}\b")
RE_ACCOUNT = re.compile(r"(?<![\d.])\d{12}(?![\d.])")
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RE_GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
RE_ARN = re.compile(r"\barn:aws[\w-]*:[^\s]*")
RE_RES_ID = re.compile(r"\b(?:vpc|subnet|sg|i|ami|vol|snap|eni|igw|nat|rtb|acl|eipalloc|lt|key|fs|fsap|ap)-[0-9a-f]{8,17}\b")
RE_KEY_ID = re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|ANPA|AGPA|AIPA|ANVA)[A-Z0-9]{12,}\b")
RE_LONG_TOKEN = re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Z])[A-Za-z0-9]{16,}\b")
ZERO_GUID = "00000000-0000-0000-0000-000000000000"


def unsafe(s: str) -> bool:
    """True if the string may carry account data (unmasked)."""
    for m in RE_ACCOUNT_DASH.findall(s):
        if m not in MASKED_ACCOUNT:
            return True
    for m in RE_ACCOUNT.findall(s):
        if m not in MASKED_ACCOUNT:
            return True
    for m in RE_EMAIL.findall(s):
        if m.lower() != "user@example.com":
            return True
    for m in RE_GUID.findall(s):
        if m != ZERO_GUID:
            return True
    if RE_KEY_ID.search(s) or RE_LONG_TOKEN.search(s):  # access-key / opaque IDs
        return True
    if RE_RES_ID.search(s):  # resource IDs from the real account
        return True
    if RE_ARN.search(s):  # ARNs are instance data, never UI labels
        return True
    return False


def clean(s: str | None, limit: int = MAX_HELP) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    if not s or unsafe(s) or len(s) > limit:
        return None
    return s


# ---------------------------------------------------------------- text model

FOOTER = {"CloudShell", "Agent Toolkit for AWS"}
CHROME_HEAD = {"Skip to Main Content", "[Option+S]"}
RE_DATE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}"
)
RE_DATA_CELL = re.compile(r"^(?:[-\d.,/: ]+|.*\b\d+ (?:seconds?|minutes?|hours?|days?|months?|years?)\b.*|.* ago|Active - .*|Inactive - .*)$")
RE_SELECT_COL = re.compile(r"(?i)\bselect(ion|or)\b")
RE_COUNT_HDR = re.compile(r"^(?P<label>.{2,80}?) \((?P<n>\d+|\d+\+)\)$")
BANNER_PREFIXES = ("Share your feedback", "Take this short survey", "Introducing ")
NOISE = {"", " ", "Info", "Learn more", "Loading", "...", "All", "Last updated", "Refresh",
         "Share feedback", "Previous page", "Next page"}


def read_lines(path: Path) -> list[str]:
    """innerText -> lines, with the console chrome and inlined iframe JS cut off."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[str] = []
    for ln in raw.split("\n"):
        if '"use strict"' in ln or ln.strip() in FOOTER:
            break
        out.append(ln.rstrip("\r").replace("\xa0", " "))
    while out and (out[0].strip() in CHROME_HEAD):
        out.pop(0)
    return out


def strip_account_header(lines: list[str]) -> list[str]:
    """Drop region / account / user lines that precede the breadcrumbs."""
    for i, ln in enumerate(lines[:8]):
        if "(1234-5678-9012)" in ln or RE_ACCOUNT_DASH.search(ln):
            # next line is the IAM user / role name
            return lines[i + 2:]
    return lines


def split_breadcrumbs(lines: list[str]) -> tuple[list[str], int]:
    """Breadcrumbs are rendered twice in a row (mobile + desktop)."""
    for k in range(1, 8):
        if len(lines) >= 2 * k and lines[:k] == lines[k:2 * k] and all(x.strip() for x in lines[:k]):
            return lines[:k], 2 * k
    return [], 0


def is_sentence(s: str) -> bool:
    s = s.strip()
    return len(s) > 60 or s.endswith(".") or s.endswith(". ") or s.endswith(":")


def short_label(s: str) -> bool:
    s = s.strip()
    if s.startswith(BANNER_PREFIXES):
        return False
    return 0 < len(s) <= 70 and not s.endswith(".") and not RE_DATE.match(s) and s not in NOISE


# ---------------------------------------------------------------- nav

def extract_nav(lines: list[str], start: int, nav_links: set[str]) -> tuple[list[dict], int]:
    """Consume the side-nav block that follows the breadcrumbs.

    Lines that are crawled L2 labels are links; short non-link lines directly
    followed by links are group headers.  Returns (tree, index after nav)."""
    i = start
    tree: list[dict] = []
    group: dict | None = None
    seen_any = False
    misses = 0
    end = start
    seen_labels: set[str] = set()
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            if seen_any:
                break
            i += 1
            continue
        if s in nav_links:
            if s in seen_labels:
                break  # main content starts repeating nav labels
            seen_labels.add(s)
            node = {"label": s}
            (group["children"] if group else tree).append(node)
            seen_any = True
            misses = 0
            end = i + 1
        else:
            lookahead = [x.strip() for x in lines[i + 1:i + 3]]
            if short_label(s) and any(x in nav_links for x in lookahead):
                group = {"label": s, "children": []}
                tree.append(group)
                misses = 0
            else:
                misses += 1
                if misses > 1 or seen_any:
                    break
        i += 1
    # drop empty groups (usually the service title line)
    tree = [n for n in tree if "children" not in n or n["children"]]
    return tree, end


# ---------------------------------------------------------------- tables

def parse_columns(lines: list[str], i: int) -> tuple[list[str], int]:
    """Column header row: optional "<x> selection" line, then (\t, label) pairs
    (first label sometimes without a leading tab). Header rows repeat (sticky)."""
    cols: list[str] = []
    j = i
    while j < len(lines):
        s = lines[j]
        if RE_SELECT_COL.search(s.strip()) and not s.startswith("\t"):
            if cols:
                break
            j += 1
            continue
        if s.strip() == "" and s.startswith("\t"):
            if j + 1 < len(lines) and lines[j + 1].strip():
                lab = lines[j + 1].strip()
                if cols and lab == cols[0]:
                    break  # duplicate sticky header row
                if not RE_SELECT_COL.search(lab):
                    cols.append(lab)
                j += 2
                continue
            break
        if not cols and short_label(s) and j + 1 < len(lines) and lines[j + 1].startswith("\t"):
            cols.append(s.strip())
            j += 1
            continue
        break
    return cols, j


def find_column_row(lines: list[str], i: int, limit: int = 40) -> int | None:
    for j in range(i, min(len(lines), i + limit)):
        if lines[j].startswith("\t") and lines[j].strip() == "" and j + 1 < len(lines) and lines[j + 1].strip():
            # back up over a "<x> selection" / first-untabbed-label
            k = j
            if k - 1 >= i and RE_SELECT_COL.search(lines[k - 1].strip()):
                return k - 1
            if k - 1 >= i and short_label(lines[k - 1]) and lines[k - 1].strip() not in {"1"}:
                return k - 1
            return k
    return None


def extract_tables(lines: list[str], start: int) -> list[dict]:
    tables = []
    i = start
    while i < len(lines):
        s = lines[i].strip()
        m = RE_COUNT_HDR.match(s)
        if m:
            row = find_column_row(lines, i + 1)
            if row is not None:
                cols, after = parse_columns(lines, row)
                if cols:
                    # header actions between header and column row
                    actions: list[str] = []
                    filt = None
                    for x in lines[i + 1:row]:
                        if x.endswith(" ") and x.strip():
                            continue  # inline link fragment
                        x = x.strip()
                        if x[:1].islower():
                            continue
                        if not short_label(x) or x.isdigit() or x.endswith(")"):
                            continue
                        if x.startswith("Filter") or x.startswith("Find") or x.startswith("Search") or x.startswith("Any "):
                            filt = filt or x
                            continue
                        if len(x.split()) > 5:
                            continue
                        if x not in actions:
                            actions.append(x)
                    # empty state: a short line + sentence after the header rows
                    empty = None
                    for x in lines[after:after + 8]:
                        x = x.strip()
                        if x.startswith("No ") or x.startswith("You have no") or x.startswith("There are no"):
                            empty = clean(x)
                            break
                    t: dict = OrderedDict()
                    t["resource_label"] = clean(m.group("label"), 80)
                    t["columns"] = [c for c in (clean(c, 80) for c in cols) if c]
                    t["header_actions"] = [a for a in (clean(a, 60) for a in actions) if a]
                    if filt:
                        t["filter_placeholder"] = clean(filt, 80)
                    if empty:
                        t["empty_state"] = empty
                    t["confidence"] = "medium"
                    tables.append(t)
                    i = after
                    continue
        i += 1
    # fallback: column rows with no "Resource (N)" header above them
    consumed = set()
    for t in tables:
        consumed.update(t["columns"])
    i = start
    while i < len(lines):
        if lines[i].startswith("\t") and lines[i].strip() == "":
            row = find_column_row(lines, max(start, i - 1), 3)
            r0 = row if row is not None else i
            # data rows follow two blank lines; header rows follow "1"/"..."/selection/one blank
            is_data = r0 >= 2 and lines[r0 - 1].strip() == "" and lines[r0 - 2].strip() == ""
            cols, after = parse_columns(lines, r0)
            cols = [c for c in (clean(c, 80) for c in cols) if c]
            if any(RE_DATA_CELL.search(c) for c in cols):
                is_data = True
            if is_data:
                i = max(after, i + 1)
                continue
            if len(cols) >= 2 and not set(cols) <= consumed:
                label = None
                for x in reversed(lines[max(start, i - 25):i]):
                    x2 = x.strip()
                    if short_label(x2) and not x2.isdigit() and not RE_SELECT_COL.search(x2) and x2 not in cols:
                        label = x2
                        break
                t = OrderedDict()
                t["resource_label"] = clean(label, 80)
                t["columns"] = cols
                t["header_actions"] = []
                t["confidence"] = "low"
                tables.append({k: v for k, v in t.items() if v is not None})
                consumed.update(cols)
                i = max(after, i + 1)
                continue
        i += 1
    return tables


# ---------------------------------------------------------------- forms

OPTION_PAIRS = [("Disable", "Enable"), ("Enable", "Disable"), ("On", "Off"), ("Off", "On"),
                ("Yes", "No"), ("Turn on", "Turn off")]
HELP_STARTS = ("Choose", "Select", "Enter", "Specify", "Only", "This ", "The ", "You can", "Use ", "Using ")
BUTTONS = {"Cancel", "Next", "Previous", "Create", "Add new tag", "Remove", "Edit", "Save changes",
           "Choose bucket", "Browse S3", "Skip to review", "Submit"}


def extract_form(lines: list[str], start: int) -> list[dict]:
    """Sections = a short line followed by (" ", "Info") or a blank line.
    Fields = a short line followed by "Info" or by a helper sentence, or with an
    "- optional" suffix.  Everything is low confidence."""
    sections: list[dict] = []
    cur: dict | None = None
    i = start
    n = len(lines)

    def new_section(title: str):
        nonlocal cur
        cur = OrderedDict(title=clean(title, 100) or "(untitled)", fields=[])
        sections.append(cur)

    while i < n:
        s = lines[i].strip()
        nxt = lines[i + 1] if i + 1 < n else ""
        nxt2 = lines[i + 2].strip() if i + 2 < n else ""
        if not short_label(s) or s in BUTTONS or s.isdigit():
            i += 1
            continue
        # section heading
        if (nxt == " " and nxt2 == "Info") or (nxt.strip() == "" and i + 2 < n and is_sentence(lines[i + 2])):
            new_section(s)
            i += 1
            continue
        is_field = (nxt.strip() == "Info" or s.endswith("- optional")
                    or (is_sentence(nxt) and len(nxt.strip()) > len(s)))
        if not is_field:
            i += 1
            continue
        if cur is None:
            new_section("(form)")
        label = s
        optional = label.endswith("- optional")
        if optional:
            label = label[: -len("- optional")].strip()
        j = i + 1
        if j < n and lines[j].strip() == "Info":
            j += 1
        help_ = None
        if j < n and is_sentence(lines[j]):
            help_ = clean(lines[j].strip())
            j += 1
        # options: short lines, each optionally followed by a description sentence
        opts: list[str] = []
        ends: list[int] = []  # line index after each option (for re-scanning)
        k = j
        while k < n:
            o = lines[k].strip()
            if not short_label(o) or o in BUTTONS:
                break
            following = lines[k + 1] if k + 1 < n else ""
            if following.strip() == "Info" or following == " " or o.endswith("- optional"):
                break  # next field / section
            if len(opts) >= 2 and is_sentence(following) and following.strip().startswith(HELP_STARTS):
                break  # a new field label with its own helper text
            opts.append(o)
            k += 1
            if k < n and is_sentence(lines[k]):
                k += 1
            ends.append(k)
            if len(opts) >= 12:
                break
        field: dict = OrderedDict(label=clean(label, 100))
        if not field["label"]:
            i += 1
            continue
        low = label.lower()
        if label == "Tags" or "tag" in low and any(lines[x].strip() == "Add new tag" for x in range(j, min(n, j + 6))):
            field["type"] = "tags"
            opts = []
        elif tuple(opts[:2]) in OPTION_PAIRS:
            field["type"] = "radio"
            k = ends[1]  # re-scan whatever follows the pair
            opts = opts[:2]
        elif len(opts) >= 2:
            field["type"] = "radio"
        elif len(opts) == 1:
            field["type"] = "select"
            field["default"] = clean(opts[0], 80)
            opts = []
        else:
            field["type"] = "text"
        if opts:
            field["options"] = [o for o in (clean(o, 100) for o in opts) if o]
            if field["type"] == "radio":
                field["default"] = field["options"][0] if field["options"] else None
        field["required"] = not optional
        if help_:
            field["help"] = help_
        field["confidence"] = "low"
        cur["fields"].append({k2: v for k2, v in field.items() if v is not None})
        i = max(k, i + 1)
    return [s for s in sections if s["fields"]]


def extract_steps(lines: list[str], start: int) -> list[dict]:
    steps = []
    for i in range(start, len(lines) - 1):
        m = re.match(r"^Step (\d+)(?: - optional)?$", lines[i].strip())
        if m:
            title = clean(lines[i + 1].strip(), 100)
            if title and all(s["title"] != title for s in steps):
                steps.append(OrderedDict(title=title, optional=lines[i].strip().endswith("optional")))
    return steps


# ---------------------------------------------------------------- pages

def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "page"


def classify(entry: dict, has_table: bool, has_tabs: bool, steps: list) -> str:
    label = (entry.get("label") or "").lower()
    url = entry.get("url") or ""
    title = (entry.get("title") or "").lower()
    if re.search(r"(?i)/details?(/|$)|Details:|[?&]name=", url) and "create" not in url.lower():
        return "detail"
    if entry.get("depth") == "CREATE" or steps or "create" in url.lower() or title.startswith("create") \
            or (entry.get("depth") == "L3" and label.startswith(("create", "purchase", "import", "export"))):
        return "create"
    if "setting" in label or "preferences" in url or label == "edit":
        return "settings"
    if "dashboard" in label or "dashboard" in url:
        return "dashboard"
    if has_table:
        return "list"
    if entry.get("depth") == "L3" and has_tabs:
        return "detail"
    return "other"


def tab_order(lines: list[str], tab_labels: list[str]) -> list[str]:
    """Clicked tabs are numbered from 02; tab 01 is the default. Recover it as the
    line just before the first clicked tab inside a contiguous tab row."""
    if not tab_labels:
        return []
    def norm(x: str) -> str:
        return re.sub(r"\s*\(\d+\)$", "", x.strip())
    tab_labels = list(OrderedDict.fromkeys(norm(t) for t in tab_labels))
    stripped = [norm(l) for l in lines]
    for i, s in enumerate(stripped):
        if s == tab_labels[0]:
            run = [s]
            j = i + 1
            while j < len(stripped) and stripped[j] in tab_labels and stripped[j] not in run:
                run.append(stripped[j])
                j += 1
            if len(run) == len(tab_labels) or len(tab_labels) == 1:
                first = stripped[i - 1] if i > 0 else None
                out = list(tab_labels)
                if first and short_label(first) and first not in out:
                    out.insert(0, first)  # inferred default tab (low confidence)
                return out
    return list(tab_labels)


def instance_names(lines: list[str]) -> set[str]:
    """First cell of every table data row (rows follow two blank lines). These are
    resource names from the captured account and must never reach a spec."""
    names = set()
    for i in range(2, len(lines) - 1):
        if lines[i - 1].strip() == "" and lines[i - 2].strip() == "":
            if lines[i].startswith("\t") and lines[i].strip() == "":
                cell = lines[i + 1].strip()
            else:
                cell = lines[i].strip() if i + 1 < len(lines) and lines[i + 1].startswith("\t") else ""
            if len(cell) >= 4 and " " not in cell:
                names.add(cell)
    return names


def redact(obj, deny: set[str]):
    """Drop strings that are instance names; replace embedded ones."""
    if isinstance(obj, dict):
        out = OrderedDict()
        for k, v in obj.items():
            if k == "captures":
                out[k] = v
                continue
            v2 = redact(v, deny)
            if v2 is None and k in ("title", "label"):
                v2 = "{resource-name}"  # required keys keep a placeholder
            if v2 is not None:
                out[k] = v2
        return out
    if isinstance(obj, list):
        return [x for x in (redact(v, deny) for v in obj) if x is not None]
    if isinstance(obj, str):
        if obj in deny:
            return None
        for d in sorted(deny, key=lambda x: (-len(x), x)):
            if d in obj:
                obj = obj.replace(d, "{resource-name}")
        return obj
    return obj


def collect_denylist(entries: list[dict], cap: Path) -> set[str]:
    deny: set[str] = set()
    for e in entries:
        f = e.get("file", "")
        if f.endswith(".png"):
            deny |= instance_names(read_lines(cap / (f[:-4] + ".txt")))
        if e.get("label") and classify(e, False, False, []) == "detail":
            deny.add(e["label"].strip())
    return deny


def build_service(svc: str, entries: list[dict], cap: Path, global_deny: set[str] | None = None) -> dict:
    nav_links = {e["label"].strip() for e in entries if e.get("depth") == "L2" and e.get("label")}
    pages: "OrderedDict[str, dict]" = OrderedDict()
    nav_tree: list[dict] = []
    console_path = None
    used_ids: set[str] = set()
    page_by_url: dict[str, str] = {}
    parent_ids: dict[str, str] = {}
    tabbed = set()
    for e in entries:
        if e.get("tab"):
            tabbed.add(e.get("url", "") + "|" + (e.get("label") or "") + "|" + str(e.get("depth")))

    for e in entries:
        f = e.get("file")
        if not f:
            continue
        url = e.get("url", "")
        if console_path is None and url.startswith("http"):
            m = re.match(r"https://[^/]+(/[^/?#]+)", url)
            console_path = m.group(1) + "/" if m else None
        txt = cap / (f[: -len(".png")] + ".txt" if f.endswith(".png") else f)
        rel = f[: -len(".png")] if f.endswith(".png") else f
        key_base = e.get("url", "") + "|" + (e.get("label") or "") + "|" + str(e.get("depth"))
        if e.get("depth") == "CREATE":
            key_base = str(Path(f).parent)
        tab = e.get("tab")
        is_detail = classify(e, False, key_base in tabbed, []) == "detail"
        if is_detail and e.get("label"):
            # one spec page per resource type; capture names carry instance names -> glob them
            key_base = "detail|" + parent_ids.get(e.get("parent", ""), "resource")
            rel = re.sub(r"^(.*?/\d+-L\d)-[^/]*?(--tab-.*)?$", r"\1-*\2", rel)
        if key_base in page_by_url:
            pid = page_by_url[key_base]
            p = pages[pid]
            p["captures"].append(rel)
            if tab and tab not in p["_tabs"]:
                p["_tabs"].append(tab)
            lines = strip_account_header(read_lines(txt))
            if e.get("depth") == "CREATE" and "expanded" in f:
                # the expanded capture is the superset: re-parse the form from it
                crumbs, body = split_breadcrumbs(lines)
                p["_form_lines"] = (lines, body)
            continue

        lines = strip_account_header(read_lines(txt))
        crumbs, body = split_breadcrumbs(lines)
        tree, after_nav = extract_nav(lines, body, nav_links)
        if len(tree) > len(nav_tree):
            nav_tree = tree
        main_start = after_nav or body
        tables = extract_tables(lines, main_start)
        steps = extract_steps(lines, main_start)
        title = (e.get("title") or "").split(" | ")[0].strip()
        if e.get("depth") == "CREATE":
            label = Path(f).parent.name.split("-", 1)[-1].replace("-", " ")
        else:
            label = e.get("label") or ("landing" if e.get("depth") == "L1" else title)
        kind = classify(e, bool(tables), key_base in tabbed, steps)
        inst = None
        if kind == "detail" and e.get("label"):
            # the clicked label is an instance name (data): never let it into the spec
            inst = e["label"].strip()
            parent_id = parent_ids.get(e.get("parent", ""), "resource")
            label = f"{parent_id}-detail"
            crumbs = ["{resource-name}" if c.strip() == inst else c for c in crumbs]
            url = url.replace(inst, "{resource-name}")
        pid = slug(label)
        if pid in used_ids:
            n = 2
            while f"{pid}-{n}" in used_ids:
                n += 1
            pid = f"{pid}-{n}"
        used_ids.add(pid)
        page_by_url[key_base] = pid
        if url.startswith("http") and kind != "detail":
            parent_ids.setdefault(url, pid)
        if kind == "detail":
            title = "{resource-name}"  # instance names are data, not UI
        p = OrderedDict()
        p["id"] = pid
        p["kind"] = kind
        p["title"] = clean(title, 100) or clean(label, 100) or pid
        route = re.sub(r"[?&]region=[\w-]+", "", url.split(".amazon.com", 1)[-1]) if url.startswith("http") else None
        p["route"] = clean(route, 200) if route else None
        p["breadcrumbs"] = [c for c in (clean(c, 80) for c in crumbs) if c] or None
        p["captures"] = [rel]
        p["provenance"] = "capture"
        p["_tabs"] = [tab] if tab else []
        p["_inst"] = inst
        p["_lines"] = lines
        p["_main"] = main_start
        p["_form_lines"] = (lines, main_start) if kind in ("create", "settings") else None
        if tables:
            p["table"] = tables[0]
            if len(tables) > 1:
                p["extra_tables"] = tables[1:]
        if steps:
            p["steps"] = [dict(s) for s in steps]
        pages[pid] = p

    # finalise
    out_pages = []
    for p in pages.values():
        tabs = tab_order(p["_lines"], p["_tabs"])
        if tabs:
            tabs = [re.sub(r"\s*\(\d+\)$", "", t) for t in tabs]  # drop live counts
            p["tabs"] = list(OrderedDict.fromkeys(t for t in (clean(t, 80) for t in tabs) if t))
        if p["_form_lines"] is not None:
            lines, start = p["_form_lines"]
            secs = extract_form(lines, start)
            if secs:
                if p.get("steps"):
                    p["steps"][0]["sections"] = secs
                else:
                    p["sections"] = secs
        inst = p.get("_inst")
        for k in ("_tabs", "_lines", "_main", "_form_lines", "_inst"):
            p.pop(k, None)
        q = {k: v for k, v in p.items() if v not in (None, [], {})}
        if inst and len(inst) >= 3:
            caps = q.pop("captures")
            q = json.loads(json.dumps(q).replace(json.dumps(inst)[1:-1], "{resource-name}"))
            q["captures"] = caps
            q = OrderedDict((k, q[k]) for k in p if k in q)
        out_pages.append(q)

    # nav: attach page ids
    label_to_id = {}
    for e in entries:
        if e.get("depth") == "L2" and e.get("label"):
            key = e.get("url", "") + "|" + e["label"] + "|L2"
            if key in page_by_url:
                label_to_id.setdefault(e["label"].strip(), page_by_url[key])

    def attach(nodes):
        res = []
        for nd in nodes:
            o = OrderedDict(label=clean(nd["label"], 80) or nd["label"])
            if nd["label"] in label_to_id:
                o["page_id"] = label_to_id[nd["label"]]
            if nd.get("children"):
                o["children"] = attach(nd["children"])
            res.append(o)
        return res

    deny = set(global_deny) if global_deny is not None else collect_denylist(entries, cap)
    nav_labels = {n["label"] for n in nav_tree} | {c["label"] for n in nav_tree for c in n.get("children", [])}
    deny -= nav_labels
    out_pages = redact(out_pages, deny)

    spec = OrderedDict()
    spec["$schema"] = "../schema.json"
    spec["cloud"] = CLOUD
    spec["service"] = svc
    spec["console_path"] = console_path
    spec["status"] = "draft"
    spec["nav"] = attach(nav_tree)
    spec["pages"] = out_pages
    spec["gaps_note"] = ("Auto-extracted draft from text captures; field types, sections and option "
                         "lists are heuristic (confidence: low). Review against screenshots before use.")
    return spec


def load_manifest(cap: Path) -> dict[str, list[dict]]:
    by_svc: "OrderedDict[str, list[dict]]" = OrderedDict()
    mf = cap / "manifest.jsonl"
    for ln in mf.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            e = json.loads(ln)
        except json.JSONDecodeError:
            continue  # the crawl may still be writing the last line
        svc = e.get("svc")
        if not svc or not e.get("file"):
            continue
        by_svc.setdefault(svc, []).append(e)
    return by_svc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--captures", required=True, type=Path, help="crawl dir containing manifest.jsonl")
    ap.add_argument("--out", required=True, type=Path, help="output dir, e.g. ui-spec/aws")
    ap.add_argument("--service", action="append", help="limit to service(s) (console path name)")
    ap.add_argument("--suffix", default=".json", help="file suffix (use .draft.json to avoid overwriting reviewed specs)")
    ap.add_argument("--force", action="store_true", help="overwrite specs whose status is 'reviewed'")
    a = ap.parse_args(argv)
    by_svc = load_manifest(a.captures)
    a.out.mkdir(parents=True, exist_ok=True)
    n = 0
    # instance names are collected across ALL services (a bucket name shows up in RDS forms)
    global_deny = collect_denylist([e for es in by_svc.values() for e in es], a.captures)
    for svc, entries in by_svc.items():
        if a.service and svc not in a.service:
            continue
        spec = build_service(svc, entries, a.captures, global_deny)
        name = {"dynamodbv2": "dynamodb"}.get(svc, svc)
        dest = a.out / f"{name}{a.suffix}"
        if dest.exists() and not a.force:
            try:
                if json.loads(dest.read_text()).get("status") == "reviewed":
                    print(f"skip {dest} (reviewed; use --force or --suffix .draft.json)", file=sys.stderr)
                    continue
            except (OSError, json.JSONDecodeError):
                pass
        dest.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        np = len(spec["pages"])
        nf = sum(len(s["fields"]) for p in spec["pages"] for s in p.get("sections", []))
        nf += sum(len(s["fields"]) for p in spec["pages"] for st in p.get("steps", []) for s in st.get("sections", []))
        print(f"{dest}: {np} pages, {nf} fields")
        n += 1
    print(f"{n} service spec(s) written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

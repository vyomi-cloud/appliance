#!/usr/bin/env python3
"""Watch AWS, GCP and Azure for changes to the services Vyomi simulates.

Each run snapshots, for every service in tracked.json:
  - API surface   AWS botocore service models (operation → input/output members),
                  Google API Discovery documents (method → parameters/request/
                  response), Azure REST API spec commits (new API versions)
  - SDK releases  PyPI, Maven Central and Go module proxy latest versions
  - CLI releases  AWS CLI, Azure CLI, gcloud
  - Lifecycle     AWS What's New, GCP release notes and Azure Updates feeds,
                  filtered to tracked services
and diffs against the previous snapshot (STATE file). Output (OUT dir):
  changes.json   every change, each tagged actionable (→ a backlog issue) or not
  summary.md     a human summary
  state.json     the new snapshot (next run's baseline)
The first run (no STATE) records a baseline and reports nothing.

Actionable = API surface changes (new/removed/changed operations, new Azure API
versions) and lifecycle notices (deprecations, retirements, breaking changes).
SDK/CLI version bumps and feature announcements are recorded, not actioned.

    STATE=prev/state.json OUT=out GITHUB_TOKEN=... python3 watch_upstream.py
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TRACKED = json.load(open(os.path.join(HERE, "tracked.json")))
OUT = os.environ.get("OUT", os.path.join(HERE, "out"))
LIFECYCLE = re.compile(r"deprecat|retire|retirement|end of (life|support)|sunset|breaking|discontinu|no longer (be )?supported|will be removed|removal", re.I)
ERRORS: list[str] = []


def fetch(url: str, accept: str = "", timeout: int = 40) -> bytes:
    h = {"User-Agent": "vyomi-upstream-watch"}
    if accept:
        h["Accept"] = accept
    if "api.github.com" in url and os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def fetch_json(url: str):
    return json.loads(fetch(url, "application/json"))


def sig(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


def safe(label: str, fn, default):
    try:
        return fn()
    except Exception as e:  # one source failing must not stop the others
        ERRORS.append(f"{label}: {str(e)[:160]}")
        return default


# ── API surfaces ────────────────────────────────────────────────────────────
def aws_surface() -> dict:
    tag = fetch_json("https://pypi.org/pypi/botocore/json")["info"]["version"]
    out = {"_version": tag}
    for svc in TRACKED["aws"]["botocore"]:
        def one(svc=svc):
            vers = sorted(x["name"] for x in fetch_json(f"https://api.github.com/repos/boto/botocore/contents/botocore/data/{svc}?ref={tag}") if x["type"] == "dir")
            model = fetch_json(f"https://raw.githubusercontent.com/boto/botocore/{tag}/botocore/data/{svc}/{vers[-1]}/service-2.json")
            shapes = model.get("shapes", {})
            def members(ref):
                sh = shapes.get((ref or {}).get("shape", ""), {})
                return sorted(sh.get("members", {}).keys()), sorted(sh.get("required", []))
            ops = {}
            for name, op in model.get("operations", {}).items():
                im, ir = members(op.get("input"))
                om, _ = members(op.get("output"))
                ops[name] = {"in": im, "required": ir, "out": om, "http": op.get("http", {}).get("method", ""),
                             "deprecated": bool(op.get("deprecated"))}
            return {"api_version": vers[-1], "ops": ops}
        out[svc] = safe(f"aws/{svc}", one, None)
    return out


def gcp_surface() -> dict:
    out = {}
    for api in TRACKED["gcp"]["discovery"]:
        def one(api=api):
            name, ver = api.split("/")
            try:
                doc = fetch_json(f"https://www.googleapis.com/discovery/v1/apis/{name}/{ver}/rest")
            except Exception:
                # Newer APIs aren't in the central directory; they serve their
                # discovery document from their own endpoint.
                doc = fetch_json(f"https://{name}.googleapis.com/$discovery/rest?version={ver}")
            ops = {}
            def walk(res):
                for r in (res or {}).values():
                    for m in (r.get("methods") or {}).values():
                        ops[m["id"]] = {"params": sorted((m.get("parameters") or {}).keys()),
                                        "request": (m.get("request") or {}).get("$ref", ""),
                                        "response": (m.get("response") or {}).get("$ref", ""),
                                        "http": m.get("httpMethod", ""),
                                        "deprecated": "deprecated" in (m.get("description") or "").lower()[:200]}
                    walk(r.get("resources"))
            walk(doc.get("resources"))
            return {"revision": doc.get("revision", ""), "ops": ops}
        out[api] = safe(f"gcp/{api}", one, None)
    return out


def azure_spec_commits(since: str) -> dict:
    out = {}
    for spec in TRACKED["azure"]["specs"]:
        def one(spec=spec):
            q = f"path=specification/{spec}&per_page=30" + (f"&since={since}" if since else "&per_page=1")
            return [{"sha": c["sha"][:10], "date": c["commit"]["committer"]["date"],
                     "title": c["commit"]["message"].split("\n")[0][:200], "url": c["html_url"]}
                    for c in fetch_json(f"https://api.github.com/repos/Azure/azure-rest-api-specs/commits?{q}")]
        out[spec] = safe(f"azure/{spec}", one, [])
    return out


# ── SDK + CLI versions ──────────────────────────────────────────────────────
def versions() -> dict:
    v = {}
    for p in TRACKED["sdks"]["pypi"]:
        v[f"pypi:{p}"] = safe(f"pypi/{p}", lambda p=p: fetch_json(f"https://pypi.org/pypi/{p}/json")["info"]["version"], None)
    for coord in TRACKED["sdks"]["maven"]:
        g, a = coord.split(":")
        v[f"maven:{coord}"] = safe(f"maven/{coord}", lambda g=g, a=a: fetch_json(
            f"https://search.maven.org/solrsearch/select?q=g:{g}+AND+a:{a}&rows=1&wt=json")["response"]["docs"][0]["latestVersion"], None)
    for mod in TRACKED["sdks"]["go"]:
        v[f"go:{mod}"] = safe(f"go/{mod}", lambda mod=mod: fetch_json(
            f"https://proxy.golang.org/{urllib.parse.quote(mod.lower(), safe='/')}/@latest")["Version"], None)
    v["cli:aws"] = safe("cli/aws", lambda: fetch_json("https://api.github.com/repos/aws/aws-cli/tags?per_page=1")[0]["name"], None)
    v["cli:azure"] = safe("cli/azure", lambda: fetch_json("https://api.github.com/repos/Azure/azure-cli/releases/latest")["tag_name"], None)
    v["cli:gcloud"] = safe("cli/gcloud", lambda: fetch_json("https://dl.google.com/dl/cloudsdk/channels/rapid/components-2.json")["version"], None)
    return v


# ── Lifecycle / announcement feeds ──────────────────────────────────────────
def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def feeds() -> list[dict]:
    items = []
    def aws():
        root = ET.fromstring(fetch(TRACKED["feeds"]["aws"]))
        for it in root.iter("item"):
            title, desc = it.findtext("title", ""), _text(it.findtext("description", ""))
            hit = [k for k in TRACKED["aws"]["keywords"] if k.lower() in (title + " " + desc).lower()]
            if hit:
                items.append({"cloud": "aws", "id": it.findtext("guid", "") or it.findtext("link", ""), "title": title,
                              "link": it.findtext("link", ""), "services": hit, "text": desc[:600]})
    def gcp():
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(fetch(TRACKED["feeds"]["gcp"]))
        for e in root.findall("a:entry", ns)[:10]:
            content = e.findtext("a:content", "", ns)
            day = e.findtext("a:title", "", ns)
            link = (e.find("a:link", ns).get("href") if e.find("a:link", ns) is not None else "")
            # One entry per day; split it into per-product sections.
            for part in re.split(r"<h2[^>]*>", content)[1:]:
                product = _text(part.split("</h2>")[0])
                if not any(p.lower() == product.lower() for p in TRACKED["gcp"]["products"]):
                    continue
                for sec in re.split(r"<h3[^>]*>", part)[1:]:
                    kind = _text(sec.split("</h3>")[0])
                    body = _text(sec.split("</h3>", 1)[-1])
                    items.append({"cloud": "gcp", "id": f"{day}|{product}|{kind}|{sig(body)}",
                                  "title": f"{product}: {kind} ({day})", "link": link, "services": [product],
                                  "kind": kind, "text": body[:600]})
    def azure():
        root = ET.fromstring(fetch(TRACKED["feeds"]["azure"]).lstrip(b"\xef\xbb\xbf"))
        for it in root.iter("item"):
            title, desc = it.findtext("title", ""), _text(it.findtext("description", ""))
            cats = [c.text or "" for c in it.findall("category")]
            hit = [k for k in TRACKED["azure"]["keywords"] if k.lower() in (title + " " + desc + " " + " ".join(cats)).lower()]
            if hit:
                items.append({"cloud": "azure", "id": it.findtext("guid", "") or it.findtext("link", ""), "title": title,
                              "link": it.findtext("link", ""), "services": hit, "categories": cats, "text": desc[:600]})
    safe("feed/aws", aws, None)
    safe("feed/gcp", gcp, None)
    safe("feed/azure", azure, None)
    return items


# ── Diff ────────────────────────────────────────────────────────────────────
def diff_ops(cloud: str, svc: str, old: dict, new: dict) -> list[dict]:
    ch = []
    o, n = (old or {}).get("ops", {}), (new or {}).get("ops", {})
    for op in sorted(set(n) - set(o)):
        ch.append({"cloud": cloud, "service": svc, "kind": "operation-added", "key": f"{cloud}:{svc}:{op}:added",
                   "title": f"{cloud.upper()} {svc}: new operation {op}", "detail": n[op], "actionable": True})
    for op in sorted(set(o) - set(n)):
        ch.append({"cloud": cloud, "service": svc, "kind": "operation-removed", "key": f"{cloud}:{svc}:{op}:removed",
                   "title": f"{cloud.upper()} {svc}: operation {op} removed", "detail": o[op], "actionable": True})
    for op in sorted(set(o) & set(n)):
        if o[op] != n[op]:
            delta = {k: {"was": o[op].get(k), "now": n[op].get(k)} for k in n[op] if o[op].get(k) != n[op].get(k)}
            what = "deprecated" if n[op].get("deprecated") and not o[op].get("deprecated") else "changed"
            ch.append({"cloud": cloud, "service": svc, "kind": f"operation-{what}", "key": f"{cloud}:{svc}:{op}:{sig(n[op])}",
                       "title": f"{cloud.upper()} {svc}: operation {op} {what}", "detail": delta, "actionable": True})
    return ch


def main() -> int:
    prev = {}
    if os.environ.get("STATE") and os.path.exists(os.environ["STATE"]):
        try:
            prev = json.load(open(os.environ["STATE"]))
        except Exception:
            prev = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    baseline = not prev

    state = {"at": now, "aws": aws_surface(), "gcp": gcp_surface(), "versions": versions()}
    state["azure_since"] = now
    azure = azure_spec_commits("" if baseline else prev.get("azure_since", ""))
    feed_items = feeds()
    seen = set(prev.get("seen_feed_ids", []))
    state["seen_feed_ids"] = sorted((seen | {i["id"] for i in feed_items}))[-3000:]

    changes: list[dict] = []
    if not baseline:
        for svc, cur in state["aws"].items():
            if svc.startswith("_") or cur is None:
                continue
            old = prev.get("aws", {}).get(svc)
            if old is None:
                continue
            if old.get("api_version") != cur.get("api_version"):
                changes.append({"cloud": "aws", "service": svc, "kind": "api-version", "key": f"aws:{svc}:apiver:{cur['api_version']}",
                                "title": f"AWS {svc}: new API version {cur['api_version']}", "actionable": True})
            changes += diff_ops("aws", svc, old, cur)
        for api, cur in state["gcp"].items():
            old = prev.get("gcp", {}).get(api)
            if cur is None or old is None:
                continue
            changes += diff_ops("gcp", api, old, cur)
        for spec, commits in azure.items():
            for c in commits:
                new_ver = bool(re.search(r"\b20\d\d-\d\d-\d\d(-preview)?\b", c["title"]))
                life = bool(LIFECYCLE.search(c["title"]))
                changes.append({"cloud": "azure", "service": spec, "kind": "spec-commit", "key": f"azure:{spec}:{c['sha']}",
                                "title": f"Azure {spec}: {c['title']}", "link": c["url"],
                                "actionable": new_ver or life})
        for k, v in state["versions"].items():
            was = prev.get("versions", {}).get(k)
            if v and was and v != was:
                changes.append({"cloud": "sdk", "service": k, "kind": "release", "key": f"ver:{k}:{v}",
                                "title": f"{k}: {was} → {v}", "actionable": False})
        for it in feed_items:
            if it["id"] in seen:
                continue
            text = f"{it['title']} {it.get('kind','')} {' '.join(it.get('categories', []))} {it['text']}"
            life = bool(LIFECYCLE.search(text)) or it.get("kind", "").lower() in ("deprecated", "breaking", "breaking change")
            changes.append({"cloud": it["cloud"], "service": ", ".join(it["services"]), "kind": "lifecycle" if life else "announcement",
                            "key": f"feed:{it['cloud']}:{sig(it['id'])}", "title": it["title"], "link": it.get("link", ""),
                            "detail": it["text"], "actionable": life})

    os.makedirs(OUT, exist_ok=True)
    json.dump(state, open(os.path.join(OUT, "state.json"), "w"))
    json.dump({"at": now, "baseline": baseline, "changes": changes, "errors": ERRORS},
              open(os.path.join(OUT, "changes.json"), "w"), indent=1)

    act = [c for c in changes if c["actionable"]]
    ops = sum(len((s or {}).get("ops", {})) for k, s in state["aws"].items() if not k.startswith("_")) + \
          sum(len((s or {}).get("ops", {})) for s in state["gcp"].values())
    lines = [f"### Upstream watch — {now}", "",
             f"Tracking {ops} AWS + GCP operations, {len(TRACKED['azure']['specs'])} Azure spec areas, "
             f"{len(state['versions'])} SDK/CLI packages and 3 lifecycle feeds.", ""]
    if baseline:
        lines.append("First run: baseline recorded; changes are reported from the next run.")
    else:
        lines.append(f"**{len(changes)} change(s), {len(act)} actionable.**")
        for c in sorted(changes, key=lambda c: (not c["actionable"], c["cloud"], c["title"]))[:200]:
            lines.append(f"- {'🔧' if c['actionable'] else '·'} `{c['kind']}` {c['title']}" + (f" ([link]({c['link']}))" if c.get("link") else ""))
    if ERRORS:
        lines += ["", f"Sources that failed this run ({len(ERRORS)}): " + "; ".join(ERRORS[:10])]
    open(os.path.join(OUT, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

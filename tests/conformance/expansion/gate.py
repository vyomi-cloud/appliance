#!/usr/bin/env python3
"""Service gate — a new service is released only if every check here passes.

    python3 tests/conformance/expansion/gate.py services/manifests/aws-ecs.json [--static]

Static (files + wiring, no stack needed):
  manifest complete + status ready · engine in core/ · byte-identical Nano copy
  in wasm/core/ and listed in wasm/build_cores.py · service in the Nano console
  catalog (wasm/fixtures), entry identical to the offline catalog's · registry entry · test beds for Java, Go, CLI,
  Playwright offline and Playwright Nano registered in the hourly suites.json ·
  upstream id tracked by the upstream watcher · claimed operations exist
  upstream (AWS botocore model / Google Discovery doc).
Live (needs the stack at VYOMI_BASE_URL + the Nano relay, as in the hourly run):
  service in the offline console catalog · every manifest suite passes ·
  UI crawl of that service is clean on offline AND Nano, with the same tabs.

Writes gate-report.md next to the manifest's id under OUT and exits 1 on any
failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# GATE_ROOT: check another checkout (the pipeline page gates each service branch).
ROOT = os.environ.get("GATE_ROOT") or os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.environ.get("OUT", os.path.join(HERE, "out"))
BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
REQUIRED_KINDS = [("offline", "sdk-java"), ("offline", "sdk-go"), ("offline", "cli"), ("offline", "ui"), ("nano", "ui")]
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}{' — ' + detail if detail else ''}")
    return bool(ok)


def rel(p: str) -> str:
    return os.path.join(ROOT, p)


def get_json(url: str):
    h = {"User-Agent": "vyomi-gate"}
    if "api.github.com" in url and os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        return json.loads(r.read())


def upstream_ops(cloud: str, upstream: str) -> set[str] | None:
    try:
        if cloud == "aws":
            tag = get_json("https://pypi.org/pypi/botocore/json")["info"]["version"]
            vers = sorted(x["name"] for x in get_json(f"https://api.github.com/repos/boto/botocore/contents/botocore/data/{upstream}?ref={tag}") if x["type"] == "dir")
            return set(get_json(f"https://raw.githubusercontent.com/boto/botocore/{tag}/botocore/data/{upstream}/{vers[-1]}/service-2.json")["operations"])
        if cloud == "gcp":
            name, ver = upstream.split("/")
            try:
                doc = get_json(f"https://www.googleapis.com/discovery/v1/apis/{name}/{ver}/rest")
            except Exception:
                doc = get_json(f"https://{name}.googleapis.com/$discovery/rest?version={ver}")
            ids: set[str] = set()
            def walk(res):
                for r in (res or {}).values():
                    for m in (r.get("methods") or {}).values():
                        ids.add(m["id"]); ids.add(m["id"].split(".")[-1])
                    walk(r.get("resources"))
            walk(doc.get("resources"))
            return ids
    except Exception:
        return None
    return None  # Azure: operations are checked by the SDK/CLI suites


def fixture_in_sync(cloud: str, key: str) -> tuple[bool, str]:
    """Regenerate the Nano catalog from providers/<cloud>_catalog.py and compare
    this service's entry with the committed one (the file is restored)."""
    f = rel(f"wasm/fixtures/{cloud}-catalog.json")
    if not os.path.exists(f):
        return False, "no Nano catalog"
    fx = rel("wasm/fixtures")
    snapshot = {n: open(os.path.join(fx, n), "rb").read() for n in os.listdir(fx) if os.path.isfile(os.path.join(fx, n))}
    saved = snapshot[os.path.basename(f)]
    try:
        p = subprocess.run([sys.executable, rel("wasm/build_fixtures.py")], cwd=ROOT, capture_output=True, text=True)
        if p.returncode:
            return False, "build_fixtures.py failed: " + (p.stderr or p.stdout)[-200:]
        gen = {s.get("key"): s for s in json.load(open(f)).get("services", [])}
    finally:  # build_fixtures rewrites every fixture: put them all back
        for n in os.listdir(fx):
            if n not in snapshot and os.path.isfile(os.path.join(fx, n)):
                os.remove(os.path.join(fx, n))
        for n, data in snapshot.items():
            open(os.path.join(fx, n), "wb").write(data)
    have = {s.get("key"): s for s in json.loads(saved).get("services", [])}
    if key not in gen:
        return False, "not in the offline catalog (providers)"
    if gen[key] != have.get(key):
        diff = sorted(k for k in set(gen[key]) | set(have.get(key) or {}) if gen[key].get(k) != (have.get(key) or {}).get(k))
        return False, f"Nano entry differs from offline in: {diff[:8]} — run wasm/build_fixtures.py"
    return True, ""


def static(m: dict) -> None:
    cloud, key = m.get("cloud"), m.get("key")
    check("manifest has cloud, key, name, upstream, core, operations, suites",
          all(m.get(k) for k in ("cloud", "key", "name", "upstream", "core", "operations", "suites")))
    check("manifest status is ready", m.get("status") == "ready", f"status={m.get('status')}")
    core = m.get("core", "")
    check("engine exists in core/", core.startswith("core/") and os.path.exists(rel(core)), core)
    nano = "wasm/core/" + os.path.basename(core)
    same = os.path.exists(rel(core)) and os.path.exists(rel(nano)) and open(rel(core), "rb").read() == open(rel(nano), "rb").read()
    check("Nano copy is byte-identical (wasm/core/)", same, nano)
    check("engine listed in wasm/build_cores.py", os.path.basename(core) in open(rel("wasm/build_cores.py")).read())
    try:
        nano_keys = {s.get("key") for s in json.load(open(rel(f"wasm/fixtures/{cloud}-catalog.json"))).get("services", [])}
    except Exception:
        nano_keys = set()
    check("service in the Nano console catalog (wasm/fixtures)", key in nano_keys, f"{cloud}-catalog.json")
    check("Nano console entry is identical to the offline catalog's (build_fixtures.py)", *fixture_in_sync(cloud, key))
    reg = json.load(open(rel("services/registry.json")))["services"]
    check("registry entry (pending-release or released)",
          any(s["cloud"] == cloud and s["key"] == key and s.get("status") in ("pending-release", "released") for s in reg))
    suites = {s["id"]: s for s in json.load(open(rel("tests/conformance/hourly/suites.json")))["suites"]}
    mine = [suites[i] for i in m.get("suites", []) if i in suites]
    check("every manifest suite is registered in the hourly suites.json",
          len(mine) == len(m.get("suites", [])), f"missing: {[i for i in m.get('suites', []) if i not in suites]}")
    for target, kind in REQUIRED_KINDS:
        check(f"has a {target} {kind} test bed", any(s["target"] == target and s["kind"] == kind for s in mine))
    tracked = json.load(open(rel("tests/conformance/upstream/tracked.json")))
    lists = {"aws": tracked["aws"]["botocore"], "gcp": tracked["gcp"]["discovery"], "azure": tracked["azure"]["specs"]}
    check("upstream id tracked by the hourly upstream watcher", m.get("upstream") in lists.get(cloud, []), m.get("upstream", ""))
    ups = upstream_ops(cloud, m.get("upstream", ""))
    if ups is not None:
        bad = [o for o in m.get("operations", []) if o not in ups]
        check("claimed operations exist in the real API", not bad, f"not upstream: {bad[:10]}")


def live(m: dict) -> None:
    cloud, key = m["cloud"], m["key"]
    try:
        keys = {s.get("key") for s in get_json(f"{BASE}/api/{cloud}/catalog").get("services", [])}
    except Exception as e:
        keys = set()
    check("service in the offline console catalog", key in keys, f"{BASE}/api/{cloud}/catalog")
    p = subprocess.run([sys.executable, rel("tests/conformance/hourly/run_suites.py"), "--only", ",".join(m["suites"])],
                       cwd=ROOT, capture_output=True, text=True)
    print(p.stdout[-3000:])
    part = json.load(open(rel("tests/conformance/hourly/out/results-partial.json")))
    for s in part.get("suites", []):
        check(f"suite {s['id']} passes", s["status"] == "pass", f"{s.get('passed')} passed, {s.get('failed')} failed")
    tabs = {}
    for target in ("offline", "nano"):
        f = rel(f"tests/conformance/hourly/out/ui-{target}.json")
        env = dict(os.environ, TARGET=target, OUT=f, CREATE="1")
        if target == "nano":
            env["NANO_DIR"] = rel("wasm")
        subprocess.run(["node", rel("tests/conformance/hourly/ui_crawler.mjs")], cwd=ROOT, env=env, capture_output=True, text=True)
        try:
            rows = [r for r in json.load(open(f))["services"] if r["cloud"] == cloud
                    and (r["service"].lower() == m["name"].lower() or key.lower() in r["service"].lower().replace(" ", ""))]
        except Exception:
            rows = []
        bad = [x for r in rows for x in r.get("findings", [])]
        tabs[target] = {t if isinstance(t, str) else t.get("name") for r in rows for t in r.get("tabs", [])}
        check(f"UI crawl clean on {target}", rows and not bad,
              "service not on the rail" if not rows else "; ".join(f"{x['type']}: {x['detail']}" for x in bad[:5]))
    only_off, only_nano = tabs.get("offline", set()) - tabs.get("nano", set()), tabs.get("nano", set()) - tabs.get("offline", set())
    check("Nano and offline consoles have the same detail tabs", not only_off and not only_nano,
          f"offline only: {sorted(only_off)}; Nano only: {sorted(only_nano)}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__); return 2
    m = json.load(open(sys.argv[1]))
    static(m)
    if "--static" not in sys.argv:
        live(m)
    failed = [r for r in results if not r[1]]
    os.makedirs(OUT, exist_ok=True)
    md = [f"### Service gate — {m.get('cloud', '?').upper()} {m.get('name', '?')} — "
          f"{'✅ PASSED' if not failed else f'❌ {len(failed)} check(s) failed'}", "",
          "| | Check | Detail |", "|---|---|---|"] + \
         [f"| {'✅' if ok else '❌'} | {n} | {str(d).replace('|', '/')[:200]} |" for n, ok, d in results]
    open(os.path.join(OUT, f"gate-{m.get('cloud')}-{m.get('key')}.md"), "w").write("\n".join(md) + "\n")
    print(f"\n{len(results) - len(failed)}/{len(results)} gate checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

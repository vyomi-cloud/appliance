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
import re
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


def _mb(v) -> float:
    """'256m' / '1g' / '512MiB' / 268435456 → MB."""
    t = str(v).strip().lower().replace("ib", "").replace("b", "")
    mult = {"k": 1 / 1024, "m": 1, "g": 1024}
    return float(t[:-1]) * mult[t[-1]] if t and t[-1] in mult else float(t) / (1024 * 1024)


def backend_static(m: dict) -> None:
    """Offline data-plane backend: cheap, permissively licensed, multi-arch,
    pinned, wired into the stack (tests/conformance/expansion/backends.json)."""
    pol = json.load(open(os.path.join(HERE, "backends.json")))
    P = pol["policy"]
    b = m.get("backend") or {}
    kind = b.get("kind")
    if not check("manifest declares its offline backend (in-process / container / substrate)",
                 kind in ("in-process", "container", "substrate"), f"backend={b or 'missing'}"):
        return
    upid = f"{m.get('cloud')}:{m.get('upstream')}"
    rec = next((n for n, x in pol["shared"].items() if upid in x.get("for", [])), None)
    rec_inproc = m.get("upstream") in pol["in_process"].get(m.get("cloud"), [])
    matches = (rec and b.get("name") == rec) or (rec_inproc and kind == "in-process") or (not rec and not rec_inproc)
    # A `reason` may pick a different REAL backend, never drop one: where a data-plane
    # backend is recommended, in-process means the resource doesn't really work
    # (no traffic, no kubectl, no DNS answer, no mail) — v3.0.10-v3.0.23 shipped that way.
    swap_ok = bool(b.get("reason")) and not (rec and kind == "in-process")
    check("backend is the recommended one, or a different real backend the manifest justifies", matches or swap_ok,
          f"recommended: {rec or ('in-process' if rec_inproc else 'none')}; chose {b.get('name') or kind}")
    tier = b.get("tier", "lite")
    if kind == "substrate":
        check("substrate backends are Pro or Max only", tier in ("pro", "max"), f"tier={tier}")
        return
    if kind == "in-process":
        return
    lic = b.get("license", "")
    check("backend license is permissive (or GPL as an unmodified separate container)",
          lic in P["license_allow"] or lic in P["license_allow_separate_process"], f"license={lic or 'missing'}")
    check("backend license is not denied (SSPL / BSL / RSAL / Elastic / AGPL / proprietary)",
          lic not in P["license_deny"], f"license={lic}")
    img = b.get("image", "")
    tag = img.rsplit(":", 1)[1] if ":" in img.split("/")[-1] else ""
    check("backend image is pinned to a version (not latest)", bool(tag) and tag != "latest" and any(c.isdigit() for c in tag), img)
    svc = b.get("compose_service", "")
    budget = P["budget_idle_mb"].get(tier, 128)
    import yaml
    for f in ("docker-compose.yml", "docker-compose.cloudlite.yml"):
        d = (yaml.safe_load(open(rel(f))) or {}).get("services", {})
        c = d.get(svc) or {}
        lim = ((c.get("deploy") or {}).get("resources") or {}).get("limits", {}).get("memory") or c.get("mem_limit")
        check(f"backend service `{svc}` in {f}: image, profile full, healthcheck, mem limit ≤ {budget} MB ({tier})",
              bool(c) and c.get("image") == img and "full" in (c.get("profiles") or []) and bool(c.get("healthcheck"))
              and lim is not None and _mb(lim) <= budget,
              "missing" if not c else f"image={c.get('image')} profiles={c.get('profiles')} healthcheck={bool(c.get('healthcheck'))} mem={lim}")
    ci = [l.strip() for l in open(rel("tests/conformance/hourly/ci-services.txt")) if l.strip() and not l.startswith("#")]
    check("backend service started by CI / gate / hourly (ci-services.txt)", svc in ci, svc)
    try:
        out = subprocess.run(["docker", "manifest", "inspect", img], capture_output=True, text=True, timeout=120)
        archs = set(re.findall(r'"architecture":\s*"(\w+)"', out.stdout))
        check("backend image is multi-arch (amd64 + arm64)", set(P["arch_required"]) <= archs,
              f"architectures: {sorted(archs) or out.stderr.strip()[:120]}")
    except FileNotFoundError:
        check("backend image is multi-arch (amd64 + arm64)", False, "docker not available to inspect the image")


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
    backend_static(m)
    ups = upstream_ops(cloud, m.get("upstream", ""))
    if ups is not None:
        bad = [o for o in m.get("operations", []) if o not in ups]
        check("claimed operations exist in the real API", not bad, f"not upstream: {bad[:10]}")


def blank_like_real(m: dict, f: dict) -> bool:
    """A blank cell the real cloud console also shows blank (e.g. CloudFormation
    "Status reason" on a successful event). Declared per column in the manifest
    as {"tab": ..., "column": ..., "why": ...}; `why` is required and printed in
    the gate report so a reviewer can check it against the real console."""
    if f.get("type") != "PLACEHOLDER_CELL":
        return False
    for e in m.get("blank_like_real_console", []):
        if e.get("why") and f'column "{e.get("column")}"' in f.get("detail", "") and \
                (not e.get("tab") or f.get("tab") == e["tab"] or f"tab {e['tab']}:" in f.get("detail", "")):
            return True
    return False


def live(m: dict) -> None:
    cloud, key = m["cloud"], m["key"]
    b = m.get("backend") or {}
    if b.get("kind") == "container":
        budget = json.load(open(os.path.join(HERE, "backends.json")))["policy"]["budget_idle_mb"].get(b.get("tier", "lite"), 128)
        p = subprocess.run(["docker", "compose", "-f", rel("docker-compose.yml"), "ps", "-q", b.get("compose_service", "")],
                           capture_output=True, text=True)
        cid = p.stdout.strip().splitlines()[:1]
        used = None
        if cid:
            st = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", cid[0]], capture_output=True, text=True)
            used = _mb(st.stdout.split("/")[0]) if st.stdout.strip() else None
        check(f"backend idle memory ≤ {budget} MB", used is not None and used <= budget,
              f"{b.get('compose_service')}: {round(used, 1) if used is not None else 'not running'} MB")
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
        # Only this service (the full console takes ~40 min per target).
        only = "|".join(re.escape(x) for x in {m["name"], key, key.replace("-", " ")})
        env = dict(os.environ, TARGET=target, OUT=f, CREATE="1", ONLY=only)
        if target == "nano":
            env["NANO_DIR"] = rel("wasm")
        subprocess.run(["node", rel("tests/conformance/hourly/ui_crawler.mjs")], cwd=ROOT, env=env, capture_output=True, text=True)
        try:
            rows = [r for r in json.load(open(f))["services"] if r["cloud"] == cloud
                    and (r["service"].lower() == m["name"].lower() or key.lower() in r["service"].lower().replace(" ", ""))]
        except Exception:
            rows = []
        bad = [x for r in rows for x in r.get("findings", []) if not blank_like_real(m, x)]
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
    for e in m.get("blank_like_real_console", []):
        check(f"blank like the real console: {e.get('tab', '*')} / {e.get('column')}", bool(e.get("why")),
              e.get("why") or "needs a why (what the real console shows)")
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

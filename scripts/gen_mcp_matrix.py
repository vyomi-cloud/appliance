#!/usr/bin/env python3
"""Generate the knowledge `vyomi mcp` embeds: cmd/vyomi/mcp_matrix.json, mcp_caps.json.gz, mcp_docs.json.gz.

Never hand-edit the outputs. They are derived from the code so they cannot drift:

  services/registry.json           WHICH services are released (status, version):
                                   the same registry release.yml publishes as
                                   services.json for vyomi.cloud
  providers/capabilities.py        per-service summaries (enrichment)
  core/pack_catalog.py             service packs: API actions + data plane (enrichment)
  providers/{aws,gcp,azure}.py     tool_response(): per-SDK / CLI endpoint config
  docker-compose.appliance.yml     host ports of the simulator + emulator containers
  .env.example                     documented VYOMI_* settings
  scripts/mcp_wiring.json          hand-curated client wiring per home (offline / nano / mesh: env vars,
                                   TLS, gotchas) and registry-key -> capability-file aliases
  VERSION                          appliance version stamped into the matrix
  core/capabilities/{aws,gcp,azure}/*.json
                                   v4 capability registry -> mcp_caps.json.gz (level per substrate,
                                   tier, mesh, limitations, tests) + per-service roll-ups in the matrix
  wasm/docs/<cloud>/*.json         generated API docs (wired operations) -> mcp_docs.json.gz, with the
  wasm/nano-docs.js                CLI/SDK/curl snippets the Nano console shows, rendered by running
                                   nano-docs.js under node with the endpoint "{sim}" (needs `node`)

Import hygiene: providers/__init__.py pulls in FastAPI and core.app_context boots
the platform (and writes .cloudlearn_state.sqlite3). Both are stubbed so this
script is side-effect free and needs no third-party packages.

The .gz outputs are written deterministically (sorted keys, gzip mtime=0, no file name); --check compares
their decompressed JSON, so a different zlib build cannot make CI flaky.

Usage:
  python3 scripts/gen_mcp_matrix.py           # write the three outputs
  python3 scripts/gen_mcp_matrix.py --check   # exit 1 if any committed output is stale (CI)
"""
from __future__ import annotations

import argparse
import copy
import gzip
import io
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cmd" / "vyomi" / "mcp_matrix.json"
OUT_CAPS = ROOT / "cmd" / "vyomi" / "mcp_caps.json.gz"
OUT_DOCS = ROOT / "cmd" / "vyomi" / "mcp_docs.json.gz"
WIRING = ROOT / "scripts" / "mcp_wiring.json"
CAPS_DIR = ROOT / "core" / "capabilities"
DOCS_DIR = ROOT / "wasm" / "docs"
NANO_DOCS_JS = ROOT / "wasm" / "nano-docs.js"
CLOUDS = ("aws", "gcp", "azure")
SCHEMA = 2
# Worst first: a service's level is the worst level across its capabilities.
LEVELS = ("not_simulated", "config_only", "limited", "full")

# tool_response() keys per provider module, normalised to the MCP's `lang` names.
TOOL_KEYS = {
    "aws": {"cli": "cli", "sdk/python": "python", "sdk/nodejs": "nodejs", "sdk/java": "java", "sdk/go": "go"},
    "gcp": {"gcloud": "cli", "sdk/python": "python", "sdk/nodejs": "nodejs", "sdk/java": "java", "sdk/go": "go"},
    "azure": {"cli": "cli", "sdk/python": "python", "sdk/nodejs": "nodejs", "sdk/java": "java", "sdk/go": "go"},
}


def _sandbox_imports() -> None:
    sys.path.insert(0, str(ROOT))
    providers = types.ModuleType("providers")
    providers.__path__ = [str(ROOT / "providers")]  # skip providers/__init__ (FastAPI)
    sys.modules["providers"] = providers
    import core  # noqa: F401  (plain package, no side effects)

    app_context = types.ModuleType("core.app_context")
    app_context.gcp_project_name = lambda project=None: project or "cloudlearn"
    sys.modules["core.app_context"] = app_context
    sys.modules["core"].app_context = app_context


def _pack_service_id(pack_id: str, cloud: str) -> str:
    parts = pack_id.split(".")
    if parts and parts[0] == "cloudlearn":
        parts = parts[1:]
    if parts and parts[0] == cloud:
        parts = parts[1:]
    if parts and parts[-1] == "basic":
        parts = parts[:-1]
    return ".".join(parts)


def _services(cloud: str, wiring: dict) -> list[dict]:
    """Released services from services/registry.json, enriched with capability
    summaries and pack actions. capabilities.py / pack ids that differ from the
    registry key are mapped through wiring["id_aliases"]."""
    from providers.capabilities import SERVICE_CAPABILITIES
    from core.pack_catalog import packs_for_provider

    aliases = wiring.get("id_aliases", {}).get(cloud, {})
    registry = json.loads((ROOT / "services" / "registry.json").read_text())["services"]
    out: dict[str, dict] = {}
    for svc in registry:
        if svc.get("cloud") != cloud or svc.get("status") != "released":
            continue  # pending-release services appear once the release bot flips them
        out[svc["key"]] = {
            "id": svc["key"],
            "name": svc.get("name", svc["key"]),
            "status": svc.get("status", "released"),
            "released_in": svc.get("released_in", ""),
        }
    unmatched = []
    for cap in SERVICE_CAPABILITIES.get(cloud, []):
        sid = aliases.get(cap["id"], cap["id"])
        if sid in out:
            out[sid]["summary"] = cap.get("summary", "")
        else:
            unmatched.append(f"capabilities:{cap['id']}")
    for pack in packs_for_provider(cloud):
        if pack.get("type") != "service":
            continue
        pid = _pack_service_id(pack.get("id", ""), cloud)
        sid = aliases.get(pid, pid)
        if sid not in out:
            unmatched.append(f"pack:{pack.get('id')}")
            continue
        api = pack.get("api") or {}
        out[sid]["pack_id"] = pack.get("id")
        if api.get("actions"):
            out[sid]["actions"] = list(api["actions"])
        if api.get("dataPlane"):
            out[sid]["data_plane"] = api["dataPlane"]
        if api.get("protocol"):
            out[sid]["protocol"] = api["protocol"]
    if unmatched:  # an engine that is not in the registry: surface it, don't invent a status
        print(f"note: {cloud}: not in services/registry.json, left out of the matrix: "
              + ", ".join(sorted(unmatched)), file=sys.stderr)
    return [out[k] for k in sorted(out)]


def _tools(cloud: str) -> dict:
    import importlib

    mod = importlib.import_module(f"providers.{cloud}")
    tools = {}
    for key, lang in TOOL_KEYS[cloud].items():
        try:
            resp = copy.deepcopy(mod.tool_response(key))
        except Exception as exc:  # a broken tool_response must fail the build loudly
            raise SystemExit(f"providers/{cloud}.py tool_response({key!r}) failed: {exc}")
        if not isinstance(resp, dict) or resp.get("error"):
            continue
        resp.pop("provider_surface", None)
        resp.pop("provider", None)
        tools[lang] = resp
    return tools


def _host_ports() -> dict:
    """service -> ["host:container", ...] from the appliance compose file (no PyYAML)."""
    text = (ROOT / "docker-compose.appliance.yml").read_text()
    ports: dict[str, list[str]] = {}
    in_services, current, in_ports = False, None, False
    for line in text.splitlines():
        if re.match(r"^services:\s*$", line):
            in_services = True
            continue
        if in_services and re.match(r"^\S", line):
            break  # next top-level key (volumes:, networks:)
        if not in_services:
            continue
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if m:
            current, in_ports = m.group(1), False
            continue
        if re.match(r"^    ports:\s*$", line):
            in_ports = True
            continue
        if in_ports:
            pm = re.match(r"""^\s+-\s+["']?(\d+:\d+)["']?\s*$""", line)
            if pm:
                ports.setdefault(current, []).append(pm.group(1))
            elif re.match(r"^    \S", line):
                in_ports = False
    return dict(sorted(ports.items()))


def _settings() -> list[dict]:
    """VYOMI_* knobs documented in .env.example (commented-out ones included)."""
    out, doc = [], []
    for raw in (ROOT / ".env.example").read_text().splitlines():
        line = raw.strip()
        m = re.match(r"^#?\s*(VYOMI_[A-Z0-9_]+)=(.*)$", line)
        if m:
            out.append({"name": m.group(1), "default": m.group(2).strip(),
                        "doc": " ".join(doc).strip(), "commented_out": line.startswith("#")})
            continue
        if line.startswith("#") and not line.startswith("# ──") and not line.startswith("# ─"):
            doc.append(line.lstrip("# ").strip())
        else:
            doc = []
    return out


# ── knowledge v2: capabilities (core/capabilities) ─────────────────────────────

CAP_KEYS = ("title", "level", "tier", "mesh", "limitations", "tests")


def _capabilities() -> dict:
    """{cloud: {stem: [capability, ...]}} from core/capabilities/<cloud>/<stem>.json, in file order.
    Skips `$doc`-style keys; _tiers.json and backends/ live outside the per-cloud folders."""
    out: dict[str, dict[str, list]] = {}
    for cloud in CLOUDS:
        out[cloud] = {}
        for f in sorted((CAPS_DIR / cloud).glob("*.json")):
            if f.name.startswith("_"):
                continue
            caps = []
            for cid, v in json.loads(f.read_text()).items():
                if cid.startswith("$") or not isinstance(v, dict):
                    continue
                c = {"id": cid}
                for k in CAP_KEYS:
                    if k in v and v[k] not in (None, False):
                        c[k] = v[k]
                caps.append(c)
            out[cloud][f.stem] = caps
    return out


def _worst(levels) -> str:
    known = [lv for lv in levels if lv in LEVELS]
    return min(known, key=LEVELS.index) if known else ""


def _rollup(caps: list) -> dict:
    """Per-service summary of its capabilities. `levels` is the worst level per substrate (plan K1);
    `level_counts` keeps the spread. `tier`/`mesh` describe the service's anchor capability (the first
    in its file, e.g. azure.aks.cluster.crud): a service whose anchor needs a mesh needs one to be useful,
    while one mesh-only extra (lambda.microvms) does not make all of Lambda mesh-only; those extras are
    listed in `mesh_only` / counted in `pro_capabilities`."""
    if not caps:
        return {}
    out = {"capabilities": len(caps), "levels": {}, "level_counts": {}}
    for sub in ("nano", "offline"):
        lv = [(c.get("level") or {}).get(sub, "") for c in caps]
        out["levels"][sub] = _worst(lv)
        counts: dict[str, int] = {}
        for x in lv:
            if x:
                counts[x] = counts.get(x, 0) + 1
        out["level_counts"][sub] = counts
    if caps[0].get("tier"):
        out["tier"] = caps[0]["tier"]
    if caps[0].get("mesh"):
        out["mesh"] = True
    pro = sum(1 for c in caps if c.get("tier"))
    if pro:
        out["pro_capabilities"] = pro
    mesh_only = [c["id"] for c in caps if c.get("mesh")]
    if mesh_only:
        out["mesh_only"] = mesh_only
    return out


def _cap_alias(cloud: str, sid: str, wiring: dict) -> tuple[str, str]:
    """(stem, id prefix) for a registry key: capability_aliases, else the key itself."""
    a = wiring.get("capability_aliases", {}).get(cloud, {}).get(sid, sid)
    stem, _, prefix = a.partition("#")
    return stem, prefix


def _attach_rollups(clouds: dict, caps: dict, wiring: dict, titles: dict) -> None:
    """Registry services get `capability_service` + roll-up; capability files with no registry entry are
    listed as `v4_services` (v4 services the v3 registry never had, e.g. bedrock, eks)."""
    for cloud in CLOUDS:
        used = set()
        for svc in clouds[cloud]["services"]:
            stem, prefix = _cap_alias(cloud, svc["id"], wiring)
            cs = [c for c in caps[cloud].get(stem, []) if c["id"].startswith(prefix)]
            if not cs:
                continue
            used.add(stem)
            svc["capability_service"] = stem + ("#" + prefix if prefix else "")
            svc.update(_rollup(cs))
        v4 = []
        for stem in sorted(caps[cloud]):
            if stem in used or not caps[cloud][stem]:
                continue
            v4.append({"id": stem, "name": titles.get(cloud, {}).get(stem, stem), "status": "v4", **_rollup(caps[cloud][stem])})
        clouds[cloud]["v4_services"] = v4


# ── knowledge v2: API docs + snippets (wasm/docs, wasm/nano-docs.js) ───────────

# Runs the Nano console's own snippet templates (wasm/nano-docs.js) under node, so the MCP hands out exactly
# what the console's "SDK & CLI usage" shows, aimed at the endpoint placeholder {sim}. nano-docs.js is a
# browser IIFE: a minimal window/document shim is enough because only the pure template functions run.
_NODE_RENDER = r"""
const fs = require("fs"), vm = require("vm");
const [jsPath, docsDir, ...clouds] = process.argv.slice(1);
let src = fs.readFileSync(jsPath, "utf8");
const hook = "_snips: snips,";
if (!src.includes(hook)) { console.error("nano-docs.js no longer exports `_snips: snips,`"); process.exit(3); }
src = src.replace(hook, hook + " _pickOps: pickOps,");
const ctx = { window: {}, document: { baseURI: "http://localhost/" }, URL, console };
vm.createContext(ctx); vm.runInContext(src, ctx);
const ND = ctx.window.NanoDocs, out = {};
for (const cloud of clouds) {
  out[cloud] = {};
  for (const f of fs.readdirSync(docsDir + "/" + cloud).filter((x) => x.endsWith(".json")).sort()) {
    const d = JSON.parse(fs.readFileSync(docsDir + "/" + cloud + "/" + f, "utf8"));
    const apis = (d.apis || []).map((a) => {
      const pick = a.ops && a.ops.length ? ND._pickOps(a).map((o) => a.ops.indexOf(o)) : [];
      return { id: a.id, title: a.title || "", pick, ops: (a.ops || []).map((o) => ({ o: o, s: ND._snips(cloud, a, o, "{sim}") })) };
    });
    out[cloud][f.replace(/\.json$/, "")] = { d, apis };
  }
}
process.stdout.write(JSON.stringify(out));
"""


def _lang(label: str) -> str:
    if re.search(r"curl", label, re.I):
        return "curl"
    if label.startswith("Python"):
        return "python"
    if label.startswith("JavaScript"):
        return "javascript"
    return "cli"


def _by_lang(snips: list) -> dict:
    """[[label, text], ...] -> {cli|python|javascript|curl: text}. Several snippets for one language
    (e.g. `az rest` + native `az`) are stacked with a comment naming each, as the console's SDK tab does."""
    groups: dict[str, list] = {}
    for label, text in snips:
        groups.setdefault(_lang(label), []).append((label, text))
    out = {}
    for lang, items in groups.items():
        if len(items) == 1:
            out[lang] = items[0][1]
        else:
            mark = "// " if lang == "javascript" else "# "
            out[lang] = "\n\n".join(mark + label + "\n" + text for label, text in items)
    return out


def _aws_cli_fix(api: dict, text: str) -> str:
    """wasm/docs derives an AWS API's `cli` word from botocore's serviceId (secrets-manager, api-gateway,
    cloudwatch-logs, elastic-load-balancing-v2, sfn, s3), but the AWS CLI command is the botocore service
    name (secretsmanager, apigateway, logs, elbv2, stepfunctions) and low-level S3 is `s3api`. Until
    scripts/gen_nano_docs.py emits the right word, correct it here so the MCP hands out commands that run."""
    want = "s3api" if api.get("id") == "s3" else api.get("id", "")
    have = api.get("cli", "")
    if not want or not have or want == have:
        return text
    return text.replace("aws --endpoint-url {sim} " + have + " ", "aws --endpoint-url {sim} " + want + " ")


def _short(text: str, n: int = 160) -> str:
    t = re.split(r"(?<=\.)\s", str(text or "").strip(), maxsplit=1)[0]
    return t if len(t) <= n else t[: n - 3] + "..."


def _docs() -> dict:
    node = shutil.which("node")
    if not node:
        raise SystemExit("gen_mcp_matrix.py needs `node` to render snippets from wasm/nano-docs.js")
    r = subprocess.run([node, "-e", _NODE_RENDER, str(NANO_DOCS_JS), str(DOCS_DIR), *CLOUDS],
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise SystemExit("rendering snippets with wasm/nano-docs.js failed: " + r.stderr.strip()[:500])
    raw = json.loads(r.stdout)
    out: dict[str, dict] = {}
    for cloud in CLOUDS:
        out[cloud] = {}
        for stem, entry in sorted(raw[cloud].items()):
            d = entry["d"]
            apis = []
            for ai, a in enumerate(entry["apis"]):
                raw_api = d["apis"][ai]
                ops = []
                for item in a["ops"]:
                    o = item["o"]
                    op = {"n": o["n"], "m": o.get("m", ""), "u": o.get("ex") or o.get("u", ""), "d": _short(o.get("d", "")),
                          "s": _by_lang(item["s"])}
                    if cloud == "aws" and "cli" in op["s"]:
                        op["s"]["cli"] = _aws_cli_fix(raw_api, op["s"]["cli"])
                    names = sorted({str(x).lower() for x in (o.get("py"), o.get("cli"), o.get("az")) if x} - {o["n"].lower()})
                    if names:
                        op["k"] = names
                    ops.append(op)
                if ops:
                    apis.append({"id": a["id"], "title": a["title"], "pick": a["pick"], "ops": ops})
            svc = {"title": d.get("title", stem), "id": d.get("id", stem), "category": d.get("category", ""),
                   "source": f"wasm/docs/{cloud}/{stem}.json", "ops": sum(len(a["ops"]) for a in apis), "apis": apis,
                   "features": [[f.get("id", ""), f.get("l", "")] for f in d.get("features", [])]}
            if d.get("data"):
                svc["data"] = [{"n": x.get("n", ""), "u": str(x.get("u", "")).replace("{EP}", "{sim}"), "c": x.get("c", "")}
                               for x in d["data"]]
            out[cloud][stem] = svc
    return out


def _doc_titles() -> dict:
    ix = json.loads((DOCS_DIR / "index.json").read_text())
    return {c: {s["id"]: s.get("t", s["id"]) for s in ix.get("clouds", {}).get(c, [])} for c in CLOUDS}


# ── assembling the three outputs ──────────────────────────────────────────────

def _homes(wiring: dict) -> dict:
    homes = {}
    for hid, h in wiring["homes"].items():
        if "same_as" in h:
            h = {**wiring["homes"][h["same_as"]], "same_as": h["same_as"], "_comment": h.get("_comment", "")}
        homes[hid] = {k: v for k, v in h.items() if k != "_comment"}
        if h.get("_comment"):
            homes[hid]["about"] = h["_comment"] if isinstance(h["_comment"], str) else " ".join(h["_comment"])
    return homes


def build() -> tuple[dict, dict, dict]:
    _sandbox_imports()
    from core.provider_registry import get_provider

    wiring = json.loads(WIRING.read_text())
    caps = _capabilities()
    homes = _homes(wiring)
    clouds = {}
    for cloud in CLOUDS:
        info = get_provider(cloud)
        clouds[cloud] = {
            "display_name": info.get("name", cloud),
            "native_services": info.get("native_services", []),
            "services": _services(cloud, wiring),
            "tools": _tools(cloud),
            "wiring": homes["offline"]["clouds"][cloud],   # legacy (schema 1) field: the offline home
        }
    _attach_rollups(clouds, caps, wiring, _doc_titles())
    version = (ROOT / "VERSION").read_text().strip()
    matrix = {
        "schema": SCHEMA,
        "generated_by": "scripts/gen_mcp_matrix.py",
        "appliance_version": version,
        "defaults": {"sim_port": 9000, "tls_port": 9443, "host": "127.0.0.1", "azure_account": "devstoreaccount1"},
        "host_ports": _host_ports(),
        "settings": _settings(),
        "clouds": clouds,
        "homes": homes,
        "scan": wiring["scan"],
    }
    caps_out = {"schema": SCHEMA, "generated_by": "scripts/gen_mcp_matrix.py", "appliance_version": version,
                "source": "core/capabilities/{aws,gcp,azure}/*.json",
                "clouds": {c: {stem: {"file": f"core/capabilities/{c}/{stem}.json", "capabilities": caps[c][stem]}
                               for stem in caps[c]} for c in CLOUDS}}
    docs_out = {"schema": SCHEMA, "generated_by": "scripts/gen_mcp_matrix.py", "appliance_version": version,
                "source": "wasm/docs/<cloud>/*.json, snippets rendered by wasm/nano-docs.js with endpoint {sim}",
                "clouds": _docs()}
    return matrix, caps_out, docs_out


def _json(v) -> str:
    return json.dumps(v, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _gz(text: str) -> bytes:
    """Deterministic gzip: no file name, mtime 0, fixed level."""
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, compresslevel=9, mtime=0) as f:
        f.write(text.encode("utf-8"))
    return buf.getvalue()


def _gunzip(path: Path) -> str:
    try:
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, EOFError, UnicodeDecodeError):
        return ""


def _stale_cap_sources(current: str, rendered: str) -> list[str]:
    """Source capability files whose content differs between the committed and the fresh caps index."""
    try:
        old = json.loads(current)["clouds"]
    except (ValueError, KeyError, TypeError):
        return []
    new = json.loads(rendered)["clouds"]
    out = []
    for c in CLOUDS:
        for stem in sorted(set(old.get(c, {})) | set(new.get(c, {}))):
            if old.get(c, {}).get(stem) != new.get(c, {}).get(stem):
                out.append(f"core/capabilities/{c}/{stem}.json")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if a committed output is stale")
    args = ap.parse_args()
    matrix, caps, docs = build()
    outputs = [(OUT, _json(matrix), False), (OUT_CAPS, _json(caps), True), (OUT_DOCS, _json(docs), True)]
    if args.check:
        stale = 0
        for path, rendered, gz in outputs:
            current = _gunzip(path) if (gz and path.exists()) else (path.read_text() if path.exists() else "")
            if current != rendered:
                stale += 1
                why = ""
                if path == OUT_CAPS:
                    srcs = _stale_cap_sources(current, rendered)
                    why = (" (changed: " + ", ".join(srcs[:10]) + ("…" if len(srcs) > 10 else "") + ")") if srcs else ""
                print(f"{path.relative_to(ROOT)} is stale{why}: run python3 scripts/gen_mcp_matrix.py", file=sys.stderr)
        if stale:
            return 1
        print("mcp knowledge up to date (mcp_matrix.json, mcp_caps.json.gz, mcp_docs.json.gz)")
        return 0
    for path, rendered, gz in outputs:
        if gz:
            path.write_bytes(_gz(rendered))
        else:
            path.write_text(rendered)
    ncaps = sum(len(v["capabilities"]) for c in CLOUDS for v in caps["clouds"][c].values())
    nops = sum(s["ops"] for c in CLOUDS for s in docs["clouds"][c].values())
    counts = ", ".join(f"{c}={len(matrix['clouds'][c]['services'])}+{len(matrix['clouds'][c]['v4_services'])}" for c in CLOUDS)
    print(f"wrote {OUT.relative_to(ROOT)} (v{matrix['appliance_version']}; services registry+v4 {counts}), "
          f"{OUT_CAPS.relative_to(ROOT)} ({ncaps} capabilities), {OUT_DOCS.relative_to(ROOT)} ({nops} operations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

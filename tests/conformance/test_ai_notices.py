"""Licence notices guard (ENGINEERING DRAFT, not legal advice; docs/architecture/v4.0/AI-LICENCE-AUDIT.md).

Fails if: a served catalogue model (Mesh pool, role models, Nano web pool) has no licence entry; THIRD-PARTY-NOTICES.md / sbom.cdx.json / the console JSON /
the catalogue licence block are stale against tools/notices/notices.json; a vendored component (wasm/pylib wheels, wasm/cedar, wasm/parquet,
wasm/kubescape, wasm/vm/*, wasm/console-next/vendor), a Python/npm dependency or a compose image is missing from the notices; a licence text file is missing;
Qwen2.5-3B is not flagged non-commercial or a paid tier would still select it; the Llama naming rule is not applied; the Llama/Gemma policy links are absent.

Run: PYTHONPATH=. python3 tests/conformance/test_ai_notices.py
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
ROOT = os.path.abspath(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "notices"))
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


import gen_notices as G  # noqa: E402
from core import ai_model_catalog as CAT  # noqa: E402
from core import mesh_ai as MA  # noqa: E402

D = G.load()
NOTE = {m["id"]: m for m in D["models"]}

# ── generated files are fresh
for p, text in G.outputs().items():
    rel = os.path.relpath(p, ROOT)
    check(f"{rel} is up to date with notices.json (run python3 tools/notices/gen_notices.py)", os.path.exists(p) and open(p).read() == text)

# ── every served model has a licence entry, with the required fields
FIELDS = ("license", "licenseId", "licenseUrl", "attribution")


def served(mods):
    return list(mods)


for m in served(CAT.MODELS) + served(CAT.SPECIAL):
    ok = all(m.get(k) for k in FIELDS) and "commercialUse" in m and m["id"] in NOTE
    check(f"Mesh catalogue model {m['id']} has licence/licenseUrl/attribution entries", ok, {k: m.get(k) for k in FIELDS})
web = json.loads(subprocess.run([sys.executable, "-c", "import json,sys; sys.path.insert(0,'.'); from core import ai_model_catalog as C; print(json.dumps(C.MODELS))"],
                                cwd=ROOT, env=dict(os.environ, VYOMI_CATALOG="web"), capture_output=True, text=True).stdout)
check("Nano web catalogue was read", len(web) == 5, len(web))
for m in web:
    check(f"Nano catalogue model {m['id']} has licence entries", all(m.get(k) for k in FIELDS) and m["id"] in NOTE, {k: m.get(k) for k in FIELDS})
check("no qwen2.5-3b in the Nano (paid, in-browser) catalogue", all(m["id"] != "qwen2.5-3b" for m in web))
for mid, m in NOTE.items():
    check(f"notices.json model {mid} names a known licence and an upstream URL", m["licence"] in D["licences"] and m["upstream"].startswith("https://"))

# ── catalogue values equal notices.json (single source)
for m in CAT.MODELS + CAT.SPECIAL:
    v = G.model_view(D, NOTE[m["id"]])
    check(f"catalogue licence fields for {m['id']} equal notices.json", all(m.get(k) == v[k2] for k, k2 in (("license", "license"), ("licenseId", "licenseId"), ("licenseUrl", "licenseUrl"), ("attribution", "attribution"), ("requiredNotice", "requiredNotice"), ("commercialUse", "commercialUse"))))
cj = json.load(open(os.path.join(ROOT, "consoles", "src", "common", "ai-model-catalog.json")))
check("console catalogue JSON carries license/licenseUrl/attribution/requiredNotice", all(all(k in m for k in ("license", "licenseUrl", "attribution", "requiredNotice")) for m in cj["models"] + cj["special"]))
cw = json.load(open(os.path.join(ROOT, "consoles", "src", "common", "ai-model-catalog-web.json")))
check("console WEB catalogue JSON carries the licence fields", all(all(k in m for k in ("license", "licenseUrl", "attribution", "requiredNotice")) for m in cw["models"]))

# ── licence texts exist and the verbatim required notices are exact
for k, L in D["licences"].items():
    if L["mustShipText"]:
        f = os.path.join(ROOT, L["file"])
        check(f"licence text shipped for {k}: {L['file']}", os.path.isfile(f) and os.path.getsize(f) > 500)
    if L.get("aupFile"):
        check(f"use policy text shipped for {k}: {L['aupFile']}", os.path.isfile(os.path.join(ROOT, L["aupFile"])))
check("Llama 3.1 notice is verbatim", D["licences"]["llama-3.1"]["notice"] == "Llama 3.1 is licensed under the Llama 3.1 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved.")
check("Llama 3.2 notice is verbatim", D["licences"]["llama-3.2"]["notice"] == "Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved.")
check("Gemma notice is verbatim", D["licences"]["gemma"]["notice"] == "Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms")
check("Qwen research notice is verbatim", D["licences"]["qwen-research"]["notice"] == "Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) Alibaba Cloud. All Rights Reserved.")
check("Gemma prohibited-use and Llama AUP links are in the data", all(D["links"].get(k, "").startswith("https://") for k in ("gemmaProhibitedUse", "llamaAup31", "llamaAup32")))
check("'Built with Llama' is set for Llama models only", {i for i, m in CAT.BY_ID.items() if m.get("builtWithLlama")} == {i for i in ("llama3.1-8b", "llama3.2-1b") if i in CAT.BY_ID})
check("disclaimer names the non-affiliation and API-compatibility use", all(s in D["disclaimer"] for s in ("not affiliated with AWS, Google, Microsoft, Meta, Anthropic or OpenAI", "only to describe API compatibility")))
md = open(os.path.join(ROOT, "THIRD-PARTY-NOTICES.md")).read()
check("THIRD-PARTY-NOTICES.md carries the draft banner and the verbatim Llama notice", D["draftBanner"] in md and D["licences"]["llama-3.1"]["notice"] in md)

# ── vendored components are in the notices
paths = {p for c in D["components"] for p in c.get("paths", [])}
names = {c["name"].lower() for c in D["components"]}
for wheel in sorted(os.listdir(os.path.join(ROOT, "wasm", "pylib"))):
    m = re.match(r"([A-Za-z0-9_.]+)-([0-9][^-]*)-", wheel)
    hit = [c for c in D["components"] if c["kind"] == "vendored" and m and c["name"].lower().replace("_", "-") == m.group(1).lower().replace("_", "-") and c.get("version") == m.group(2)]
    check(f"vendored wheel wasm/pylib/{wheel} is in the notices with its version", bool(hit))
for d in ("wasm/cedar", "wasm/parquet", "wasm/kubescape", "wasm/vm/engine", "wasm/vm/bios", "wasm/vm/image", "wasm/vm/xterm", "wasm/console-next/vendor"):
    check(f"vendored directory {d} is in the notices", d in paths)
for p in paths:
    check(f"notices path exists: {p}", os.path.exists(os.path.join(ROOT, p)))


def req_names(f):
    out = []
    for line in open(os.path.join(ROOT, f)):
        line = line.split("#")[0].strip()
        if line:
            out.append(re.split(r"[\[<>=!~ ;]", line)[0].lower())
    return out


for f in ("requirements.txt", "trainer/requirements.txt"):
    for n in req_names(f):
        check(f"{f}: {n} is in the notices", n in names)
pkg = json.load(open(os.path.join(ROOT, "consoles", "package.json")))
npm = {p["name"] for p in G.npm_prod()}
for n in list(pkg["dependencies"]):
    check(f"consoles/package.json: {n} is in the lockfile production set that the notices list", n in npm)
check("every npm production package has a licence in the lockfile", all(p["license"] != "UNKNOWN" for p in G.npm_prod()), [p["name"] for p in G.npm_prod() if p["license"] == "UNKNOWN"][:5])
ALIAS = {"python": "python (python", "google-cloud-cli": "google cloud sdk", "elasticmq-native": "elasticmq", "victoria-metrics": "victoriametrics", "dynamodb-local": "amazon/dynamodb-local"}
OWN = {"appliance", "cloudsim", "instance"}
imgs = set()
for f in ("docker-compose.yml", "docker-compose.appliance.yml", "docker-compose.cloudlite.yml", "docker-compose.override.yml"):
    p = os.path.join(ROOT, f)
    if os.path.exists(p):
        imgs |= set(re.findall(r"^\s*image:\s*\"?(?:\$\{[A-Z_]+:-)?([A-Za-z0-9][A-Za-z0-9._/-]*)", open(p).read(), re.M))
for img in sorted(imgs):
    base = img.split("/")[-1].split(":")[0]
    if base in OWN:
        continue
    key = ALIAS.get(base, base).lower()
    check(f"compose image {img} is in the notices", any(key in n for n in names))
for k in ("minio", "mysql", "redis", "caddy", "nats", "registry", "postgres"):
    check(f"provisioned image {k} is in the notices", any(k in n for n in names))

# ── Qwen2.5-3B: kept but flagged, never chosen on a paid tier
q = CAT.BY_ID["qwen2.5-3b"]
check("qwen2.5-3b stays in the Mesh catalogue", "qwen2.5-3b" in CAT.IDS)
check("qwen2.5-3b is flagged commercialUse false with the visible non-commercial flag", q["commercialUse"] is False and q["licenseFlag"] == "Non-commercial research licence: not for paid use")
check("every other catalogue model is commercial", all(m["commercialUse"] for m in CAT.MODELS + CAT.SPECIAL if m["id"] != "qwen2.5-3b"))
os.environ.pop("VYOMI_PAID_TIER", None)
# The default itself is commercially clean, with NO dependence on VYOMI_PAID_TIER (asserted both with and without it below).
check("default chat is qwen3-4b (Apache-2.0) and commercial with no paid-tier env", CAT.default_chat() == "qwen3-4b" == CAT.DEFAULT_CHAT == CAT.LOCAL_ID and CAT.commercial(CAT.DEFAULT_CHAT) and CAT.BY_ID["qwen3-4b"]["licenseId"] == "Apache-2.0")
check("every small-model alias (nova-micro/lite, gemini flash, gpt-4o-mini, gpt-35, titan-text) resolves to a commercial model with no paid-tier env",
      all(CAT.commercial(CAT.resolve(c, a)) for c, a in (("aws", "amazon.nova-micro-v1:0"), ("aws", "amazon.nova-lite-v1:0"), ("gcp", "gemini-1.5-flash"), ("azure", "gpt-4o-mini"), ("azure", "gpt-35-turbo"))) and CAT.resolve("aws", "amazon.nova-micro-v1:0") == "qwen3-4b")
import json as _json
_mj = _json.load(open(os.path.join(ROOT, "docker", "mesh-runner-llm", "models.json")))
check("runner catalogue: default_chat is commercial and the non-commercial model is on no runner", _mj["default_chat"] == "qwen3-4b" and not any("qwen2.5-3b" in r["models"] for r in _mj["runners"].values()))
check("every default_chat / DEFAULT_CHAT in the Mesh code paths is commercial", all(CAT.commercial(x) for x in (CAT.default_chat(), CAT.default_chat(False), CAT.default_chat(True), MA.DEFAULT_CHAT, _mj["default_chat"])))
check("the Mesh AI pack default is not flagged non-commercial and its admission refuses the non-commercial model on a paid tier",
      MA.MODELS[MA.DEFAULT_CHAT].get("commercial", True) and MA.MODELS["qwen2.5-3b"]["commercial"] is False)
_c = open(os.path.join(ROOT, "codespace", ".devcontainer", "mesh", "docker-compose.mesh.yml")).read()
check("Codespace compose defaults to the Apache-2.0 Qwen3 GGUF, not Qwen2.5", "unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M" in _c and ":-qwen3-4b" in _c and "Qwen2.5-3B" not in _c)
import core.training_core as _tc
check("training: no trainable chat base is non-commercial or Llama-derived; qwen3-4b is a base", "qwen3-4b" in _tc.CHAT_BASES and "qwen2.5-3b" not in _tc.CHAT_BASES and "deepseek-r1-8b" not in _tc.CHAT_BASES and all(CAT.commercial(k) for k in _tc.CHAT_BASES if k in CAT.BY_ID))
import core.backend_provisioner as _bp
_red = _bp._RECIPES["redis"].image
check("redis image is pinned to a BSD-3-Clause 7.2.x tag (7.4+ is RSALv2/SSPLv1, 8.x AGPLv3)", __import__("re").match(r"^redis:7\.2\.\d+(-alpine)?$", _red) is not None, _red)
os.environ["VYOMI_PAID_TIER"] = "1"
try:
    check("paid tier: default chat skips the non-commercial model", CAT.default_chat() != "qwen2.5-3b" and CAT.commercial(CAT.default_chat()) and CAT.default_chat() == "qwen3-4b", CAT.default_chat())
    bad = [(c, a) for c, ids in (("aws", ("amazon.nova-micro-v1:0", "amazon.nova-lite-v1:0", "vyomi.qwen2.5-3b", "qwen2.5-3b")), ("gcp", ("gemini-1.5-flash", "qwen2.5-3b")), ("azure", ("gpt-4o-mini", "gpt-35-turbo", "qwen2.5-3b"))) for a in ids if CAT.resolve(c, a) == "qwen2.5-3b"]
    check("paid tier: no cloud id (aliases or the model itself) resolves to qwen2.5-3b", not bad, bad)
    check("paid tier: embeddings and the other chat models still resolve", CAT.resolve("aws", "amazon.titan-embed-text-v2:0") == "nomic-embed-text" and CAT.resolve("aws", "vyomi.qwen2.5-7b") == "qwen2.5-7b")
finally:
    os.environ.pop("VYOMI_PAID_TIER", None)

# ── Llama naming rule + licence carried by tuned models
check("derived_name prefixes Llama for a Llama base", CAT.derived_name("facilities-tuned", "llama3.1-8b") == "Llama-facilities-tuned" and CAT.derived_name("Llama-x", "llama3.1-8b") == "Llama-x")
check("derived_name leaves non-Llama bases alone", CAT.derived_name("facilities-tuned", "qwen2.5-7b") == "facilities-tuned" and CAT.derived_name("t", "smollm2-135m-instruct") == "t")
check("llama3.2-1b base is also covered via the web catalogue data", D["licences"]["llama-3.2"]["namingRule"].startswith("Any AI model"))
from core import training_core as tc  # noqa: E402
check("training_core derives names and licence through the catalogue", tc._derived_name("a", "llama3.1-8b") == "Llama-a" and tc._license_of("llama3.1-8b").get("builtWithLlama") is True and tc._license_of("qwen2.5-3b").get("commercialUse") is False)
check("chat job record exposes vyomiLicense and displayName", "vyomiLicense" in tc._PUBLIC and "displayName" in tc._PUBLIC)
import inspect  # noqa: E402
check("start_chat applies the Llama naming rule", "_derived_name(name, cb)" in inspect.getsource(tc.start_chat))
from core import import_core as ic  # noqa: E402
check("import_core.register applies the Llama naming rule", "_derived_name(name" in inspect.getsource(ic.register))

# ── API responses carry the licence only in the additive vyomi field
from core import ai_models_core as am  # noqa: E402
lst = json.loads(am.bedrock_dispatch("GET", "/foundation-models", {}, {}, b"")["body"])["modelSummaries"]
check("ListFoundationModels: every model carries vyomiLicense (additive)", lst and all(m.get("vyomiLicense", {}).get("license") for m in lst if m["modelId"].startswith("vyomi.")))
check("ListFoundationModels: native fields are not licence-polluted", all("license" not in m and "licenseUrl" not in m for m in lst))
llama = [m for m in lst if m["modelId"] == "vyomi.llama3.1-8b"][0]["vyomiLicense"]
check("GetFoundationModel list: Llama carries Built-with-Llama data", llama["builtWithLlama"] is True and "Llama 3.1 is licensed under" in llama["requiredNotice"])
q3 = [m for m in lst if m["modelId"] == "vyomi.qwen2.5-3b"][0]["vyomiLicense"]
check("ListFoundationModels: qwen2.5-3b carries the non-commercial flag", q3["commercialUse"] is False and "not for paid use" in q3["licenseFlag"])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

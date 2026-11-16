#!/usr/bin/env python3
"""Generate the third-party notices from the ONE data file tools/notices/notices.json.

Writes (all deterministic, no timestamps):
  THIRD-PARTY-NOTICES.md                         human-readable notices (models, software, licence index)
  sbom.cdx.json                                  CycloneDX 1.5 SBOM listing the same components
  consoles/src/common/third-party-notices.json   what the console "Notices & licences" page renders

The npm production dependencies (with their licences) are read from consoles/package-lock.json; everything else comes from
notices.json. ENGINEERING DRAFT, not legal advice. `--check` exits 1 if any generated file differs from what is on disk.
Run: python3 tools/notices/gen_notices.py
"""
from __future__ import annotations

import hashlib
import json
import os
import pprint
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "tools", "notices", "notices.json")
LOCK = os.path.join(ROOT, "consoles", "package-lock.json")
OUT_MD = os.path.join(ROOT, "THIRD-PARTY-NOTICES.md")
OUT_SBOM = os.path.join(ROOT, "sbom.cdx.json")
OUT_CONSOLE = os.path.join(ROOT, "consoles", "src", "common", "third-party-notices.json")
CATALOG = os.path.join(ROOT, "core", "ai_model_catalog.py")
BEGIN, END = "# BEGIN GENERATED LICENCES\n", "# END GENERATED LICENCES\n"
CATALOG_KEYS = ("license", "licenseId", "licenseUrl", "attribution", "requiredNotice", "commercialUse", "builtWithLlama", "licenseFlag", "aupUrl", "copyright", "upstream")
REPO_BLOB = "https://github.com/vyomi-cloud/appliance/blob/main/"
NPM_SPDX = {"MIT": "mit", "Apache-2.0": "apache-2.0", "ISC": "isc", "BSD-3-Clause": "bsd-3-clause", "BSD-2-Clause": "bsd-2-clause"}


def load():
    with open(DATA) as f:
        return json.load(f)


def npm_prod():
    """Production (non-dev) packages from the console lockfile: [{name, version, license}] sorted."""
    with open(LOCK) as f:
        lock = json.load(f)
    out = []
    for k, v in lock.get("packages", {}).items():
        if not k or v.get("dev"):
            continue
        name = v.get("name") or k.split("node_modules/")[-1]
        out.append({"name": name, "version": v.get("version", ""), "license": str(v.get("license") or "UNKNOWN")})
    out.sort(key=lambda p: (p["name"], p["version"]))
    return out


def lic_ref(d, key):
    return d["licences"][key]


def model_view(d, m):
    L = lic_ref(d, m["licence"])
    commercial = m.get("commercialUse", True) and L.get("commercialUse", True)
    return {
        "id": m["id"], "name": m["name"], "license": L["name"], "licenseId": L["spdx"], "licenseUrl": L["url"],
        "attribution": ("%s. %s, %s." % (L["builtWith"], m["name"], L["name"])) if L.get("builtWith") else ("%s: %s. %s" % (m["name"], L["name"], m["copyright"] if str(m["copyright"]).startswith("Copyright") else "Copyright holder: %s." % m["copyright"])),
        "requiredNotice": m.get("notice") or L.get("notice", ""), "builtWithLlama": bool(L.get("builtWith")), "commercialUse": bool(commercial),
        "upstream": m["upstream"], "copyright": m["copyright"], "where": m.get("where", ""), "note": m.get("note", ""),
        "aupUrl": L.get("aupUrl", ""), "flag": "" if commercial else L.get("flag", "Non-commercial licence: not for paid use"),
        "alsoDerivedFrom": [lic_ref(d, k)["name"] for k in m.get("alsoDerivedFrom", [])], "verified": m.get("verified", ""),
    }


def comp_view(d, c):
    L = lic_ref(d, c["licence"])
    lic = [L["name"]] + [lic_ref(d, k)["name"] for k in c.get("alsoLicences", [])]
    return {"name": c["name"], "kind": c["kind"], "version": c.get("version") or c.get("versionSpec", ""), "scope": c.get("scope", ""),
            "license": " + ".join(lic), "licenseId": L["spdx"], "licenseUrl": L["url"], "upstream": c["upstream"], "copyright": c["copyright"],
            "paths": c.get("paths", []), "note": c.get("note", ""), "verified": c.get("verified", "")}


def console_doc(d):
    npm = npm_prod()
    counts = {}
    for p in npm:
        counts[p["license"]] = counts.get(p["license"], 0) + 1
    return {
        "_comment": "GENERATED from tools/notices/notices.json by tools/notices/gen_notices.py - do not edit.",
        "draftBanner": d["draftBanner"], "disclaimer": d["disclaimer"], "links": d["links"],
        "licences": {k: {x: v[x] for x in ("name", "spdx", "url", "file", "notice", "builtWith", "aupUrl", "namingRule", "flag") if v.get(x)} for k, v in d["licences"].items()},
        "models": [model_view(d, m) for m in d["models"]],
        "components": [comp_view(d, c) for c in d["components"]],
        "npm": {"count": len(npm), "byLicense": dict(sorted(counts.items())), "source": "consoles/package-lock.json (production dependencies)"},
        "repoBlob": REPO_BLOB,
    }


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def make_md(d):
    L = []
    w = L.append
    w("# Third-party notices and model licences")
    w("")
    w("> %s" % d["draftBanner"])
    w("> GENERATED by `tools/notices/gen_notices.py` from `tools/notices/notices.json`. Do not edit by hand.")
    w("")
    w(d["disclaimer"])
    w("")
    w("Full licence texts are in [`licenses/`](licenses/). The software bill of materials is [`sbom.cdx.json`](sbom.cdx.json) (CycloneDX 1.5).")
    w("Vyomi's own code is under the [Vyomi Appliance License](LICENSE); third-party components keep their own licences.")
    w("")
    w("## Models")
    w("")
    w("| Model (catalogue id) | Licence | Copyright holder | Upstream | Commercial use | Where |")
    w("|---|---|---|---|---|---|")
    for m in d["models"]:
        v = model_view(d, m)
        cu = "yes" if v["commercialUse"] else "**NO: " + v["flag"] + "**"
        w("| %s (`%s`) | %s (`%s`) | %s | %s | %s | %s |" % (esc(v["name"]), v["id"], esc(v["license"]), v["licenseId"], esc(v["copyright"]), v["upstream"], cu, esc(v["where"])))
    w("")
    w("### Required notices (verbatim from the licences)")
    w("")
    for k, lic in d["licences"].items():
        used = [m for m in d["models"] if m["licence"] == k]
        if not used or not lic.get("notice"):
            continue
        w("**%s**" % lic["name"])
        w("")
        if lic.get("builtWith"):
            w("- %s" % lic["builtWith"])
        w("- %s" % lic["notice"])
        if lic.get("aupUrl"):
            w("- Acceptable / prohibited use policy: %s (text in `%s`)" % (lic["aupUrl"], lic["aupFile"]))
        if lic.get("namingRule"):
            w("- Naming rule: %s" % lic["namingRule"])
        if lic.get("flag"):
            w("- **%s**" % lic["flag"])
        w("- Models: %s" % ", ".join("%s" % m["name"] for m in used))
        w("")
    w("Apache-2.0 and MIT models: the licence text and any upstream NOTICE are kept; the copyright holder and source link are in the table above. "
      "DeepSeek R1 models are MIT (\"Copyright (c) 2023 DeepSeek\") and derived from Qwen (Apache-2.0).")
    w("")
    w("## Software")
    w("")
    kinds = [("vendored", "Vendored in this repository"), ("runtime", "Loaded at run time from a CDN (not vendored)"), ("image", "Container images and servers"), ("python", "Python dependencies")]
    for kind, title in kinds:
        rows = [c for c in d["components"] if c["kind"] == kind]
        if not rows:
            continue
        w("### %s" % title)
        w("")
        w("| Component | Version | Licence | Copyright holder | Upstream | Check | Notes |")
        w("|---|---|---|---|---|---|---|")
        for c in rows:
            v = comp_view(d, c)
            ver = v["version"] + (" (%s)" % v["scope"] if v["scope"] else "")
            chk = "licence text read" if v["verified"] == "fetched" else "from knowledge, confirm"
            w("| %s | %s | %s (`%s`) | %s | %s | %s | %s |" % (esc(v["name"]), esc(ver), esc(v["license"]), v["licenseId"], esc(v["copyright"]), v["upstream"], chk, esc(v["note"] + (" Paths: " + ", ".join("`%s`" % p for p in v["paths"]) if v["paths"] else ""))))
        w("")
    npm = npm_prod()
    w("### Console JavaScript packages (production, from `consoles/package-lock.json`)")
    w("")
    w("%d packages are bundled into the Vyomi consoles. Each keeps its own copyright notice in its package; the licence texts are in `licenses/`." % len(npm))
    w("")
    w("| Package | Version | Licence |")
    w("|---|---|---|")
    for p in npm:
        w("| %s | %s | %s |" % (esc(p["name"]), esc(p["version"]), esc(p["license"])))
    w("")
    w("## Licence texts")
    w("")
    w("| Licence | SPDX id | Text |")
    w("|---|---|---|")
    for k, lic in d["licences"].items():
        w("| %s | `%s` | %s |" % (esc(lic["name"]), lic["spdx"], ("[`%s`](%s)" % (lic["file"], lic["file"])) if lic["file"] else "not shipped (proprietary terms: %s)" % lic["url"]))
        if lic.get("aupFile"):
            w("| %s: use policy | | [`%s`](%s) |" % (esc(lic["name"]), lic["aupFile"], lic["aupFile"]))
    w("")
    return "\n".join(L)


def purl_for(c):
    n = c["name"].split(" (")[0].replace(" ", "-").lower()
    if c["kind"] == "python":
        return "pkg:pypi/%s%s" % (n, ("@" + c["version"]) if c.get("version") else "")
    return ""


def make_sbom(d):
    comps = []
    for m in d["models"]:
        v = model_view(d, m)
        comps.append({"type": "machine-learning-model", "bom-ref": "model:" + m["id"], "name": m["name"], "supplier": {"name": m["copyright"]},
                      "licenses": [{"license": {"id": lic_ref(d, m["licence"])["spdx"]}}] if not lic_ref(d, m["licence"])["spdx"].startswith("LicenseRef") else [{"license": {"name": lic_ref(d, m["licence"])["name"], "url": v["licenseUrl"]}}],
                      "externalReferences": [{"type": "website", "url": m["upstream"]}],
                      "properties": [{"name": "vyomi:catalogId", "value": m["id"]}, {"name": "vyomi:commercialUse", "value": str(v["commercialUse"]).lower()}]})
    for c in d["components"]:
        L = lic_ref(d, c["licence"])
        lics = [L] + [lic_ref(d, k) for k in c.get("alsoLicences", [])]
        lj = [({"license": {"id": x["spdx"]}} if not x["spdx"].startswith("LicenseRef") else {"license": {"name": x["name"], "url": x["url"]}}) for x in lics]
        ctype = {"python": "library", "vendored": "library", "runtime": "library", "image": "container"}[c["kind"]]
        comp = {"type": ctype, "bom-ref": "component:%s:%s" % (c["kind"], c["name"]), "name": c["name"], "supplier": {"name": c["copyright"]},
                "licenses": lj, "externalReferences": [{"type": "website", "url": c["upstream"]}], "properties": [{"name": "vyomi:kind", "value": c["kind"]}]}
        if c.get("version"):
            comp["version"] = c["version"]
        if c.get("versionSpec"):
            comp["properties"].append({"name": "vyomi:versionSpec", "value": c["versionSpec"]})
        for p in c.get("paths", []):
            comp["properties"].append({"name": "vyomi:path", "value": p})
        pu = purl_for(c)
        if pu:
            comp["purl"] = pu
        comps.append(comp)
    for p in npm_prod():
        spdx = p["license"]
        comps.append({"type": "library", "bom-ref": "npm:%s@%s" % (p["name"], p["version"]), "name": p["name"], "version": p["version"],
                      "purl": "pkg:npm/%s@%s" % (p["name"].replace("@", "%40", 1) if p["name"].startswith("@") else p["name"], p["version"]),
                      "licenses": [{"license": {"id": spdx}}] if spdx != "UNKNOWN" else [{"license": {"name": "UNKNOWN"}}],
                      "properties": [{"name": "vyomi:kind", "value": "npm"}]})
    body = json.dumps(comps, sort_keys=True)
    serial = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "vyomi-sbom:" + hashlib.sha256(body.encode()).hexdigest()))
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": serial, "version": 1,
            "metadata": {"component": {"type": "application", "name": "vyomi-appliance", "bom-ref": "vyomi-appliance"},
                         "properties": [{"name": "vyomi:status", "value": "engineering draft generated from tools/notices/notices.json; not legal advice"}]},
            "components": comps}


def catalog_block(d):
    """The generated _LICENSE_DATA literal for core/ai_model_catalog.py (pure stdlib: it also ships to Nano/Pyodide)."""
    data = {}
    for m in d["models"]:
        v = model_view(d, m)
        data[m["id"]] = {"license": v["license"], "licenseId": v["licenseId"], "licenseUrl": v["licenseUrl"], "attribution": v["attribution"],
                         "requiredNotice": v["requiredNotice"], "commercialUse": v["commercialUse"], "builtWithLlama": v["builtWithLlama"],
                         "licenseFlag": v["flag"], "aupUrl": v["aupUrl"], "copyright": v["copyright"], "upstream": v["upstream"]}
    return "_LICENSE_DATA = " + pprint.pformat(data, width=150, sort_dicts=True) + "\n"


def catalog_text(d):
    s = open(CATALOG).read()
    i, j = s.index(BEGIN) + len(BEGIN), s.index(END)
    return s[:i] + catalog_block(d) + s[j:]


def outputs():
    d = load()
    return {CATALOG: catalog_text(d),
            OUT_MD: make_md(d) + "\n",
            OUT_SBOM: json.dumps(make_sbom(d), indent=1) + "\n",
            OUT_CONSOLE: json.dumps(console_doc(d), indent=1) + "\n"}


if __name__ == "__main__":
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not os.path.exists(p) or open(p).read() != t]
        for p in stale:
            print("STALE", os.path.relpath(p, ROOT))
        sys.exit(1 if stale else 0)
    for p, t in outs.items():
        with open(p, "w") as f:
            f.write(t)
        print("wrote", os.path.relpath(p, ROOT))

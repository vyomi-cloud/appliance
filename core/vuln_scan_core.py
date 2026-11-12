"""Image / package vulnerability scanning (substrate-free) — the vulnerability engine behind
ECR-style image scanning, Defender for Containers (ACR) and Artifact Registry vulnerability scanning.

Two engines produce the SAME finding shape; the result always says which one ran:

  * ``vyomi-advisory`` (this module, pure Python — Nano and offline): matches the package
    inventory of an image against a small BUNDLED, CURATED advisory snapshot (``ADVISORIES``) and
    an end-of-life table (``EOL``). The inventory is read from the image's real stored config blob
    (``history[].created_by`` install commands with pinned versions, ``Env`` runtime versions,
    labels, and an optional ``vyomi.sbom`` label / SBOM JSON). Layer tarballs are NOT unpacked.
  * ``trivy`` (offline appliance only, providers/trivy_runner.py): the real Trivy CLI container
    scans an exported archive of the image; its parsed report is attached with
    ``attach_trivy_report`` and takes over from the advisory engine for that image.

Honest limits (also in the capability JSON): the advisory snapshot is a few dozen well-known CVEs,
not a live feed; distro-backported fixes are not modelled for OS packages; an image whose config
carries no pinned install commands / SBOM yields an inventory of its base image only.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re

ENGINE_ADVISORY = "vyomi-advisory"
SNAPSHOT = "2026-11-01"          # date the bundled advisory snapshot was curated
SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]


def _a(cve, pkgs, eco, ranges, sev, cvss, title):
    return {"id": cve, "pkgs": pkgs, "eco": eco, "ranges": ranges, "severity": sev, "cvss": cvss, "title": title}


# ranges: [(introduced, fixed)] — vulnerable when introduced <= v < fixed.
ADVISORIES = [
    _a("CVE-2014-0160", ["openssl", "libssl1.0", "libssl1.0.0"], "os", [("1.0.1", "1.0.1g")], "HIGH", 7.5, "OpenSSL TLS heartbeat read overrun (Heartbleed)"),
    _a("CVE-2021-3449", ["openssl", "libssl1.1"], "os", [("1.1.1", "1.1.1k")], "MEDIUM", 5.9, "OpenSSL NULL pointer dereference in TLS renegotiation"),
    _a("CVE-2022-0778", ["openssl", "libssl1.1", "libssl3"], "os", [("1.0.2", "1.0.2zd"), ("1.1.1", "1.1.1n"), ("3.0.0", "3.0.2")], "HIGH", 7.5, "OpenSSL infinite loop in BN_mod_sqrt() while parsing certificates"),
    _a("CVE-2023-0286", ["openssl", "libssl1.1", "libssl3"], "os", [("1.1.1", "1.1.1t"), ("3.0.0", "3.0.8")], "HIGH", 7.4, "OpenSSL X.400 address type confusion in X.509 GeneralName"),
    _a("CVE-2022-37434", ["zlib", "zlib1g", "libz"], "os", [("0", "1.2.13")], "CRITICAL", 9.8, "zlib heap buffer over-read/overflow in inflate() via large gzip header extra field"),
    _a("CVE-2021-3156", ["sudo"], "os", [("1.8.2", "1.8.32"), ("1.9.0", "1.9.5p2")], "HIGH", 7.8, "sudo heap-based buffer overflow (Baron Samedit)"),
    _a("CVE-2023-4863", ["libwebp", "libwebp7"], "os", [("0", "1.3.2")], "HIGH", 8.8, "libwebp heap buffer overflow in WebP lossless decoding"),
    _a("CVE-2023-4863", ["pillow"], "pypi", [("0", "10.0.1")], "HIGH", 8.8, "Pillow bundles a libwebp with a heap buffer overflow in WebP decoding"),
    _a("CVE-2023-38545", ["curl", "libcurl"], "os", [("7.69.0", "8.4.0")], "CRITICAL", 9.8, "curl SOCKS5 heap buffer overflow"),
    _a("CVE-2018-18074", ["requests"], "pypi", [("0", "2.20.0")], "HIGH", 7.5, "requests sends the Authorization header to a different host on redirect"),
    _a("CVE-2023-32681", ["requests"], "pypi", [("2.3.0", "2.31.0")], "MEDIUM", 6.1, "requests leaks Proxy-Authorization headers to destination servers"),
    _a("CVE-2023-37920", ["certifi"], "pypi", [("0", "2023.7.22")], "HIGH", 7.5, "certifi trusts the removed e-Tugra root certificates"),
    _a("CVE-2020-14343", ["pyyaml"], "pypi", [("0", "5.4")], "CRITICAL", 9.8, "PyYAML arbitrary code execution through full_load/FullLoader"),
    _a("CVE-2022-29217", ["pyjwt"], "pypi", [("1.5.0", "2.4.0")], "HIGH", 7.5, "PyJWT algorithm confusion with non-default key types"),
    _a("CVE-2022-28346", ["django"], "pypi", [("2.2", "2.2.28"), ("3.2", "3.2.13"), ("4.0", "4.0.4")], "CRITICAL", 9.8, "Django SQL injection in QuerySet.annotate(), aggregate() and extra()"),
    _a("CVE-2023-30861", ["flask"], "pypi", [("0", "2.2.5"), ("2.3.0", "2.3.2")], "HIGH", 7.5, "Flask session cookie can be cached and served to other clients behind a caching proxy"),
    _a("CVE-2020-8203", ["lodash"], "npm", [("0", "4.17.19")], "HIGH", 7.4, "lodash prototype pollution in zipObjectDeep"),
    _a("CVE-2021-23337", ["lodash"], "npm", [("0", "4.17.21")], "HIGH", 7.2, "lodash command injection via the template function"),
    _a("CVE-2021-44228", ["log4j-core"], "maven", [("2.0", "2.15.0")], "CRITICAL", 10.0, "Apache Log4j2 JNDI remote code execution (Log4Shell)"),
    _a("CVE-2021-45046", ["log4j-core"], "maven", [("2.0", "2.16.0")], "CRITICAL", 9.0, "Apache Log4j2 incomplete fix for Log4Shell in non-default configurations"),
    _a("CVE-2022-22965", ["spring-beans"], "maven", [("5.3.0", "5.3.18"), ("5.2.0", "5.2.20")], "CRITICAL", 9.8, "Spring Framework RCE via data binding on JDK 9+ (Spring4Shell)"),
]

# product -> [(cycle prefix, end-of-life date)] — only dates that are public and stable.
EOL = {
    "python": [("3.6", "2021-12-23"), ("3.7", "2023-06-27"), ("3.8", "2024-10-07"), ("3.9", "2025-10-31")],
    "node": [("12", "2022-04-30"), ("14", "2023-04-30"), ("16", "2023-09-11"), ("18", "2025-04-30")],
    "alpine": [("3.14", "2023-05-01"), ("3.15", "2023-11-01"), ("3.16", "2024-05-23"), ("3.17", "2024-11-22"), ("3.18", "2025-05-09")],
    "debian": [("9", "2022-06-30"), ("10", "2024-06-30")],
    "ubuntu": [("16.04", "2021-04-30"), ("18.04", "2023-05-31"), ("20.04", "2025-05-31")],
}
_PRODUCT_ALIASES = {"nodejs": "node", "python3": "python"}


# ── versions ────────────────────────────────────────────────────────────────
def _norm(v: str) -> str:
    v = str(v or "").strip().lstrip("vV")
    v = re.sub(r"^\d+:", "", v)                       # debian epoch
    v = re.sub(r"-r\d+$", "", v)                      # alpine release
    v = re.sub(r"(\+|~)[A-Za-z0-9.+~]*$", "", v)      # +deb11u1 / ~ubuntu
    v = re.sub(r"-\d+(\.\d+)*(ubuntu\d*|build\d*)?$", "", v)   # debian revision
    return v


def _tokens(v: str) -> list:
    return [(0, int(t)) if t.isdigit() else (1, t.lower()) for t in re.findall(r"\d+|[A-Za-z]+", _norm(v))]


def version_cmp(a: str, b: str) -> int:
    ta, tb = _tokens(a), _tokens(b)
    for i in range(max(len(ta), len(tb))):
        x = ta[i] if i < len(ta) else (0, 0)
        y = tb[i] if i < len(tb) else (0, 0)
        if x == y:
            continue
        if x[0] != y[0]:                              # a letter suffix ("1.1.1k") outranks a missing/numeric part
            return 1 if x[0] == 1 else -1
        return -1 if x < y else 1
    return 0


def _vulnerable(ver: str, ranges) -> str | None:
    for intro, fixed in ranges:
        if version_cmp(ver, intro) >= 0 and version_cmp(ver, fixed) < 0:
            return fixed
    return None


# ── inventory from the stored image config ──────────────────────────────────
_BASE_FROM_NAME = re.compile(r"(?:^|/)(python|node|nodejs|alpine|debian|ubuntu)(?::|$)")
_APK = re.compile(r"\bapk\s+(?:--?\S+\s+)*add\s+(.*?)(?:&&|;|$)")
_APT = re.compile(r"\bapt(?:-get)?\s+(?:-\S+\s+)*install\s+(.*?)(?:&&|;|$)")
_PIP = re.compile(r"\bpip3?\s+(?:--?\S+\s+)*install\s+(.*?)(?:&&|;|$)")
_NPM = re.compile(r"\bnpm\s+(?:i|install|add)\s+(.*?)(?:&&|;|$)")
_ENVVER = {"PYTHON_VERSION": "python", "NODE_VERSION": "node", "GOLANG_VERSION": "go", "JAVA_VERSION": "java"}


def _pairs(blob: str, sep: str):
    for tok in blob.split():
        if tok.startswith("-") or sep not in tok:
            continue
        name, _, ver = tok.partition(sep)
        ver = ver.lstrip("=")
        if name and ver and re.match(r"^[A-Za-z0-9_.\-]+$", name) and re.match(r"^[0-9][\w.+~:\-]*$", ver):
            yield name, ver


def parse_base(repo: str, tag: str, config: dict | None = None) -> tuple[str, str] | None:
    """(product, version) of the image's base from labels, else the repository/tag name."""
    labels = ((config or {}).get("config") or {}).get("Labels") or {}
    for hint in (labels.get("vyomi.base"), labels.get("org.opencontainers.image.base.name"), f"{repo}:{tag}"):
        m = _BASE_FROM_NAME.search(str(hint or ""))
        if m:
            prod = _PRODUCT_ALIASES.get(m.group(1), m.group(1))
            ver = str(hint).split(":", 1)[1] if ":" in str(hint) else ""
            vm = re.match(r"(\d+(?:\.\d+)*)", ver)
            return prod, (vm.group(1) if vm else "")
    return None


def inventory_from_config(config: dict | None, repo: str = "", tag: str = "") -> dict:
    """{base, packages:[{name,version,eco,source}], source} — everything read from the stored config blob."""
    config = config or {}
    pk, seen = [], set()

    def add(name, ver, eco, src):
        k = (eco, name.lower(), ver)
        if k not in seen:
            seen.add(k)
            pk.append({"name": name, "version": ver, "eco": eco, "source": src})

    labels = (config.get("config") or {}).get("Labels") or {}
    sbom = labels.get("vyomi.sbom")
    explicit = False
    if sbom:
        try:
            for p in json.loads(sbom):
                add(str(p["name"]), str(p["version"]), str(p.get("eco") or p.get("type") or "os"), "sbom-label")
            explicit = True
        except Exception:
            pass
    for h in config.get("history") or []:
        cmd = str(h.get("created_by") or "")
        for rx, sep, eco in ((_APK, "=", "os"), (_APT, "=", "os"), (_PIP, "==", "pypi"), (_NPM, "@", "npm")):
            for m in rx.finditer(cmd):
                for name, ver in _pairs(m.group(1), sep):
                    add(name, ver, eco, "history")
    for e in (config.get("config") or {}).get("Env") or []:
        k, _, v = str(e).partition("=")
        if k in _ENVVER and v:
            add(_ENVVER[k], v, "runtime", "env")
    base = parse_base(repo, tag, config)
    return {"base": {"product": base[0], "version": base[1]} if base else None, "packages": pk,
            "source": "sbom-label" if explicit else ("config-history" if pk else "base-image-only")}


# ── the scan ────────────────────────────────────────────────────────────────
def scan_inventory(inv: dict, today: datetime.date | None = None) -> dict:
    today = today or datetime.date.today()
    findings = []
    for p in inv.get("packages") or []:
        for adv in ADVISORIES:
            if p["name"].lower() not in adv["pkgs"] or adv["eco"] != p["eco"] and not (adv["eco"] == "os" and p["eco"] == "os"):
                continue
            fixed = _vulnerable(p["version"], adv["ranges"])
            if fixed is not None:
                findings.append({"vulnerabilityId": adv["id"], "package": p["name"], "installedVersion": p["version"],
                                 "fixedVersion": fixed, "severity": adv["severity"], "cvss": adv["cvss"], "title": adv["title"],
                                 "ecosystem": p["eco"], "source": p.get("source", "")})
    eol = []
    comps = [(inv["base"]["product"], inv["base"]["version"])] if inv.get("base") else []
    comps += [(p["name"], p["version"]) for p in inv.get("packages") or [] if p["eco"] == "runtime"]
    for prod, ver in comps:
        prod = _PRODUCT_ALIASES.get(prod, prod)
        for cycle, date in EOL.get(prod, []):
            if ver and (ver == cycle or ver.startswith(cycle + ".")) and datetime.date.fromisoformat(date) < today:
                if not any(e["product"] == prod and e["cycle"] == cycle for e in eol):
                    eol.append({"product": prod, "version": ver, "cycle": cycle, "endOfLife": date})
                break
    findings.sort(key=lambda f: (SEV_ORDER.index(f["severity"]), -f["cvss"], f["vulnerabilityId"], f["package"]))
    return {"engine": ENGINE_ADVISORY, "advisorySnapshot": SNAPSHOT, "advisoryCount": len(ADVISORIES),
            "findings": findings, "endOfLife": eol, "inventory": inv, "summary": summarize(findings, eol)}


def summarize(findings, eol=()) -> dict:
    by = {s: 0 for s in SEV_ORDER[:4]}
    for f in findings:
        by[f["severity"]] = by.get(f["severity"], 0) + 1
    return {"total": len(findings), "bySeverity": by, "endOfLifeComponents": len(list(eol))}


def scan_image(config: dict | None, repo: str = "", tag: str = "", trivy_report: dict | None = None,
               today: datetime.date | None = None) -> dict:
    """Scan one image from its config blob. A parsed Trivy report (offline appliance) takes over."""
    base = scan_inventory(inventory_from_config(config, repo, tag), today)
    if trivy_report:
        f = trivy_report["findings"]
        base.update({"engine": "trivy", "trivyVersion": trivy_report.get("trivyVersion", ""), "findings": f,
                     "summary": summarize(f, base["endOfLife"])})
    return base


def parse_trivy_report(report: dict) -> dict:
    """Trivy `--format json` (SchemaVersion 2) -> the finding shape above."""
    out = []
    for res in report.get("Results") or []:
        eco = {"pip": "pypi", "python-pkg": "pypi", "npm": "npm", "node-pkg": "npm", "jar": "maven", "pom": "maven"}.get(res.get("Type", ""), "os")
        for v in res.get("Vulnerabilities") or []:
            cv = 0.0
            for src in (v.get("CVSS") or {}).values():
                cv = max(cv, float(src.get("V3Score") or 0))
            out.append({"vulnerabilityId": v.get("VulnerabilityID", ""), "package": v.get("PkgName", ""),
                        "installedVersion": v.get("InstalledVersion", ""), "fixedVersion": v.get("FixedVersion", ""),
                        "severity": v.get("Severity", "UNKNOWN"), "cvss": cv, "title": v.get("Title") or v.get("Description", "")[:120],
                        "ecosystem": eco, "source": "trivy"})
    out.sort(key=lambda f: (SEV_ORDER.index(f["severity"]) if f["severity"] in SEV_ORDER else 4, -f["cvss"], f["vulnerabilityId"]))
    return {"findings": out, "trivyVersion": (report.get("Metadata") or {}).get("TrivyVersion", "")}


def finding_id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


# ── registry walkers ────────────────────────────────────────────────────────
def _config_of_manifest(body, get_blob):
    """The image config JSON of an OCI/Docker v2 image manifest (None for indexes / unreadable)."""
    try:
        man = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
        digest = (man.get("config") or {}).get("digest")
        if not digest:
            return None
        blob = get_blob(digest)
        if blob is None:
            return None
        return json.loads(blob.decode("utf-8") if isinstance(blob, (bytes, bytearray)) else blob)
    except Exception:
        return None


def scan_acr_store(store, trivy_reports: dict | None = None) -> list:
    """Every tagged image in an Azure Container Registry store (core/azure_acr_core.AcrRegistryStore) ->
    [{repo, tag, digest, scan}]. Reads each image's stored config blob; layers are never unpacked."""
    out = []
    for repo_name, repo in sorted((getattr(store, "repos", None) or {}).items()):
        for tag, t in sorted((repo.get("tags") or {}).items()):
            man = (repo.get("manifests") or {}).get(t.get("digest"))
            if not man:
                continue
            cfg = _config_of_manifest(man.get("body") or b"", lambda d, r=repo: (r.get("blobs") or {}).get(d))
            out.append({"repo": repo_name, "tag": tag, "digest": t["digest"],
                        "scan": scan_image(cfg, repo_name, tag, (trivy_reports or {}).get(t["digest"]))})
    return out

#!/usr/bin/env python3
"""Generate the IAM permission catalog for the services Vyomi simulates (design: docs/architecture/v4.0/IAM-FAITHFUL-DESIGN.md).

    python3 scripts/gen_iam_catalog.py aws          # fetch AWS Service Reference for the in-scope prefixes
    python3 scripts/gen_iam_catalog.py aws --offline-check   # validate the committed files only (no network; used by tests)

Permission IDs are copied VERBATIM from the vendor source (rule: catalog IDs are read-only; Vyomi data lives in the `vyomi` block that
the engine adds at load time, never in the ID). Output: core/iam_catalog/<cloud>/<service>.json, deterministic (sorted, no timestamps)
so a refresh shows up as a reviewable diff.

AWS source: https://servicereference.us-east-1.amazonaws.com/ (official, machine-readable: actions, access levels, resource types,
condition keys and the API-operation -> authorized-action map that drives the request->permission contract)."""
import json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AWS_INDEX = "https://servicereference.us-east-1.amazonaws.com/"

# IAM service prefixes of the AWS services in the v4 console registry (consoles/src/aws/services/registry.js) and the cross-service
# prefixes their policies use. Add a prefix when a service is added (appliance rule 13 / IAM onboarding gate).
AWS_PREFIXES = ["s3", "dynamodb", "ec2", "ecr", "eks", "lambda", "rds", "apigateway", "execute-api", "iam", "sts", "kms",
                "secretsmanager", "sqs", "sns", "events", "logs", "cloudwatch", "cloudformation", "bedrock", "bedrock-agentcore",
                "ssm", "states", "kinesis", "redshift", "securityhub", "ce", "imagebuilder", "networkmanager", "backup",
                "elasticloadbalancing", "route53", "cognito-idp", "wafv2", "cloudtrail", "organizations", "tag"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "vyomi-iam-catalog"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _level(p):
    if p.get("IsPermissionManagement"): return "permissions"
    if p.get("IsTaggingOnly"): return "tagging"
    if p.get("IsList"): return "list"
    if p.get("IsWrite"): return "write"
    return "read"


def aws_service(entry):
    d = _get(entry["url"])
    acts = {}
    for a in d.get("Actions", []):
        p = (a.get("Annotations") or {}).get("Properties", {})
        acts[a["Name"]] = {"l": _level(p), "r": sorted({r["Name"] for r in a.get("Resources", [])}),
                           "k": sorted(a.get("ActionConditionKeys", [])), **({"d": 1} if p.get("IsDataPlane") else {})}
    ops = {}
    for o in d.get("Operations", []):
        names = sorted({x["Name"] for x in o.get("AuthorizedActions", []) if x.get("Service") == d["Name"]})
        if names: ops[o["Name"]] = names
    return {"cloud": "aws", "service": d["Name"], "name": d.get("ServiceName", ""), "version": d.get("Version", ""),
            "actions": dict(sorted(acts.items())),
            "resources": {r["Name"]: sorted(r.get("ARNFormats", [])) for r in sorted(d.get("Resources", []), key=lambda r: r["Name"])},
            "conditionKeys": {k["Name"]: (k.get("Types") or [""])[0] for k in sorted(d.get("ConditionKeys", []), key=lambda k: k["Name"])},
            "operations": dict(sorted(ops.items()))}


def gen_aws():
    idx = {e["service"]: e for e in _get(AWS_INDEX)}
    out = os.path.join(ROOT, "core", "iam_catalog", "aws"); os.makedirs(out, exist_ok=True)
    total = 0
    for pre in AWS_PREFIXES:
        if pre not in idx:
            print("  !! not in the AWS Service Reference:", pre); continue
        doc = aws_service(idx[pre]); total += len(doc["actions"])
        with open(os.path.join(out, pre + ".json"), "w") as f:
            json.dump(doc, f, indent=0, sort_keys=False, separators=(",", ":")); f.write("\n")
        print(f"  {pre:22} {len(doc['actions']):5} actions {len(doc['operations']):5} operations")
    print("aws total actions:", total)


AZ_RAW = "https://raw.githubusercontent.com/MicrosoftDocs/azure-docs/main/articles/role-based-access-control/permissions/"
AZ_LIST = "https://api.github.com/repos/MicrosoftDocs/azure-docs/contents/articles/role-based-access-control/permissions"
# Providers every Azure estate uses beyond the console registry's resource types (identity, policy, diagnostics, networking edge).
AZ_EXTRA = ["Microsoft.Authorization", "Microsoft.Resources", "Microsoft.ManagedIdentity", "Microsoft.Insights", "Microsoft.Security",
            "Microsoft.CognitiveServices", "Microsoft.MachineLearningServices", "Microsoft.Network", "Microsoft.Compute", "Microsoft.Storage",
            "Microsoft.KeyVault", "Microsoft.Sql", "Microsoft.DocumentDB", "Microsoft.Web", "Microsoft.ContainerService",
            "Microsoft.ContainerRegistry", "Microsoft.ServiceBus", "Microsoft.EventGrid", "Microsoft.ApiManagement",
            "Microsoft.OperationalInsights", "Microsoft.Cdn", "Microsoft.App", "Microsoft.Search", "Microsoft.StreamAnalytics",
            "Microsoft.AppConfiguration", "Microsoft.RecoveryServices", "Microsoft.Management"]


def az_providers():
    import re
    reg = open(os.path.join(ROOT, "consoles", "src", "azure", "services", "registry.js")).read()
    prov = set(AZ_EXTRA) | {t.split("/")[0] for t in re.findall(r'type:\s*"(Microsoft\.[A-Za-z.]+)', reg)}
    return sorted(prov)


def gen_azure():
    import re
    want = {p.lower(): p for p in az_providers()}
    files = [x["name"] for x in _get(AZ_LIST) if x["name"].endswith(".md") and x["name"] != "index.md"]
    got = {}
    for fn in files:
        prov, kind = None, None
        for line in _az_text(AZ_RAW + fn).splitlines():
            m = re.match(r"## (microsoft\.[a-z0-9.]+)\s*$", line, re.I)
            if m: prov, kind = want.get(m.group(1).lower(), m.group(1)), None; continue
            if re.match(r"> \| \**(Data)?Action\** \|", line): kind = "data" if "DataAction" in line else "action"; continue
            r = re.match(r"> \| `([^`]+)` \| (.*?) \|\s*$", line)
            if r and prov and prov.lower() in want and kind:
                got.setdefault(prov, {"actions": {}, "dataActions": {}})["dataActions" if kind == "data" else "actions"][r.group(1)] = r.group(2)
    out = os.path.join(ROOT, "core", "iam_catalog", "azure"); os.makedirs(out, exist_ok=True)
    total = 0
    for low, prov in sorted(want.items()):
        if prov not in got and not any(k.lower() == low for k in got):
            print("  !! not in the Azure permissions reference:", prov); continue
        key = next(k for k in got if k.lower() == low); d = got[key]; n = len(d["actions"]) + len(d["dataActions"]); total += n
        doc = {"cloud": "azure", "service": key, "actions": dict(sorted(d["actions"].items())), "dataActions": dict(sorted(d["dataActions"].items()))}
        with open(os.path.join(out, key + ".json"), "w") as f:
            json.dump(doc, f, indent=0, separators=(",", ":")); f.write("\n")
        print(f"  {key:38} {len(d['actions']):5} actions {len(d['dataActions']):5} dataActions")
    print("azure total operations:", total)


GCP_BASE = "https://cloud.google.com/iam/docs/roles-permissions/"
GCP_SUPPORT = "https://cloud.google.com/iam/docs/custom-roles-permissions-support"
# Page slugs of the GCP products in the v4 console registry (consoles/src/gcp/services/registry.js) plus cross-service ones. The generator
# now crawls EVERY page of Google's published predefined-roles reference (index = GCP_BASE minus the slash); this list is the floor
# that must stay a subset (tests assert it) so a registry service can never silently drop out.
GCP_SLUGS = ["storage", "compute", "container", "cloudsql", "firestore", "redis", "run", "cloudfunctions", "pubsub",
             "cloudscheduler", "eventarc", "apigateway", "iam", "resourcemanager", "artifactregistry", "clouddeploy", "config", "backupdr",
             "cloudbuild", "aiplatform", "monitoring", "logging", "cloudkms", "secretmanager", "firebaseauth", "dns", "serviceusage",
             "servicenetworking", "securitycenter", "orgpolicy", "iap", "vpcaccess", "cloudtasks", "bigquery", "workflows",
             # added by WP gcp-coverage: Binary Authorization, Marketplace (consumer procurement + offer catalog), Cloud Hub (Service Health + App Hub)
             "binaryauthorization", "consumerprocurement", "commerceoffercatalog", "servicehealth", "apphub", "config"]
# Per-permission stage = the "Custom roles support level" of Google's published permission list (same data the public
# iam.googleapis.com/v1/permissions:queryTestablePermissions returns as customRolesSupportLevel; absent there == SUPPORTED).
# Real console labels: SUPPORTED -> "Supported", TESTING -> "Testing", NOT_SUPPORTED -> "Not applicable".
GCP_STAGES = ("SUPPORTED", "TESTING", "NOT_SUPPORTED")


def _az_text(url):
    """Fetch text; when VYOMI_IAM_SRC_CACHE is set, serve/store pages under that directory (re-runs and review without the network)."""
    import re
    cd = os.environ.get("VYOMI_IAM_SRC_CACHE")
    cp = os.path.join(cd, re.sub(r"[^A-Za-z0-9]+", "_", url)) if cd else None
    if cp and os.path.exists(cp):
        return open(cp, encoding="utf-8").read()
    req = urllib.request.Request(url, headers={"User-Agent": "vyomi-iam-catalog"})
    with urllib.request.urlopen(req, timeout=90) as r:
        t = r.read().decode()
    if cp:
        os.makedirs(cd, exist_ok=True); open(cp, "w", encoding="utf-8").write(t)
    return t


def gcp_all_slugs():
    import re
    t = _az_text(GCP_BASE.rstrip("/"))
    return sorted(set(re.findall(r'href="/iam/docs/roles-permissions/([a-z0-9-]+)"', t)))


def gcp_support_levels():
    """{permission: SUPPORTED|TESTING|NOT_SUPPORTED} from the published permission list."""
    import re
    t = _az_text(GCP_SUPPORT)
    out = {}
    for m in re.finditer(r'<td class="column1-class"><code[^>]*>([A-Za-z0-9_.]+)</code></td>\s*<td class="column2-class"><code[^>]*>([A-Z_]+)</code>', t):
        assert m.group(2) in GCP_STAGES, m.group(0)
        out[m.group(1)] = m.group(2)
    return out


def gcp_service(slug):
    import re, html
    t = _az_text(GCP_BASE + slug).replace("<wbr>", "")
    perms = {}
    for m in re.finditer(r'<h4 class="permission-name[^"]*" id="([^"]+)"', t):
        perms[m.group(1)] = {}
    roles = {}
    for row in re.split(r"<tr>", t):
        m = re.search(r'<h4 class="role-title[^"]*" id="([^"]+)"[^>]*>([^<]*)</h4>\s*<p[^>]*>\(<code[^>]*>(roles/[^<]+)</code>\)', row)
        if not m:
            continue
        # description span is `role-description custom` (Google-written text) or plain `role-description`; may hold several <p>
        d = re.search(r'<span class="role-description(?: custom)?">(.*?)</span>', row, re.S)
        td = row.split('<td class="role-permissions">', 1)[-1]
        plist = sorted({x for x in re.findall(r"<code[^>]*>([a-z][A-Za-z0-9]*\.[A-Za-z0-9.]*[A-Za-z0-9])</code>", td)})
        desc = html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", "", re.sub(r"</(p|li|ul)>", " ", d.group(1))))).strip() if d else ""
        roles[m.group(3)] = {"title": html.unescape(m.group(2)).strip(), "desc": desc, "permissions": plist}
    for r in roles.values():
        for x in r["permissions"]:
            perms.setdefault(x, {})
    return {"cloud": "gcp", "service": slug, "permissions": dict(sorted(perms.items())), "roles": dict(sorted(roles.items()))}


def gen_gcp():
    out = os.path.join(ROOT, "core", "iam_catalog", "gcp"); os.makedirs(out, exist_ok=True)
    slugs = gcp_all_slugs()
    assert set(GCP_SLUGS) <= set(slugs), set(GCP_SLUGS) - set(slugs)
    docs = {}
    for slug in slugs:
        try:
            docs[slug] = gcp_service(slug)
        except Exception as e:
            print("  !! no page for", slug, e)
    # a role is listed on exactly one shard (its first page, sorted); later pages that re-list it keep only the permission cross-refs
    seen = set()
    for slug in sorted(docs):
        for rid in list(docs[slug]["roles"]):
            if rid in seen: del docs[slug]["roles"][rid]
            else: seen.add(rid)
    levels = gcp_support_levels()
    # permissions in the published support list that no roles page mentions: home them on the shard that owns their service prefix
    owner = {}
    for slug, d in docs.items():
        for p in d["permissions"]: owner.setdefault(p.split(".")[0], slug)
    have = {p for d in docs.values() for p in d["permissions"]}
    orphan = sorted(set(levels) - have)
    for p in orphan:
        pre = p.split(".")[0]
        slug = owner.get(pre) or (pre if pre in docs else None)
        if slug is None:
            slug = pre; docs[slug] = {"cloud": "gcp", "service": slug, "permissions": {}, "roles": {}}
        docs[slug]["permissions"][p] = {}
    tp = tr = 0
    for slug, doc in sorted(docs.items()):
        doc["permissions"] = {p: ({"stage": levels[p]} if p in levels else {}) for p in sorted(doc["permissions"])}
        tp += len(doc["permissions"]); tr += len(doc["roles"])
        with open(os.path.join(out, slug + ".json"), "w") as f:
            json.dump(doc, f, indent=0, separators=(",", ":")); f.write("\n")
    for fn in os.listdir(out):                      # drop shards that no longer exist upstream
        if fn.endswith(".json") and not fn.startswith("_") and fn[:-5] not in docs: os.remove(os.path.join(out, fn))
    idx = {"cloud": "gcp", "kind": "index", "stages": list(GCP_STAGES),
           "services": {s: {"permissions": len(d["permissions"]), "roles": len(d["roles"])} for s, d in sorted(docs.items())}}
    with open(os.path.join(out, "_index.json"), "w") as f:
        json.dump(idx, f, indent=0, separators=(",", ":")); f.write("\n")
    allp = {p for d in docs.values() for p in d["permissions"]}
    from collections import Counter
    print("gcp shards:", len(docs), "permissions:", len(allp), "(entries", tp, ") roles:", tr,
          "roles with description:", sum(1 for d in docs.values() for r in d["roles"].values() if r["desc"]),
          "stages:", dict(Counter(levels.get(p, "(none)") for p in allp)), "orphans homed:", len(orphan))

AZ_ROLES_RAW = "https://raw.githubusercontent.com/MicrosoftDocs/azure-docs/main/articles/role-based-access-control/built-in-roles/"
AZ_ROLE_CATEGORIES = ["privileged", "general", "compute", "networking", "storage", "web-and-mobile", "containers", "databases", "analytics",
                      "ai-machine-learning", "internet-of-things", "integration", "identity", "security", "devops", "migration", "monitor",
                      "management-and-governance", "hybrid-multicloud"]


def gen_azure_roles():
    """Azure built-in role definitions (verbatim JSON blocks from the per-category built-in-roles pages) -> core/iam_catalog/azure/_roles.json."""
    import re
    roles = {}
    for cat in AZ_ROLE_CATEGORIES:
        for blk in re.findall(r"```json\n(.*?)\n```", _az_text(AZ_ROLES_RAW + cat + ".md"), re.S):
            try: j = json.loads(blk)
            except ValueError: continue
            if j.get("type") != "Microsoft.Authorization/roleDefinitions" or not j.get("roleName"): continue
            perms = j.get("permissions") or [{}]
            g = lambda k: [x for p in perms for x in p.get(k, [])]
            roles[j["name"]] = {"id": j["name"], "roleName": j["roleName"], "description": j.get("description", ""), "category": cat,
                                "actions": g("actions"), "notActions": g("notActions"), "dataActions": g("dataActions"),
                                "notDataActions": g("notDataActions"), "assignableScopes": j.get("assignableScopes", [])}
    doc = {"cloud": "azure", "kind": "roles", "roles": dict(sorted(roles.items(), key=lambda kv: kv[1]["roleName"].lower()))}
    with open(os.path.join(ROOT, "core", "iam_catalog", "azure", "_roles.json"), "w") as f:
        json.dump(doc, f, indent=0, separators=(",", ":")); f.write("\n")
    print("azure built-in roles:", len(roles))


def check(cloud):
    d = os.path.join(ROOT, "core", "iam_catalog", cloud); n = 0
    for f in sorted(x for x in os.listdir(d) if not x.startswith("_")):
        j = json.load(open(os.path.join(d, f))); assert j["cloud"] == cloud and (j.get("actions") or j.get("dataActions") or j.get("permissions")), f
        n += len(j.get("actions", {})) + len(j.get("dataActions", {})) + len(j.get("permissions", {}))
    print(cloud, "catalog ok:", n, "permissions")


if __name__ == "__main__":
    cloud = sys.argv[1] if len(sys.argv) > 1 else "aws"
    if "--offline-check" in sys.argv: check(cloud)
    elif cloud == "aws": gen_aws()
    elif cloud == "azure" and "roles" in sys.argv[2:]: gen_azure_roles()
    elif cloud == "azure": gen_azure()
    elif cloud == "gcp": gen_gcp()
    else: sys.exit(f"{cloud}: generator not written yet (see the design doc, phase 0)")

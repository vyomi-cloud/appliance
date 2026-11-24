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


def _az_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "vyomi-iam-catalog"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


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
# Page slugs of the GCP products in the v4 console registry (consoles/src/gcp/services/registry.js) plus cross-service ones.
GCP_SLUGS = ["storage", "compute", "container", "cloudsql", "firestore", "redis", "run", "cloudfunctions", "pubsub",
             "cloudscheduler", "eventarc", "apigateway", "iam", "resourcemanager", "artifactregistry", "clouddeploy", "backupdr",
             "cloudbuild", "aiplatform", "monitoring", "logging", "cloudkms", "secretmanager", "firebaseauth", "dns", "serviceusage",
             "servicenetworking", "securitycenter", "orgpolicy", "iap", "vpcaccess", "cloudtasks", "bigquery", "workflows",
             # added by WP gcp-coverage: Binary Authorization, Marketplace (consumer procurement + offer catalog), Cloud Hub (Service Health + App Hub)
             "binaryauthorization", "consumerprocurement", "commerceoffercatalog", "servicehealth", "apphub"]


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
        d = re.search(r'<span class="role-description custom">\s*<p>\s*(.*?)\s*</p>', row, re.S)
        td = row.split('<td class="role-permissions">', 1)[-1]
        plist = sorted({x for x in re.findall(r"<code[^>]*>([a-z][A-Za-z0-9]*\.[A-Za-z0-9.]*[A-Za-z0-9])</code>", td)})
        roles[m.group(3)] = {"title": html.unescape(m.group(2)).strip(), "desc": html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", "", d.group(1)))) if d else "",
                             "permissions": plist}
    for r in roles.values():
        for x in r["permissions"]:
            perms.setdefault(x, {})
    return {"cloud": "gcp", "service": slug, "permissions": dict(sorted(perms.items())), "roles": dict(sorted(roles.items()))}


def gen_gcp():
    out = os.path.join(ROOT, "core", "iam_catalog", "gcp"); os.makedirs(out, exist_ok=True)
    tp = tr = 0
    for slug in GCP_SLUGS:
        try:
            doc = gcp_service(slug)
        except Exception as e:
            print("  !! no page for", slug, e); continue
        tp += len(doc["permissions"]); tr += len(doc["roles"])
        with open(os.path.join(out, slug + ".json"), "w") as f:
            json.dump(doc, f, indent=0, separators=(",", ":")); f.write("\n")
        print(f"  {slug:20} {len(doc['permissions']):5} permissions {len(doc['roles']):4} roles")
    print("gcp total permissions:", tp, "roles:", tr)

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

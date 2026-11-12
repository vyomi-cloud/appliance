#!/usr/bin/env python3
"""Generate the Nano consoles' "API reference" + "SDK & CLI usage" data (wasm/docs/).

Deterministic: same inputs -> byte-identical output (sorted keys, no timestamps).

Inputs
  * core/capabilities/<cloud>/*.json   the registry (console features, levels, declared API ops)
  * consoles/src/<cloud>/services/registry.js   the console service list (ids/titles/categories)
  * botocore service models            AWS operations, shapes, protocol, CLI/boto3/JS names
  * googleapiclient discovery docs     GCP methods, params, schemas
  * core/aws_wire_router.py            PROBED, not read: every operation is sent to the real Nano
                                       router (the same code the browser runs) and classified
                                       wired / not wired from the answer, so the reference only
                                       lists operations that really answer.
  * ARM resource types the router reports as simulated (Azure)

Output
  wasm/docs/index.json           service list + coverage per cloud
  wasm/docs/<cloud>/<id>.json    one service reference (ops, examples, registry features)
  wasm/docs/coverage.json        coverage / gap report

Dev dependency (generation time only; outputs are committed):
  pip install botocore google-api-python-client
Run:  python3 scripts/gen_nano_docs.py [--check]
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import OrderedDict, defaultdict
from urllib.parse import parse_qsl, urlencode

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "wasm", "docs")

import botocore  # noqa: E402
import botocore.serialize  # noqa: E402
import botocore.session  # noqa: E402
from core.aws_wire_router import AwsWireRouter, _SIGNING  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import nano_docs_extras as X  # noqa: E402

# ───────────────────────────── helpers ─────────────────────────────
UNWIRED = re.compile(
    r"Unsupported|No route|UnknownOperation|InvalidAction|not implemented|NotImplemented|Unknown path|"
    r"Unknown operation|not simulated|UnrecognizedOperation|ResourceTypeNotSupported|Not Found Handler|"
    r"unknown route|is not supported by|unrecognized", re.I)


def kebab(s):
    return re.sub(r"(?<!^)(?=[A-Z][a-z])|(?<=[a-z0-9])(?=[A-Z])", "-", s).lower()


def snake(s):
    return kebab(s).replace("-", "_")


def clean(html, n=170):
    t = re.sub(r"<[^>]+>", " ", html or "")
    t = re.sub(r"&[a-z]+;", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    t = m.group(1) if m else t
    return t[: n - 1] + "…" if len(t) > n else t


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")


def load_registry(cloud):
    """{service_id: [feature,...]} from core/capabilities/<cloud>/*.json."""
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "core", "capabilities", cloud, "*.json"))):
        d = json.load(open(f))
        feats = []
        for k, v in d.items():
            if k.startswith("$"):
                continue
            feats.append({"id": k, "title": v.get("title", ""), "nano": (v.get("level") or {}).get("nano", ""),
                          "api": v.get("api", []), "limits": v.get("limitations", [])})
        out[os.path.basename(f)[:-5]] = feats
    return out


def console_services(cloud):
    """[(id,title,category)] parsed from the console registry.js (single source for the service list)."""
    src = open(os.path.join(ROOT, "consoles", "src", cloud, "services", "registry.js")).read()
    res = []
    for m in re.finditer(r'\{\s*id:\s*"([^"]+)"(?:,\s*icon:\s*"[^"]*")?,\s*title:\s*"([^"]+)"[^}]*?category:\s*"([^"]+)"', src):
        res.append((m.group(1), m.group(2), m.group(3)))
    return res


# ───────────────────────────── AWS ─────────────────────────────
def sample(shape, name="x", depth=0, all_members=False):
    t = shape.type_name
    if t == "structure":
        if depth > 3:
            return {}
        req = set(shape.required_members)
        return {k: sample(v, k, depth + 1, all_members) for k, v in shape.members.items() if k in req or all_members}
    if t == "list":
        return [sample(shape.member, name, depth + 1, all_members)] if depth < 4 else []
    if t == "map":
        return {"key": sample(shape.value, name, depth + 1, all_members)}
    if t == "string":
        if shape.enum:
            return shape.enum[0]
        return "my-" + kebab(name)
    if t in ("integer", "long"):
        return int(shape.metadata.get("min", 1) or 1)
    if t in ("float", "double"):
        return 1.0
    if t == "boolean":
        return True
    if t == "timestamp":
        return "2026-01-01T00:00:00Z"
    if t == "blob":
        return "ZXhhbXBsZQ=="
    return "x"


def probe_sample(shape, name="x", depth=0):
    """Same as sample() but wire-safe (timestamps numeric, blobs bytes) for the serializer."""
    t = shape.type_name
    if t == "timestamp":
        return 1767225600
    if t == "blob":
        return b"data"
    if t == "structure":
        if depth > 3:
            return {}
        req = set(shape.required_members)
        return {k: probe_sample(v, k, depth + 1) for k, v in shape.members.items() if k in req}
    if t == "list":
        return [probe_sample(shape.member, name, depth + 1)] if depth < 4 else []
    if t == "map":
        return {"key": probe_sample(shape.value, name, depth + 1)}
    return sample(shape, name, depth)


AUTH = "AWS4-HMAC-SHA256 Credential=test/20260101/us-east-1/%s/aws4_request, SignedHeaders=host, Signature=x"
# botocore service whose requests cannot be addressed through a path-style single endpoint (host-prefix routed)
NOT_PROBEABLE = {}

# console service -> botocore services that document it
AWS_MAP = {
    "apigateway": ["apigateway", "apigatewayv2"],
    "backup": ["backup"],
    "bedrock": ["bedrock", "bedrock-runtime", "bedrock-agent", "bedrock-agent-runtime", "bedrock-agentcore", "bedrock-agentcore-control",
                "bedrock-data-automation", "bedrock-data-automation-runtime"],
    "cloudformation": ["cloudformation"],
    "cloudwatch": ["cloudwatch", "logs"],
    "cost-explorer": ["ce", "savingsplans"],
    "dynamodb": ["dynamodb", "dynamodbstreams", "dax", "application-autoscaling"],
    "ec2": ["ec2", "autoscaling", "elbv2", "elb", "dlm", "rbin", "mgn"],
    "ecr": ["ecr"],
    "eventbridge": ["events", "scheduler", "pipes", "schemas"],
    "iam": ["iam", "sts", "organizations", "ram"],
    "imagebuilder": ["imagebuilder"],
    "kinesis": ["kinesis"],
    "kms": ["kms"],
    "lambda": ["lambda"],
    "networkmanager": ["networkmanager"],
    "rds": ["rds", "rds-data", "docdb", "neptune", "dms", "glue"],
    "redshift": ["redshift", "redshift-data"],
    "s3": ["s3", "s3control", "s3tables", "s3vectors", "s3files", "cloudfront", "cloudtrail", "fsx"],
    "secretsmanager": ["secretsmanager"],
    "securityhub": ["securityhub", "guardduty", "inspector2", "codeconnections", "codestar-connections"],
    "sns": ["sns"],
    "sqs": ["sqs"],
    "ssm": ["ssm"],
    "states": ["stepfunctions"],
    "vpc": ["vpc-lattice", "network-firewall", "route53resolver"],
}
AWS_EXTRA_TITLE = {"marketplace": "AWS Marketplace"}


def gen_aws():
    sess = botocore.session.get_session()
    services = {}
    for sname in sorted(sess.get_available_services()):
        m = sess.get_service_model(sname)
        sign = m.metadata.get("signingName") or m.metadata.get("endpointPrefix")
        if sign not in _SIGNING:
            continue
        sid = m.metadata.get("serviceId", sname)
        protocol = m.protocol
        wire_style = {"json": "JSON-RPC (X-Amz-Target)", "query": "Query (Action=…)", "ec2": "EC2 Query (Action=…)",
                      "rest-json": "REST + JSON", "rest-xml": "REST + XML", "smithy-rpc-v2-cbor": "Smithy RPC v2 (CBOR)"}.get(protocol, protocol)
        ser = botocore.serialize.create_serializer(protocol, False)
        router = AwsWireRouter()
        ops, unwired = [], {}
        if sname in NOT_PROBEABLE:
            unwired = {n: NOT_PROBEABLE[sname] for n in m.operation_names}
        else:
            for on in sorted(m.operation_names):
                op = m.operation_model(on)
                try:
                    params = probe_sample(op.input_shape) if op.input_shape else {}
                    req = ser.serialize_to_request(params, op)
                    h = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in req["headers"].items()}
                    h["host"] = "x"
                    h["x-amz-account-id"] = "123456789012"
                    h["authorization"] = AUTH % sign
                    path = req["url_path"]
                    q = {}
                    if req.get("query_string"):
                        path += "?" + urlencode(req["query_string"], doseq=True)
                        q = dict(parse_qsl(path.split("?", 1)[1]))
                    b0 = req["body"]
                    body = urlencode(b0, doseq=True).encode() if isinstance(b0, dict) else (b0 if isinstance(b0, bytes) else str(b0).encode())
                    out = router.handle(req["method"], path, q, h, body)
                except Exception as e:  # noqa: BLE001
                    unwired[on] = "probe error: " + type(e).__name__
                    continue
                b = out["body"][:700].decode("utf8", "replace")
                s3like = sign != "s3" and b.startswith("<?xml") and "<Error><Code>" in b and "ErrorResponse" not in b and "<Errors>" not in b
                if out["status"] == 501 or UNWIRED.search(b) or s3like:
                    unwired[on] = "HTTP %d" % out["status"]
                    continue
                # documented record
                inp = op.input_shape
                outs = op.output_shape
                prm = []
                if inp:
                    req_set = set(inp.required_members)
                    for k, v in sorted(inp.members.items(), key=lambda kv: (kv[0] not in req_set, kv[0])):
                        prm.append([k, v.type_name, 1 if k in req_set else 0])
                http = op.http
                rec = {
                    "n": on, "m": http.get("method", "POST"), "u": http.get("requestUri", "/"),
                    "d": clean(op.documentation), "cli": kebab(on), "py": snake(on),
                    "in": sample(inp, "in") if inp else {},
                    "out": sample(outs, "out", all_members=True) if outs else {},
                    "p": prm[:14],
                }
                if protocol in ("json", "smithy-rpc-v2-cbor"):
                    rec["t"] = (m.metadata.get("targetPrefix", "") + "." + on)
                ops.append(rec)
        # JS client names (AWS SDK v3)
        sid_clean = sid.replace(" ", "")
        services[sname] = {
            "id": sname, "title": m.metadata.get("serviceFullName", sid), "signing": sign, "style": wire_style, "protocol": protocol,
            "version": m.metadata.get("apiVersion", ""), "target": m.metadata.get("targetPrefix", ""),
            "json": m.metadata.get("jsonVersion", ""),
            "cli": sid.lower().replace(" ", "-"), "py_client": sname,
            "js_pkg": "@aws-sdk/client-" + sid.lower().replace(" ", "-"), "js_client": sid_clean + "Client",
            "ops": ops, "total": len(m.operation_names), "wired": len(ops),
            "unwired": sorted(unwired),
        }
    return services


# ───────────────────────────── GCP ─────────────────────────────
GCP_MAP = {   # console service -> [(discovery name, version)]
    "artifacts": [("artifactregistry", "v1")], "backupdr": [("backupdr", "v1")], "cloudbuild": [("cloudbuild", "v1")],
    "clouddeploy": [("clouddeploy", "v1")], "cloudscheduler": [("cloudscheduler", "v1")], "compute": [("compute", "v1")],
    "eventarc": [("eventarc", "v1")], "firestore": [("firestore", "v1")], "datastore": [("datastore", "v1")],
    "functions": [("cloudfunctions", "v2"), ("cloudfunctions", "v1")], "iam-admin": [("iam", "v1"), ("iamcredentials", "v1"), ("sts", "v1")],
    "kms": [("cloudkms", "v1")], "security/kms": [("cloudkms", "v1")], "kubernetes": [("container", "v1")], "logs": [("logging", "v2")],
    "memorystore": [("redis", "v1")], "monitoring": [("monitoring", "v3")], "networking": [("compute", "v1#net"), ("networkmanagement", "v1"), ("dns", "v1")],
    "pubsub": [("pubsub", "v1")], "resource-manager": [("cloudresourcemanager", "v3"), ("cloudresourcemanager", "v1")],
    "run": [("run", "v2")], "secret-manager": [("secretmanager", "v1")], "security/secret-manager": [("secretmanager", "v1")],
    "securitycenter": [("securitycenter", "v1")], "security/scc": [("securitycenter", "v1")], "sql": [("sqladmin", "v1beta4"), ("sqladmin", "v1")],
    "storage": [("storage", "v1")], "vertex-ai": [("aiplatform", "v1"), ("aiplatform", "v1beta1")],
    "security/binauthz": [("binaryauthorization", "v1")], "bigquery": [("bigquery", "v2")], "dns": [("dns", "v1")],
    "trace": [("cloudtrace", "v2"), ("cloudtrace", "v1")],
}
# services with no console page of their own but a real wire on the simulator (id, title, category)
GCP_EXTRA_SERVICES = [("bigquery", "BigQuery", "Analytics"), ("dns", "Cloud DNS", "Networking"), ("trace", "Cloud Trace", "Operations")]
GCLOUD_GROUP = {"pubsub": "pubsub", "secretmanager": "secrets", "cloudkms": "kms", "storage": "storage", "run": "run", "compute": "compute",
                "container": "container", "sqladmin": "sql", "redis": "redis", "cloudscheduler": "scheduler", "artifactregistry": "artifacts",
                "cloudfunctions": "functions", "logging": "logging", "iam": "iam", "cloudbuild": "builds", "eventarc": "eventarc",
                "monitoring": "monitoring", "firestore": "firestore", "dns": "dns", "bigquery": "bigquery", "binaryauthorization": "container binauthz", "aiplatform": "ai", "clouddeploy": "deploy", "cloudresourcemanager": "projects"}
GCP_VAL = {"project": "vyomi-project", "projectId": "vyomi-project", "projectsId": "vyomi-project", "location": "us-central1", "locationsId": "us-central1",
           "zone": "us-central1-a", "region": "us-central1", "bucket": "my-bucket", "object": "my-object", "instance": "my-instance",
           "name": "my-name", "parent": "my-parent"}


def gcp_val(pname):
    return GCP_VAL.get(pname, "my-" + kebab(pname))


def flat_methods(doc):
    out = []

    def walk(res, prefix):
        for mn, md in sorted((res.get("methods") or {}).items()):
            out.append((prefix + [mn], md))
        for rn, rd in sorted((res.get("resources") or {}).items()):
            walk(rd, prefix + [rn])
    walk(doc, [])
    return out


def schema_sample(doc, ref, depth=0, seen=()):
    """Small, readable body: up to 3 scalar fields (+ labels), nested messages left out."""
    sch = (doc.get("schemas") or {}).get(ref) if isinstance(ref, str) else None
    if sch is None:
        return {}
    o = {}
    props = sorted((sch.get("properties") or {}).items())
    pri = [kv for kv in props if kv[0] in ("name", "displayName", "description", "labels")] + [kv for kv in props if kv[0] not in ("name", "displayName", "description", "labels")]
    for k, v in pri:
        if len(o) >= 3:
            break
        if v.get("readOnly") or "$ref" in v:
            continue
        t = v.get("type")
        if t == "array":
            it = v.get("items", {})
            if "$ref" in it:
                continue
            o[k] = ["example"]
        elif t == "object":
            o[k] = {"key": "value"}
        elif t == "boolean":
            o[k] = True
        elif t in ("integer", "number"):
            o[k] = 1
        elif v.get("enum"):
            o[k] = v["enum"][0]
        else:
            o[k] = "example"
    return o


def param_value(pname, pd):
    """Example value for a GCP path/query parameter; resource-name params follow their pattern."""
    pat = pd.get("pattern") or ""
    if pat.startswith("^") and "/" in pat:
        segs = re.sub(r"\[\^/\][+*]", "\x00", pat.strip("^$")).split("/")
        out, prev = [], ""
        for sg in segs:
            if sg == "\x00":
                out.append("vyomi-project" if prev == "projects" else ("us-central1" if prev == "locations" else "my-" + re.sub(r"s$", "", prev)))
            else:
                out.append(sg)
                prev = sg
        return "/".join(out)
    return gcp_val(pname)


def gen_gcp_apis(names):
    """Probe every method of the named discovery docs against the Nano router."""
    from googleapiclient import discovery_cache
    ddir = os.path.join(os.path.dirname(discovery_cache.__file__), "documents")
    res = {}
    NETRES = {"networks", "subnetworks", "firewalls", "firewallPolicies", "routes", "routers", "addresses", "globalAddresses", "forwardingRules",
              "globalForwardingRules", "targetHttpProxies", "targetHttpsProxies", "urlMaps", "backendServices", "healthChecks", "vpnGateways",
              "vpnTunnels", "externalVpnGateways", "interconnects", "interconnectAttachments", "networkEndpointGroups", "securityPolicies", "sslCertificates"}
    for (name, ver) in names:
        netonly = ver.endswith("#net")
        ver = ver.replace("#net", "")
        fp = os.path.join(ddir, "%s.%s.json" % (name, ver))
        if not os.path.exists(fp):
            continue
        doc = json.load(open(fp))
        router = AwsWireRouter()
        router.STRICT_GCP_PROJECT = False
        base = doc.get("servicePath", "")
        ops, unwired = [], []
        for path_ids, md in flat_methods(doc):
            if netonly and not (set(path_ids) & NETRES):
                continue
            mid = md.get("id", ".".join([name] + path_ids))
            tpl = md.get("path", "") or md.get("flatPath", "")
            params = md.get("parameters", {})
            url = tpl
            for pn in re.findall(r"\{\+?([^}]+)\}", tpl):
                pv = param_value(pn, params.get(pn, {}))
                url = re.sub(r"\{\+?%s\}" % re.escape(pn), pv, url)
            if base and not url.startswith(base.rstrip("/")) and not url.startswith("/"):
                url = base + url
            if not url.startswith("/"):
                url = "/" + url
            q = {pn: param_value(pn, pd) for pn, pd in params.items() if pd.get("required") and pd.get("location") == "query"}
            body_ref = (md.get("request") or {}).get("$ref")
            body = json.dumps(schema_sample(doc, body_ref)).encode() if body_ref else b""
            try:
                p2 = url + ("?" + urlencode(q) if q else "")
                out = router.handle(md["httpMethod"], p2, q, {"host": "x", "content-type": "application/json"}, body)
            except Exception as e:  # noqa: BLE001
                unwired.append(mid)
                continue
            b = out["body"][:700].decode("utf8", "replace")
            s3like = b.startswith("<?xml") and "<Error><Code>" in b
            if out["status"] == 501 or UNWIRED.search(b) or s3like:
                unwired.append(mid)
                continue
            prm = []
            for pn in md.get("parameterOrder", []):
                prm.append([pn, params.get(pn, {}).get("location", "path"), params.get(pn, {}).get("type", "string"), 1, param_value(pn, params.get(pn, {}))])
            for pn, pd in sorted(params.items()):
                if pn not in md.get("parameterOrder", []) and pd.get("required"):
                    prm.append([pn, pd.get("location", "query"), pd.get("type", "string"), 1, param_value(pn, pd)])
            resp_ref = (md.get("response") or {}).get("$ref")
            ops.append({
                "n": mid, "m": md["httpMethod"], "u": "/" + tpl.lstrip("/") if not tpl.startswith("/") else tpl,
                "d": clean(md.get("description", "")),
                "p": prm[:12], "in": schema_sample(doc, body_ref) if body_ref else None,
                "out": schema_sample(doc, resp_ref) if resp_ref else {},
                "sdk": ".".join(path_ids[:-1]) + "|" + path_ids[-1],   # googleapiclient resource chain | method
                "ex": url,
            })
        res[name + "." + ver + ("#net" if netonly else "")] = {
            "id": name, "version": ver, "title": doc.get("title", name) + (" (network resources)" if netonly else ""), "root": doc.get("rootUrl", ""), "servicePath": base,
            "ops": ops, "total": len(ops) + len(unwired), "wired": len(ops), "unwired": sorted(unwired),
            "gcloud": GCLOUD_GROUP.get(name, ""),
        }
    return res


# ───────────────────────────── Azure ─────────────────────────────
# ARM type -> (az group, python client, python operations attribute, js package) for the types the console covers.
AZ_SDK = {
    "Microsoft.Compute/virtualMachines": ("vm", "azure.mgmt.compute.ComputeManagementClient", "virtual_machines", "@azure/arm-compute"),
    "Microsoft.Compute/disks": ("disk", "azure.mgmt.compute.ComputeManagementClient", "disks", "@azure/arm-compute"),
    "Microsoft.Storage/storageAccounts": ("storage account", "azure.mgmt.storage.StorageManagementClient", "storage_accounts", "@azure/arm-storage"),
    "Microsoft.Sql/servers": ("sql server", "azure.mgmt.sql.SqlManagementClient", "servers", "@azure/arm-sql"),
    "Microsoft.DocumentDB/databaseAccounts": ("cosmosdb", "azure.mgmt.cosmosdb.CosmosDBManagementClient", "database_accounts", "@azure/arm-cosmosdb"),
    "Microsoft.KeyVault/vaults": ("keyvault", "azure.mgmt.keyvault.KeyVaultManagementClient", "vaults", "@azure/arm-keyvault"),
    "Microsoft.ServiceBus/namespaces": ("servicebus namespace", "azure.mgmt.servicebus.ServiceBusManagementClient", "namespaces", "@azure/arm-servicebus"),
    "Microsoft.Web/sites": ("webapp", "azure.mgmt.web.WebSiteManagementClient", "web_apps", "@azure/arm-appservice"),
    "Microsoft.Web/serverfarms": ("appservice plan", "azure.mgmt.web.WebSiteManagementClient", "app_service_plans", "@azure/arm-appservice"),
    "Microsoft.Network/virtualNetworks": ("network vnet", "azure.mgmt.network.NetworkManagementClient", "virtual_networks", "@azure/arm-network"),
    "Microsoft.Network/networkSecurityGroups": ("network nsg", "azure.mgmt.network.NetworkManagementClient", "network_security_groups", "@azure/arm-network"),
    "Microsoft.Network/dnsZones": ("network dns zone", "azure.mgmt.dns.DnsManagementClient", "zones", "@azure/arm-dns"),
    "Microsoft.Network/publicIPAddresses": ("network public-ip", "azure.mgmt.network.NetworkManagementClient", "public_ip_addresses", "@azure/arm-network"),
    "Microsoft.Network/networkInterfaces": ("network nic", "azure.mgmt.network.NetworkManagementClient", "network_interfaces", "@azure/arm-network"),
    "Microsoft.Network/loadBalancers": ("network lb", "azure.mgmt.network.NetworkManagementClient", "load_balancers", "@azure/arm-network"),
    "Microsoft.Network/networkManagers": ("network manager", "azure.mgmt.network.NetworkManagementClient", "network_managers", "@azure/arm-network"),
    "Microsoft.ContainerRegistry/registries": ("acr", "azure.mgmt.containerregistry.ContainerRegistryManagementClient", "registries", "@azure/arm-containerregistry"),
    "Microsoft.ContainerService/managedClusters": ("aks", "azure.mgmt.containerservice.ContainerServiceClient", "managed_clusters", "@azure/arm-containerservice"),
    "Microsoft.ApiManagement/service": ("apim", "azure.mgmt.apimanagement.ApiManagementClient", "api_management_service", "@azure/arm-apimanagement"),
    "Microsoft.EventGrid/topics": ("eventgrid topic", "azure.mgmt.eventgrid.EventGridManagementClient", "topics", "@azure/arm-eventgrid"),
    "Microsoft.OperationalInsights/workspaces": ("monitor log-analytics workspace", "azure.mgmt.loganalytics.LogAnalyticsManagementClient", "workspaces", "@azure/arm-operationalinsights"),
    "Microsoft.Insights/metricAlerts": ("monitor metrics alert", "azure.mgmt.monitor.MonitorManagementClient", "metric_alerts", "@azure/arm-monitor"),
    "Microsoft.CognitiveServices/accounts": ("cognitiveservices account", "azure.mgmt.cognitiveservices.CognitiveServicesManagementClient", "accounts", "@azure/arm-cognitiveservices"),
    "Microsoft.AppConfiguration/configurationStores": ("appconfig", "azure.mgmt.appconfiguration.AppConfigurationManagementClient", "configuration_stores", "@azure/arm-appconfiguration"),
    "Microsoft.App/containerApps": ("containerapp", "azure.mgmt.appcontainers.ContainerAppsAPIClient", "container_apps", "@azure/arm-appcontainers"),
    "Microsoft.Resources/resourceGroups": ("group", "azure.mgmt.resource.ResourceManagementClient", "resource_groups", "@azure/arm-resources"),
    "Microsoft.ManagedIdentity/userAssignedIdentities": ("identity", "azure.mgmt.msi.ManagedServiceIdentityClient", "user_assigned_identities", "@azure/arm-msi"),
    "Microsoft.Cdn/profiles": ("afd profile", "azure.mgmt.cdn.CdnManagementClient", "profiles", "@azure/arm-cdn"),
    "Microsoft.Cache/redis": ("redis", "azure.mgmt.redis.RedisManagementClient", "redis", "@azure/arm-rediscache"),
    "Microsoft.RecoveryServices/vaults": ("backup vault", "azure.mgmt.recoveryservices.RecoveryServicesClient", "vaults", "@azure/arm-recoveryservices"),
}
AZ_API_VERSION = {
    "Microsoft.Compute": "2024-03-01", "Microsoft.Storage": "2023-05-01", "Microsoft.Sql": "2023-05-01-preview", "Microsoft.DocumentDB": "2024-05-15",
    "Microsoft.KeyVault": "2023-07-01", "Microsoft.ServiceBus": "2022-10-01-preview", "Microsoft.Web": "2023-12-01", "Microsoft.Network": "2024-01-01",
    "Microsoft.ContainerRegistry": "2023-07-01", "Microsoft.ContainerService": "2024-02-01", "Microsoft.ApiManagement": "2023-05-01-preview",
    "Microsoft.EventGrid": "2022-06-15", "Microsoft.OperationalInsights": "2022-10-01", "Microsoft.Insights": "2018-03-01",
    "Microsoft.CognitiveServices": "2023-05-01", "Microsoft.AppConfiguration": "2023-03-01", "Microsoft.App": "2023-05-01",
    "Microsoft.Resources": "2021-04-01", "Microsoft.ManagedIdentity": "2023-01-31", "Microsoft.Cdn": "2023-05-01", "Microsoft.Cache": "2023-08-01",
    "Microsoft.RecoveryServices": "2023-04-01",
}
AZ_MAP = {   # console service id -> ARM types documented under it
    "storage": ["Microsoft.Storage/storageAccounts"], "vms": ["Microsoft.Compute/virtualMachines", "Microsoft.Compute/disks", "Microsoft.Network/networkInterfaces", "Microsoft.Network/publicIPAddresses"],
    "sql": ["Microsoft.Sql/servers"], "cosmos": ["Microsoft.DocumentDB/databaseAccounts"], "keyvaults": ["Microsoft.KeyVault/vaults"],
    "servicebus": ["Microsoft.ServiceBus/namespaces"], "functionapp": ["Microsoft.Web/sites"], "appservices": ["Microsoft.Web/sites", "Microsoft.Web/serverfarms"],
    "vnets": ["Microsoft.Network/virtualNetworks", "Microsoft.Network/loadBalancers", "Microsoft.Network/routeTables", "Microsoft.Network/privateEndpoints", "Microsoft.Network/natGateways", "Microsoft.Network/azureFirewalls", "Microsoft.Network/bastionHosts"],
    "nsgs": ["Microsoft.Network/networkSecurityGroups", "Microsoft.Network/applicationSecurityGroups"],
    "frontdoor": ["Microsoft.Cdn/profiles"], "networkmanagers": ["Microsoft.Network/networkManagers"], "dns": ["Microsoft.Network/dnsZones"],
    "resourcegroups": ["Microsoft.Resources/resourceGroups", "Microsoft.Resources/deployments"], "acr": ["Microsoft.ContainerRegistry/registries"],
    "aks": ["Microsoft.ContainerService/managedClusters"], "apim": ["Microsoft.ApiManagement/service"], "eventgrid": ["Microsoft.EventGrid/topics", "Microsoft.EventGrid/domains", "Microsoft.EventGrid/systemTopics"],
    "monitor": ["Microsoft.Insights/metricAlerts"], "loganalytics": ["Microsoft.OperationalInsights/workspaces"],
    "defender": [], "entra": ["Microsoft.Authorization/roleAssignments", "Microsoft.Authorization/roleDefinitions", "Microsoft.ManagedIdentity/userAssignedIdentities"],
    "subscriptions": ["Microsoft.Authorization/policyAssignments", "Microsoft.Authorization/policyDefinitions"], "cost": [],
    "cognitiveservices": ["Microsoft.CognitiveServices/accounts"], "appconfiguration": ["Microsoft.AppConfiguration/configurationStores"],
    "streamanalytics": [], "containerapps": ["Microsoft.App/containerApps", "Microsoft.App/jobs", "Microsoft.App/managedEnvironments"],
    "recoveryservices": ["Microsoft.RecoveryServices/vaults"],
}
# v4 additions: ARM types the router answers (probed) that the console services above did not list yet
for _sid, _ts in {
    "defender": ["Microsoft.Security/automations", "Microsoft.Security/pricings"],
    "monitor": ["Microsoft.Insights/actionGroups", "Microsoft.Insights/activityLogAlerts", "Microsoft.Insights/autoscaleSettings",
                "Microsoft.Insights/scheduledQueryRules", "Microsoft.Insights/dataCollectionRules", "Microsoft.Insights/workbooks",
                "Microsoft.Insights/components", "Microsoft.Monitor/accounts", "Microsoft.Dashboard/grafana"],
    "streamanalytics": ["Microsoft.StreamAnalytics/streamingjobs"],
    "vnets": ["Microsoft.Network/ddosProtectionPlans", "Microsoft.Network/firewallPolicies", "Microsoft.Network/networkWatchers"],
    "subscriptions": ["Microsoft.Authorization/locks", "Microsoft.Authorization/roleAssignments"],
    "appservices": ["Microsoft.Web/certificates"],
    "cost": [], "common": [],
}.items():
    AZ_MAP[_sid] = AZ_MAP.get(_sid, []) + [t for t in _ts if t not in AZ_MAP.get(_sid, [])]
AZ_EXTRA_SERVICES = [("redis", "Azure Cache for Redis", "Databases", ["Microsoft.Cache/redis"]),
                     ("search", "Azure AI Search", "AI + machine learning", ["Microsoft.Search/searchServices"]),
                     ("logic", "Logic Apps", "Integration", ["Microsoft.Logic/workflows"])]
AZ_API_VERSION.update({"Microsoft.Security": "2023-12-01-preview", "Microsoft.Dashboard": "2023-09-01", "Microsoft.Monitor": "2023-04-03",
                       "Microsoft.StreamAnalytics": "2021-10-01-preview", "Microsoft.Authorization": "2022-04-01", "Microsoft.Search": "2023-11-01",
                       "Microsoft.Logic": "2019-05-01"})
AZ_SDK.update({
    "Microsoft.Insights/actionGroups": ("monitor action-group", "azure.mgmt.monitor.MonitorManagementClient", "action_groups", "@azure/arm-monitor"),
    "Microsoft.Insights/activityLogAlerts": ("monitor activity-log alert", "azure.mgmt.monitor.MonitorManagementClient", "activity_log_alerts", "@azure/arm-monitor"),
    "Microsoft.Insights/autoscaleSettings": ("monitor autoscale", "azure.mgmt.monitor.MonitorManagementClient", "autoscale_settings", "@azure/arm-monitor"),
    "Microsoft.Insights/scheduledQueryRules": ("monitor scheduled-query", "azure.mgmt.monitor.MonitorManagementClient", "scheduled_query_rules", "@azure/arm-monitor"),
    "Microsoft.Security/automations": ("", "azure.mgmt.security.SecurityCenter", "automations", "@azure/arm-security"),
    "Microsoft.Logic/workflows": ("logic workflow", "azure.mgmt.logic.LogicManagementClient", "workflows", "@azure/arm-logic"),
    "Microsoft.Search/searchServices": ("search service", "azure.mgmt.search.SearchManagementClient", "services", "@azure/arm-search"),
    "Microsoft.Network/networkWatchers": ("network watcher", "azure.mgmt.network.NetworkManagementClient", "network_watchers", "@azure/arm-network"),
})
AZ_DATA = {   # data-plane notes per console service (native wire the SDKs/CLIs use)
    "storage": [("Blob", "GET {EP}/devstoreaccount1/{container}?restype=container&comp=list", "azure-storage-blob / `az storage blob`"),
                ("Queue", "GET {EP}/azure-data/queue/devstoreaccount1?comp=list", "azure-storage-queue / `az storage queue`")],
    "keyvaults": [("Secrets", "GET {EP}/secrets?api-version=7.4", "azure-keyvault-secrets (https endpoint) / `az rest`")],
    "cosmos": [("SQL API", "GET {EP}/dbs", "azure-cosmos (https endpoint) / `az rest`")],
    "appconfiguration": [("Key-values", "GET {EP}/azure-data/appconfig/{store}/kv", "azure-appconfiguration / `az appconfig kv`")],
}


def gen_azure_types(router):
    """Probe each ARM resource type (list at subscription scope + CRUD on a resource group) against the router."""
    sub = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
    router.handle("PUT", sub + "/resourceGroups/docs-rg?api-version=2021-04-01", {}, {"host": "x", "content-type": "application/json"}, b'{"location":"eastus"}')
    res = {}
    types = sorted({t for ts in AZ_MAP.values() for t in ts} | {t for e in AZ_EXTRA_SERVICES for t in e[3]})
    for t in types:
        rp, rt = t.split("/", 1)
        api = AZ_API_VERSION.get(rp, "2023-01-01")
        q = {"api-version": api}
        probes = {}
        for label, m, p, body in (
            ("list", "GET", "%s/providers/%s/%s?api-version=%s" % (sub, rp, rt, api), b""),
            ("listrg", "GET", "%s/resourceGroups/docs-rg/providers/%s/%s?api-version=%s" % (sub, rp, rt, api), b""),
            ("put", "PUT", "%s/resourceGroups/docs-rg/providers/%s/%s/docs-res?api-version=%s" % (sub, rp, rt, api), b'{"location":"eastus","properties":{}}'),
            ("get", "GET", "%s/resourceGroups/docs-rg/providers/%s/%s/docs-res?api-version=%s" % (sub, rp, rt, api), b""),
            ("delete", "DELETE", "%s/resourceGroups/docs-rg/providers/%s/%s/docs-res?api-version=%s" % (sub, rp, rt, api), b"")):
            try:
                out = router.handle(m, p, q, {"host": "x", "content-type": "application/json"}, body)
            except Exception:  # noqa: BLE001
                probes[label] = False
                continue
            b = out["body"][:500].decode("utf8", "replace")
            probes[label] = not (out["status"] == 501 or UNWIRED.search(b))
        res[t] = {"probes": probes, "api": api}
    return res


def az_ops(t, info, display):
    rp, rt = t.split("/", 1)
    api = info["api"]
    sub = "/subscriptions/{subscriptionId}"
    rg = sub + "/resourceGroups/{resourceGroupName}"
    sdk = AZ_SDK.get(t)
    py_attr = sdk[2] if sdk else ""
    base = "%s/providers/%s/%s" % (rg, rp, rt)
    ops = []
    pr = info["probes"]
    if pr.get("list"):
        ops.append({"n": "List by subscription", "m": "GET", "u": "%s/providers/%s/%s?api-version=%s" % (sub, rp, rt, api), "az": "list", "py": "list_by_subscription" if "Resources" not in rp else "list", "d": "List every %s in the subscription." % display})
    if pr.get("listrg"):
        ops.append({"n": "List by resource group", "m": "GET", "u": "%s?api-version=%s" % (base, api), "az": "list -g {rg}", "py": "list" if "Compute" in rp or "Network" in rp or "Web" in rp else "list_by_resource_group", "d": "List the %s in a resource group." % display})
    if pr.get("get"):
        ops.append({"n": "Get", "m": "GET", "u": "%s/{name}?api-version=%s" % (base, api), "az": "show -g {rg} -n {name}", "py": "get", "d": "Get one %s." % display})
    if pr.get("put"):
        ops.append({"n": "Create or update", "m": "PUT", "u": "%s/{name}?api-version=%s" % (base, api), "az": "create -g {rg} -n {name} -l eastus", "py": "begin_create_or_update", "d": "Create or replace a %s." % display,
                    "in": {"location": "eastus", "tags": {"env": "dev"}, "properties": {}}})
    if pr.get("delete"):
        ops.append({"n": "Delete", "m": "DELETE", "u": "%s/{name}?api-version=%s" % (base, api), "az": "delete -g {rg} -n {name} --yes", "py": "begin_delete", "d": "Delete a %s." % display})
    return ops


# ───────────────────────────── assembly ─────────────────────────────
def title_of(sid, reg, extra=None):
    return (extra or {}).get(sid) or sid


def feature_rows(feats):
    return [{"id": f["id"], "t": f["title"], "l": f["nano"], "a": f["api"], "x": f["limits"][:1]} for f in feats]


GLOBAL_WIRED = {}


def verify_extras():
    """Send every hand-authored op to the real Nano router; fail on anything that does not answer (503 = needs local LLM)."""
    router = AwsWireRouter()
    router.STRICT_GCP_PROJECT = False
    h = {"host": "x", "content-type": "application/json", "api-key": "test", "x-goog-api-key": "test", "authorization": "Bearer dev"}
    for m, p, b in X.VERIFY_SETUP:
        router.handle(m, p, dict(parse_qsl(p.split("?", 1)[1])), h, json.dumps(b).encode())
    bad = 0
    for (cloud, sid), ex in sorted(X.EXTRAS.items()):
        for o in ex["api"]["ops"]:
            u = re.sub(r"\{[^}]+\}", "x", o["u"])
            q = dict(parse_qsl(u.split("?", 1)[1])) if "?" in u else {}
            body = json.dumps(o["in"]).encode() if o["in"] is not None else b""
            out = router.handle(o["m"], u if cloud == "azure" else u.split("?", 1)[0], q, h, body)
            txt = out["body"][:300].decode("utf8", "replace")
            ok = out["status"] < 400 or (o.get("llm") and out["status"] == 503) or (out["status"] == 404 and "{" in o["u"])
            print("%-4s %-60s %s %s" % ("ok" if ok else "FAIL", o["n"][:60], out["status"], "" if ok else txt))
            bad += not ok
    sys.exit(1 if bad else 0)


def main():
    if "--verify-extras" in sys.argv:
        return verify_extras()
    check = "--check" in sys.argv
    cov = {"botocore": botocore.__version__}
    index = {"clouds": {}}
    # ── AWS
    reg = load_registry("aws")
    aws = gen_aws()
    used = set()
    svcs = []
    consoles = console_services("aws")
    for sid, title, cat in consoles + [(k, k, "Other") for k in reg if k not in {c[0] for c in consoles}]:
        apis = [aws[a] for a in AWS_MAP.get(sid, []) if a in aws]
        for a in AWS_MAP.get(sid, []):
            used.add(a)
        feats = reg.get(sid, [])
        if not apis and not feats:
            continue
        svcs.append(("aws", sid, title, cat, apis, feats))
    extra = [aws[a] for a in sorted(aws) if a not in used]
    for a in extra:
        svcs.append(("aws", "api-" + a["id"], a["title"], "Additional wired APIs", [a], []))
    # ── GCP
    reg_g = load_registry("gcp")
    consoles_g = console_services("gcp")
    names = sorted({n for v in GCP_MAP.values() for n in v})
    gdocs = gen_gcp_apis(names)
    seen_ids = set()
    for sid, title, cat in consoles_g + [(k, k, "Other") for k in reg_g if k not in {c[0] for c in console_services("gcp")}] + GCP_EXTRA_SERVICES + [("gemini", X.EXTRAS[("gcp", "gemini")]["title"], X.EXTRAS[("gcp", "gemini")]["category"])]:
        apis = [gdocs["%s.%s" % n] for n in GCP_MAP.get(sid, []) if "%s.%s" % n in gdocs]
        feats = reg_g.get(sid, reg_g.get(sid.split("/")[-1], []))
        if sid.split("/")[-1] in seen_ids:
            continue
        seen_ids.add(sid.split("/")[-1])
        svcs.append(("gcp", sid, title, cat, apis, feats))
    # ── Azure
    reg_a = load_registry("azure")
    consoles_a = console_services("azure")
    arm = gen_azure_types(AwsWireRouter())
    for sid, title, cat in consoles_a + [(k, k, "Other") for k in reg_a if k not in {c[0] for c in consoles_a}]:
        types = AZ_MAP.get(sid, [])
        feats = reg_a.get(sid, [])
        svcs.append(("azure", sid, title, cat, ("azure", types), feats))
    for sid, title, cat, types in AZ_EXTRA_SERVICES:
        svcs.append(("azure", sid, title, cat, ("azure", types), []))

    GLOBAL_WIRED["aws"] = {o["n"] for a in aws.values() for o in a["ops"]}
    GLOBAL_WIRED["gcp"] = {o["n"] for a in gdocs.values() for o in a["ops"]} | {o["n"].split(".", 1)[-1] for a in gdocs.values() for o in a["ops"]}
    cloud_idx = {"aws": [], "gcp": [], "azure": []}
    cov_services = []
    for cloud, sid, title, cat, apis, feats in svcs:
        doc = {"cloud": cloud, "id": sid, "title": title, "category": cat, "features": feature_rows(feats)}
        if cloud == "azure":
            types = apis[1]
            adocs = []
            for t in types:
                disp = AZ_SDK.get(t, ("", "", "", ""))
                ops = az_ops(t, arm[t], t.split("/")[1])
                sdk = AZ_SDK.get(t)
                adocs.append({"id": t, "title": t, "arm": True, "api": arm[t]["api"], "az": sdk[0] if sdk else "", "py_client": sdk[1] if sdk else "",
                              "py_attr": sdk[2] if sdk else "", "js_pkg": sdk[3] if sdk else "", "ops": ops, "total": 5, "wired": len(ops),
                              "unwired": [o for o, k in (("List", "list"), ("ListRG", "listrg"), ("Get", "get"), ("Put", "put"), ("Delete", "delete")) if not arm[t]["probes"].get(k)]})
            doc["apis"] = adocs
            doc["data"] = [{"n": a, "u": b, "c": c} for a, b, c in AZ_DATA.get(sid, [])]
        else:
            doc["apis"] = apis
        ex = X.EXTRAS.get((cloud, sid))
        if ex:
            e = dict(ex["api"])
            e.update({"extra": True, "total": len(e["ops"]), "wired": len(e["ops"]), "unwired": []})
            doc["apis"] = list(doc["apis"]) + [e]
        doc["ops"] = sum(len(a["ops"]) for a in doc["apis"])
        doc["total"] = sum(a["total"] for a in doc["apis"])
        # registry-declared ops vs wired (AWS: by name; GCP: by method suffix)
        wired_names = set()
        for a in doc["apis"]:
            for o in a["ops"]:
                wired_names.add(o["n"])
                if cloud == "gcp":
                    wired_names.add(o["n"].split(".", 1)[-1])
        claimed = [(f["id"], o) for f in feats for o in f["api"]]
        gset = GLOBAL_WIRED.get(cloud, set())
        miss = []
        if cloud in ("aws", "gcp"):
            for fid, o in claimed:
                key = re.split(r"[ (]", o)[0].split(".")[-1] if cloud == "aws" else re.split(r"[ (]", o)[0]
                if "Vyomi" in o or "convenience" in o or re.search(r"[*{}/]|CRUD", key):
                    continue
                if key not in gset and not any(w.endswith("." + key) or w == key for w in gset):
                    miss.append([fid, o])
        doc["registry_unreachable"] = miss
        dump(os.path.join(OUT, cloud, sid.replace("/", "_") + ".json"), doc)
        entry = {"id": sid, "t": title, "c": cat, "f": sid.replace("/", "_") + ".json", "o": doc["ops"], "n": doc["total"], "ft": len(feats)}
        cloud_idx[cloud].append(entry)
        cov_services.append({"cloud": cloud, "id": sid, "ops": doc["ops"], "total": doc["total"], "features": len(feats),
                             "claimed_api_ops": len(claimed), "claimed_unreachable": len(miss),
                             "unwired_sample": [u for a in doc["apis"] for u in a.get("unwired", [])][:6]})
    for c in cloud_idx:
        cloud_idx[c].sort(key=lambda e: (e["c"], e["t"]))
    index["clouds"] = cloud_idx
    index["sources"] = {"botocore": botocore.__version__}
    dump(os.path.join(OUT, "index.json"), index)
    summary = {}
    for c in ("aws", "gcp", "azure"):
        ss = [s for s in cov_services if s["cloud"] == c]
        summary[c] = {"services": len(ss), "ops_documented": sum(s["ops"] for s in ss), "ops_total_in_apis": sum(s["total"] for s in ss),
                      "registry_features": sum(s["features"] for s in ss), "claimed_api_ops": sum(s["claimed_api_ops"] for s in ss),
                      "claimed_unreachable": sum(s["claimed_unreachable"] for s in ss)}
    dump(os.path.join(OUT, "coverage.json"), {"summary": summary, "services": cov_services, "sources": {"botocore": botocore.__version__}})
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

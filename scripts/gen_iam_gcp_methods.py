#!/usr/bin/env python3
"""Generate core/iam_catalog/gcp/_methods.json from the public Google API Discovery documents.

Each Discovery method has an id (storage.objects.get), httpMethod and path. The IAM permission is not in Discovery, so it is
derived (candidate generation below) and ONLY emitted when it exists in the verbatim roles-permissions catalog
(core/iam_catalog/gcp/*.json). Methods whose permission cannot be derived are listed in the output under "unmatched" and are
resolved by OVERRIDES (id -> permission(s), with a reason). Methods that need no permission are in NO_PERMISSION.

Usage: python scripts/gen_iam_gcp_methods.py [--cache DIR]      (network needed unless the cache is warm)
"""
import argparse, glob, json, os, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "core", "iam_catalog", "gcp")
OUT = os.path.join(CAT, "_methods.json")

# Discovery API id -> preferred versions (first that exists wins; all listed are included)
APIS = ["storage:v1", "compute:v1", "container:v1", "sqladmin:v1", "sqladmin:v1beta4", "firestore:v1", "redis:v1", "run:v2", "run:v1",
        "cloudfunctions:v2", "cloudfunctions:v1", "pubsub:v1", "cloudscheduler:v1", "eventarc:v1", "apigateway:v1", "iam:v1",
        "cloudresourcemanager:v3", "cloudresourcemanager:v1", "artifactregistry:v1", "clouddeploy:v1", "backupdr:v1",
        "cloudbuild:v1", "aiplatform:v1", "monitoring:v3", "logging:v2", "cloudkms:v1", "secretmanager:v1", "dns:v1",
        "cloudtasks:v2", "workflows:v1", "bigquery:v2", "serviceusage:v1", "orgpolicy:v2", "securitycenter:v1",
        "vpcaccess:v1", "servicenetworking:v1", "iap:v1", "identitytoolkit:v1", "iamcredentials:v1", "serviceusage:v1beta1"]

# permission-prefix aliases: discovery id prefix -> permission prefixes to try
PREFIX = {"firestore": ["datastore"], "sql": ["cloudsql"], "sqladmin": ["cloudsql"], "cloudresourcemanager": ["resourcemanager"], "identitytoolkit": ["firebaseauth"],
          "iamcredentials": ["iam"], "servicenetworking": ["servicenetworking"], "monitoring": ["monitoring"],
          "vpcaccess": ["vpcaccess"], "cloudfunctions": ["cloudfunctions"], "bigquery": ["bigquery"]}
VERB = {"insert": ["create"], "patch": ["update"], "aggregatedList": ["list"], "update": ["update"], "get": ["get"],
        "list": ["list"], "delete": ["delete"], "create": ["create"], "setIamPolicy": ["setIamPolicy"],
        "getIamPolicy": ["getIamPolicy"], "export": ["export"], "import": ["import"], "run": ["run", "invoke"],
        "call": ["invoke"], "generateAccessToken": ["getAccessToken"], "signBlob": ["signBlob"], "signJwt": ["signJwt"],
        "generateIdToken": ["getOpenIdToken"], "cancel": ["cancel", "delete"], "wait": ["get"], "upload": ["create"],
        "restart": ["restart"], "failover": ["failover"], "clone": ["clone"], "query": ["create"]}
DROP = {"projects", "locations", "regions", "zones", "global", "organizations", "folders", "billingAccounts", "v1", "v2",
        "regionOperations", "zoneOperations", "globalOperations"}
# methods that require no IAM permission (Google documents testIamPermissions as "none required")
NO_PERMISSION_VERBS = {"testIamPermissions"}

# Manual overrides: Discovery method id -> (permissions, reason).  Reasons are mandatory.
OVERRIDES = {
    "storage.objects.insert": (["storage.objects.create"], "upload verb is insert; overwrite additionally needs storage.objects.delete (XML/JSON PUT)"),
    "storage.objects.rewrite": (["storage.objects.get", "storage.objects.create"], "rewrite reads the source and writes the destination"),
    "storage.objects.copy": (["storage.objects.get", "storage.objects.create"], "copy reads the source and writes the destination"),
    "storage.objects.compose": (["storage.objects.get", "storage.objects.create"], "compose reads sources and writes the destination"),
    "storage.objects.watchAll": (["storage.objects.list"], "watch on a bucket's objects needs list"),
    "storage.buckets.insert": (["storage.buckets.create"], "insert->create"),
    "storage.buckets.lockRetentionPolicy": (["storage.buckets.update"], "lock needs buckets.update"),
    "storage.buckets.getStorageLayout": (["storage.buckets.get"], "layout read"),
    "compute.instances.start": (["compute.instances.start"], "verbatim"),
    "compute.instances.stop": (["compute.instances.stop"], "verbatim"),
    "compute.instances.reset": (["compute.instances.reset"], "verbatim"),
    "compute.instances.attachDisk": (["compute.instances.attachDisk", "compute.disks.use"], "also uses the disk"),
    "compute.instances.setMetadata": (["compute.instances.setMetadata"], "verbatim"),
    "compute.instances.setServiceAccount": (["compute.instances.setServiceAccount", "iam.serviceAccounts.actAs"], "requires actAs on the SA"),
    "compute.instances.setLabels": (["compute.instances.setLabels"], "verbatim"),
    "compute.instances.setMachineType": (["compute.instances.setMachineType"], "verbatim"),
    "compute.instances.setTags": (["compute.instances.setTags"], "verbatim"),
    "compute.instances.addAccessConfig": (["compute.instances.updateNetworkInterface"], "access config edits the NIC"),
    "compute.instances.deleteAccessConfig": (["compute.instances.updateNetworkInterface"], "access config edits the NIC"),
    "compute.instances.getSerialPortOutput": (["compute.instances.getSerialPortOutput"], "verbatim"),
    "compute.instances.insert": (["compute.instances.create"], "insert->create (also needs compute.disks.create + networks.use, handled by host)"),
    "compute.firewalls.insert": (["compute.firewalls.create"], "insert->create"),
    "pubsub.projects.topics.publish": (["pubsub.topics.publish"], "publish"),
    "pubsub.projects.subscriptions.pull": (["pubsub.subscriptions.consume"], "pull consumes"),
    "pubsub.projects.subscriptions.acknowledge": (["pubsub.subscriptions.consume"], "ack consumes"),
    "pubsub.projects.subscriptions.modifyAckDeadline": (["pubsub.subscriptions.consume"], "modifyAckDeadline consumes"),
    "pubsub.projects.subscriptions.modifyPushConfig": (["pubsub.subscriptions.update"], "push config is an update"),
    "pubsub.projects.topics.subscriptions.list": (["pubsub.topics.get"], "documented as topics.get on the topic"),
    "pubsub.projects.topics.snapshots.list": (["pubsub.topics.get"], "documented as topics.get on the topic"),
    "iam.projects.serviceAccounts.keys.create": (["iam.serviceAccountKeys.create"], "resource is serviceAccountKeys"),
    "iam.projects.serviceAccounts.keys.list": (["iam.serviceAccountKeys.list"], "serviceAccountKeys"),
    "iam.projects.serviceAccounts.keys.get": (["iam.serviceAccountKeys.get"], "serviceAccountKeys"),
    "iam.projects.serviceAccounts.keys.delete": (["iam.serviceAccountKeys.delete"], "serviceAccountKeys"),
    "iam.projects.serviceAccounts.keys.upload": (["iam.serviceAccountKeys.create"], "upload creates a key"),
    "iam.projects.serviceAccounts.disable": (["iam.serviceAccounts.disable"], "verbatim"),
    "iam.projects.serviceAccounts.enable": (["iam.serviceAccounts.enable"], "verbatim"),
    "iam.projects.serviceAccounts.undelete": (["iam.serviceAccounts.undelete"], "verbatim"),
    "iam.projects.serviceAccounts.signBlob": (["iam.serviceAccounts.signBlob"], "verbatim"),
    "iam.projects.serviceAccounts.signJwt": (["iam.serviceAccounts.signJwt"], "verbatim"),
    "iam.projects.roles.create": (["iam.roles.create"], "custom role"),
    "iam.projects.roles.patch": (["iam.roles.update"], "custom role"),
    "iam.projects.roles.delete": (["iam.roles.delete"], "custom role"),
    "iam.projects.roles.get": (["iam.roles.get"], "custom role"),
    "iam.projects.roles.list": (["iam.roles.list"], "custom role"),
    "iam.projects.roles.undelete": (["iam.roles.undelete"], "custom role"),
    "iam.roles.get": (["iam.roles.get"], "predefined role"),
    "iam.roles.list": (["iam.roles.list"], "predefined role"),
    "iam.roles.queryGrantableRoles": ([], "no permission documented"),
    "iam.permissions.queryTestablePermissions": ([], "no permission documented"),
    "iamcredentials.projects.serviceAccounts.generateAccessToken": (["iam.serviceAccounts.getAccessToken"], "token generation"),
    "iamcredentials.projects.serviceAccounts.generateIdToken": (["iam.serviceAccounts.getOpenIdToken"], "token generation"),
    "iamcredentials.projects.serviceAccounts.signBlob": (["iam.serviceAccounts.signBlob"], "signing"),
    "iamcredentials.projects.serviceAccounts.signJwt": (["iam.serviceAccounts.signJwt"], "signing"),
    "cloudkms.projects.locations.keyRings.cryptoKeys.encrypt": (["cloudkms.cryptoKeyVersions.useToEncrypt"], "crypto use"),
    "cloudkms.projects.locations.keyRings.cryptoKeys.decrypt": (["cloudkms.cryptoKeyVersions.useToDecrypt"], "crypto use"),
    "cloudkms.projects.locations.keyRings.cryptoKeys.cryptoKeyVersions.asymmetricSign": (["cloudkms.cryptoKeyVersions.useToSign"], "crypto use"),
    "cloudkms.projects.locations.keyRings.cryptoKeys.cryptoKeyVersions.asymmetricDecrypt": (["cloudkms.cryptoKeyVersions.useToDecrypt"], "crypto use"),
    "cloudkms.projects.locations.keyRings.cryptoKeys.cryptoKeyVersions.getPublicKey": (["cloudkms.cryptoKeyVersions.viewPublicKey"], "public key"),
    "cloudkms.projects.locations.keyRings.cryptoKeys.cryptoKeyVersions.destroy": (["cloudkms.cryptoKeyVersions.destroy"], "verbatim"),
    "cloudkms.projects.locations.keyRings.cryptoKeys.cryptoKeyVersions.restore": (["cloudkms.cryptoKeyVersions.restore"], "verbatim"),
    "secretmanager.projects.secrets.addVersion": (["secretmanager.versions.add"], "versions.add"),
    "secretmanager.projects.secrets.versions.access": (["secretmanager.versions.access"], "verbatim"),
    "secretmanager.projects.secrets.versions.disable": (["secretmanager.versions.disable"], "verbatim"),
    "secretmanager.projects.secrets.versions.enable": (["secretmanager.versions.enable"], "verbatim"),
    "secretmanager.projects.secrets.versions.destroy": (["secretmanager.versions.destroy"], "verbatim"),
    "secretmanager.projects.secrets.versions.get": (["secretmanager.versions.get"], "verbatim"),
    "secretmanager.projects.secrets.versions.list": (["secretmanager.versions.list"], "verbatim"),
    "secretmanager.projects.secrets.patch": (["secretmanager.secrets.update"], "patch->update"),
    "logging.entries.write": (["logging.logEntries.create"], "entries.write creates log entries"),
    "logging.entries.list": (["logging.logEntries.list"], "entries.list"),
    "monitoring.projects.timeSeries.create": (["monitoring.timeSeries.create"], "verbatim"),
    "monitoring.projects.timeSeries.list": (["monitoring.timeSeries.list"], "verbatim"),
    "dns.managedZones.create": (["dns.managedZones.create"], "verbatim"),
    "dns.changes.create": (["dns.changes.create"], "verbatim"),
    "dns.resourceRecordSets.create": (["dns.resourceRecordSets.create"], "verbatim"),
    "dns.resourceRecordSets.list": (["dns.resourceRecordSets.list"], "verbatim"),
    "sql.instances.insert": (["cloudsql.instances.create"], "insert->create"),
    "sql.instances.restart": (["cloudsql.instances.restart"], "verbatim"),
    "sql.instances.failover": (["cloudsql.instances.failover"], "verbatim"),
    "sql.instances.promoteReplica": (["cloudsql.instances.promoteReplica"], "verbatim"),
    "sql.instances.clone": (["cloudsql.instances.clone"], "verbatim"),
    "sql.instances.export": (["cloudsql.instances.export"], "verbatim"),
    "sql.instances.import": (["cloudsql.instances.import"], "verbatim"),
    "sql.users.insert": (["cloudsql.users.create"], "insert->create"),
    "sql.databases.insert": (["cloudsql.databases.create"], "insert->create"),
    "sql.backupRuns.insert": (["cloudsql.backupRuns.create"], "insert->create"),
    "container.projects.locations.clusters.create": (["container.clusters.create"], "verbatim"),
    "run.projects.locations.services.create": (["run.services.create"], "verbatim"),
    "run.projects.locations.jobs.run": (["run.jobs.run"], "verbatim"),
    "cloudfunctions.projects.locations.functions.call": (["cloudfunctions.functions.call"], "verbatim"),
    "cloudfunctions.projects.locations.functions.generateUploadUrl": (["cloudfunctions.functions.sourceCodeSet"], "upload url sets source"),
    "cloudfunctions.projects.locations.functions.generateDownloadUrl": (["cloudfunctions.functions.sourceCodeGet"], "download url gets source"),
    "cloudscheduler.projects.locations.jobs.run": (["cloudscheduler.jobs.run"], "verbatim"),
    "cloudscheduler.projects.locations.jobs.pause": (["cloudscheduler.jobs.update"], "pause/resume are updates"),
    "cloudscheduler.projects.locations.jobs.resume": (["cloudscheduler.jobs.update"], "pause/resume are updates"),
    "cloudresourcemanager.projects.create": (["resourcemanager.projects.create"], "verbatim"),
    "cloudresourcemanager.projects.search": (["resourcemanager.projects.get"], "search filters by get"),
    "cloudresourcemanager.projects.list": (["resourcemanager.projects.list"], "verbatim"),
    "cloudresourcemanager.projects.move": (["resourcemanager.projects.move"], "verbatim"),
    "cloudresourcemanager.projects.undelete": (["resourcemanager.projects.undelete"], "verbatim"),
    "cloudresourcemanager.projects.getIamPolicy": (["resourcemanager.projects.getIamPolicy"], "verbatim"),
    "cloudresourcemanager.projects.setIamPolicy": (["resourcemanager.projects.setIamPolicy"], "verbatim"),
    "cloudresourcemanager.folders.getIamPolicy": (["resourcemanager.folders.getIamPolicy"], "verbatim"),
    "cloudresourcemanager.folders.setIamPolicy": (["resourcemanager.folders.setIamPolicy"], "verbatim"),
    "cloudresourcemanager.organizations.getIamPolicy": (["resourcemanager.organizations.getIamPolicy"], "verbatim"),
    "cloudresourcemanager.organizations.setIamPolicy": (["resourcemanager.organizations.setIamPolicy"], "verbatim"),
    "cloudresourcemanager.projects.getAncestry": (["resourcemanager.projects.get"], "ancestry read"),
    "cloudresourcemanager.projects.setIamPolicy_v1": (["resourcemanager.projects.setIamPolicy"], "v1 variant"),
    "artifactregistry.projects.locations.repositories.create": (["artifactregistry.repositories.create"], "verbatim"),
    "artifactregistry.projects.locations.repositories.dockerImages.list": (["artifactregistry.dockerimages.list"], "dockerimages lower-case in catalog"),
    "artifactregistry.projects.locations.repositories.dockerImages.get": (["artifactregistry.dockerimages.get"], "dockerimages lower-case in catalog"),
    "bigquery.jobs.insert": (["bigquery.jobs.create"], "insert->create"),
    "bigquery.datasets.insert": (["bigquery.datasets.create"], "insert->create"),
    "bigquery.tables.insert": (["bigquery.tables.create"], "insert->create"),
    "bigquery.tabledata.list": (["bigquery.tables.getData"], "list rows"),
    "bigquery.tabledata.insertAll": (["bigquery.tables.updateData"], "streaming insert"),
    "bigquery.jobs.query": (["bigquery.jobs.create"], "query job"),
    "bigquery.jobs.getQueryResults": (["bigquery.jobs.get"], "results of a job"),
    "bigquery.projects.list": (["resourcemanager.projects.list"], "projects list"),
    "firestore.projects.databases.documents.createDocument": (["datastore.entities.create"], "Firestore (Datastore mode) / native doc create"),
    "firestore.projects.databases.documents.get": (["datastore.entities.get"], "doc get"),
    "firestore.projects.databases.documents.list": (["datastore.entities.list"], "doc list"),
    "firestore.projects.databases.documents.patch": (["datastore.entities.update"], "doc update"),
    "firestore.projects.databases.documents.delete": (["datastore.entities.delete"], "doc delete"),
    "firestore.projects.databases.documents.commit": (["datastore.entities.update", "datastore.entities.create"], "commit writes"),
    "firestore.projects.databases.documents.batchGet": (["datastore.entities.get"], "batchGet reads"),
    "firestore.projects.databases.documents.batchWrite": (["datastore.entities.update", "datastore.entities.create"], "batchWrite writes"),
    "firestore.projects.databases.documents.runQuery": (["datastore.entities.get", "datastore.entities.list"], "query reads"),
    "firestore.projects.databases.documents.runAggregationQuery": (["datastore.entities.get", "datastore.entities.list"], "aggregation reads"),
    "firestore.projects.databases.documents.listCollectionIds": (["datastore.entities.list"], "collection ids"),
    "firestore.projects.databases.documents.beginTransaction": (["datastore.databases.get"], "transaction"),
    "firestore.projects.databases.documents.rollback": (["datastore.databases.get"], "transaction"),
    "firestore.projects.databases.documents.listDocuments": (["datastore.entities.list"], "doc list"),
}
# Pattern overrides (regex on the Discovery id -> (permissions, reason)); evaluated after OVERRIDES, before derivation.
RULES = [
    (r"^storage\.bucketAccessControls\.(get|list)$", ["storage.buckets.getIamPolicy"], "bucket ACL read == getIamPolicy"),
    (r"^storage\.bucketAccessControls\.", ["storage.buckets.setIamPolicy"], "bucket ACL write == setIamPolicy"),
    (r"^storage\.defaultObjectAccessControls\.(get|list)$", ["storage.buckets.getIamPolicy"], "default object ACL read"),
    (r"^storage\.defaultObjectAccessControls\.", ["storage.buckets.setIamPolicy"], "default object ACL write"),
    (r"^storage\.objectAccessControls\.(get|list)$", ["storage.objects.getIamPolicy"], "object ACL read"),
    (r"^storage\.objectAccessControls\.", ["storage.objects.setIamPolicy"], "object ACL write"),
    (r"^storage\.notifications\.(get|list)$", ["storage.buckets.get"], "notification config read needs buckets.get"),
    (r"^storage\.notifications\.", ["storage.buckets.update"], "notification config write needs buckets.update"),
    (r"^storage\.buckets\.operations\.(get|list)$", ["storage.buckets.get"], "bucket long-running op read"),
    (r"^storage\.buckets\.operations\.", ["storage.buckets.update"], "bucket long-running op control"),
    (r"^container\.projects\.locations\.clusters\.nodePools\.(get|list|fetch\w*)$", ["container.clusters.get"], "node pools are read through clusters.get"),
    (r"^container\.projects\.locations\.clusters\.nodePools\.create$", ["container.clusters.update"], "node pool create needs clusters.update"),
    (r"^container\.projects\.locations\.clusters\.nodePools\.", ["container.clusters.update"], "node pool mutations need clusters.update"),
    (r"^run\.projects\.locations\.domainmappings\.|^run\.namespaces\.domainmappings\.", None, "domain mappings: Cloud Run v1 API, permission not in catalog roles"),
]
RULES_IGNORED = True


def load_perms():
    perms = set()
    for f in glob.glob(os.path.join(CAT, "*.json")):
        if os.path.basename(f).startswith("_"):
            continue
        perms |= set(json.load(open(f))["permissions"])
    return perms


def fetch(url, cache):
    key = os.path.join(cache, re.sub(r"[^A-Za-z0-9]+", "_", url)[:150] + ".json")
    if os.path.exists(key):
        return json.load(open(key))
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    open(key, "wb").write(data)
    return json.loads(data)


def walk(node, out):
    for m in (node.get("methods") or {}).values():
        out.append(m)
    for r in (node.get("resources") or {}).values():
        walk(r, out)


def _norm(c):
    c = re.sub(r"^(region|zone|global)(?=[A-Z])", "", c)
    return c[:1].lower() + c[1:]


def candidates(mid):
    parts = mid.split(".")
    api, verb = parts[0], parts[-1]
    mid_chain = [p for p in parts[1:-1]]
    chain = [p for p in mid_chain[:-1] if p not in DROP] + mid_chain[-1:]
    chain = [_norm(c) for c in chain]
    prefixes = [api] + PREFIX.get(api, [])
    verbs = VERB.get(verb, []) + [verb]
    out = []
    for pre in prefixes:
        for take in (1, 2, 3):
            if len(chain) >= take:
                for v in verbs:
                    out.append(f"{pre}.{'.'.join(chain[-take:])}.{v}")
        if not chain:
            for v in verbs:
                out.append(f"{pre}.{v}")
    return out


def fallback_verbs(verb):
    """Heuristic verb class for custom verbs (suspendInstances, getHealth, ...) -> standard permission verb."""
    v = verb.lower()
    if v.startswith("get") or v.startswith("search") or v in ("wait", "check"):
        return ["get", "list"]
    if v.startswith("list") or v.startswith("fetch") or v.startswith("query"):
        return ["list", "get"]
    if v.startswith("create") or v.startswith("add") or v.startswith("insert"):
        return ["create", "update"]
    if v.startswith("delete") or v.startswith("remove") or v.startswith("destroy"):
        return ["delete", "update"]
    return ["update"]


def derive(mid, perms, lower):
    """-> (permission, fallback_flag) or (None, False). `lower` maps lower-cased perm -> verbatim perm."""
    for c in candidates(mid):
        if c in perms:
            return c, False
        if c.lower() in lower:
            return lower[c.lower()], False
    parts = mid.split(".")
    api, verb = parts[0], parts[-1]
    chain = [_norm(p) for p in parts[1:-1] if p not in DROP] or [_norm(p) for p in parts[1:-1]][-1:]
    for pre in [api] + PREFIX.get(api, []):
        for take in (1, 2):
            if len(chain) >= take:
                for v in fallback_verbs(verb):
                    c = f"{pre}.{'.'.join(chain[-take:])}.{v}"
                    if c.lower() in lower:
                        return lower[c.lower()], True
    return None, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "gcp-discovery-cache"))
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True)
    perms = load_perms()
    lower = {p.lower(): p for p in perms}
    fallbacks = set()
    directory = fetch("https://www.googleapis.com/discovery/v1/apis", a.cache)["items"]
    by_id = {i["id"]: i for i in directory}
    docs = {}
    def get(api):
        item = by_id.get(api)
        if not item:
            return api, None
        try:
            return api, fetch(item["discoveryRestUrl"], a.cache)
        except Exception as e:  # noqa
            print("fetch failed", api, e, file=sys.stderr)
            return api, None
    with ThreadPoolExecutor(8) as ex:
        for api, d in ex.map(get, APIS):
            if d:
                docs[api] = d
    methods, unmatched, none_req = [], [], []
    seen = set()
    for api, d in docs.items():
        svc = d["name"]
        host = re.sub(r"^https?://", "", d["rootUrl"]).rstrip("/")
        sp = "/" + d.get("servicePath", "").strip("/") if d.get("servicePath", "").strip("/") else ""
        ms = []
        walk(d, ms)
        for m in ms:
            mid = m["id"]
            verb = mid.split(".")[-1]
            path = (sp + "/" + m.get("flatPath", m["path"]).lstrip("/")).replace("//", "/")
            # also keep the non-flat variant (uses {+name})
            variants = {(sp + "/" + m["path"].lstrip("/")).replace("//", "/")}
            if verb in NO_PERMISSION_VERBS:
                perm = []
            elif next((r for r in RULES if r[1] and re.match(r[0], mid)), None):
                rule = next(r for r in RULES if r[1] and re.match(r[0], mid))
                perm = list(rule[1])
            elif mid in OVERRIDES:
                perm = list(OVERRIDES[mid][0])
            else:
                p1, fb = derive(mid, perms, lower)
                perm = [p1] if p1 else None
                if fb:
                    fallbacks.add(mid)
            if perm is None:
                unmatched.append(mid)
                continue
            for pv in sorted(variants):
                k = (m["httpMethod"], host, pv, mid)
                if k in seen:
                    continue
                seen.add(k)
                methods.append({"id": mid, "m": m["httpMethod"], "h": host, "p": pv, "perm": perm, "svc": svc, "f": 1 if mid in fallbacks else 0,
                                "k": "parent" if verb in ("create", "insert", "list", "aggregatedList", "search", "listDocuments", "createDocument", "addVersion", "write", "query", "listCollectionIds", "listEffectiveTags") else "item"})
    bad = sorted({p for e in methods for p in e["perm"] if p not in perms})
    out = {"_comment": "generated by scripts/gen_iam_gcp_methods.py from Google API Discovery; do not hand-edit",
           "apis": sorted(docs), "methods": methods, "unmatched": sorted(set(unmatched)), "fallback_ids": sorted(fallbacks),
           "overrides": {k: {"perm": v[0], "reason": v[1]} for k, v in sorted(OVERRIDES.items())},
           "overrides_not_in_catalog": bad}
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    ids = {e["id"] for e in methods}
    print(f"apis={len(docs)} methods={len(ids)} entries={len(methods)} unmatched={len(set(unmatched))} "
          f"bad_perms={bad[:10]} size={os.path.getsize(OUT)//1024}KB")


if __name__ == "__main__":
    main()

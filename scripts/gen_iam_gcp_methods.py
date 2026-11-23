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
        "vpcaccess:v1", "servicenetworking:v1", "iap:v1", "identitytoolkit:v1", "iamcredentials:v1", "serviceusage:v1beta1",
        "binaryauthorization:v1", "apphub:v1"]

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

# --- second pass (added by WP gcp-coverage) ------------------------------------------------------------------------------------
# Applied only to methods the first-pass derive() could not resolve. Results are flagged f=1 (heuristic, same as fallback verbs)
# unless the permission is the verbatim <api>.<noun>.<verb> of the method. Every permission is validated against the catalog
# (`bad_perms` must stay empty), so nothing is invented.
MODS = ("network", "organization", "org", "region", "zone", "global", "folder", "project")
EXTRA_VERBS = {"addAttestationRule": ["setAttestationRules"], "removeAttestationRule": ["setAttestationRules"],
               "listAttestationRules": ["getAttestationRules"], "patch": ["update"]}
OP_VERBS = {"get": ["get"], "list": ["list", "get"], "wait": ["get"], "cancel": ["cancel", "update"], "delete": ["delete", "update"]}


def _singular(s):
    return s[:-3] + "y" if s.endswith("ies") else (s[:-1] if s.endswith("s") and not s.endswith("ss") else s)


def _variants(x):
    out = [x, _norm(x)]
    y = x
    for _ in range(2):                       # strip up to two leading scope words: regionNetworkFirewallPolicies -> firewallPolicies
        for m in MODS:
            if y.lower().startswith(m) and len(y) > len(m) and y[len(m)].isupper():
                y = y[len(m):]
                y = y[:1].lower() + y[1:]
                out.append(y)
                break
    if x.lower().startswith("region") and "Network" in x:
        out.append(x.replace("Network", "", 1))          # regionNetworkFirewallPolicies -> regionFirewallPolicies
    return list(dict.fromkeys(out))


def _cap(x):
    return x[:1].upper() + x[1:]


def derive_ext(mid, lower):
    """Wider noun search: raw/scope-stripped nouns, camel-joined parent+child nouns (tensorboards.experiments -> tensorboardExperiments),
    long-running `operations.*` methods resolved against the parent resource, `<api>.googleapis.com_<noun>.<verb>` permission names."""
    import itertools
    parts = mid.split(".")
    api, verb = parts[0], parts[-1]
    mc = parts[1:-1]
    op = len(mc) > 1 and mc[-1] == "operations"
    if op:
        mc = mc[:-1]
    chain = [p for p in mc[:-1] if p not in DROP] + mc[-1:]
    if not chain:
        return None, False
    if op:
        vl, base = OP_VERBS.get(verb, [verb]), []
    else:
        base = VERB.get(verb, []) + [verb]
        fb = fallback_verbs(verb)
        if re.search(r"(Rule|Association|Rules)$", verb):
            fb = ["get", "list"] if verb.startswith(("get", "list")) else ["update"]
        vl = EXTRA_VERBS.get(verb, []) + base + fb
    for pre in [api] + PREFIX.get(api, []):
        for take in (1, 2, 3):
            if len(chain) < take:
                continue
            seg = chain[-take:]
            names = set()
            if take == 1:
                names |= set(_variants(seg[0]))
            else:
                for combo in itertools.product(*[_variants(x) for x in seg]):
                    names.add(".".join(combo))
                    names.add(combo[-2] + _cap(combo[-1]))
                    names.add(_singular(combo[-2]) + _cap(combo[-1]))
                pre_els = seg[:-1]
                for r in range(1, len(pre_els) + 1):
                    for sub in itertools.combinations(pre_els, r):
                        w = "".join(_cap(_singular(x)) if i else _singular(x) for i, x in enumerate(sub))
                        for lv in _variants(seg[-1]):
                            names.add(w + _cap(lv))
            for n in sorted(names):
                for v in vl:
                    for c in ("%s.%s.%s" % (pre, n, v), "%s.googleapis.com_%s.%s" % (pre, n, v)):
                        if c.lower() in lower:
                            return lower[c.lower()], not (n == chain[-1] and v in base)
    return None, False


def _grp(prefix, table, reason):
    """prefix regex (matched against the Discovery id minus the verb) + {verb regex: permission(s)} -> alias rows."""
    return [(r"^%s\.(?:%s)$" % (prefix, vr), ([perm] if isinstance(perm, str) else list(perm)), reason) for vr, perm in table.items()]


_CRUD = lambda ns, n: {"create": ns + "." + n + ".create", "get": ns + "." + n + ".get", "list": ns + "." + n + ".list",
                       "patch|update": ns + "." + n + ".update", "delete": ns + "." + n + ".delete"}
# Documented-permission aliases: the method's Discovery id does not name its permission (resource renamed in IAM, or several API
# resources are governed by one permission family). Reason strings say which.
ALIASES = (
    _grp(r"sql\.(?:backups|Backups)", {"(?i:createBackup)": "cloudsql.backupRuns.create", "(?i:deleteBackup)": "cloudsql.backupRuns.delete",
         "(?i:getBackup)": "cloudsql.backupRuns.get", "(?i:listBackups)": "cloudsql.backupRuns.list", "(?i:updateBackup)": "cloudsql.backupRuns.update"},
         "Cloud SQL backups (v1 backups.*) are governed by the cloudsql.backupRuns.* family")
    + _grp(r"sql\.connect", {"generateEphemeral": "cloudsql.instances.connect", "get": "cloudsql.instances.connect", "resolve": "cloudsql.instances.connect"},
           "connect API requires cloudsql.instances.connect")
    + _grp(r"sql\.operations", {"get": "cloudsql.instances.get", "list": "cloudsql.instances.list", "cancel": "cloudsql.instances.update"},
           "Cloud SQL operations inherit the instance permission (no cloudsql.operations.* permission exists in the catalog)")
    + _grp(r"cloudbuild\.(?:projects\.(?:locations\.)?)?triggers", {"create|run|webhook": "cloudbuild.builds.create", "get": "cloudbuild.builds.get",
           "list": "cloudbuild.builds.list", "patch|delete": "cloudbuild.builds.update"}, "build triggers are governed by cloudbuild.builds.* (roles/cloudbuild.builds.editor)")
    + _grp(r"cloudbuild\.projects\.(?:locations\.)?(?:githubEnterpriseConfigs|bitbucketServerConfigs)", {"create": "cloudbuild.integrations.create",
           "get": "cloudbuild.integrations.get", "list|repos\.list": "cloudbuild.integrations.list", "patch|connectedRepositories\.batchCreate|removeBitbucketServerConnectedRepository": "cloudbuild.integrations.update",
           "delete": "cloudbuild.integrations.delete"}, "GitHub Enterprise / Bitbucket Server configs are cloudbuild.integrations.*")
    + _grp(r"cloudbuild\.projects\.(?:locations\.)?operations", {"cancel": "cloudbuild.builds.update"}, "cancelling an operation cancels the build: builds.update")
    + _grp(r"logging\.(?:projects\.|folders\.|organizations\.|billingAccounts\.)?(?:locations\.)?savedQueries", {"create": "logging.queries.share",
           "get": "logging.queries.getShared", "list": "logging.queries.listShared", "patch": "logging.queries.updateShared", "delete": "logging.queries.deleteShared"},
           "saved queries are logging.queries.* (shared)")
    + _grp(r"logging\.(?:projects\.|folders\.|organizations\.|billingAccounts\.)?(?:locations\.)?recentQueries", {"list": "logging.queries.usePrivate"}, "recent queries are private queries")
    + _grp(r"logging\.projects\.metrics", {"create": "logging.logMetrics.create", "get": "logging.logMetrics.get", "list": "logging.logMetrics.list",
           "update": "logging.logMetrics.update", "delete": "logging.logMetrics.delete"}, "logs-based metrics are logging.logMetrics.*")
    + _grp(r"logging(?:\.(?:projects|folders|organizations|billingAccounts))?", {"getSettings": "logging.settings.get", "updateSettings": "logging.settings.update"}, "logging settings")
    + [(r"^logging\.entries\.tail$", ["logging.logEntries.list"], "tailLogEntries streams entries.list"),
       (r"^logging\.entries\.copy$", ["logging.buckets.copyLogEntries"], "copy log entries")]
    + _grp(r"securitycenter\.(?:projects|folders|organizations)\.notificationConfigs", {"create": "securitycenter.notificationconfig.create", "get": "securitycenter.notificationconfig.get",
           "list": "securitycenter.notificationconfig.list", "patch": "securitycenter.notificationconfig.update", "delete": "securitycenter.notificationconfig.delete"}, "SCC notification configs")
    + _grp(r"securitycenter\.organizations", {"getOrganizationSettings": "securitycenter.organizationsettings.get", "updateOrganizationSettings": "securitycenter.organizationsettings.update"}, "SCC organization settings")
    + _grp(r"securitycenter\.(?:projects|folders|organizations)\.assets", {"updateSecurityMarks": "securitycenter.assetsecuritymarks.update"}, "asset security marks")
    + _grp(r"securitycenter\.(?:projects|folders|organizations)\.securityHealthAnalyticsSettings\.customModules", {"create": "securitycenter.securityhealthanalyticscustommodules.create",
           "get": "securitycenter.securityhealthanalyticscustommodules.get", "list|listDescendant": "securitycenter.securityhealthanalyticscustommodules.list",
           "patch": "securitycenter.securityhealthanalyticscustommodules.update", "delete": "securitycenter.securityhealthanalyticscustommodules.delete",
           "simulate": "securitycenter.securityhealthanalyticscustommodules.simulate"}, "Security Health Analytics custom modules")
    + _grp(r"securitycenter\.(?:projects|folders|organizations)\.securityHealthAnalyticsSettings\.effectiveCustomModules", {"get": "securitycenter.effectivesecurityhealthanalyticscustommodules.get",
           "list": "securitycenter.effectivesecurityhealthanalyticscustommodules.list"}, "effective SHA custom modules")
    + _grp(r"cloudresourcemanager\.liens", {"create|delete": "resourcemanager.projects.updateLiens", "get|list": "resourcemanager.projects.get"}, "liens are governed by projects.updateLiens / projects.get")
    + _grp(r"cloudresourcemanager\.organizations", {"setOrgPolicy|clearOrgPolicy": "orgpolicy.policy.set"}, "legacy v1 org policy methods require orgpolicy.policy.set")
    + _grp(r"cloudkms(?:\.(?:projects|folders))?", {"getAutokeyConfig": "cloudkms.autokeyConfigs.get", "updateAutokeyConfig": "cloudkms.autokeyConfigs.update",
           "getKajPolicyConfig|showEffectiveKeyAccessJustificationsEnrollmentConfig|showEffectiveKeyAccessJustificationsPolicyConfig": "cloudkms.kajPolicyConfigs.get",
           "updateKajPolicyConfig": "cloudkms.kajPolicyConfigs.update"}, "KMS autokey / key access justifications config")
    + _grp(r"cloudkms\.projects\.locations", {"ekmConfig\.getIamPolicy": "cloudkms.ekmConfigs.getIamPolicy", "ekmConfig\.setIamPolicy": "cloudkms.ekmConfigs.setIamPolicy",
           "updateEkmConfig": "cloudkms.ekmConfigs.update"}, "EKM config")
    + _grp(r"container\.projects\.zones\.clusters\.nodePools", {"get|list|fetchNodePoolUpgradeInfo": "container.clusters.get", "create|delete|update|autoscaling|rollback|setManagement|setSize": "container.clusters.update"},
           "legacy zonal node pool methods follow the node-pool rule: reads clusters.get, mutations clusters.update")
    + _grp(r"artifactregistry\.projects", {"getProjectSettings": "artifactregistry.projectsettings.get", "updateProjectSettings": "artifactregistry.projectsettings.update"}, "project settings")
    + _grp(r"artifactregistry\.projects\.locations\.repositories\.\w+", {"import|upload": "artifactregistry.repositories.uploadArtifacts"}, "package import/upload writes artifacts")
    + _grp(r"redis\.projects\.locations\.clusters\.tokenAuthUsers", {"get|list|authTokens\.get|authTokens\.list": "redis.clusters.get", "addAuthToken|delete|authTokens\.delete": "redis.clusters.update"}, "cluster token auth users are managed through clusters")
    + _grp(r"redis\.projects\.locations\.aclPolicies\.revisions", {"get": "redis.aclPolicies.get", "list": "redis.aclPolicies.list"}, "ACL policy revisions")
    + _grp(r"storage\.rapidCaches", {"insert": "storage.anywhereCaches.create", "get": "storage.anywhereCaches.get", "list": "storage.anywhereCaches.list",
           "update|disable": "storage.anywhereCaches.update"}, "rapidCaches is the pre-GA name of anywhereCaches")
    + _grp(r"monitoring\.services\.serviceLevelObjectives", {"create": "monitoring.slos.create", "get": "monitoring.slos.get", "list": "monitoring.slos.list", "patch": "monitoring.slos.update", "delete": "monitoring.slos.delete"}, "SLOs")
    + [(r"^monitoring\.projects\.collectdTimeSeries\.create$", ["monitoring.timeSeries.create"], "collectd writes time series"),
       (r"^monitoring\.projects\.groups\.members\.list$", ["monitoring.groups.get"], "listing members reads the group"),
       (r"^monitoring\.uptimeCheckIps\.list$", ["monitoring.uptimeCheckConfigs.list"], "uptime check IPs"),
              (r"^cloudtasks\.projects\.locations\.queues\.tasks\.(batchCreate|buffer)$", ["cloudtasks.tasks.create"], "task creation"),
       (r"^cloudtasks\.projects\.locations\.queues\.tasks\.batchDelete$", ["cloudtasks.tasks.delete"], "task deletion"),
       (r"^bigquery\.models\.patch$", ["bigquery.models.updateMetadata"], "patch updates metadata"),
       (r"^pubsub\.projects\.schemas\.validateMessage$", ["pubsub.schemas.validate"], "validate message"),
       (r"^eventarc\.projects\.locations\.updateGoogleChannelConfig$", ["eventarc.googleChannelConfigs.update"], "google channel config"),
       (r"^serviceusage\.services\.batchEnable$", ["serviceusage.services.enable"], "batch enable"),
       (r"^serviceusage\.services\.batchGet$", ["serviceusage.services.get"], "batch get")]
    + _grp(r"serviceusage\.services\.consumerQuotaMetrics(?:\.limits(?:\.(?:adminOverrides|consumerOverrides))?)?", {"get|list": "serviceusage.quotas.get",
           "create|delete|patch|importAdminOverrides|importConsumerOverrides": "serviceusage.quotas.update"}, "quota metrics and overrides")
    + _grp(r"serviceusage\.services\.consumerQuotaMetrics\.limits\.(?:adminOverrides|consumerOverrides)", {"list": "serviceusage.quotas.get"}, "quota override list")
    + _grp(r"servicenetworking\.services", {"connections\.create|connections\.patch": "servicenetworking.services.addPeering", "connections\.deleteConnection": "servicenetworking.services.deleteConnection",
           "connections\.list": "servicenetworking.services.get", "dnsRecordSets\.add": "servicenetworking.services.addDnsRecordSet", "dnsRecordSets\.get|dnsRecordSets\.list": "servicenetworking.services.get",
           "dnsRecordSets\.remove": "servicenetworking.services.removeDnsRecordSet", "dnsRecordSets\.update": "servicenetworking.services.updateDnsRecordSet",
           "dnsZones\.add": "servicenetworking.services.addDnsZone", "dnsZones\.remove": "servicenetworking.services.removeDnsZone",
           "projects\.global\.networks\.dnsZones\.(?:get|list)": "servicenetworking.services.get", "projects\.global\.networks\.get": "servicenetworking.services.getConsumerConfig",
           "projects\.global\.networks\.getVpcServiceControls": "servicenetworking.services.getVpcServiceControls", "projects\.global\.networks\.updateConsumerConfig": "servicenetworking.services.updateConsumerConfig",
           "projects\.global\.networks\.peeredDnsDomains\.create": "servicenetworking.services.createPeeredDnsDomain", "projects\.global\.networks\.peeredDnsDomains\.delete": "servicenetworking.services.deletePeeredDnsDomain",
           "projects\.global\.networks\.peeredDnsDomains\.list": "servicenetworking.services.listPeeredDnsDomains"}, "Service Networking")
    + [(r"^iap\.(?:getIamPolicy)$", ["iap.web.getIamPolicy"], "IAP web resource policy"), (r"^iap\.setIamPolicy$", ["iap.web.setIamPolicy"], "IAP web resource policy"),
       (r"^iap\.getIapSettings$", ["iap.web.getSettings"], "IAP settings"), (r"^iap\.updateIapSettings$", ["iap.web.updateSettings"], "IAP settings")]
    + _grp(r"iap\.projects\.iap_tunnel\.locations\.destGroups", {"create": "iap.tunnelDestGroups.create", "get": "iap.tunnelDestGroups.get", "list": "iap.tunnelDestGroups.list",
           "patch": "iap.tunnelDestGroups.update", "delete": "iap.tunnelDestGroups.delete"}, "IAP TCP destination groups")
    + _grp(r"compute\.(?:region)?InstanceGroupManagerResizeRequests", {"insert|cancel|delete": "compute.instanceGroupManagers.update", "get|list": "compute.instanceGroupManagers.get"}, "resize requests act on the managed instance group")
    + _grp(r"compute\.(?:imageViews|imageFamilyViews)", {"get": "compute.images.get", "list": "compute.images.list"}, "image views read images")
    + _grp(r"compute\.projects", {"enableXpnHost": "compute.organizations.enableXpnHost", "disableXpnHost": "compute.organizations.disableXpnHost",
           "enableXpnResource": "compute.organizations.enableXpnResource", "disableXpnResource": "compute.organizations.disableXpnResource"}, "Shared VPC administration is compute.organizations.*Xpn*")
    + _grp(r"backupdr\.projects\.locations\.backupVaults\.dataSources", {"get": "backupdr.bvdatasources.get", "list": "backupdr.bvdatasources.list", "patch": "backupdr.bvdatasources.update",
           "abandonBackup": "backupdr.bvdatasources.abandonBackup", "fetchAccessToken": "backupdr.bvdatasources.fetchAccessToken", "finalizeBackup": "backupdr.bvdatasources.finalizeBackup",
           "initiateBackup": "backupdr.bvdatasources.initiateBackup", "remove": "backupdr.bvdatasources.remove", "setInternalStatus": "backupdr.bvdatasources.setInternalStatus"},
           "backup vault data sources are the bvdatasources.* permission family")
    + _grp(r"backupdr\.projects\.locations\.backupVaults\.dataSources\.backups", {"get": "backupdr.bvbackups.get", "list": "backupdr.bvbackups.list", "patch": "backupdr.bvbackups.update",
           "delete": "backupdr.bvbackups.delete", "restore": "backupdr.bvbackups.restore"}, "backup vault backups are the bvbackups.* permission family")
    + _grp(r"backupdr\.projects\.locations\.autoProtectionPolicies\.bindings", {"create": "backupdr.autoprotectionbindings.create", "get": "backupdr.autoprotectionbindings.get",
           "list": "backupdr.autoprotectionbindings.list", "initiateDelete": "backupdr.autoprotectionbindings.delete"}, "auto protection bindings")
    + _grp(r"firestore\.projects\.databases\.documents", {"listen": "datastore.entities.get", "partitionQuery|executePipeline": "datastore.entities.list", "write": "datastore.entities.update"},
           "Firestore streaming/pipeline document methods use the datastore.entities.* permissions (Firestore in Native mode shares them)")
    + [(r"^binaryauthorization\.(?:projects|systempolicy)\.getPolicy$", ["binaryauthorization.policy.get"], "get policy"),
       (r"^binaryauthorization\.projects\.updatePolicy$", ["binaryauthorization.policy.update"], "update policy"),
       (r"^binaryauthorization\.projects\.platforms\.gke\.policies\.evaluate$", ["binaryauthorization.platformPolicies.evaluatePolicy"], "evaluate platform policy"),
       (r"^binaryauthorization\.projects\.platforms\.policies\.replacePlatformPolicy$", ["binaryauthorization.platformPolicies.replace"], "replace platform policy"),
       (r"^apphub\.projects\.locations\.discoveredServices\.lookup$", ["apphub.discoveredServices.get"], "lookup reads the discovered service"),
       (r"^apphub\.projects\.locations\.discoveredWorkloads\.lookup$", ["apphub.discoveredWorkloads.get"], "lookup reads the discovered workload"),
       (r"^apphub\.projects\.locations\.lookupServiceProjectAttachment$", ["apphub.serviceProjectAttachments.lookup"], "lookup attachment"),
       (r"^apphub\.projects\.locations\.detachServiceProjectAttachment$", ["apphub.serviceProjectAttachments.detach"], "detach attachment")]
    + _grp(r"identitytoolkit\.(?:projects\.(?:tenants\.)?)?accounts", {"lookup|query|batchGet": "firebaseauth.users.get", "update": "firebaseauth.users.update",
           "delete|batchDelete": "firebaseauth.users.delete", "batchCreate|signUp": "firebaseauth.users.create", "sendOobCode": "firebaseauth.users.sendEmail"}, "Identity Toolkit admin account methods")
    + _grp(r"identitytoolkit\.projects(?:\.tenants)?", {"createSessionCookie": "firebaseauth.users.createSession", "queryAccounts": "firebaseauth.users.get"}, "session cookies / query")
)


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
            # The flatPath names every collection (/v1/projects/{p}/locations/{l}/indexes/{i}); the plain path is the generic /v1/{+name},
            # which cannot tell resources apart. Use the flat template when Discovery has one (precise matching), else the plain one.
            variants = {path} if m.get("flatPath") else {(sp + "/" + m["path"].lstrip("/")).replace("//", "/")}
            if verb in NO_PERMISSION_VERBS:
                perm = []
            elif next((r for r in RULES if r[1] and re.match(r[0], mid)), None):
                rule = next(r for r in RULES if r[1] and re.match(r[0], mid))
                perm = list(rule[1])
            elif mid in OVERRIDES:
                perm = list(OVERRIDES[mid][0])
            else:
                p1, fb = derive(mid, perms, lower)
                if not p1:
                    p1, fb = derive_ext(mid, lower)
                perm = [p1] if p1 else None
                if perm is None:
                    al = next((a for a in ALIASES if re.match(a[0], mid) and all(x in perms for x in a[1])), None)
                    if al:
                        perm, fb = list(al[1]), True
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

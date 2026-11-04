"""GCP Admin Activity audit log derivation — substrate-independent, stdlib only.

Every successful mutating call served on a GCP control-plane wire is described as a Cloud Audit
Log entry (`cloudaudit.googleapis.com/activity`, protoPayload type AuditLog) and written into the
Cloud Logging core, exactly where `gcloud logging read` / the Logs Explorer / Eventarc Audit-Log
triggers / the Privacy & Security page read it back. Only calls in the table below are described
(the well-known resource create/update/delete/IAM methods); read calls and Data Access logs are not
generated here (Data Access logs come from the IAM audit-config path).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

# (http methods, path regex, serviceName, methodName, resource template using regex groups)
_TABLE = [
    (("POST",), r"^/storage/v1/b$", "storage.googleapis.com", "storage.buckets.create", "projects/_/buckets/{bucket}"),
    (("DELETE",), r"^/storage/v1/b/([^/]+)$", "storage.googleapis.com", "storage.buckets.delete", "projects/_/buckets/{1}"),
    (("PATCH", "PUT"), r"^/storage/v1/b/([^/]+)$", "storage.googleapis.com", "storage.buckets.update", "projects/_/buckets/{1}"),
    (("POST",), r"^/v1/projects/([^/]+)/locations/([^/]+)/keyRings$", "cloudkms.googleapis.com", "google.cloud.kms.v1.KeyManagementService.CreateKeyRing", "projects/{1}/locations/{2}/keyRings"),
    (("POST",), r"^/v1/(projects/[^/]+/locations/[^/]+/keyRings/[^/]+)/cryptoKeys$", "cloudkms.googleapis.com", "google.cloud.kms.v1.KeyManagementService.CreateCryptoKey", "{1}/cryptoKeys"),
    (("POST",), r"^/v1/(projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/:]+)/cryptoKeyVersions:import$", "cloudkms.googleapis.com", "google.cloud.kms.v1.KeyManagementService.ImportCryptoKeyVersion", "{1}"),
    (("POST",), r"^/v1/(projects/[^/]+/locations/[^/]+/keyRings/[^/]+)/importJobs$", "cloudkms.googleapis.com", "google.cloud.kms.v1.KeyManagementService.CreateImportJob", "{1}/importJobs"),
    (("POST",), r"^/v1/projects/([^/]+)/secrets$", "secretmanager.googleapis.com", "google.cloud.secretmanager.v1.SecretManagerService.CreateSecret", "projects/{1}/secrets"),
    (("DELETE",), r"^/v1/(projects/[^/]+/secrets/[^/:]+)$", "secretmanager.googleapis.com", "google.cloud.secretmanager.v1.SecretManagerService.DeleteSecret", "{1}"),
    (("PUT",), r"^/v1/(projects/[^/]+/topics/[^/:]+)$", "pubsub.googleapis.com", "google.pubsub.v1.Publisher.CreateTopic", "{1}"),
    (("DELETE",), r"^/v1/(projects/[^/]+/topics/[^/:]+)$", "pubsub.googleapis.com", "google.pubsub.v1.Publisher.DeleteTopic", "{1}"),
    (("PUT",), r"^/v1/(projects/[^/]+/subscriptions/[^/:]+)$", "pubsub.googleapis.com", "google.pubsub.v1.Subscriber.CreateSubscription", "{1}"),
    (("POST",), r"^/v2/(projects/[^/]+/locations/[^/]+)/services$", "run.googleapis.com", "google.cloud.run.v2.Services.CreateService", "{1}/services"),
    (("DELETE",), r"^/v2/(projects/[^/]+/locations/[^/]+/services/[^/:]+)$", "run.googleapis.com", "google.cloud.run.v2.Services.DeleteService", "{1}"),
    (("POST",), r"^/v2/(projects/[^/]+/locations/[^/]+)/jobs$", "run.googleapis.com", "google.cloud.run.v2.Jobs.CreateJob", "{1}/jobs"),
    (("POST",), r"^/v2/(projects/[^/]+/locations/[^/]+/jobs/[^/:]+):run$", "run.googleapis.com", "google.cloud.run.v2.Jobs.RunJob", "{1}"),
    (("POST",), r"^/v1/projects/([^/]+)/databases$", "firestore.googleapis.com", "google.firestore.admin.v1.FirestoreAdmin.CreateDatabase", "projects/{1}/databases"),
    (("DELETE",), r"^/v1/(projects/[^/]+/databases/[^/:]+)$", "firestore.googleapis.com", "google.firestore.admin.v1.FirestoreAdmin.DeleteDatabase", "{1}"),
    (("POST",), r"^/v1/projects/([^/]+)/rulesets$", "firebaserules.googleapis.com", "google.firebase.rules.v1.FirebaseRulesService.CreateRuleset", "projects/{1}/rulesets"),
    (("POST",), r"^/v1/projects/([^/]+)/releases$", "firebaserules.googleapis.com", "google.firebase.rules.v1.FirebaseRulesService.CreateRelease", "projects/{1}/releases"),
    (("POST",), r"^/sql/v1beta4/projects/([^/]+)/instances$", "sqladmin.googleapis.com", "cloudsql.instances.create", "projects/{1}/instances"),
    (("DELETE",), r"^/sql/v1beta4/projects/([^/]+)/instances/([^/]+)$", "sqladmin.googleapis.com", "cloudsql.instances.delete", "projects/{1}/instances/{2}"),
    (("POST",), r"^/compute/[^/]+/projects/([^/]+)/zones/([^/]+)/instances$", "compute.googleapis.com", "v1.compute.instances.insert", "projects/{1}/zones/{2}/instances"),
    (("DELETE",), r"^/compute/[^/]+/projects/([^/]+)/zones/([^/]+)/instances/([^/]+)$", "compute.googleapis.com", "v1.compute.instances.delete", "projects/{1}/zones/{2}/instances/{3}"),
    (("POST",), r"^/compute/[^/]+/projects/([^/]+)/global/networks$", "compute.googleapis.com", "v1.compute.networks.insert", "projects/{1}/global/networks"),
    (("POST",), r"^/compute/[^/]+/projects/([^/]+)/global/firewalls$", "compute.googleapis.com", "v1.compute.firewalls.insert", "projects/{1}/global/firewalls"),
    (("POST",), r"^/compute/[^/]+/projects/([^/]+)/zones/([^/]+)/disks/([^/]+)/createSnapshot$", "compute.googleapis.com", "v1.compute.disks.createSnapshot", "projects/{1}/zones/{2}/disks/{3}"),
    (("POST",), r"^/v1/(projects/[^/]+/locations/[^/]+)/clusters$", "container.googleapis.com", "google.container.v1.ClusterManager.CreateCluster", "{1}/clusters"),
    (("DELETE",), r"^/v1/(projects/[^/]+/locations/[^/]+/clusters/[^/:]+)$", "container.googleapis.com", "google.container.v1.ClusterManager.DeleteCluster", "{1}"),
    (("POST",), r"^/v1/projects/([^/]+)/serviceAccounts$", "iam.googleapis.com", "google.iam.admin.v1.CreateServiceAccount", "projects/{1}/serviceAccounts"),
    (("POST",), r"^/v1/(projects/[^/:]+):setIamPolicy$", "cloudresourcemanager.googleapis.com", "SetIamPolicy", "{1}"),
]
_COMPILED = [(m, re.compile(rx), svc, meth, tpl) for m, rx, svc, meth, tpl in _TABLE]


def describe(method: str, path: str):
    p = path.split("?", 1)[0]
    for ms, rx, svc, meth, tpl in _COMPILED:
        if method.upper() in ms:
            m = rx.match(p)
            if m:
                res = tpl
                for i, g in enumerate(m.groups(), 1):
                    res = res.replace("{%d}" % i, g or "")
                return svc, meth, res
    return None


def _project_of(path: str, query: dict, res: str) -> str:
    m = re.search(r"projects/([^/_][^/]*)", res) or re.search(r"/projects/([^/:]+)", path)
    if m:
        return m.group(1)
    return str((query or {}).get("project") or "") or ""


def build_entry(method: str, path: str, status: int, query: dict | None, headers: dict | None, body_json: dict | None = None):
    """-> a LogEntry (dict) for the call, or None when it is not an audited mutation."""
    if status >= 400:
        return None
    d = describe(method, path)
    if not d:
        return None
    svc, meth, res = d
    if res.endswith("{bucket}"):
        res = res.replace("{bucket}", str((body_json or {}).get("name") or ""))
    project = _project_of(path, query or {}, res)
    if not project:
        return None
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    who = h.get("x-cloudlearn-principal") or h.get("x-vyomi-principal") or "admin@vyomi.local"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return {
        "logName": "projects/%s/logs/cloudaudit.googleapis.com%%2Factivity" % project,
        "resource": {"type": "audited_resource", "labels": {"service": svc, "method": meth}},
        "severity": "NOTICE", "timestamp": now,
        "insertId": uuid.uuid4().hex[:20],
        "protoPayload": {
            "@type": "type.googleapis.com/google.cloud.audit.AuditLog",
            "serviceName": svc, "methodName": meth, "resourceName": res,
            "authenticationInfo": {"principalEmail": who},
            "requestMetadata": {"callerIp": h.get("x-forwarded-for", "127.0.0.1").split(",")[0].strip(), "callerSuppliedUserAgent": h.get("user-agent", "vyomi")},
            "authorizationInfo": [{"resource": res, "permission": meth, "granted": True}],
            "status": {},
        },
        "labels": {"vyomi.audit": "admin-activity"},
    }

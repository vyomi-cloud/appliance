"""Cloud-provider plugin registry for the WASM (Nano) substrate.

ADDING A NEW CLOUD (Oracle, IBM, Alibaba, DigitalOcean, ...) is additive:
write a module that subclasses CloudProvider, map its API operations to the
shared generic backends (object-store / nosql / queue / ...), and call
`register(MyCloud())`. No core change, no new storage logic, no fork — exactly
the ADR-001 model carried into the browser.

The service worker (sw.js) hands each intercepted SDK request to `dispatch()`,
which routes (provider, service, operation, params) to the right plugin.
"""
from __future__ import annotations

from typing import Any, Callable

from ..backends.store import Backends

# An operation handler: (backends, account, params) -> response dict
Handler = Callable[[Backends, str, dict], dict]


class CloudProvider:
    """Base class. A cloud declares its id + a map of (service, op) -> handler."""
    id: str = ""           # "aws" | "gcp" | "azure" | "oracle" | ...
    label: str = ""
    # how the SW recognises this cloud's requests (host suffix / path prefix /
    # x-amz-target style). Kept declarative so the SW stays provider-agnostic.
    match_hosts: tuple[str, ...] = ()
    match_paths: tuple[str, ...] = ()

    def handlers(self) -> dict[tuple[str, str], Handler]:
        """Return {(service, operation): handler}. Override in each cloud."""
        return {}


_REGISTRY: dict[str, CloudProvider] = {}

# ── Per-resource cloudsim event/activity log ────────────────────────────────
# Which operations count as "mutating" → recorded in the activity log. Keyed by
# the operation name the console dispatches (catalog CRUD + lifecycle + the few
# native sub-resource ops GCP/Azure funnel through _resource_dispatch). Reads
# (List/Get/Query/Scan/…) are intentionally NOT logged — only state changes.
_MUTATING_OPS = {
    "Create", "Update", "Delete", "Terminate", "Start", "Stop", "Reboot", "Modify",
    # native sub-resource ops seen on the _resource path (GCP cores)
    "CreateSubscription", "CreateDatabase", "DeleteObject", "PutObject", "Pause", "Resume", "Run", "Resize", "Upgrade", "Failover",
}


def _emit_event(provider: str, service: str, resource: str, action: str,
                result: dict | None = None) -> None:
    """Best-effort: append one cloudsim event for a mutating op. NEVER raises —
    event logging must not break a request (that's a hard rule of the boundary)."""
    try:
        from core import nano_events
        ok = True
        if isinstance(result, dict) and result.get("ok") is False:
            ok = False
        status = "ok" if ok else (str(result.get("code")) if isinstance(result, dict) and result.get("code") else "error")
        detail = f"{action} {service}" + (f"/{resource}" if resource else "") + " " + (
            "completed" if ok else "failed: " + str((result or {}).get("message") or status))
        nano_events.record(provider=provider, service=service, resource=resource or "",
                           action=action, status=status, detail=detail)
    except Exception:
        pass


def _events_query(params: dict) -> dict:
    """Serve the console's resource-events fetch. params may carry
    {resource, provider, service, limit}. Returns {ok, events:[…]} newest-first."""
    try:
        from core import nano_events
        evs = nano_events.list_events(
            resource=params.get("resource") or None,
            provider=params.get("provider") or None,
            service=params.get("service") or None,
            limit=int(params.get("limit") or 200),
        )
        return {"ok": True, "events": evs}
    except Exception as e:
        return {"ok": True, "events": [], "error": str(e)}


def register(provider: CloudProvider) -> None:
    if not provider.id:
        raise ValueError("provider.id is required")
    _REGISTRY[provider.id] = provider


def providers() -> list[str]:
    return sorted(_REGISTRY)


def _resource_dispatch(backends: Backends, provider: str, operation: str,
                       account: str, params: dict) -> dict:
    """Generic catalog-driven CRUD, cloud-agnostic. The console drives every
    service the same way (list/create on collection_path, get/update/delete on
    resource_path), so one handler backs them all. `params.service` is the
    catalog service key (ec2, s3, iam, …); `params.name` the resource id."""
    svc = params.get("service", "")
    name = params.get("name", "")
    body = params.get("body") or {}
    out = _resource_dispatch_inner(backends, provider, operation, account, svc, name, body)
    if provider == "gcp":
        out = _gcp_fill_out(svc, operation, out)
    # cloudsim event: record mutating ops (best-effort). For a sub-resource op the
    # "resource" is the CHILD's name (body.name) when present, else the parent name.
    if operation in _MUTATING_OPS:
        res_name = str(body.get("name") or name or "") if operation in (
            "CreateSubscription", "CreateDatabase") else str(name or body.get("name") or "")
        _emit_event(provider, svc, res_name, operation, out)
    return out


def _ec2_launch_defaults(body: dict) -> dict:
    """An EC2 launch comes back fully described, like RunInstances: instance id,
    running state, addresses in the default VPC, AMI, AZ and launch time."""
    import time as _t
    import uuid as _u
    h = _u.uuid4().hex
    o = [int(h[i:i + 2], 16) for i in range(0, 8, 2)]
    out = dict(body or {})
    priv = f"10.0.{o[0] % 16 * 16 + o[1] % 16}.{o[2] % 250 + 4}"
    pub = f"54.{160 + o[0] % 80}.{o[1]}.{o[3] % 250 + 2}"
    out.setdefault("instance_id", "i-" + h[8:25])
    out.setdefault("instance_type", "t3.micro")
    out.setdefault("state", "running")
    out.setdefault("status", out["state"])
    out.setdefault("private_ip", priv)
    out.setdefault("public_ip", pub)
    out.setdefault("public_dns", "ec2-" + out["public_ip"].replace(".", "-") + ".compute-1.amazonaws.com")
    out.setdefault("image_id", "ami-0" + h[25:32] + h[:9])
    out.setdefault("availability_zone", "us-east-1a")
    out.setdefault("vpc_id", "vpc-0" + h[:16])
    out.setdefault("subnet_id", "subnet-0" + h[16:32])
    out.setdefault("launch_time", _t.strftime("%Y-%m-%dT%H:%M:%S.000Z", _t.gmtime()))
    return out


def _gcp_fill(svc: str, rec):
    """A GCP resource comes back described the way the real API describes it: the
    fields every grid column reads (state, location, created/updated time, …) are
    filled with provider-shaped defaults when the create form left them out."""
    if not isinstance(rec, dict) or not rec.get("name"):
        return rec
    import time as _t
    now = _t.strftime("%Y-%m-%dT%H:%M:%S.000000Z", _t.gmtime())
    name = str(rec["name"]).rsplit("/", 1)[-1]
    d = {
        "firestore": {"type": "FIRESTORE_NATIVE", "locationId": "us-central1", "state": "READY"},
        "functions": {"state": "ACTIVE", "runtime": "python312", "entryPoint": "handler",
                      "createTime": now, "updateTime": now},
        "apigateway": {"displayName": name, "state": "ACTIVE", "createTime": now},
        "vpc": {"autoCreateSubnetworks": True, "mtu": 1460, "routingConfig": {"routingMode": "REGIONAL"},
                "creationTimestamp": now},
        "eventarc": {"event_provider": "google.cloud.pubsub.topic.v1.messagePublished",
                     "destination": "cloud-run", "region": "us-central1", "state": "ACTIVE"},
        "secretmanager": {"created": rec.get("createTime") or now, "latest_version": "1",
                          "replication": "automatic"},
        "kms": {"keyring": "demo", "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
                "protection": "SOFTWARE", "state": "ENABLED"},
        "compute": {"zone": "us-central1-a", "machineType": "e2-medium"},
    }.get(svc)
    if not d:
        return rec
    out = dict(rec)
    if svc == "kms":
        prim = out.get("primary") if isinstance(out.get("primary"), dict) else {}
        d = {**d, "algorithm": prim.get("algorithm") or d["algorithm"],
             "protection": prim.get("protectionLevel") or d["protection"],
             "state": prim.get("state") or d["state"]}
    if svc == "secretmanager" and isinstance(out.get("replication"), dict):
        d = {k: v for k, v in d.items() if k != "replication"}
        out["replication"] = "automatic" if "automatic" in out["replication"] else "user-managed"
    for k, v in d.items():
        if out.get(k) in (None, "", [], {}):
            out[k] = v
    return out


def _gcp_fill_out(svc: str, operation: str, out):
    if not isinstance(out, dict) or not out.get("ok", True):
        return out
    if operation == "List" and isinstance(out.get("items"), list):
        return {**out, "items": [_gcp_fill(svc, r) for r in out["items"]]}
    if operation in ("Create", "Get", "Update"):
        return _gcp_fill(svc, out)
    return out


def _resource_dispatch_inner(backends: Backends, provider: str, operation: str,
                             account: str, svc: str, name: str, body: dict) -> dict:
    # GCP: the 7 conformance-core services are served by the proven cores (the
    # same ones the relay serves over native google-cloud-* wire), not the
    # generic store. Lazy import to avoid load-order coupling (like _arm_dispatch).
    if provider == "gcp":
        from . import gcp_core_adapter as _gca
        if svc in _gca.GCP_CORE_SERVICES:
            return _gca.resource_op(svc, operation, name, body)
    if provider == "azure":
        from . import azure_core_adapter as _aca
        if svc in _aca.AZURE_DP_SERVICES:
            return _aca.resource_op(svc, operation, name, body)
    r = backends.resources
    if name and provider == "aws" and svc == "ec2" and r.get(provider, account, svc, name) is None:
        # The grid links an instance by its i-… id, the store keys it by Name tag.
        name = next((k for k, v in r.collections.get(provider + "/" + account + "/" + svc, {}).items()
                     if v.get("instance_id") == name), name)
    if operation == "List":
        return {"ok": True, "items": r.list(provider, account, svc)}
    if operation == "Create":
        if provider == "aws" and svc == "ec2":
            body = _ec2_launch_defaults(body)
        if provider == "gcp":   # stored described, so created/updated times stay fixed
            body = _gcp_fill(svc, body)
        return {"ok": True, **r.create(provider, account, svc, body)}
    if operation == "Get":
        rec = r.get(provider, account, svc, name)
        if not rec and name == "_settings":
            # Detail-tab settings that were never saved: an empty record, so the
            # tab renders each field's default (not a 404 for a normal state).
            return {"ok": True, "name": name}
        return {"ok": True, **rec} if rec else {"ok": False, "code": "NotFound", "name": name}
    if operation == "Update":
        rec = r.update(provider, account, svc, name, body)
        return {"ok": True, **rec} if rec else {"ok": False, "code": "NotFound", "name": name}
    if operation == "Delete":
        ok = r.delete(provider, account, svc, name)
        return {"ok": ok, "code": None if ok else "NotFound", "name": name}
    # Lifecycle actions for compute-like resources (EC2 instances, GCE VMs, RDS
    # DBs, …). The console POSTs collection/{name}/{start,stop,reboot,terminate};
    # flip the in-store record's state/status so the grid reflects it. EC2 reads
    # `state` (running/stopped); RDS/most others read `status` — patch both.
    if operation in ("Start", "Stop", "Reboot"):
        rec = r.get(provider, account, svc, name)
        if not rec:
            return {"ok": False, "code": "NotFound", "name": name}
        st, status = {
            "Start":  ("running", "available"),
            "Stop":   ("stopped", "stopped"),
            "Reboot": ("running", "available"),
        }[operation]
        updated = r.update(provider, account, svc, name, {"state": st, "status": status})
        return {"ok": True, **(updated or {"name": name, "state": st, "status": status})}
    if operation == "Terminate":
        # EC2 terminate == remove the instance (console then refetches the list).
        ok = r.delete(provider, account, svc, name)
        return {"ok": ok, "code": None if ok else "NotFound", "name": name}
    return {"ok": False, "code": "UnsupportedOperation", "operation": operation}


def _arm_dispatch(backends: Backends, method: str, params: dict) -> dict:
    """Native Azure Resource Manager control plane. Unlike the generic
    catalog CRUD (which rides /api/{cloud}/{service} paths), the Azure console
    speaks real ARM — /subscriptions/{sub}/resourceGroups/{rg}/providers/
    Microsoft.X/{type}/{name}?api-version= — served verbatim by the substrate-
    free AzureArm core (the in-WASM analogue of azure_services.handle_arm).
    `operation` carries the HTTP method; params carries {path, query, body}.
    Returns the raw HTTP envelope under __http so the SW can honour the real
    ARM status code, headers (Azure-AsyncOperation/Location) and body."""
    arm = getattr(backends, "_azure_arm", None)
    if arm is None:
        # Prefer the SHARED registry instance (the one nano_persist captures/
        # restores) so ARM resources + children are reload-durable; only build a
        # standalone one if the registry is unavailable (isolated tests).
        try:
            from core import nano_registry
            arm = nano_registry.get().get("az_arm")
        except Exception:
            arm = None
        if arm is None:
            from core.azure_arm_core import AzureArm
            arm = AzureArm()
        backends._azure_arm = arm
    resp = arm.handle(method, params.get("path", ""),
                      params.get("query") or {}, params.get("body"))
    return {"ok": resp["status"] < 400, "__http": resp}


# Per-resource weights — kept identical to the appliance's host-distribution
# (server.py) so the Nano dashboard reports the SAME footprint the full appliance
# would: a VM ~ 2 vCPU / 2 GiB / 8 GB, a light resource (bucket, table, key, …) ~ 1/4 VM.
_PER_VM = {"vcpu": 2.0, "ram_mb": 2048, "disk_mb": 8192}
_PER_LIGHT = {"vcpu": 0.5, "ram_mb": 512, "disk_mb": 2048}
# Which catalog/ARM service keys count as a VM (heavier weight) per cloud.
_VM_SERVICES = {
    "aws": {"ec2", "rds"},
    "gcp": {"compute", "gce", "instances", "computeengine"},
    "azure": {"microsoft.compute/virtualmachines"},
}


def _weigh(resources: int, vms: int) -> dict:
    light = max(0, resources - vms)
    return {
        "vcpus":   round(vms * _PER_VM["vcpu"]   + light * _PER_LIGHT["vcpu"],   2),
        "ram_mb":  int(vms * _PER_VM["ram_mb"]   + light * _PER_LIGHT["ram_mb"]),
        "disk_mb": int(vms * _PER_VM["disk_mb"]  + light * _PER_LIGHT["disk_mb"]),
    }


def _logs_group_count() -> int:
    """CloudWatch Logs groups held by the shared in-browser store (core/logs_core.py)."""
    try:
        from core import nano_registry
        return len(nano_registry.get()["logs"].log_groups)
    except Exception:
        return 0


def _elb_census():
    from core import nano_registry
    return nano_registry.get()["elbv2"].load_balancers


def _census_dispatch(backends: Backends, provider: str) -> dict:
    """Count the LIVE in-memory resources this page's backend holds for `provider`,
    across every core store, and weight them the same way the appliance does. The
    console page runs this and persists the result so the (Pyodide-less) dashboard
    can show a REAL per-cloud footprint instead of a nominal per-space estimate."""
    provider = (provider or "").lower()
    by_service: dict[str, int] = {}
    vms = 0
    try:
        # AWS data-plane services are served by the proven cores (module-level
        # singletons in aws_core_adapter), not the generic ResourceStore — count
        # them via the same list handlers the console uses.
        if provider == "aws":
            from . import aws_core_adapter as A
            aws_counts = {
                "s3":             len(A.s3_list_buckets().get("buckets", [])),
                "dynamodb":       len(A.ddb_list_tables().get("tables", [])),
                "kms":            len(A.kms_list_keys().get("value", [])),
                "secretsmanager": len(A.secrets_list().get("value", [])),
                "sqs":            len(A.sqs_list_queues().get("queues", [])),
                "iam": (len(A.iam_list_users().get("users", [])) +
                        len(A.iam_list_roles().get("roles", [])) +
                        len(A.iam_list_policies().get("policies", [])) +
                        len(A.iam_list_groups().get("groups", []))),
                "rds":            len(A.rds_list().get("databases", [])),
                "logs":           _logs_group_count(),
                "elbv2":          len(_elb_census()),
            }
            try:   # Systems Manager parameters live in the shared registry store
                from core import nano_registry
                aws_counts["ssm"] = len(nano_registry.get()["ssm"].parameters)
            except Exception:
                pass
            try:   # Step Functions lives in the shared registry store (console + relay wire)
                from core import nano_registry
                aws_counts["stepfunctions"] = len(nano_registry.get()["sfn"].machines)
            except Exception:
                pass
            try:   # Lambda + API Gateway + VPC live in the shared registry's compute store
                from . import dataplane_adapter as DP
                aws_counts["lambda"] = len(DP.lambda_list().get("functions", []))
                aws_counts["apigateway"] = len(DP.apigw_list().get("apis", []))
                aws_counts["vpc"] = len(DP.vpc_list().get("vpcs", []))
                aws_counts["eventbridge"] = len(DP.extras_list({"key": "eventbridge/rules"}).get("value", []))
            except Exception:
                pass
            for svc, n in aws_counts.items():
                if n:
                    by_service[svc] = by_service.get(svc, 0) + n
            vms += aws_counts["rds"]  # DB instances are VM-like

            # Console compute/network models (dataplane_adapter, persisted registry):
            # Lambda functions, API Gateway APIs, VPCs, and the generic "extras" CRUD
            # (EventBridge rules, EBS volumes, snapshots, …) keyed "service/kind".
            from . import dataplane_adapter as DP
            dp_counts = {
                "lambda":     len(DP.lambda_list().get("functions", [])),
                "apigateway": len(DP.apigw_list().get("apis", [])),
                "vpc":        len(DP.vpc_list().get("vpcs", [])),
            }
            for key, coll in DP._EXTRAS.items():
                dp_counts[key.split("/")[0]] = dp_counts.get(key.split("/")[0], 0) + len(coll)
            for svc, n in dp_counts.items():
                if n:
                    by_service[svc] = by_service.get(svc, 0) + n

        # Generic catalog CRUD collections (EC2, Lambda, and every GCP service)
        # live in the shared ResourceStore, namespaced "provider/account/service".
        vm_svcs = _VM_SERVICES.get(provider, set())
        prefix = provider + "/"
        for key, coll in getattr(backends.resources, "collections", {}).items():
            if not key.startswith(prefix):
                continue
            svc = key.rsplit("/", 1)[-1]
            n = len(coll)
            if not n:
                continue
            by_service[svc] = by_service.get(svc, 0) + n
            if svc.lower() in vm_svcs:
                vms += n

        # Data-plane cores (Azure blob/queue/cosmos/key vault/service bus/sql/rbac and
        # GCP storage/firestore/kms/secrets/pubsub/iam/cloudsql) hold their resources in
        # the cores' own stores, not the ResourceStore — count them via the same list
        # handlers the console uses so created resources reach the savings metrics.
        if provider == "azure":
            from . import azure_core_adapter as AZ
            from . import dataplane_adapter as DP
            for svc in ("blobcontainers", "cosmosdbs", "kvsecrets", "kvkeys", "queues"):
                n = len(AZ.resource_op(svc, "List").get("items", []))
                if n:
                    by_service[svc] = by_service.get(svc, 0) + n
            dp_counts = {
                "servicebus": len(DP.sb_list().get("topics", [])),
                "azuresql":   len(DP.sql_list().get("servers", [])),
                "azurerbac":  len(DP.rbac_list().get("assignments", [])),
            }
            for svc, n in dp_counts.items():
                if n:
                    by_service[svc] = by_service.get(svc, 0) + n
        if provider == "gcp":
            from . import gcp_core_adapter as GC
            for svc in ("storage", "firestore", "kms", "secretmanager", "pubsub", "iam", "cloudsql", "cloudscheduler", "container", "iamcredentials", "redis"):
                n = len(GC.resource_op(svc, "List").get("items", []))
                if n:
                    by_service[svc] = by_service.get(svc, 0) + n

        # Azure resources live in the ARM core's flat state, keyed by resource id.
        if provider == "azure":
            arm = getattr(backends, "_azure_arm", None)
            # AzureArm keeps its flat map in `_state` (lower-cased resource ids). Count
            # top-level resources only (<ns>/<type>/<name>); children (subnets, APIs, …)
            # have longer ids and are not separately billed resources.
            for rid in getattr(arm, "_state", {}) or {}:
                i = rid.find("/providers/")
                if i < 0:
                    continue  # resource groups etc. have no /providers/ segment
                tail = rid[i + len("/providers/"):].split("/")
                if len(tail) != 3:
                    continue
                rtype = (tail[0] + "/" + tail[1]).lower()
                by_service[rtype] = by_service.get(rtype, 0) + 1
                if rtype in _VM_SERVICES["azure"]:
                    vms += 1
    except Exception as e:  # census is best-effort — never break a console
        return {"ok": True, "provider": provider, "resources": 0, "vms": 0,
                "by_service": {}, "error": str(e), **_weigh(0, 0)}

    resources = sum(by_service.values())
    return {"ok": True, "provider": provider, "resources": resources, "vms": vms,
            "by_service": by_service, **_weigh(resources, vms)}


# Verbs that begin a mutating per-cloud handler op (CreateBucket, DeleteTable,
# PutObject, PutItem, Invoke, …). Used to decide whether to log a handler-path op.
_MUTATING_PREFIXES = ("Create", "Delete", "Put", "Update", "Modify", "Start",
                      "Stop", "Reboot", "Terminate", "Invoke", "Send", "Purge",
                      "Authorize", "PutEvent")
# Common param keys that carry a resource name, in priority order.
_NAME_KEYS = ("name", "bucket", "table", "queue", "key", "id", "function", "topic")


def _handler_resource_name(params: dict) -> str:
    for k in _NAME_KEYS:
        v = params.get(k)
        if v:
            return str(v)
    return ""


def dispatch(backends: Backends, provider: str, service: str, operation: str,
             account: str = "default", params: dict | None = None) -> dict:
    """Route one call to the right cloud plugin's handler."""
    # Per-resource cloudsim event/activity log query — provider-neutral pseudo
    # service (the console fetches a resource's events through this). Handled
    # BEFORE the provider lookup so it works even for a neutral provider id.
    if service == "_events":
        return _events_query(params or {})
    p = _REGISTRY.get(provider)
    if p is None:
        return {"ok": False, "code": "UnknownProvider", "provider": provider,
                "available": providers()}
    # Generic catalog-driven CRUD — handled centrally, not per-cloud, so a new
    # cloud's services get list/create/get/update/delete for free.
    if service == "_resource":
        return _resource_dispatch(backends, provider, operation, account, params or {})
    # Native Azure ARM control plane (real /subscriptions/* wire).
    if service == "_arm":
        return _arm_dispatch(backends, operation, params or {})
    # Key Vault secrets/keys data plane for the Azure console (native cores).
    if service == "_kv":
        from . import azure_core_adapter
        return azure_core_adapter.kv_raw(operation, params or {})
    # Live resource census for the dashboard's per-cloud footprint pies.
    if service == "_census":
        return _census_dispatch(backends, provider)
    h = p.handlers().get((service, operation))
    if h is None:
        return {"ok": False, "code": "UnsupportedOperation",
                "provider": provider, "service": service, "operation": operation}
    out = h(backends, account, params or {})
    out.setdefault("ok", True)
    # cloudsim event: record mutating per-cloud handler ops (CreateBucket, PutItem,
    # DeleteQueue, …). Best-effort — never breaks the request.
    if operation.startswith(_MUTATING_PREFIXES):
        _emit_event(provider, service, _handler_resource_name(params or {}), operation, out)
    return out

"""Amazon ECS (EC2 Container Service) core — substrate-independent.

Speaks the NATIVE ECS wire: JSON 1.1 over `POST /` with
`X-Amz-Target: AmazonEC2ContainerServiceV20141113.<Operation>` (botocore model
`ecs`, 2014-11-13), so an unmodified aws-sdk / aws-cli / Terraform / CDK works
against it. No fastapi / boto3 / socket imports -> loads under Pyodide (this exact
file runs offline and in Nano). State lives in an `EcsStore` (plain JSON-safe
dicts) and persists through the store seam (`persist()` hook -> SQLite offline,
IndexedDB in Nano).

What is real: cluster / task-definition (revisions, families, ACTIVE -> INACTIVE ->
DELETE_IN_PROGRESS) / service (deployments, rolling update on a new task
definition, desired-count reconciliation, events) / task (RunTask, StopTask,
containers, network bindings, ENI attachments) / container-instance / capacity
provider / tag / account-setting / attribute lifecycles; native error codes and
messages; nextToken pagination; ListTasks / ListServices filters.

Local-emulator conventions: tasks reach RUNNING immediately (the real service goes
PROVISIONING -> PENDING -> RUNNING). The `runtime` seam (`store.runtime`, optional)
lets the offline appliance back tasks with real containers on the Docker substrate
(Pro / Max); without it (Free / Lite / Nano) the service is a control plane only.
"""
from __future__ import annotations

import base64
import re
import time
import uuid
from dataclasses import dataclass, field

REGION = "us-east-1"
ACCOUNT_ID = "123456789012"
TARGET_PREFIX = "AmazonEC2ContainerServiceV20141113."
_BUILTIN_PROVIDERS = ("FARGATE", "FARGATE_SPOT")


@dataclass
class EcsResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    media_type: str = "application/x-amz-json-1.1"


class EcsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


def _err(code, msg, status=400):
    return EcsError(code, msg, status)


class EcsStore:
    """The seam. Every attribute is plain JSON data (nano_persist / SQLite friendly)."""

    def __init__(self, account_id: str = ACCOUNT_ID, region: str = REGION) -> None:
        self.account_id, self.region = account_id, region
        self.clusters: dict = {}     # name -> cluster
        self.taskdefs: dict = {}     # family -> {"next": int, "revisions": {rev(str) -> taskdef}}
        self.services: dict = {}     # cluster -> {name -> service}
        self.tasks: dict = {}        # cluster -> {taskId -> task}
        self.instances: dict = {}    # cluster -> {instanceId -> container instance}
        self.providers: dict = {}    # name -> capacity provider
        self.tags: dict = {}         # arn -> {key -> value}
        self.settings: dict = {}     # name -> {"value", "principalArn"}
        self.attributes: dict = {}   # cluster -> [attribute]
        self.meta: dict = {}         # arn -> {"created": epoch} (console-only bookkeeping)
        self.runtime = None          # optional container backend (not persisted)

    def persist(self) -> None:
        """Flush hook (no-op in memory)."""


class InMemoryEcsStore(EcsStore):
    pass


# ── helpers ──────────────────────────────────────────────────────────────────
def _now() -> float:
    return round(time.time(), 3)


def _hex(n: int = 32) -> str:
    return uuid.uuid4().hex[:n] if n <= 32 else (uuid.uuid4().hex + uuid.uuid4().hex)[:n]


def _arn(store, kind: str, rest: str) -> str:
    return f"arn:aws:ecs:{store.region}:{store.account_id}:{kind}/{rest}"


def _cluster_arn(store, name):
    return _arn(store, "cluster", name)


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _cname(store, ref) -> str:
    ref = (ref or "default").strip() or "default"
    if ref.startswith("arn:"):
        m = re.fullmatch(r"arn:aws:ecs:[^:]*:[^:]*:cluster/(.+)", ref)
        if not m:
            raise _err("InvalidParameterException", "Invalid cluster reference.")
        return m.group(1)
    return ref


def _cluster(store, ref) -> dict:
    name = _cname(store, ref)
    c = store.clusters.get(name)
    if c is None or c["status"] == "INACTIVE":
        raise _err("ClusterNotFoundException", "Cluster not found.")
    return c


def _tags_in(tags) -> dict:
    out = {}
    for t in tags or []:
        k = t.get("key")
        if not k:
            raise _err("InvalidParameterException", "Tag key must not be empty.")
        out[k] = t.get("value", "")
    return out


def _tags_out(store, arn) -> list:
    return [{"key": k, "value": v} for k, v in (store.tags.get(arn) or {}).items()]


def _with_tags(store, d: dict, arn: str, include) -> dict:
    d = dict(d)
    if include is not None and "TAGS" in include:
        d["tags"] = _tags_out(store, arn)
    else:
        d.pop("tags", None)
    return d


def _page(items: list, limit, token, default=100, maxn=100):
    try:
        start = int(base64.b64decode(token).decode()) if token else 0
    except Exception:
        raise _err("InvalidParameterException", "Invalid token.")
    n = int(limit) if limit else default
    if n < 1 or n > maxn:
        raise _err("InvalidParameterException", f"maxResults must be between 1 and {maxn}.")
    chunk = items[start:start + n]
    nxt = base64.b64encode(str(start + n).encode()).decode() if start + n < len(items) else None
    return chunk, nxt


_OPS: dict = {}


def op(fn):
    _OPS["".join(w.capitalize() for w in fn.__name__.split("_"))] = fn
    return fn


def _req(p: dict, *names):
    for n in names:
        if p.get(n) in (None, "", []):
            raise _err("InvalidParameterException", f"{n} is required.")


# ── clusters ─────────────────────────────────────────────────────────────────
def _cluster_view(store, c: dict, include=None) -> dict:
    name = c["clusterName"]
    tasks = store.tasks.get(name, {}).values()
    svcs = store.services.get(name, {}).values()
    v = dict(c)
    v["registeredContainerInstancesCount"] = sum(1 for i in store.instances.get(name, {}).values() if i["status"] != "INACTIVE")
    v["runningTasksCount"] = sum(1 for t in tasks if t["lastStatus"] == "RUNNING")
    v["pendingTasksCount"] = sum(1 for t in tasks if t["lastStatus"] in ("PROVISIONING", "PENDING"))
    v["activeServicesCount"] = sum(1 for s in svcs if s["status"] == "ACTIVE")
    v["statistics"] = []
    if include and "STATISTICS" in include:
        v["statistics"] = [{"name": "runningEC2TasksCount", "value": "0"}, {"name": "runningFargateTasksCount", "value": str(v["runningTasksCount"])},
                           {"name": "pendingEC2TasksCount", "value": "0"}, {"name": "pendingFargateTasksCount", "value": "0"},
                           {"name": "activeEC2ServiceCount", "value": "0"}, {"name": "activeFargateServiceCount", "value": str(v["activeServicesCount"])},
                           {"name": "drainingEC2ServiceCount", "value": "0"}, {"name": "drainingFargateServiceCount", "value": "0"}]
    return _with_tags(store, v, c["clusterArn"], include)


@op
def create_cluster(store, p):
    name = p.get("clusterName") or "default"
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,255}", name):
        raise _err("InvalidParameterException", "Cluster name must be 1-255 characters: letters, numbers, hyphens and underscores.")
    cur = store.clusters.get(name)
    if cur and cur["status"] != "INACTIVE":
        return {"cluster": _cluster_view(store, cur, ["TAGS", "SETTINGS", "CONFIGURATIONS"])}
    settings = p.get("settings") or [{"name": "containerInsights", "value": "disabled"}]
    for prov in p.get("capacityProviders") or []:
        _provider(store, prov)
    c = {"clusterArn": _cluster_arn(store, name), "clusterName": name, "status": "ACTIVE",
         "registeredContainerInstancesCount": 0, "runningTasksCount": 0, "pendingTasksCount": 0, "activeServicesCount": 0,
         "statistics": [], "tags": [], "settings": settings, "capacityProviders": list(p.get("capacityProviders") or []),
         "defaultCapacityProviderStrategy": list(p.get("defaultCapacityProviderStrategy") or [])}
    if p.get("configuration"):
        c["configuration"] = p["configuration"]
    if p.get("serviceConnectDefaults"):
        c["serviceConnectDefaults"] = p["serviceConnectDefaults"]
    store.clusters[name] = c
    store.services.setdefault(name, {})
    store.tasks.setdefault(name, {})
    store.instances.setdefault(name, {})
    if p.get("tags"):
        store.tags[c["clusterArn"]] = _tags_in(p["tags"])
    store.meta[c["clusterArn"]] = {"created": _now()}
    store.persist()
    return {"cluster": _cluster_view(store, c, ["TAGS", "SETTINGS", "CONFIGURATIONS"])}


@op
def describe_clusters(store, p):
    refs = p.get("clusters") or ["default"]
    include = p.get("include") or []
    out, fail = [], []
    for r in refs:
        name = _cname(store, r)
        c = store.clusters.get(name)
        if c is None:
            fail.append({"arn": _cluster_arn(store, name), "reason": "MISSING"})
        else:
            out.append(_cluster_view(store, c, include))
    return {"clusters": out, "failures": fail}


@op
def list_clusters(store, p):
    arns = [c["clusterArn"] for c in store.clusters.values() if c["status"] != "INACTIVE"]
    chunk, nxt = _page(arns, p.get("maxResults"), p.get("nextToken"))
    return _clean({"clusterArns": chunk, "nextToken": nxt})


@op
def update_cluster(store, p):
    _req(p, "cluster")
    c = _cluster(store, p["cluster"])
    if "settings" in p:
        c["settings"] = p["settings"]
    if "configuration" in p:
        c["configuration"] = p["configuration"]
    if "serviceConnectDefaults" in p:
        c["serviceConnectDefaults"] = p["serviceConnectDefaults"]
    store.persist()
    return {"cluster": _cluster_view(store, c, ["TAGS", "SETTINGS", "CONFIGURATIONS"])}


@op
def update_cluster_settings(store, p):
    _req(p, "cluster", "settings")
    c = _cluster(store, p["cluster"])
    cur = {s["name"]: s["value"] for s in c.get("settings", [])}
    for s in p["settings"]:
        if s.get("name") != "containerInsights" or s.get("value") not in ("enabled", "disabled", "enhanced"):
            raise _err("InvalidParameterException", "The specified setting is invalid.")
        cur[s["name"]] = s["value"]
    c["settings"] = [{"name": k, "value": v} for k, v in cur.items()]
    store.persist()
    return {"cluster": _cluster_view(store, c, ["TAGS", "SETTINGS"])}


@op
def put_cluster_capacity_providers(store, p):
    _req(p, "cluster")
    c = _cluster(store, p["cluster"])
    for prov in p.get("capacityProviders") or []:
        _provider(store, prov)
    c["capacityProviders"] = list(p.get("capacityProviders") or [])
    c["defaultCapacityProviderStrategy"] = list(p.get("defaultCapacityProviderStrategy") or [])
    store.persist()
    return {"cluster": _cluster_view(store, c, ["TAGS", "SETTINGS"])}


@op
def delete_cluster(store, p):
    _req(p, "cluster")
    c = _cluster(store, p["cluster"])
    name = c["clusterName"]
    if any(s["status"] != "INACTIVE" for s in store.services.get(name, {}).values()):
        raise _err("ClusterContainsServicesException", "The Cluster cannot be deleted while Services are active.")
    if any(t["lastStatus"] != "STOPPED" for t in store.tasks.get(name, {}).values()):
        raise _err("ClusterContainsTasksException", "The Cluster cannot be deleted while Tasks are active.")
    if any(i["status"] != "INACTIVE" for i in store.instances.get(name, {}).values()):
        raise _err("ClusterContainsContainerInstancesException", "The Cluster cannot be deleted while Container Instances are active or draining.")
    c["status"] = "INACTIVE"
    v = _cluster_view(store, c, ["TAGS", "SETTINGS"])
    store.persist()
    return {"cluster": v}


# ── capacity providers ───────────────────────────────────────────────────────
def _provider(store, name) -> dict:
    if name in _BUILTIN_PROVIDERS:
        return {"capacityProviderArn": _arn(store, "capacity-provider", name), "name": name, "status": "ACTIVE", "tags": []}
    cp = store.providers.get(name)
    if cp is None or cp["status"] == "INACTIVE":
        raise _err("InvalidParameterException", "The specified capacity provider does not exist. Specify a valid name or ARN and try again.")
    return cp


@op
def create_capacity_provider(store, p):
    _req(p, "name")
    name = p["name"]
    if name in _BUILTIN_PROVIDERS or name.lower().startswith(("aws", "ecs", "fargate")):
        raise _err("InvalidParameterException", "Capacity provider names cannot start with 'aws', 'ecs' or 'fargate'.")
    if name in store.providers and store.providers[name]["status"] == "ACTIVE":
        raise _err("InvalidParameterException", "The specified capacity provider already exists. To change the configuration of an existing capacity provider, update the capacity provider.")
    asg = p.get("autoScalingGroupProvider")
    if not asg or not asg.get("autoScalingGroupArn"):
        raise _err("InvalidParameterException", "autoScalingGroupProvider.autoScalingGroupArn is required.")
    cp = {"capacityProviderArn": _arn(store, "capacity-provider", name), "name": name, "status": "ACTIVE",
          "autoScalingGroupProvider": {"managedScaling": {"status": "DISABLED", "targetCapacity": 100, "minimumScalingStepSize": 1,
                                                          "maximumScalingStepSize": 10000, "instanceWarmupPeriod": 300},
                                       "managedTerminationProtection": "DISABLED", "managedDraining": "ENABLED", **asg},
          "updateStatus": "UPDATE_COMPLETE", "tags": [], "type": "EC2_AUTOSCALING"}
    ms = asg.get("managedScaling")
    if ms:
        cp["autoScalingGroupProvider"]["managedScaling"] = {**cp["autoScalingGroupProvider"]["managedScaling"], **ms}
    store.providers[name] = cp
    if p.get("tags"):
        store.tags[cp["capacityProviderArn"]] = _tags_in(p["tags"])
    store.persist()
    return {"capacityProvider": _with_tags(store, cp, cp["capacityProviderArn"], ["TAGS"])}


@op
def describe_capacity_providers(store, p):
    names = p.get("capacityProviders")
    allp = [_provider(store, n) for n in _BUILTIN_PROVIDERS] + [c for c in store.providers.values() if c["status"] == "ACTIVE"]
    out, fail = [], []
    if names:
        for n in names:
            n = n.rsplit("/", 1)[-1]
            hit = next((c for c in allp if c["name"] == n), None)
            if hit:
                out.append(hit)
            else:
                fail.append({"arn": _arn(store, "capacity-provider", n), "reason": "MISSING"})
    else:
        out = allp
    chunk, nxt = _page(out, p.get("maxResults"), p.get("nextToken"), 10, 10)
    inc = p.get("include") or []
    return _clean({"capacityProviders": [_with_tags(store, c, c["capacityProviderArn"], inc) for c in chunk], "failures": fail, "nextToken": nxt})


@op
def update_capacity_provider(store, p):
    _req(p, "name")
    cp = _provider(store, p["name"])
    if p["name"] in _BUILTIN_PROVIDERS:
        raise _err("InvalidParameterException", "Built-in capacity providers cannot be updated.")
    asg = p.get("autoScalingGroupProvider") or {}
    cp["autoScalingGroupProvider"] = {**cp["autoScalingGroupProvider"], **asg}
    store.persist()
    return {"capacityProvider": cp}


@op
def delete_capacity_provider(store, p):
    _req(p, "capacityProvider")
    name = p["capacityProvider"].rsplit("/", 1)[-1]
    if name in _BUILTIN_PROVIDERS:
        raise _err("InvalidParameterException", "Built-in capacity providers cannot be deleted.")
    cp = _provider(store, name)
    for c in store.clusters.values():
        if c["status"] != "INACTIVE" and name in c.get("capacityProviders", []):
            raise _err("ResourceInUseException", "The specified capacity provider is in use and cannot be removed.")
    cp["status"] = "INACTIVE"
    store.persist()
    return {"capacityProvider": cp}


# ── task definitions ─────────────────────────────────────────────────────────
_NETMODES = ("bridge", "host", "awsvpc", "none")
_FARGATE_CPU_MEM = {256: (512, 2048), 512: (1024, 4096), 1024: (2048, 8192), 2048: (4096, 16384), 4096: (8192, 30720),
                    8192: (16384, 61440), 16384: (32768, 122880)}


def _norm_container(c: dict, netmode: str) -> dict:
    if not c.get("name"):
        raise _err("ClientException", "Container.name should not be null or empty.")
    if not c.get("image"):
        raise _err("ClientException", "Container.image should not be null or empty.")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,255}", c["name"]):
        raise _err("ClientException", "Invalid container name. Container names may contain letters, numbers, underscores and hyphens.")
    v = dict(c)
    v.setdefault("cpu", 0)
    v.setdefault("essential", True)
    ports = []
    for pm in c.get("portMappings") or []:
        cp = pm.get("containerPort")
        if cp is None:
            raise _err("ClientException", "Container.portMappings.containerPort should not be null.")
        hp = pm.get("hostPort", cp if netmode in ("awsvpc", "host") else 0)
        ports.append({"containerPort": cp, "hostPort": hp, "protocol": pm.get("protocol", "tcp")})
    v["portMappings"] = ports
    for k in ("environment", "mountPoints", "volumesFrom", "systemControls"):
        v.setdefault(k, [])
    return v


def _resolve_td(store, ref: str, active_only=False) -> dict:
    ref = (ref or "").strip()
    if ref.startswith("arn:"):
        m = re.fullmatch(r"arn:aws:ecs:[^:]*:[^:]*:task-definition/([^:]+):(\d+)", ref)
        if not m:
            raise _err("ClientException", "Unable to describe task definition.")
        fam, rev = m.group(1), m.group(2)
    elif ":" in ref:
        fam, rev = ref.rsplit(":", 1)
    else:
        fam, rev = ref, None
    f = store.taskdefs.get(fam)
    if not f:
        raise _err("ClientException", "Unable to describe task definition.")
    if rev is None:
        act = [int(r) for r, t in f["revisions"].items() if t["status"] == "ACTIVE"]
        if not act:
            raise _err("ClientException", "Unable to describe task definition.")
        rev = str(max(act))
    td = f["revisions"].get(str(rev))
    if td is None or (active_only and td["status"] != "ACTIVE"):
        raise _err("ClientException", "Unable to describe task definition.")
    return td


@op
def register_task_definition(store, p):
    _req(p, "family", "containerDefinitions")
    fam = p["family"]
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,255}", fam):
        raise _err("ClientException", "Family must be 1-255 characters: letters, numbers, hyphens and underscores.")
    compat = list(p.get("requiresCompatibilities") or [])
    fargate = "FARGATE" in compat
    netmode = p.get("networkMode") or ("awsvpc" if fargate else "bridge")
    if netmode not in _NETMODES:
        raise _err("ClientException", f"Invalid network mode: {netmode}.")
    if fargate and netmode != "awsvpc":
        raise _err("ClientException", "Fargate only supports network mode 'awsvpc'.")
    cpu, mem = p.get("cpu"), p.get("memory")
    if fargate:
        if not cpu or not mem:
            raise _err("ClientException", "Fargate requires task definition to have both cpu and memory.")
        try:
            lo, hi = _FARGATE_CPU_MEM[int(cpu)]
            ok = lo <= int(mem) <= hi
        except Exception:
            ok = False
        if not ok:
            raise _err("ClientException", "No Fargate configuration exists for given values.")
    conts = [_norm_container(c, netmode) for c in p["containerDefinitions"]]
    names = [c["name"] for c in conts]
    if len(set(names)) != len(names):
        raise _err("ClientException", "Duplicate container name.")
    if not any(c["essential"] for c in conts):
        raise _err("ClientException", "Task definition does not have any essential container.")
    f = store.taskdefs.setdefault(fam, {"next": 1, "revisions": {}})
    rev = f["next"]
    f["next"] += 1
    arn = _arn(store, "task-definition", f"{fam}:{rev}")
    reqattrs = [{"name": "com.amazonaws.ecs.capability.docker-remote-api.1.18"}]
    if fargate:
        reqattrs += [{"name": "ecs.capability.task-eni"}]
    if netmode == "awsvpc":
        reqattrs += [{"name": "ecs.capability.task-eni"}] if not fargate else []
    td = _clean({
        "taskDefinitionArn": arn, "containerDefinitions": conts, "family": fam,
        "taskRoleArn": p.get("taskRoleArn"), "executionRoleArn": p.get("executionRoleArn"),
        "networkMode": netmode, "revision": rev, "volumes": list(p.get("volumes") or []), "status": "ACTIVE",
        "requiresAttributes": reqattrs, "placementConstraints": list(p.get("placementConstraints") or []),
        "compatibilities": sorted({"EC2", *(["FARGATE"] if netmode == "awsvpc" and cpu and mem else []), *compat}),
        "requiresCompatibilities": compat or None, "cpu": str(cpu) if cpu else None, "memory": str(mem) if mem else None,
        "runtimePlatform": p.get("runtimePlatform") or ({"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"} if fargate else None),
        "pidMode": p.get("pidMode"), "ipcMode": p.get("ipcMode"), "proxyConfiguration": p.get("proxyConfiguration"),
        "inferenceAccelerators": p.get("inferenceAccelerators"), "ephemeralStorage": p.get("ephemeralStorage"),
        "registeredAt": _now(), "registeredBy": f"arn:aws:iam::{store.account_id}:root"})
    f["revisions"][str(rev)] = td
    if p.get("tags"):
        store.tags[arn] = _tags_in(p["tags"])
    store.persist()
    return {"taskDefinition": td, "tags": _tags_out(store, arn)}


@op
def describe_task_definition(store, p):
    _req(p, "taskDefinition")
    td = _resolve_td(store, p["taskDefinition"])
    out = {"taskDefinition": td}
    if "TAGS" in (p.get("include") or []):
        out["tags"] = _tags_out(store, td["taskDefinitionArn"])
    return out


@op
def deregister_task_definition(store, p):
    _req(p, "taskDefinition")
    if ":" not in p["taskDefinition"]:
        raise _err("ClientException", "You must specify a revision of the task definition to deregister.")
    td = _resolve_td(store, p["taskDefinition"])
    if td["status"] == "ACTIVE":
        td["status"] = "INACTIVE"
        td["deregisteredAt"] = _now()
        store.persist()
    return {"taskDefinition": td}


@op
def delete_task_definitions(store, p):
    _req(p, "taskDefinitions")
    if len(p["taskDefinitions"]) > 10:
        raise _err("InvalidParameterException", "You can delete at most 10 task definitions per request.")
    out, fail = [], []
    for ref in p["taskDefinitions"]:
        try:
            td = _resolve_td(store, ref)
        except EcsError:
            fail.append({"arn": ref, "reason": "MISSING"})
            continue
        if td["status"] == "ACTIVE":
            fail.append({"arn": td["taskDefinitionArn"], "reason": "TaskDefinition is ACTIVE. Deregister it before deleting."})
            continue
        td["status"] = "DELETE_IN_PROGRESS"
        td["deleteRequestedAt"] = _now()
        out.append(td)
    store.persist()
    return {"taskDefinitions": out, "failures": fail}


def _all_tds(store, status="ACTIVE", prefix=None):
    out = []
    for fam, f in store.taskdefs.items():
        if prefix and not fam.startswith(prefix):
            continue
        for rev in sorted(f["revisions"], key=int):
            td = f["revisions"][rev]
            if td["status"] == status:
                out.append(td)
    return out


@op
def list_task_definitions(store, p):
    status = p.get("status") or "ACTIVE"
    tds = _all_tds(store, status, p.get("familyPrefix"))
    arns = [t["taskDefinitionArn"] for t in tds]
    if p.get("sort") == "DESC":
        arns.reverse()
    chunk, nxt = _page(arns, p.get("maxResults"), p.get("nextToken"))
    return _clean({"taskDefinitionArns": chunk, "nextToken": nxt})


@op
def list_task_definition_families(store, p):
    status = p.get("status") or "ACTIVE"
    if status == "ACTIVE":
        fams = sorted({t["family"] for t in _all_tds(store, "ACTIVE")})
    elif status == "INACTIVE":
        fams = sorted(fam for fam, f in store.taskdefs.items() if not any(t["status"] == "ACTIVE" for t in f["revisions"].values()))
    else:
        fams = sorted(store.taskdefs)
    if p.get("familyPrefix"):
        fams = [f for f in fams if f.startswith(p["familyPrefix"])]
    chunk, nxt = _page(fams, p.get("maxResults"), p.get("nextToken"))
    return _clean({"families": chunk, "nextToken": nxt})


# ── tasks ────────────────────────────────────────────────────────────────────
def _task_id(store, cluster, ref) -> str:
    ref = (ref or "").strip()
    if ref.startswith("arn:"):
        m = re.fullmatch(r"arn:aws:ecs:[^:]*:[^:]*:task/(?:([^/]+)/)?([^/]+)", ref)
        if not m:
            raise _err("InvalidParameterException", "Invalid task reference.")
        return m.group(2)
    return ref


def _new_task(store, cname: str, td: dict, *, launch_type, group, started_by, overrides, tags, net, enable_exec, instance=None,
              capacity_provider=None, platform_version=None) -> dict:
    tid = _hex(32)
    tarn = _arn(store, "task", f"{cname}/{tid}")
    now = _now()
    ov = {c["name"]: c for c in (overrides or {}).get("containerOverrides", [])}
    conts = []
    for c in td["containerDefinitions"]:
        o = ov.get(c["name"], {})
        binds = [] if td["networkMode"] == "awsvpc" else [
            {"bindIP": "0.0.0.0", "containerPort": pm["containerPort"], "hostPort": pm["hostPort"] or (32768 + len(conts) * 7 + pm["containerPort"] % 1000),
             "protocol": pm["protocol"]} for pm in c["portMappings"]]
        conts.append(_clean({
            "containerArn": _arn(store, "container", f"{cname}/{tid}/{uuid.uuid4()}"), "taskArn": tarn, "name": c["name"],
            "image": c["image"], "runtimeId": _hex(32) + _hex(32), "lastStatus": "RUNNING", "networkBindings": binds,
            "networkInterfaces": [], "healthStatus": "UNKNOWN", "managedAgents": [], "cpu": str(o.get("cpu", c.get("cpu", 0))),
            "memory": str(c["memory"]) if c.get("memory") else None,
            "memoryReservation": str(c["memoryReservation"]) if c.get("memoryReservation") else None}))
    attachments = []
    if td["networkMode"] == "awsvpc":
        sub = ((net or {}).get("awsvpcConfiguration") or {}).get("subnets") or ["subnet-0a1b2c3d4e5f60718"]
        eni = "eni-" + _hex(17)
        ip = f"10.0.{int(tid[:2], 16) % 250}.{int(tid[2:4], 16) % 250 + 1}"
        attachments = [{"id": str(uuid.uuid4()), "type": "ElasticNetworkInterface", "status": "ATTACHED",
                        "details": [{"name": "subnetId", "value": sub[0]}, {"name": "networkInterfaceId", "value": eni},
                                    {"name": "macAddress", "value": "0a:" + ":".join(tid[i:i + 2] for i in range(4, 14, 2))},
                                    {"name": "privateDnsName", "value": "ip-" + ip.replace(".", "-") + ".ec2.internal"},
                                    {"name": "privateIPv4Address", "value": ip}]}]
        for c in conts:
            c["networkInterfaces"] = [{"attachmentId": attachments[0]["id"], "privateIpv4Address": ip}]
    cpu = (overrides or {}).get("cpu") or td.get("cpu")
    mem = (overrides or {}).get("memory") or td.get("memory")
    t = _clean({
        "attachments": attachments, "attributes": [], "availabilityZone": f"{store.region}a", "capacityProviderName": capacity_provider,
        "clusterArn": _cluster_arn(store, cname), "connectivity": "CONNECTED", "connectivityAt": now,
        "containerInstanceArn": instance["containerInstanceArn"] if instance else None, "containers": conts,
        "cpu": str(cpu) if cpu else None, "memory": str(mem) if mem else None, "createdAt": now, "desiredStatus": "RUNNING",
        "enableExecuteCommand": bool(enable_exec), "group": group or f"family:{td['family']}", "healthStatus": "UNKNOWN",
        "lastStatus": "RUNNING", "launchType": launch_type, "overrides": overrides or {"containerOverrides": [], "inferenceAcceleratorOverrides": []},
        "platformVersion": platform_version if launch_type == "FARGATE" else None,
        "platformFamily": "Linux" if launch_type == "FARGATE" else None, "pullStartedAt": now, "pullStoppedAt": now, "startedAt": now,
        "startedBy": started_by, "tags": [], "taskArn": tarn, "taskDefinitionArn": td["taskDefinitionArn"], "version": 2,
        "ephemeralStorage": td.get("ephemeralStorage") or ({"sizeInGiB": 20} if launch_type == "FARGATE" else None)})
    t.setdefault("attributes", [])
    store.tasks.setdefault(cname, {})[tid] = t
    if tags:
        store.tags[tarn] = _tags_in(tags)
    if store.runtime is not None:
        try:
            store.runtime.start(cname, t, td)
        except Exception:
            pass
    return t


def _stop(store, cname, t, reason, code="UserInitiated"):
    if t["lastStatus"] == "STOPPED":
        return
    now = _now()
    t.update({"lastStatus": "STOPPED", "desiredStatus": "STOPPED", "stoppedAt": now, "stoppingAt": now, "executionStoppedAt": now,
              "stoppedReason": reason, "stopCode": code, "version": t.get("version", 1) + 1})
    for c in t["containers"]:
        c["lastStatus"] = "STOPPED"
        c["exitCode"] = 137 if code == "UserInitiated" else 0
        c["networkBindings"] = c.get("networkBindings", [])
    if t.get("attachments"):
        for a in t["attachments"]:
            a["status"] = "DELETED"
    if store.runtime is not None:
        try:
            store.runtime.stop(cname, t)
        except Exception:
            pass


def _task_view(store, t, include=None):
    return _with_tags(store, t, t["taskArn"], include)


def _pick_instance(store, cname):
    insts = [i for i in store.instances.get(cname, {}).values() if i["status"] == "ACTIVE" and i["agentConnected"]]
    if not insts:
        return None
    load = {i["containerInstanceArn"]: 0 for i in insts}
    for t in store.tasks.get(cname, {}).values():
        if t["lastStatus"] != "STOPPED" and t.get("containerInstanceArn") in load:
            load[t["containerInstanceArn"]] += 1
    return min(insts, key=lambda i: load[i["containerInstanceArn"]])


def _resolve_launch(td, launch_type, strategy, cluster):
    if launch_type:
        if launch_type not in ("EC2", "FARGATE", "EXTERNAL"):
            raise _err("InvalidParameterException", "Unsupported launch type.")
        return launch_type
    if strategy:
        names = [s.get("capacityProvider") for s in strategy]
        return "FARGATE" if any(n in _BUILTIN_PROVIDERS for n in names) else "EC2"
    if cluster.get("defaultCapacityProviderStrategy"):
        names = [s.get("capacityProvider") for s in cluster["defaultCapacityProviderStrategy"]]
        return "FARGATE" if any(n in _BUILTIN_PROVIDERS for n in names) else "EC2"
    return "EC2"


def _check_launch(td, launch_type):
    comp = td.get("requiresCompatibilities") or []
    if launch_type == "FARGATE" and "FARGATE" not in comp:
        raise _err("InvalidParameterException", "Task definition does not support launch_type FARGATE.")
    if launch_type == "EC2" and comp and "EC2" not in comp:
        raise _err("InvalidParameterException", "Task definition does not support launch_type EC2.")


def _pv(v):
    return "1.4.0" if not v or v == "LATEST" else v


@op
def run_task(store, p):
    _req(p, "taskDefinition")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    count = int(p.get("count") or 1)
    if count < 1 or count > 10:
        raise _err("InvalidParameterException", "Count must be between 1 and 10.")
    td = _resolve_td(store, p["taskDefinition"], active_only=True)
    lt = _resolve_launch(td, p.get("launchType"), p.get("capacityProviderStrategy"), c)
    _check_launch(td, lt)
    if td["networkMode"] == "awsvpc" and not (p.get("networkConfiguration") or {}).get("awsvpcConfiguration"):
        raise _err("InvalidParameterException", "Network Configuration must be provided when networkMode 'awsvpc' is specified.")
    started, failures = [], []
    for _ in range(count):
        inst = None
        if lt == "EC2":
            inst = _pick_instance(store, cname)
            if inst is None:
                failures.append({"reason": "No Container Instances were found in your cluster."})
                break
        started.append(_new_task(store, cname, td, launch_type=lt, group=p.get("group"), started_by=p.get("startedBy"),
                                 overrides=p.get("overrides"), tags=p.get("tags"), net=p.get("networkConfiguration"),
                                 enable_exec=p.get("enableExecuteCommand"), instance=inst, platform_version=_pv(p.get("platformVersion"))))
    store.persist()
    return {"tasks": [_task_view(store, t, ["TAGS"] if p.get("tags") else None) for t in started], "failures": failures}


@op
def start_task(store, p):
    _req(p, "taskDefinition", "containerInstances")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    td = _resolve_td(store, p["taskDefinition"], active_only=True)
    started, failures = [], []
    for ref in p["containerInstances"]:
        iid = ref.rsplit("/", 1)[-1]
        inst = store.instances.get(cname, {}).get(iid)
        if not inst or inst["status"] == "INACTIVE":
            failures.append({"arn": ref, "reason": "MISSING"})
            continue
        started.append(_new_task(store, cname, td, launch_type="EC2", group=p.get("group"), started_by=p.get("startedBy"),
                                 overrides=p.get("overrides"), tags=p.get("tags"), net=p.get("networkConfiguration"),
                                 enable_exec=p.get("enableExecuteCommand"), instance=inst))
    store.persist()
    return {"tasks": started, "failures": failures}


@op
def stop_task(store, p):
    _req(p, "task")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    t = store.tasks.get(cname, {}).get(_task_id(store, cname, p["task"]))
    if t is None:
        raise _err("InvalidParameterException", "The referenced task was not found.")
    _stop(store, cname, t, p.get("reason") or "Task stopped by user")
    store.persist()
    return {"task": t}


def _match_tasks(store, cname, refs):
    out, fail = [], []
    for r in refs:
        t = store.tasks.get(cname, {}).get(_task_id(store, cname, r))
        if t is None:
            fail.append({"arn": r if r.startswith("arn:") else _arn(store, "task", f"{cname}/{r}"), "reason": "MISSING"})
        else:
            out.append(t)
    return out, fail


@op
def describe_tasks(store, p):
    _req(p, "tasks")
    c = _cluster(store, p.get("cluster"))
    out, fail = _match_tasks(store, c["clusterName"], p["tasks"])
    return {"tasks": [_task_view(store, t, p.get("include")) for t in out], "failures": fail}


@op
def list_tasks(store, p):
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    want = p.get("desiredStatus") or "RUNNING"
    ts = [t for t in store.tasks.get(cname, {}).values() if t["desiredStatus"] == want]
    if p.get("family"):
        ts = [t for t in ts if t["taskDefinitionArn"].split("/")[-1].rsplit(":", 1)[0] == p["family"]]
    if p.get("serviceName"):
        ts = [t for t in ts if t.get("group") == "service:" + p["serviceName"]]
    if p.get("startedBy"):
        ts = [t for t in ts if t.get("startedBy") == p["startedBy"]]
    if p.get("launchType"):
        ts = [t for t in ts if t.get("launchType") == p["launchType"]]
    if p.get("containerInstance"):
        iid = p["containerInstance"].rsplit("/", 1)[-1]
        ts = [t for t in ts if (t.get("containerInstanceArn") or "").rsplit("/", 1)[-1] == iid]
    ts.sort(key=lambda t: t["createdAt"])
    chunk, nxt = _page([t["taskArn"] for t in ts], p.get("maxResults"), p.get("nextToken"))
    return _clean({"taskArns": chunk, "nextToken": nxt})


# ── services ─────────────────────────────────────────────────────────────────
def _svc_name(store, cname, ref) -> str:
    ref = (ref or "").strip()
    if ref.startswith("arn:"):
        m = re.fullmatch(r"arn:aws:ecs:[^:]*:[^:]*:service/(?:([^/]+)/)?([^/]+)", ref)
        if not m:
            raise _err("InvalidParameterException", "Invalid service reference.")
        return m.group(2)
    return ref


def _svc_tasks(store, cname, svc):
    return [t for t in store.tasks.get(cname, {}).values() if t.get("group") == "service:" + svc["serviceName"] and t["lastStatus"] != "STOPPED"]


def _event(svc, msg):
    svc["events"].insert(0, {"id": str(uuid.uuid4()), "createdAt": _now(), "message": msg})
    del svc["events"][100:]


def _counts(store, cname, svc):
    live = _svc_tasks(store, cname, svc)
    for d in svc["deployments"]:
        mine = [t for t in live if t["taskDefinitionArn"] == d["taskDefinition"]]
        d["runningCount"] = sum(1 for t in mine if t["lastStatus"] == "RUNNING")
        d["pendingCount"] = sum(1 for t in mine if t["lastStatus"] in ("PROVISIONING", "PENDING"))
    prim = next((d for d in svc["deployments"] if d["status"] == "PRIMARY"), None)
    svc["runningCount"] = sum(1 for t in live if t["lastStatus"] == "RUNNING")
    svc["pendingCount"] = sum(1 for t in live if t["lastStatus"] in ("PROVISIONING", "PENDING"))
    return prim


def _reconcile(store, cname, svc):
    """Drive running tasks toward desiredCount on the PRIMARY task definition; retire
    tasks of superseded deployments (rolling update); keep deployments/events current."""
    if svc["status"] != "ACTIVE":
        return
    td = _resolve_td(store, svc["taskDefinition"])
    prim = next(d for d in svc["deployments"] if d["status"] == "PRIMARY")
    want = svc["desiredCount"]
    live = _svc_tasks(store, cname, svc)
    for t in [t for t in live if t["taskDefinitionArn"] != td["taskDefinitionArn"]]:
        _stop(store, cname, t, f"Scaling activity initiated by (deployment {prim['id']})", "ServiceSchedulerInitiated")
    live = [t for t in _svc_tasks(store, cname, svc)]
    for t in sorted(live, key=lambda t: t["createdAt"], reverse=True)[want:]:
        _stop(store, cname, t, "Scaling activity initiated by (deployment %s)" % prim["id"], "ServiceSchedulerInitiated")
    live = _svc_tasks(store, cname, svc)
    placed = 0
    for _ in range(max(0, want - len(live))):
        inst = None
        if svc.get("launchType") == "EC2":
            inst = _pick_instance(store, cname)
            if inst is None:
                _event(svc, f"(service {svc['serviceName']}) was unable to place a task because no container instance met all of its requirements.")
                break
        _new_task(store, cname, td, launch_type=svc.get("launchType") or "FARGATE", group="service:" + svc["serviceName"],
                  started_by=prim["id"], overrides=None, tags=None, net=svc.get("networkConfiguration"),
                  enable_exec=svc.get("enableExecuteCommand"), instance=inst, platform_version=_pv(svc.get("platformVersion")))
        placed += 1
    for d in svc["deployments"]:
        if d["status"] == "ACTIVE":
            d["status"] = "INACTIVE"
    svc["deployments"] = [d for d in svc["deployments"] if d["status"] != "INACTIVE"]
    _counts(store, cname, svc)
    prim["desiredCount"] = want
    if svc["runningCount"] == want:
        prim["rolloutState"] = "COMPLETED"
        prim["rolloutStateReason"] = f"ECS deployment {prim['id']} completed."
        _event(svc, f"(service {svc['serviceName']}) has reached a steady state.")
    prim["updatedAt"] = _now()


def _svc_view(store, cname, svc, include=None):
    _counts(store, cname, svc)
    return _with_tags(store, svc, svc["serviceArn"], include)


def _lookup_service(store, cname, ref, active=False) -> dict:
    s = store.services.get(cname, {}).get(_svc_name(store, cname, ref))
    if s is None:
        raise _err("ServiceNotFoundException", "Service not found.")
    if active and s["status"] != "ACTIVE":
        raise _err("ServiceNotActiveException", "Service was not ACTIVE.")
    return s


_DEFAULT_DEPLOY_CFG = {"deploymentCircuitBreaker": {"enable": False, "rollback": False}, "maximumPercent": 200, "minimumHealthyPercent": 100}


def _deploy_id():
    return "ecs-svc/" + "".join(str(int(c, 16) % 10) for c in uuid.uuid4().hex[:19])


@op
def create_service(store, p):
    _req(p, "serviceName")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    name = p["serviceName"]
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,255}", name):
        raise _err("InvalidParameterException", "Service name must be 1-255 characters: letters, numbers, hyphens and underscores.")
    sched = p.get("schedulingStrategy") or "REPLICA"
    if sched not in ("REPLICA", "DAEMON"):
        raise _err("InvalidParameterException", "Unsupported scheduling strategy.")
    if p.get("desiredCount") is None and sched == "REPLICA":
        raise _err("InvalidParameterException", "Desired count is required for services with REPLICA scheduling strategy.")
    if not p.get("taskDefinition") and (p.get("deploymentController") or {}).get("type", "ECS") == "ECS":
        raise _err("InvalidParameterException", "Task definition is required.")
    td = _resolve_td(store, p["taskDefinition"], active_only=True)
    lt = _resolve_launch(td, p.get("launchType"), p.get("capacityProviderStrategy"), c)
    _check_launch(td, lt)
    if td["networkMode"] == "awsvpc" and not (p.get("networkConfiguration") or {}).get("awsvpcConfiguration"):
        raise _err("InvalidParameterException", "Network Configuration must be provided when networkMode 'awsvpc' is specified.")
    cur = store.services.setdefault(cname, {}).get(name)
    desired = int(p.get("desiredCount") or 0)
    if cur and cur["status"] == "ACTIVE":
        if cur["taskDefinition"] == td["taskDefinitionArn"] and cur["desiredCount"] == desired:
            return {"service": _svc_view(store, cname, cur, ["TAGS"])}
        raise _err("InvalidParameterException", "Creation of service was not idempotent.")
    now = _now()
    did = _deploy_id()
    dep_cfg = {**_DEFAULT_DEPLOY_CFG, **(p.get("deploymentConfiguration") or {})}
    svc = _clean({
        "serviceArn": _arn(store, "service", f"{cname}/{name}"), "serviceName": name, "clusterArn": c["clusterArn"],
        "loadBalancers": list(p.get("loadBalancers") or []), "serviceRegistries": list(p.get("serviceRegistries") or []),
        "status": "ACTIVE", "desiredCount": desired, "runningCount": 0, "pendingCount": 0, "launchType": lt,
        "capacityProviderStrategy": p.get("capacityProviderStrategy"), "platformVersion": _pv(p.get("platformVersion")) if lt == "FARGATE" else None,
        "platformFamily": "Linux" if lt == "FARGATE" else None, "taskDefinition": td["taskDefinitionArn"],
        "deploymentConfiguration": dep_cfg, "taskSets": [],
        "deployments": [{"id": did, "status": "PRIMARY", "taskDefinition": td["taskDefinitionArn"], "desiredCount": desired,
                         "pendingCount": 0, "runningCount": 0, "failedTasks": 0, "createdAt": now, "updatedAt": now,
                         "launchType": lt, "platformVersion": _pv(p.get("platformVersion")) if lt == "FARGATE" else None,
                         "platformFamily": "Linux" if lt == "FARGATE" else None,
                         "networkConfiguration": p.get("networkConfiguration"), "rolloutState": "IN_PROGRESS",
                         "rolloutStateReason": f"ECS deployment {did} in progress."}],
        "roleArn": p.get("role") or f"arn:aws:iam::{store.account_id}:role/aws-service-role/ecs.amazonaws.com/AWSServiceRoleForECS",
        "events": [], "createdAt": now, "placementConstraints": list(p.get("placementConstraints") or []),
        "placementStrategy": list(p.get("placementStrategy") or []), "networkConfiguration": p.get("networkConfiguration"),
        "healthCheckGracePeriodSeconds": p.get("healthCheckGracePeriodSeconds") or 0, "schedulingStrategy": sched,
        "deploymentController": p.get("deploymentController") or {"type": "ECS"}, "tags": [],
        "createdBy": f"arn:aws:iam::{store.account_id}:root", "enableECSManagedTags": bool(p.get("enableECSManagedTags")),
        "propagateTags": p.get("propagateTags") or "NONE", "enableExecuteCommand": bool(p.get("enableExecuteCommand"))})
    for d in svc["deployments"]:
        for k in [k for k, v in d.items() if v is None]:
            del d[k]
    if sched == "DAEMON":
        svc["desiredCount"] = svc["deployments"][0]["desiredCount"] = sum(1 for i in store.instances.get(cname, {}).values() if i["status"] == "ACTIVE")
    store.services[cname][name] = svc
    store.meta[svc["serviceArn"]] = {"created": now}
    if p.get("tags"):
        store.tags[svc["serviceArn"]] = _tags_in(p["tags"])
    _reconcile(store, cname, svc)
    store.persist()
    return {"service": _svc_view(store, cname, svc, ["TAGS"])}


@op
def describe_services(store, p):
    _req(p, "services")
    if len(p["services"]) > 10:
        raise _err("InvalidParameterException", "Cannot describe more than 10 services.")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    out, fail = [], []
    for ref in p["services"]:
        s = store.services.get(cname, {}).get(_svc_name(store, cname, ref))
        if s is None:
            fail.append({"arn": ref if ref.startswith("arn:") else _arn(store, "service", f"{cname}/{ref}"), "reason": "MISSING"})
        else:
            out.append(_svc_view(store, cname, s, p.get("include")))
    return {"services": out, "failures": fail}


@op
def list_services(store, p):
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    ss = [s for s in store.services.get(cname, {}).values() if s["status"] == "ACTIVE"
          and (not p.get("launchType") or s.get("launchType") == p["launchType"])
          and (not p.get("schedulingStrategy") or s.get("schedulingStrategy") == p["schedulingStrategy"])]
    ss.sort(key=lambda s: s["createdAt"])
    chunk, nxt = _page([s["serviceArn"] for s in ss], p.get("maxResults"), p.get("nextToken"))
    return _clean({"serviceArns": chunk, "nextToken": nxt})


@op
def update_service(store, p):
    _req(p, "service")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    s = _lookup_service(store, cname, p["service"], active=True)
    prim = next(d for d in s["deployments"] if d["status"] == "PRIMARY")
    new_td = None
    if p.get("taskDefinition"):
        new_td = _resolve_td(store, p["taskDefinition"], active_only=True)
        _check_launch(new_td, s.get("launchType") or "FARGATE")
    if p.get("desiredCount") is not None:
        if s["schedulingStrategy"] == "DAEMON":
            raise _err("InvalidParameterException", "Desired count cannot be updated for services with DAEMON scheduling strategy.")
        if int(p["desiredCount"]) < 0:
            raise _err("InvalidParameterException", "desiredCount must be non-negative.")
        s["desiredCount"] = int(p["desiredCount"])
    for k in ("deploymentConfiguration", "networkConfiguration", "healthCheckGracePeriodSeconds", "placementConstraints",
              "placementStrategy", "enableExecuteCommand", "enableECSManagedTags", "propagateTags", "loadBalancers", "serviceRegistries",
              "capacityProviderStrategy"):
        if k in p:
            s[k] = p[k]
    if p.get("platformVersion"):
        s["platformVersion"] = _pv(p["platformVersion"])
    changed_td = new_td is not None and new_td["taskDefinitionArn"] != s["taskDefinition"]
    if changed_td or p.get("forceNewDeployment"):
        prim["status"] = "ACTIVE"
        did = _deploy_id()
        now = _now()
        s["taskDefinition"] = new_td["taskDefinitionArn"] if new_td else s["taskDefinition"]
        s["deployments"].insert(0, {**{k: v for k, v in prim.items() if k not in ("id", "status")}, "id": did, "status": "PRIMARY",
                                    "taskDefinition": s["taskDefinition"], "createdAt": now, "updatedAt": now, "failedTasks": 0,
                                    "rolloutState": "IN_PROGRESS", "rolloutStateReason": f"ECS deployment {did} in progress."})
        if p.get("forceNewDeployment") and not changed_td:
            for t in _svc_tasks(store, cname, s):
                _stop(store, cname, t, "Task replaced by forced deployment", "ServiceSchedulerInitiated")
    _reconcile(store, cname, s)
    store.persist()
    return {"service": _svc_view(store, cname, s, ["TAGS"])}


@op
def delete_service(store, p):
    _req(p, "service")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    s = _lookup_service(store, cname, p["service"])
    if s["status"] == "INACTIVE":
        raise _err("ServiceNotFoundException", "Service not found.")
    if s["schedulingStrategy"] == "REPLICA" and s["desiredCount"] > 0 and not p.get("force"):
        raise _err("InvalidParameterException", "The service cannot be stopped while it is scaled above 0.")
    for t in _svc_tasks(store, cname, s):
        _stop(store, cname, t, "Service deleted", "ServiceSchedulerInitiated")
    s["status"] = "INACTIVE"
    s["desiredCount"] = 0
    for d in s["deployments"]:
        d["desiredCount"] = 0
    v = _svc_view(store, cname, s, ["TAGS"])
    store.persist()
    return {"service": v}


@op
def list_services_by_namespace(store, p):
    _req(p, "namespace")
    raise _err("NamespaceNotFoundException", "The namespace was not found.")


# ── container instances ──────────────────────────────────────────────────────
def _inst_view(store, cname, i):
    v = dict(i)
    tasks = [t for t in store.tasks.get(cname, {}).values() if t.get("containerInstanceArn") == i["containerInstanceArn"] and t["lastStatus"] != "STOPPED"]
    v["runningTasksCount"] = sum(1 for t in tasks if t["lastStatus"] == "RUNNING")
    v["pendingTasksCount"] = sum(1 for t in tasks if t["lastStatus"] != "RUNNING")
    used_cpu = sum(int(t.get("cpu") or 0) for t in tasks)
    used_mem = sum(int(t.get("memory") or 0) for t in tasks)
    rr = []
    for r in i["registeredResources"]:
        if r["name"] == "CPU":
            rr.append({**r, "integerValue": r["integerValue"] - used_cpu})
        elif r["name"] == "MEMORY":
            rr.append({**r, "integerValue": r["integerValue"] - used_mem})
        else:
            rr.append(r)
    v["remainingResources"] = rr
    return v


@op
def register_container_instance(store, p):
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    iid = _hex(32)
    iarn = _arn(store, "container-instance", f"{cname}/{iid}")
    ident = p.get("instanceIdentityDocument") or ""
    ec2 = "i-" + _hex(17)
    m = re.search(r'"instanceId"\s*:\s*"(i-[0-9a-f]+)"', ident)
    if m:
        ec2 = m.group(1)
    res = p.get("totalResources") or [{"name": "CPU", "type": "INTEGER", "integerValue": 2048},
                                      {"name": "MEMORY", "type": "INTEGER", "integerValue": 3868}]
    inst = {"containerInstanceArn": iarn, "ec2InstanceId": ec2, "version": 1,
            "versionInfo": p.get("versionInfo") or {"agentVersion": "1.79.0", "agentHash": "a1b2c3d4", "dockerVersion": "DockerVersion: 20.10.25"},
            "registeredResources": res, "remainingResources": res, "status": "ACTIVE", "agentConnected": True,
            "runningTasksCount": 0, "pendingTasksCount": 0, "agentUpdateStatus": "UPDATED",
            "attributes": list(p.get("attributes") or []), "registeredAt": _now(), "attachments": [], "tags": []}
    store.instances.setdefault(cname, {})[iid] = inst
    if p.get("tags"):
        store.tags[iarn] = _tags_in(p["tags"])
    store.persist()
    return {"containerInstance": _inst_view(store, cname, inst)}


def _find_instances(store, cname, refs):
    out, fail = [], []
    for r in refs:
        i = store.instances.get(cname, {}).get(r.rsplit("/", 1)[-1])
        if i is None:
            fail.append({"arn": r if r.startswith("arn:") else _arn(store, "container-instance", f"{cname}/{r}"), "reason": "MISSING"})
        else:
            out.append(i)
    return out, fail


@op
def list_container_instances(store, p):
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    want = p.get("status") or "ACTIVE"
    arns = [i["containerInstanceArn"] for i in store.instances.get(cname, {}).values() if i["status"] == want]
    chunk, nxt = _page(arns, p.get("maxResults"), p.get("nextToken"))
    return _clean({"containerInstanceArns": chunk, "nextToken": nxt})


@op
def describe_container_instances(store, p):
    _req(p, "containerInstances")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    out, fail = _find_instances(store, cname, p["containerInstances"])
    return {"containerInstances": [_with_tags(store, _inst_view(store, cname, i), i["containerInstanceArn"], p.get("include")) for i in out], "failures": fail}


@op
def deregister_container_instance(store, p):
    _req(p, "containerInstance")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    out, fail = _find_instances(store, cname, [p["containerInstance"]])
    if fail:
        raise _err("InvalidParameterException", "Could not find container instance.")
    i = out[0]
    running = [t for t in store.tasks.get(cname, {}).values() if t.get("containerInstanceArn") == i["containerInstanceArn"] and t["lastStatus"] != "STOPPED"]
    if running and not p.get("force"):
        raise _err("InvalidParameterException", "Found running tasks on the instance. Use force to deregister.")
    for t in running:
        _stop(store, cname, t, "Container instance deregistered", "TerminationNotice")
    i["status"] = "INACTIVE"
    i["agentConnected"] = False
    store.persist()
    return {"containerInstance": _inst_view(store, cname, i)}


@op
def update_container_instances_state(store, p):
    _req(p, "containerInstances", "status")
    if p["status"] not in ("ACTIVE", "DRAINING"):
        raise _err("InvalidParameterException", "Status must be ACTIVE or DRAINING.")
    c = _cluster(store, p.get("cluster"))
    cname = c["clusterName"]
    out, fail = _find_instances(store, cname, p["containerInstances"])
    for i in out:
        i["status"] = p["status"]
    store.persist()
    return {"containerInstances": [_inst_view(store, cname, i) for i in out], "failures": fail}


# ── tags, settings, attributes ───────────────────────────────────────────────
def _tag_target(store, arn: str):
    if not arn or not arn.startswith("arn:aws:ecs:"):
        raise _err("InvalidParameterException", "The specified resource ARN is invalid.")
    kind = arn.split(":", 5)[5].split("/", 1)[0]
    rest = arn.split(":", 5)[5].split("/", 1)[-1]
    ok = False
    if kind == "cluster":
        ok = rest in store.clusters
    elif kind == "service":
        ok = any(arn == s["serviceArn"] for ss in store.services.values() for s in ss.values())
    elif kind == "task":
        cl, _, tid = rest.partition("/")
        ok = tid in store.tasks.get(cl, {})
    elif kind == "task-definition":
        ok = any(t["taskDefinitionArn"] == arn for f in store.taskdefs.values() for t in f["revisions"].values())
    elif kind == "container-instance":
        cl, _, iid = rest.partition("/")
        ok = iid in store.instances.get(cl, {})
    elif kind == "capacity-provider":
        ok = rest in store.providers
    if not ok:
        raise _err("ResourceNotFoundException", "The specified resource was not found.")


@op
def tag_resource(store, p):
    _req(p, "resourceArn", "tags")
    _tag_target(store, p["resourceArn"])
    cur = store.tags.setdefault(p["resourceArn"], {})
    new = _tags_in(p["tags"])
    if len({**cur, **new}) > 50:
        raise _err("TooManyTagsException", "The maximum number of tags (50) was exceeded.")
    cur.update(new)
    store.persist()
    return {}


@op
def untag_resource(store, p):
    _req(p, "resourceArn", "tagKeys")
    _tag_target(store, p["resourceArn"])
    cur = store.tags.get(p["resourceArn"], {})
    for k in p["tagKeys"]:
        cur.pop(k, None)
    store.persist()
    return {}


@op
def list_tags_for_resource(store, p):
    _req(p, "resourceArn")
    _tag_target(store, p["resourceArn"])
    return {"tags": _tags_out(store, p["resourceArn"])}


_SETTING_NAMES = ("serviceLongArnFormat", "taskLongArnFormat", "containerInstanceLongArnFormat", "awsvpcTrunking", "containerInsights",
                  "fargateFIPSMode", "tagResourceAuthorization", "fargateTaskRetirementWaitPeriod", "guardDutyActivate",
                  "defaultLogDriverMode")
_DEFAULT_SETTINGS = {"serviceLongArnFormat": "enabled", "taskLongArnFormat": "enabled", "containerInstanceLongArnFormat": "enabled",
                     "awsvpcTrunking": "disabled", "containerInsights": "disabled"}


def _put_setting(store, p, default=False):
    _req(p, "name", "value")
    if p["name"] not in _SETTING_NAMES:
        raise _err("InvalidParameterException", f"The account setting name is invalid: {p['name']}.")
    if p["value"] not in ("enabled", "disabled", "on", "off", "enhanced") and not p["value"].isdigit():
        raise _err("InvalidParameterException", "The account setting value is invalid.")
    arn = f"arn:aws:iam::{store.account_id}:root" if default or not p.get("principalArn") else p["principalArn"]
    store.settings[p["name"]] = {"value": p["value"], "principalArn": arn}
    store.persist()
    return {"setting": {"name": p["name"], "value": p["value"], "principalArn": arn, "type": "user"}}


@op
def put_account_setting(store, p):
    return _put_setting(store, p)


@op
def put_account_setting_default(store, p):
    return _put_setting(store, p, True)


@op
def list_account_settings(store, p):
    root = f"arn:aws:iam::{store.account_id}:root"
    cur = {k: {"value": v, "principalArn": root} for k, v in _DEFAULT_SETTINGS.items()}
    cur.update(store.settings)
    items = [{"name": k, "value": v["value"], "principalArn": v["principalArn"], "type": "user" if k in store.settings else "aws-managed"}
             for k, v in sorted(cur.items()) if (not p.get("name") or k == p["name"]) and (not p.get("value") or v["value"] == p["value"])]
    chunk, nxt = _page(items, p.get("maxResults"), p.get("nextToken"), 10, 10)
    return _clean({"settings": chunk, "nextToken": nxt})


@op
def delete_account_setting(store, p):
    _req(p, "name")
    if p["name"] not in _SETTING_NAMES:
        raise _err("InvalidParameterException", f"The account setting name is invalid: {p['name']}.")
    cur = store.settings.pop(p["name"], None)
    store.persist()
    root = f"arn:aws:iam::{store.account_id}:root"
    return {"setting": {"name": p["name"], "value": (cur or {}).get("value") or _DEFAULT_SETTINGS.get(p["name"], "disabled"),
                        "principalArn": (cur or {}).get("principalArn") or root, "type": "user"}}


@op
def put_attributes(store, p):
    _req(p, "attributes")
    c = _cluster(store, p.get("cluster"))
    cur = store.attributes.setdefault(c["clusterName"], [])
    for a in p["attributes"]:
        if not a.get("name"):
            raise _err("InvalidParameterException", "Attribute name is required.")
        a = {**a, "targetType": a.get("targetType") or "container-instance"}
        cur[:] = [x for x in cur if not (x["name"] == a["name"] and x.get("targetId") == a.get("targetId"))]
        cur.append(a)
    store.persist()
    return {"attributes": p["attributes"]}


@op
def list_attributes(store, p):
    _req(p, "targetType")
    c = _cluster(store, p.get("cluster"))
    items = [a for a in store.attributes.get(c["clusterName"], []) if a.get("targetType") == p["targetType"]
             and (not p.get("attributeName") or a["name"] == p["attributeName"])
             and (not p.get("attributeValue") or a.get("value") == p["attributeValue"])]
    chunk, nxt = _page(items, p.get("maxResults"), p.get("nextToken"))
    return _clean({"attributes": chunk, "nextToken": nxt})


@op
def delete_attributes(store, p):
    _req(p, "attributes")
    c = _cluster(store, p.get("cluster"))
    cur = store.attributes.setdefault(c["clusterName"], [])
    gone = []
    for a in p["attributes"]:
        hit = [x for x in cur if x["name"] == a.get("name") and x.get("targetId") == a.get("targetId")]
        if not hit:
            raise _err("TargetNotFoundException", "Could not find attribute.")
        gone += hit
        cur[:] = [x for x in cur if x not in hit]
    store.persist()
    return {"attributes": gone}


@op
def discover_poll_endpoint(store, p):
    return {"endpoint": f"https://ecs.{store.region}.amazonaws.com", "telemetryEndpoint": f"https://ecs-t.{store.region}.amazonaws.com",
            "serviceConnectEndpoint": f"https://ecs-sc.{store.region}.amazonaws.com"}


@op
def update_task_protection(store, p):
    _req(p, "cluster", "tasks", "protectionEnabled")
    c = _cluster(store, p["cluster"])
    out, fail = _match_tasks(store, c["clusterName"], p["tasks"])
    prot = []
    for t in out:
        t["_protected"] = bool(p["protectionEnabled"])
        prot.append({"taskArn": t["taskArn"], "protectionEnabled": bool(p["protectionEnabled"])})
    store.persist()
    return {"protectedTasks": prot, "failures": fail}


@op
def get_task_protection(store, p):
    _req(p, "cluster")
    c = _cluster(store, p["cluster"])
    out, fail = _match_tasks(store, c["clusterName"], p.get("tasks") or [])
    return {"protectedTasks": [{"taskArn": t["taskArn"], "protectionEnabled": bool(t.get("_protected"))} for t in out], "failures": fail}


# ── dispatch ─────────────────────────────────────────────────────────────────
def _result(status, body, errtype=None):
    h = {"x-amzn-requestid": str(uuid.uuid4())}
    if errtype:
        h["x-amzn-errortype"] = errtype
    return EcsResponse(status=status, body=body, headers=h)


_MODEL_OPS = set("""CreateExpressGatewayService CreateTaskSet DeleteExpressGatewayService DeleteTaskSet DescribeServiceDeployments
DescribeServiceRevisions DescribeTaskSets ExecuteCommand ListServiceDeployments StopServiceDeployment SubmitAttachmentStateChanges
SubmitContainerStateChange SubmitTaskStateChange UpdateContainerAgent UpdateExpressGatewayService UpdateServicePrimaryTaskSet
UpdateTaskSet CreateDaemon DeleteDaemon DescribeDaemon DescribeDaemonDeployments DescribeDaemonRevisions DescribeDaemonTaskDefinition
ListDaemonDeployments ListDaemons UpdateDaemon DeleteDaemonTaskDefinition DeregisterDaemonTaskDefinition ListDaemonTaskDefinitions
RegisterDaemonTaskDefinition""".split())


def dispatch(store: EcsStore, target: str, payload: dict | None = None) -> EcsResponse:
    """Native ECS JSON-1.1 router. `target` is the X-Amz-Target header value
    (`AmazonEC2ContainerServiceV20141113.CreateCluster`)."""
    payload = payload if isinstance(payload, dict) else {}
    action = (target or "").split(".", 1)[-1].strip()
    fn = _OPS.get(action)
    if fn is None:
        if action in _MODEL_OPS:
            return _result(400, {"__type": "UnsupportedFeatureException", "message": f"{action} is not implemented by this emulator."},
                           "UnsupportedFeatureException")
        return _result(400, {"__type": "com.amazon.coral.service#UnknownOperationException", "message": ""},
                       "com.amazon.coral.service#UnknownOperationException")
    try:
        return _result(200, fn(store, payload))
    except EcsError as e:
        return _result(e.status, {"__type": e.code, "message": e.message}, e.code)

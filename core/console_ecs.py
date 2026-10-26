"""Console REST facade for Amazon ECS — the friendly JSON the AWS console SPA speaks
(`/api/ecs/...`), served by the SAME engine (core/ecs_core) as the native SDK/CLI
wire. One implementation for the offline appliance (FastAPI route) and Nano
(service-worker -> Pyodide adapter). Pure: stdlib + the core only.

    handle(store, method, path, query, body) -> (status, json-able)

`path` is the part after `/api/ecs`.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from core import ecs_core as ec

PFX = ec.TARGET_PREFIX
_NET = {"awsvpcConfiguration": {"subnets": ["subnet-0a1b2c3d4e5f60718"], "securityGroups": [], "assignPublicIp": "ENABLED"}}


def _iso(epoch) -> str:
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _call(store, op, **p):
    r = ec.dispatch(store, PFX + op, p)
    if r.status >= 400:
        raise ec.EcsError(r.body.get("__type", "Error"), r.body.get("message", op + " failed"), r.status)
    return r.body


def _short(arn: str) -> str:
    return (arn or "").split("/")[-1]


def _td_short(arn: str) -> str:
    return (arn or "").split("task-definition/")[-1]


def _cluster_view(store, c: dict) -> dict:
    v = ec._cluster_view(store, c, ["SETTINGS"])
    name = c["clusterName"]
    insights = next((s["value"] for s in c.get("settings", []) if s["name"] == "containerInsights"), "disabled")
    provs = ", ".join(c.get("capacityProviders") or []) or "None"
    return {"name": name, "arn": c["clusterArn"], "status": v["status"], "services": v["activeServicesCount"],
            "tasks": v["runningTasksCount"], "pending_tasks": v["pendingTasksCount"], "instances": v["registeredContainerInstancesCount"],
            "container_insights": insights.title(), "capacity_providers": provs,
            "created": _iso(store.meta.get(c["clusterArn"], {}).get("created")), "id": name,
            "tags": {t["key"]: t["value"] for t in ec._tags_out(store, c["clusterArn"])}}


def _service_view(store, cname, s: dict) -> dict:
    s = ec._svc_view(store, cname, s)
    dep = next((d for d in s["deployments"] if d["status"] == "PRIMARY"), {})
    return {"id": s["serviceName"], "name": s["serviceName"], "arn": s["serviceArn"], "status": s["status"].title(),
            "task_definition": _td_short(s["taskDefinition"]), "desired": s["desiredCount"], "running": s["runningCount"],
            "pending": s["pendingCount"], "launch_type": s.get("launchType") or "EC2", "scheduling": s["schedulingStrategy"],
            "deployment": (dep.get("rolloutState") or "COMPLETED").replace("_", " ").title(),
            "created": _iso(s["createdAt"])}


def _task_view(store, t: dict) -> dict:
    ip = ""
    for a in t.get("attachments", []):
        for d in a.get("details", []):
            if d["name"] == "privateIPv4Address":
                ip = d["value"]
    return {"id": _short(t["taskArn"]), "task_id": _short(t["taskArn"]), "arn": t["taskArn"], "status": t["lastStatus"].title(),
            "desired_status": t["desiredStatus"].title(), "task_definition": _td_short(t["taskDefinitionArn"]),
            "launch_type": t.get("launchType") or "EC2", "group": t.get("group") or "None", "cpu": t.get("cpu") or "-",
            "memory": t.get("memory") or "-", "private_ip": ip or "None", "started": _iso(t.get("startedAt") or t["createdAt"])}


def _td_view(td: dict) -> dict:
    return {"id": f"{td['family']}:{td['revision']}", "family": td["family"], "revision": td["revision"], "arn": td["taskDefinitionArn"],
            "status": td["status"].title().replace("_", " "), "cpu": td.get("cpu") or "None", "memory": td.get("memory") or "None",
            "network_mode": td["networkMode"], "compatibility": ", ".join(td.get("requiresCompatibilities") or td.get("compatibilities") or ["EC2"]),
            "image": ", ".join(c["image"] for c in td["containerDefinitions"]), "registered": _iso(td.get("registeredAt"))}


def _inst_view(store, cname, i: dict) -> dict:
    v = ec._inst_view(store, cname, i)
    rem = {r["name"]: r.get("integerValue", 0) for r in v["remainingResources"]}
    return {"id": _short(i["containerInstanceArn"]), "arn": i["containerInstanceArn"], "ec2_instance": i["ec2InstanceId"],
            "status": i["status"].title(), "agent_connected": "Yes" if i["agentConnected"] else "No", "running_tasks": v["runningTasksCount"],
            "cpu_available": rem.get("CPU", 0), "memory_available": rem.get("MEMORY", 0), "agent_version": i["versionInfo"].get("agentVersion", ""),
            "registered": _iso(i["registeredAt"])}


def _ensure_td(store, ref, image="nginx:latest"):
    """The console wizards create a sample task definition when the family does not exist yet."""
    fam = ref.split(":")[0]
    if fam not in store.taskdefs or not any(t["status"] == "ACTIVE" for t in store.taskdefs[fam]["revisions"].values()):
        _call(store, "RegisterTaskDefinition", family=fam, requiresCompatibilities=["FARGATE"], networkMode="awsvpc", cpu="256", memory="512",
              containerDefinitions=[{"name": "app", "image": image, "essential": True, "portMappings": [{"containerPort": 80, "protocol": "tcp"}]}])


def handle(store, method, path, query=None, body=None):
    query, body = query or {}, body or {}
    path = "/" + path.strip("/")
    method = method.upper()
    try:
        if path == "/clusters":
            if method == "GET":
                views = [_cluster_view(store, c) for c in sorted(store.clusters.values(), key=lambda c: store.meta.get(c["clusterArn"], {}).get("created", 0))
                         if c["status"] != "INACTIVE"]
                return 200, {"clusters": views, "items": views}
            if method == "POST":
                req = {"clusterName": body.get("name") or "my-cluster",
                       "settings": [{"name": "containerInsights", "value": str(body.get("container_insights") or "disabled").lower()}]}
                cap = [x.strip() for x in str(body.get("capacity_providers") or "FARGATE,FARGATE_SPOT").split(",") if x.strip()]
                if cap:
                    req["capacityProviders"] = cap
                    req["defaultCapacityProviderStrategy"] = [{"capacityProvider": cap[0], "weight": 1, "base": 0}]
                if isinstance(body.get("tags"), dict) and body["tags"]:
                    req["tags"] = [{"key": k, "value": v} for k, v in body["tags"].items()]
                c = _call(store, "CreateCluster", **req)["cluster"]
                return 201, {"ok": True, **_cluster_view(store, store.clusters[c["clusterName"]])}
        m = re.fullmatch(r"/clusters/([^/]+)", path)
        if m:
            name = m.group(1)
            if method == "GET":
                return 200, _cluster_view(store, ec._cluster(store, name))
            if method == "DELETE":
                for s in list(store.services.get(name, {}).values()):
                    if s["status"] == "ACTIVE":
                        _call(store, "DeleteService", cluster=name, service=s["serviceName"], force=True)
                for i in list(store.instances.get(name, {}).values()):
                    if i["status"] != "INACTIVE":
                        _call(store, "DeregisterContainerInstance", cluster=name, containerInstance=_short(i["containerInstanceArn"]), force=True)
                for t in list(store.tasks.get(name, {}).values()):
                    if t["lastStatus"] != "STOPPED":
                        _call(store, "StopTask", cluster=name, task=_short(t["taskArn"]), reason="Cluster deleted")
                _call(store, "DeleteCluster", cluster=name)
                return 200, {"ok": True}
            if method in ("PUT", "PATCH"):
                if body.get("container_insights"):
                    _call(store, "UpdateClusterSettings", cluster=name, settings=[{"name": "containerInsights", "value": str(body["container_insights"]).lower()}])
                if isinstance(body.get("tags"), dict):
                    arn = ec._cluster_arn(store, name)
                    store.tags[arn] = dict(body["tags"])
                    store.persist()
                return 200, _cluster_view(store, ec._cluster(store, name))
        m = re.fullmatch(r"/clusters/([^/]+)/(services|tasks|instances|capacity-providers)", path)
        if m:
            name, kind = m.groups()
            c = ec._cluster(store, name)
            if kind == "services":
                if method == "GET":
                    ss = sorted(store.services.get(name, {}).values(), key=lambda s: s["createdAt"])
                    return 200, {"services": [_service_view(store, name, s) for s in ss if s["status"] == "ACTIVE"]}
                td = body.get("task_definition") or "web"
                _ensure_td(store, td)
                req = {"cluster": name, "serviceName": body.get("service_name") or body.get("name") or "web-service", "taskDefinition": td,
                       "desiredCount": int(body.get("desired_count") or 1), "launchType": "FARGATE", "networkConfiguration": _NET}
                _call(store, "CreateService", **req)
                return 201, {"ok": True}
            if kind == "tasks":
                if method == "GET":
                    ts = sorted(store.tasks.get(name, {}).values(), key=lambda t: t["createdAt"], reverse=True)
                    return 200, {"tasks": [_task_view(store, t) for t in ts if t["lastStatus"] != "STOPPED"]}
                td = body.get("task_definition") or "web"
                _ensure_td(store, td)
                r = _call(store, "RunTask", cluster=name, taskDefinition=td, count=int(body.get("count") or 1), launchType="FARGATE",
                          networkConfiguration=_NET)
                if r["failures"] and not r["tasks"]:
                    raise ec.EcsError("InvalidParameterException", r["failures"][0]["reason"], 400)
                return 201, {"ok": True, "tasks": [_short(t["taskArn"]) for t in r["tasks"]]}
            if kind == "instances":
                if method == "GET":
                    return 200, {"instances": [_inst_view(store, name, i) for i in store.instances.get(name, {}).values() if i["status"] != "INACTIVE"]}
                _call(store, "RegisterContainerInstance", cluster=name)
                return 201, {"ok": True}
            provs = [ec._provider(store, n) for n in c.get("capacityProviders", [])]
            return 200, {"capacity_providers": [{"id": p["name"], "name": p["name"], "status": p["status"].title(), "arn": p["capacityProviderArn"],
                                                 "type": p.get("type") or "Fargate"} for p in provs]}
        m = re.fullmatch(r"/clusters/([^/]+)/(services|tasks|instances)/([^/]+)(?:/([a-z\-]+))?", path)
        if m:
            name, kind, ident, act = m.groups()
            if kind == "services":
                if method == "DELETE":
                    _call(store, "DeleteService", cluster=name, service=ident, force=True)
                    return 200, {"ok": True}
                s = ec._lookup_service(store, name, ident)
                if act in ("scale-up", "scale-down", "restart"):
                    req = {"cluster": name, "service": ident}
                    if act == "restart":
                        req["forceNewDeployment"] = True
                    else:
                        req["desiredCount"] = max(0, s["desiredCount"] + (1 if act == "scale-up" else -1))
                    _call(store, "UpdateService", **req)
                    return 200, {"ok": True}
                return 200, _service_view(store, name, s)
            if kind == "tasks":
                if method == "GET":
                    return 200, _task_view(store, store.tasks[name][ident])
                if act == "stop" or method == "DELETE":
                    _call(store, "StopTask", cluster=name, task=ident, reason="Task stopped by user")
                    return 200, {"ok": True}
            if kind == "instances":
                if act == "drain":
                    _call(store, "UpdateContainerInstancesState", cluster=name, containerInstances=[ident], status="DRAINING")
                    return 200, {"ok": True}
                if act == "activate":
                    _call(store, "UpdateContainerInstancesState", cluster=name, containerInstances=[ident], status="ACTIVE")
                    return 200, {"ok": True}
                if method == "DELETE":
                    _call(store, "DeregisterContainerInstance", cluster=name, containerInstance=ident, force=True)
                    return 200, {"ok": True}
        if path == "/task-definitions":
            if method == "GET":
                tds = ec._all_tds(store, "ACTIVE")
                return 200, {"task_definitions": [_td_view(t) for t in tds]}
            fam = body.get("family") or "web"
            cont = {"name": body.get("container_name") or "app", "image": body.get("image") or "nginx:latest", "essential": True,
                    "portMappings": [{"containerPort": int(body.get("container_port") or 80), "protocol": "tcp"}]}
            td = _call(store, "RegisterTaskDefinition", family=fam, requiresCompatibilities=["FARGATE"], networkMode="awsvpc",
                       cpu=str(body.get("cpu") or "256"), memory=str(body.get("memory") or "512"), containerDefinitions=[cont])["taskDefinition"]
            return 201, {"ok": True, "id": f"{td['family']}:{td['revision']}"}
        m = re.fullmatch(r"/task-definitions/([^/]+)(?:/([a-z\-]+))?", path)
        if m:
            ident, act = m.groups()
            td = ec._resolve_td(store, ident)
            if method == "GET":
                return 200, {**_td_view(td), "definition": td}
            if act == "deregister":
                _call(store, "DeregisterTaskDefinition", taskDefinition=ident)
                return 200, {"ok": True}
            if method == "DELETE":
                if td["status"] == "ACTIVE":
                    _call(store, "DeregisterTaskDefinition", taskDefinition=ident)
                _call(store, "DeleteTaskDefinitions", taskDefinitions=[ident])
                return 200, {"ok": True}
        return 404, {"code": "NotFound", "message": f"No console route {method} {path}"}
    except ec.EcsError as e:
        return e.status, {"ok": False, "code": e.code, "message": e.message}

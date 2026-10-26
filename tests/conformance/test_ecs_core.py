"""Amazon ECS core conformance — host CPython + Pyodide (Nano).

Drives the native JSON-1.1 wire (`AmazonEC2ContainerServiceV20141113.<Op>`) through
core.ecs_core.dispatch: cluster / task-definition / service / task / container-instance
/ capacity-provider / tag / account-setting lifecycles, rolling deployments,
desired-count reconciliation, filters, pagination and the native error codes.
"""
try:
    from core import ecs_core as ec
except ImportError:  # pragma: no cover - Pyodide flat layout
    import ecs_core as ec  # type: ignore

PFX = ec.TARGET_PREFIX
NET = {"awsvpcConfiguration": {"subnets": ["subnet-0a1b2c3d4e5f60718"]}}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or ec.InMemoryEcsStore()

    def call(op, **p):
        r = ec.dispatch(s, PFX + op, p)
        return r.status, r.body

    def ok(op, **p):
        st, b = call(op, **p)
        assert st == 200, (op, st, b)
        return b

    def err(op, code, **p):
        st, b = call(op, **p)
        _check(f"{op} -> {code}", st == 400 and b.get("__type") == code)
        return b

    # clusters
    c = ok("CreateCluster", clusterName="c1", tags=[{"key": "env", "value": "dev"}])["cluster"]
    _check("cluster ACTIVE + arn", c["status"] == "ACTIVE" and c["clusterArn"].endswith(":cluster/c1"))
    _check("CreateCluster is idempotent", ok("CreateCluster", clusterName="c1")["cluster"]["clusterArn"] == c["clusterArn"])
    d = ok("DescribeClusters", clusters=["c1", "nope"], include=["TAGS"])
    _check("DescribeClusters failures MISSING", d["failures"][0]["reason"] == "MISSING" and d["clusters"][0]["tags"] == [{"key": "env", "value": "dev"}])
    _check("ListClusters", ok("ListClusters")["clusterArns"] == [c["clusterArn"]])
    st = ok("UpdateClusterSettings", cluster="c1", settings=[{"name": "containerInsights", "value": "enabled"}])["cluster"]
    _check("UpdateClusterSettings", st["settings"] == [{"name": "containerInsights", "value": "enabled"}])
    err("DescribeTasks", "ClusterNotFoundException", cluster="nope", tasks=["x"])

    # task definitions
    td = ok("RegisterTaskDefinition", family="web", requiresCompatibilities=["FARGATE"], networkMode="awsvpc", cpu="256", memory="512",
            containerDefinitions=[{"name": "app", "image": "nginx", "portMappings": [{"containerPort": 80}]}])["taskDefinition"]
    _check("task definition revision 1 ACTIVE", td["revision"] == 1 and td["status"] == "ACTIVE" and td["containerDefinitions"][0]["essential"] is True)
    td2 = ok("RegisterTaskDefinition", family="web", requiresCompatibilities=["FARGATE"], networkMode="awsvpc", cpu="256", memory="512",
             containerDefinitions=[{"name": "app", "image": "nginx:1.27"}])["taskDefinition"]
    _check("revision increments", td2["revision"] == 2)
    _check("describe by family -> latest", ok("DescribeTaskDefinition", taskDefinition="web")["taskDefinition"]["revision"] == 2)
    _check("describe by family:rev", ok("DescribeTaskDefinition", taskDefinition="web:1")["taskDefinition"]["revision"] == 1)
    _check("ListTaskDefinitions DESC", ok("ListTaskDefinitions", familyPrefix="we", sort="DESC")["taskDefinitionArns"][0].endswith("web:2"))
    _check("ListTaskDefinitionFamilies", ok("ListTaskDefinitionFamilies")["families"] == ["web"])
    err("RegisterTaskDefinition", "ClientException", family="bad", requiresCompatibilities=["FARGATE"], networkMode="bridge", cpu="256", memory="512",
        containerDefinitions=[{"name": "a", "image": "x"}])
    err("RegisterTaskDefinition", "ClientException", family="bad2", containerDefinitions=[{"name": "a"}])
    err("DescribeTaskDefinition", "ClientException", taskDefinition="ghost:9")

    # services + deployments
    svc = ok("CreateService", cluster="c1", serviceName="s1", taskDefinition="web:1", desiredCount=2, launchType="FARGATE", networkConfiguration=NET)["service"]
    _check("service ACTIVE with 2 running", svc["status"] == "ACTIVE" and svc["runningCount"] == 2 and svc["deployments"][0]["rolloutState"] == "COMPLETED")
    _check("ListTasks for the service", len(ok("ListTasks", cluster="c1", serviceName="s1")["taskArns"]) == 2)
    up = ok("UpdateService", cluster="c1", service="s1", desiredCount=3)["service"]
    _check("scale up reconciles", up["runningCount"] == 3)
    rolled = ok("UpdateService", cluster="c1", service="s1", taskDefinition="web:2")["service"]
    _check("new task definition rolls out", rolled["taskDefinition"].endswith("web:2") and rolled["runningCount"] == 3
           and all(t["taskDefinitionArn"].endswith("web:2") for t in ok("DescribeTasks", cluster="c1", tasks=ok("ListTasks", cluster="c1")["taskArns"])["tasks"]))
    _check("DescribeServices missing", ok("DescribeServices", cluster="c1", services=["s1", "zz"])["failures"][0]["reason"] == "MISSING")
    err("CreateService", "InvalidParameterException", cluster="c1", serviceName="s1", taskDefinition="web:1", desiredCount=1, launchType="FARGATE", networkConfiguration=NET)
    err("DeleteService", "InvalidParameterException", cluster="c1", service="s1")
    err("DeleteCluster", "ClusterContainsServicesException", cluster="c1")
    err("UpdateService", "ServiceNotFoundException", cluster="c1", service="zz", desiredCount=1)

    # tasks
    r = ok("RunTask", cluster="c1", taskDefinition="web:1", launchType="FARGATE", networkConfiguration=NET, count=2, startedBy="me")
    _check("RunTask starts 2", len(r["tasks"]) == 2 and r["tasks"][0]["lastStatus"] == "RUNNING")
    _check("task has ENI attachment", r["tasks"][0]["attachments"][0]["type"] == "ElasticNetworkInterface")
    t = r["tasks"][0]
    stopped = ok("StopTask", cluster="c1", task=t["taskArn"], reason="test")["task"]
    _check("StopTask", stopped["lastStatus"] == "STOPPED" and stopped["stoppedReason"] == "test")
    _check("ListTasks defaults to RUNNING", t["taskArn"] not in ok("ListTasks", cluster="c1")["taskArns"])
    _check("ListTasks STOPPED", t["taskArn"] in ok("ListTasks", cluster="c1", desiredStatus="STOPPED")["taskArns"])
    _check("ListTasks startedBy", len(ok("ListTasks", cluster="c1", startedBy="me")["taskArns"]) == 1)
    noinst = ok("RegisterTaskDefinition", family="plain", containerDefinitions=[{"name": "a", "image": "x", "memory": 64}])["taskDefinition"]
    _check("RunTask on EC2 without container instances reports a failure",
           ok("RunTask", cluster="c1", taskDefinition="plain")["failures"][0]["reason"] == "No Container Instances were found in your cluster.")
    err("RunTask", "InvalidParameterException", cluster="c1", taskDefinition="web:1", launchType="FARGATE")
    pages = ok("ListTasks", cluster="c1", maxResults=1)
    _check("pagination token", "nextToken" in pages and len(ok("ListTasks", cluster="c1", maxResults=1, nextToken=pages["nextToken"])["taskArns"]) == 1)

    # container instances (EC2 placement)
    ci = ok("RegisterContainerInstance", cluster="c1")["containerInstance"]
    ec2 = ok("RegisterTaskDefinition", family="ec2app", containerDefinitions=[{"name": "a", "image": "x", "memory": 64}])["taskDefinition"]
    et = ok("RunTask", cluster="c1", taskDefinition="ec2app")["tasks"][0]
    _check("EC2 task placed on the instance", et["containerInstanceArn"] == ci["containerInstanceArn"] and et["launchType"] == "EC2")
    _check("instance counts the task", ok("DescribeContainerInstances", cluster="c1", containerInstances=[ci["containerInstanceArn"]])["containerInstances"][0]["runningTasksCount"] == 1)
    err("DeregisterContainerInstance", "InvalidParameterException", cluster="c1", containerInstance=ci["containerInstanceArn"])
    ok("DeregisterContainerInstance", cluster="c1", containerInstance=ci["containerInstanceArn"], force=True)

    # tags
    ok("TagResource", resourceArn=svc["serviceArn"], tags=[{"key": "k", "value": "v"}])
    _check("ListTagsForResource", ok("ListTagsForResource", resourceArn=svc["serviceArn"])["tags"] == [{"key": "k", "value": "v"}])
    ok("UntagResource", resourceArn=svc["serviceArn"], tagKeys=["k"])
    _check("UntagResource", ok("ListTagsForResource", resourceArn=svc["serviceArn"])["tags"] == [])
    err("TagResource", "ResourceNotFoundException", resourceArn="arn:aws:ecs:us-east-1:123456789012:cluster/zzz", tags=[{"key": "a", "value": "b"}])

    # capacity providers, settings
    _check("built-in providers", [p["name"] for p in ok("DescribeCapacityProviders")["capacityProviders"]][:2] == ["FARGATE", "FARGATE_SPOT"])
    ok("PutAccountSetting", name="containerInsights", value="enabled")
    _check("ListAccountSettings", any(x["name"] == "containerInsights" and x["value"] == "enabled" for x in ok("ListAccountSettings")["settings"]))

    # teardown
    ok("DeleteService", cluster="c1", service="s1", force=True)
    for a in ok("ListTasks", cluster="c1")["taskArns"]:
        ok("StopTask", cluster="c1", task=a)
    _check("DeleteTaskDefinitions needs INACTIVE", ok("DeleteTaskDefinitions", taskDefinitions=["web:1"])["failures"][0]["reason"].startswith("TaskDefinition is ACTIVE"))
    ok("DeregisterTaskDefinition", taskDefinition="web:1")
    _check("deleted", ok("DeleteTaskDefinitions", taskDefinitions=["web:1"])["taskDefinitions"][0]["status"] == "DELETE_IN_PROGRESS")
    _check("DeleteCluster -> INACTIVE", ok("DeleteCluster", cluster="c1")["cluster"]["status"] == "INACTIVE")
    _check("deleted cluster not listed", ok("ListClusters")["clusterArns"] == [])
    st, b = call("Bogus")
    _check("unknown operation", b["__type"].endswith("UnknownOperationException"))
    st, b = call("CreateTaskSet")
    _check("unimplemented op is UnsupportedFeatureException", b["__type"] == "UnsupportedFeatureException")
    return True


def test_ecs_core():
    assert run()


if __name__ == "__main__":
    run()
    print("ECS core: all checks passed")

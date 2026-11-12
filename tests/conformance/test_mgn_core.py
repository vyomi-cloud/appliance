"""AWS Application Migration Service (mgn): templates, source servers, replication/launch config, test + cutover lifecycle,
cutover launches a real EC2 instance in the EC2 model; plus the wire route through AwsWireRouter.
Run: PYTHONPATH=. python tests/conformance/test_mgn_core.py"""
import json
import re
import types

from core import mgn_core as mgn
from core import vpc_core as vpc

s = types.SimpleNamespace()


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def ec2(p):
    r = vpc.dispatch(s, p)
    assert r.status == 200, r.body
    return r.body


def op(name, body=None, status=None):
    r = mgn.dispatch(s, "POST", "/" + name, {}, {}, json.dumps(body or {}).encode())
    j = json.loads(r["body"]) if r["body"] else {}
    if status is not None and r["status"] != status:
        raise AssertionError((name, r["status"], j))
    return r["status"], j


def main():
    vid = re.search(r"<vpcId>(.*?)</vpcId>", ec2({"Action": "CreateVpc", "CidrBlock": "10.7.0.0/16"})).group(1)
    sub = re.search(r"<subnetId>(.*?)</subnetId>", ec2({"Action": "CreateSubnet", "VpcId": vid, "CidrBlock": "10.7.1.0/24"})).group(1)
    sg = re.search(r"<groupId>(.*?)</groupId>", ec2({"Action": "CreateSecurityGroup", "GroupName": "mgn-sg", "GroupDescription": "d", "VpcId": vid})).group(1)

    st, j = op("CreateReplicationConfigurationTemplate", {"stagingAreaSubnetId": "subnet-nope"})
    _check("template rejects unknown subnet", st == 400 and j["__type"] == "ValidationException")
    st, j = op("CreateReplicationConfigurationTemplate", {"stagingAreaSubnetId": sub, "bandwidthThrottling": 99999})
    _check("template validates throttle", st == 400)
    st, j = op("RegisterSourceServer", {"hostname": "web1"})
    _check("register needs a template", st == 400 and "template" in j["message"])
    st, tpl = op("CreateReplicationConfigurationTemplate", {"stagingAreaSubnetId": sub, "replicationServerInstanceType": "t3.medium"}, 201)
    _check("template created", tpl["replicationConfigurationTemplateID"].startswith("rct-") and tpl["dataPlaneRouting"] == "PRIVATE_IP")

    st, srv = op("RegisterSourceServer", {"hostname": "web1", "os": "Ubuntu 22.04", "cpus": 2, "ramBytes": 4 * 1024 ** 3,
                                          "disks": [{"deviceName": "/dev/sda", "bytes": 20 * 1024 ** 3}], "tags": {"app": "shop"}}, 201)
    sid = srv["sourceServerID"]
    _check("registered, NOT_READY", sid.startswith("s-") and srv["lifeCycle"]["state"] == "NOT_READY")
    _check("recommended type", srv["sourceProperties"]["recommendedInstanceType"] == "t3.medium")
    st, j = op("RegisterSourceServer", {"hostname": "web1"})
    _check("duplicate hostname conflict", st == 409)
    st, j = op("StartTest", {"sourceServerIDs": [sid]})
    _check("StartTest before replication done -> ConflictException", st == 409 and "NOT_READY" in j["message"])

    st, j = op("UpdateLaunchConfiguration", {"sourceServerID": sid, "targetSubnetId": "subnet-bad"})
    _check("launch config validates subnet", st == 400)
    st, j = op("UpdateLaunchConfiguration", {"sourceServerID": sid, "launchDisposition": "RUNNING"})
    _check("launch config validates disposition", st == 400)
    op("UpdateLaunchConfiguration", {"sourceServerID": sid, "targetSubnetId": sub, "securityGroupIDs": [sg], "launchDisposition": "STARTED",
                                     "copyTags": True}, 200)
    st, j = op("UpdateReplicationConfiguration", {"sourceServerID": sid, "bandwidthThrottling": 50, "stagingAreaSubnetId": sub})
    _check("replication config update", st == 200 and j["bandwidthThrottling"] == 50)

    # records-only replication advances with time (backdate the registration instead of sleeping)
    b = mgn._bag(s)
    b["servers"][sid]["registered_at"] -= 3
    st, j = op("DescribeSourceServers", {"filters": {"sourceServerIDs": [sid]}})
    _check("INITIAL_SYNC after 3s", j["items"][0]["dataReplicationInfo"]["dataReplicationState"] == "INITIAL_SYNC")
    b["servers"][sid]["registered_at"] -= 10
    st, j = op("DescribeSourceServers", {"filters": {"lifeCycleStates": ["READY_FOR_TEST"]}})
    _check("CONTINUOUS -> READY_FOR_TEST", len(j["items"]) == 1 and j["items"][0]["dataReplicationInfo"]["dataReplicationState"] == "CONTINUOUS")

    n_inst = len(vpc._model(s)["instances"])
    st, job = op("StartTest", {"sourceServerIDs": [sid]}, 202)
    iid = job["participatingServers"][0]["launchedEc2InstanceID"]
    inst = vpc._model(s)["instances"][iid]
    _check("test launched a REAL EC2 instance", len(vpc._model(s)["instances"]) == n_inst + 1 and inst["subnet_id"] == sub and inst["state"] == "running")
    _check("instance carries MGN tags + type + sg", inst["tags"]["AWSApplicationMigrationServiceSourceServerID"] == sid and inst["tags"]["app"] == "shop"
           and inst["instance_type"] == "t3.medium" and inst["sg_ids"] == [sg])
    _check("root volume sized from the replicated disk", vpc._model(s)["volumes"][inst["block_devices"][0]["volume_id"]]["size"] == 20)
    ec2({"Action": "DescribeInstances", "InstanceId.1": iid})
    st, j = op("DescribeSourceServers", {"filters": {"sourceServerIDs": [sid]}})
    _check("TEST_IN_PROGRESS + launchedInstance", j["items"][0]["lifeCycle"]["state"] == "TEST_IN_PROGRESS" and j["items"][0]["launchedInstance"]["ec2InstanceID"] == iid)
    st, j = op("StartTest", {"sourceServerIDs": [sid]})
    _check("second StartTest conflicts", st == 409)
    st, j = op("FinalizeCutover", {"sourceServerID": sid})
    _check("Finalize before cutover conflicts", st == 409)
    st, j = op("ChangeServerLifeCycleState", {"sourceServerID": sid, "lifeCycle": {"state": "CUTOVER"}})
    _check("cannot jump to CUTOVER", st == 409)
    op("TerminateTargetInstances", {"sourceServerIDs": [sid]}, 202)
    _check("test instance really terminated", vpc._model(s)["instances"][iid]["state"] == "terminated")
    st, j = op("DescribeSourceServers", {"filters": {"sourceServerIDs": [sid]}})
    _check("back to READY_FOR_TEST", j["items"][0]["lifeCycle"]["state"] == "READY_FOR_TEST" and j["items"][0]["launchedInstance"] is None)

    op("ChangeServerLifeCycleState", {"sourceServerID": sid, "lifeCycle": {"state": "READY_FOR_CUTOVER"}}, 200)
    op("UpdateLaunchConfiguration", {"sourceServerID": sid, "launchDisposition": "STOPPED", "targetInstanceTypeRightSizingMethod": "NONE", "targetInstanceType": "m5.large"}, 200)
    st, job = op("StartCutover", {"sourceServerIDs": [sid]}, 202)
    iid2 = job["participatingServers"][0]["launchedEc2InstanceID"]
    _check("cutover instance STOPPED with chosen type", vpc._model(s)["instances"][iid2]["state"] == "stopped" and vpc._model(s)["instances"][iid2]["instance_type"] == "m5.large")
    st, j = op("MarkAsArchived", {"sourceServerID": sid})
    _check("archive before CUTOVER conflicts", st == 409)
    op("FinalizeCutover", {"sourceServerID": sid}, 200)
    st, j = op("TerminateTargetInstances", {"sourceServerIDs": [sid]})
    _check("cut-over instance protected from terminate", st == 409)
    st, j = op("DeleteSourceServer", {"sourceServerID": sid})
    _check("delete requires archive", st == 409)
    op("MarkAsArchived", {"sourceServerID": sid}, 200)
    st, j = op("DescribeSourceServers", {})
    _check("archived hidden by default", j["items"] == [])
    st, j = op("DescribeSourceServers", {"filters": {"isArchived": True}})
    _check("archived listed on request", len(j["items"]) == 1)
    st, j = op("DescribeJobs", {})
    _check("jobs recorded", len(j["items"]) >= 3)
    st, j = op("DescribeJobLogItems", {"jobID": job["jobID"]})
    _check("job log items", any(x["event"] == "LAUNCH_END" for x in j["items"]))
    op("DeleteSourceServer", {"sourceServerID": sid}, 204)
    st, j = op("GetLaunchConfiguration", {"sourceServerID": sid})
    _check("deleted server not found", st == 404)
    st, j = op("Bogus", {})
    _check("unknown op", st == 404)

    # wire route through the shared router (SigV4 service scope `mgn`)
    from core.aws_wire_router import AwsWireRouter
    r = AwsWireRouter()
    hdr = {"authorization": "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/mgn/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/json"}
    out = r.handle("POST", "/DescribeReplicationConfigurationTemplates", {}, hdr, b"{}")
    _check("router serves mgn", out["status"] == 200 and "items" in json.loads(out["body"]))
    print("mgn: ALL PASS")


if __name__ == "__main__":
    main()

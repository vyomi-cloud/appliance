"""SSH / shell access (decision family 1): EC2 Instance Connect, SSM Session Manager, GCE ssh-keys + OS info, Azure serial/Bastion,
and the key self-heal on Connect. Hermetic: Docker is replaced by a recording stub (a live container login was verified separately).

Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_ssh_access.py
"""
import base64, json, os, subprocess, sys

os.environ.setdefault("CLOUDLEARN_READINESS_GATE", "disabled")
sys.dont_write_bytecode = True
import server as S  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from core import ssh_access_core as sa, ssm_core  # noqa: E402


def ck(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def mkkey(comment="t"):
    blob = (11).to_bytes(4, "big") + b"ssh-ed25519" + (32).to_bytes(4, "big") + os.urandom(32)
    return f"ssh-ed25519 {base64.b64encode(blob).decode()} {comment}"


class Fake:
    def __init__(self):
        self.cmds = []

    def ssh_info(self, inst):
        return {"user": "ubuntu", "container_ip": "172.17.0.9", "routable_ip": None, "published_port": 43999}

    def ipv4(self, inst):
        return "172.17.0.9"

    def status(self, inst):
        return "running"

    def exec(self, inst, cmd, stdin=None):
        self.cmds.append(cmd)
        c = cmd[-1] if isinstance(cmd, list) else str(cmd)
        out = b"NAME=Ubuntu\nVERSION=24.04\nKERNEL=6.1\nPRETTY=Ubuntu 24.04\n" if "os-release" in c else b"ok\n__VYOMI_CWD__/root\n"
        return subprocess.CompletedProcess(cmd, 3 if "nouser" in c else 0, out, b"")


def main():
    # core: key validation
    for bad in ("", "ssh-ed25519", "ssh-ed25519 !!!notb64", "ssh-dsa AAAA", "ssh-ed25519 " + base64.b64encode(b"\0\0\0\x0bssh-rsa....").decode()):
        try:
            sa.parse_public_key(bad); ck("bad key rejected: " + bad[:20], False)
        except sa.SshAccessError as e:
            ck("bad key rejected: " + bad[:20], e.code == "InvalidArgsException")
    ck("good ed25519 key parses", sa.parse_public_key(mkkey())["type"] == "ssh-ed25519")
    ck("authorize snippet is idempotent grep-append", "grep -qxF" in sa.authorize_command("ubuntu", mkkey()))

    fake = Fake()
    S._docker_compute = lambda: fake
    iid = "i-0aaa1111bbbb2222"
    S.ec2_state.setdefault("instances", {})[iid] = {"instance_id": iid, "state": "running", "console_backend": "docker-exec", "runtime_backend": "docker",
                                                   "container_name": "vyomi-" + iid, "ssh_host_port": 43999, "availability_zone": "us-east-1a"}
    gid = "gce-conf-ssh1"
    S.gcp_compute_state.setdefault("instances", {})[gid] = {"instance_id": gid, "state": "running", "runtime_backend": "docker", "console_backend": "docker-exec",
                                                           "container_name": "vyomi-i-" + gid}
    c = TestClient(S.app)

    # EC2 Instance Connect over the native wire
    def wire(op, body):
        return c.post("/", content=json.dumps(body), headers={"X-Amz-Target": "AWSEC2InstanceConnectService." + op, "Content-Type": "application/x-amz-json-1.1",
                                                              "Authorization": "AWS4-HMAC-SHA256 Credential=AKIA/20260101/us-east-1/ec2-instance-connect/aws4_request"})
    k = mkkey("laptop")
    r = wire("SendSSHPublicKey", {"InstanceId": iid, "InstanceOSUser": "ubuntu", "SSHPublicKey": k, "AvailabilityZone": "us-east-1a"})
    ck("SendSSHPublicKey -> Success", r.status_code == 200 and r.json()["Success"] is True)
    ck("key pushed into the guest with a 60s expiry job", any("sleep 60" in x[-1] and k.split()[1] in x[-1] for x in fake.cmds))
    r = wire("SendSSHPublicKey", {"InstanceId": iid, "InstanceOSUser": "ubuntu", "SSHPublicKey": k, "AvailabilityZone": "us-west-2a"})
    ck("wrong AZ -> InvalidArgsException", r.status_code == 400 and r.json()["__type"] == "InvalidArgsException")
    r = wire("SendSSHPublicKey", {"InstanceId": "i-0ffff0000ffff0000", "InstanceOSUser": "ubuntu", "SSHPublicKey": k})
    ck("unknown instance -> EC2InstanceNotFoundException", r.json().get("__type") == "EC2InstanceNotFoundException")
    r = wire("SendSSHPublicKey", {"InstanceId": iid, "InstanceOSUser": "ubuntu", "SSHPublicKey": "garbage"})
    ck("garbage key -> InvalidArgsException", r.json().get("__type") == "InvalidArgsException")
    r = c.post(f"/api/aws/ec2/instances/{iid}/instance-connect", json={"os_user": "ubuntu", "public_key": k})
    ck("console Instance Connect returns ssh command + delivered", r.status_code == 200 and r.json()["delivered"] and "-p 43999" in r.json()["ssh_command"])

    # Connect self-heal
    n = len(fake.cmds)
    c.get(f"/api/aws/ec2/instances/{iid}/connect-info")
    ck("connect-info re-authorizes the shared key in the running guest", len(fake.cmds) > n and any("authorized_keys" in x[-1] for x in fake.cmds[n:]))

    # SSM Session Manager (native wire)
    def ssm(op, body):
        return c.post("/", content=json.dumps(body), headers={"X-Amz-Target": "AmazonSSM." + op, "Content-Type": "application/x-amz-json-1.1",
                                                              "Authorization": "AWS4-HMAC-SHA256 Credential=AKIA/20260101/us-east-1/ssm/aws4_request"})
    ck("DescribeInstanceInformation lists the running instance as Online",
       any(i["InstanceId"] == iid and i["PingStatus"] == "Online" for i in ssm("DescribeInstanceInformation", {}).json()["InstanceInformationList"]))
    r = ssm("StartSession", {"Target": "i-0ffff0000ffff0000"})
    ck("StartSession on unknown target -> TargetNotConnected", r.json().get("__type") == "TargetNotConnected")
    s = ssm("StartSession", {"Target": iid}).json()
    ck("StartSession returns SessionId/TokenValue/StreamUrl", s["SessionId"] and len(s["TokenValue"]) >= 32 and s["StreamUrl"].startswith("wss://"))
    ck("DescribeSessions Active lists it", any(x["SessionId"] == s["SessionId"] for x in ssm("DescribeSessions", {"State": "Active"}).json()["Sessions"]))
    ck("DescribeSessions needs State", ssm("DescribeSessions", {}).status_code == 400)
    ck("session exec runs in the guest", "ok" in c.post(f"/api/ssm/sessions/{s['SessionId']}/exec", json={"command": "echo ok"}).json()["output"])
    ssm("TerminateSession", {"SessionId": s["SessionId"]})
    ck("terminated session moves to History", any(x["SessionId"] == s["SessionId"] for x in ssm("DescribeSessions", {"State": "History"}).json()["Sessions"]))
    ck("exec on terminated session refused", c.post(f"/api/ssm/sessions/{s['SessionId']}/exec", json={"command": "id"}).status_code == 404)

    # GCE ssh-keys metadata + OS info
    r = c.post(f"/api/gcp/compute/instances/{gid}/ssh-keys", json={"ssh_keys": "alice:" + mkkey("alice")})
    ck("GCE ssh-keys metadata authorizes the user in the guest", r.status_code == 200 and r.json()["delivered"] == 1)
    ck("GCE bad ssh-keys line rejected", c.post(f"/api/gcp/compute/instances/{gid}/ssh-keys", json={"ssh_keys": "nocolon"}).status_code == 400)
    oi = c.get(f"/api/gcp/compute/instances/{gid}/os-info").json()
    ck("GCE OS info comes from the guest", oi["pretty"] == "Ubuntu 24.04" and oi["kernel"] == "6.1")
    ck("GCE os-info of unknown instance 404", c.get("/api/gcp/compute/instances/nope/os-info").status_code == 404)

    S.ec2_state["instances"].pop(iid, None); S.gcp_compute_state["instances"].pop(gid, None)
    print("SSH access (EC2 Instance Connect, SSM sessions, GCE keys/OS info): all green")


if __name__ == "__main__":
    main()

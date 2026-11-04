"""SSH / shell access core — substrate-independent engine behind "get a shell into compute"
(decision family 1): AWS EC2 Instance Connect (SendSSHPublicKey / SendSerialConsoleSSHPublicKey),
SSM Session Manager (StartSession / ResumeSession / TerminateSession / DescribeSessions),
GCE metadata `ssh-keys` / OS Login keys, and the web-shell session records used by Azure serial
console, Bastion and Kudu.

NO fastapi / boto3 / socket / subprocess imports -> loads under Pyodide (Nano) and host CPython.
The core only validates, records and returns the *command to run in the guest*; the substrate
supplies the reach-in through two injected callables so the same code is real offline and honest
on Nano:

  instances()          -> {instance_id: {state, az, os_user, ...}}   (None/empty = no compute runtime)
  run(instance_id, sh) -> (returncode, stdout)                       (None = cannot reach the guest)

Offline: instances are real Docker containers with sshd, `run` is `docker exec`, so a key pushed
here really logs in with `ssh -i key user@host -p port`.
Nano: no instance runtime and no inbound TCP; reach-in needs the vyomi-tunnel TCP relay
(wasm/relay). Keys are validated and recorded (so SDK/CLI flows and errors are identical) but the
result states honestly that no guest received them.
"""
from __future__ import annotations

import base64
import re
import shlex
import time
import uuid

KEY_TTL_SECONDS = 60
_KEY_TYPES = {"ssh-ed25519": 51, "ssh-rsa": None, "ecdsa-sha2-nistp256": None,
              "ecdsa-sha2-nistp384": None, "ecdsa-sha2-nistp521": None,
              "sk-ssh-ed25519@openssh.com": None}
_OS_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_INSTANCE_RE = re.compile(r"^i-[0-9a-f]{8,17}$|^i-[a-z0-9-]{4,40}$")


class SshAccessError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


class SshAccessStore:
    def __init__(self):
        self.pushed_keys: list = []     # EC2 Instance Connect pushes (audit + expiry)
        self.sessions: dict = {}        # SSM / web-shell session id -> record
        self.gce_keys: dict = {}        # instance name -> [{user, key, expires}]


_SHARED: SshAccessStore | None = None


def shared_store() -> SshAccessStore:
    global _SHARED
    if _SHARED is None:
        _SHARED = SshAccessStore()
    return _SHARED


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


# ── public key validation ────────────────────────────────────────────────────
def parse_public_key(text: str) -> dict:
    """Validate an OpenSSH authorized_keys-style public key. Returns {type, blob, comment}."""
    parts = (text or "").strip().split()
    if len(parts) < 2 or "\n" in (text or "").strip():
        raise SshAccessError("InvalidArgsException", "SSHPublicKey is not a valid OpenSSH public key.")
    ktype, b64 = parts[0], parts[1]
    if ktype not in _KEY_TYPES:
        raise SshAccessError("InvalidArgsException", f"Unsupported SSH key type {ktype}.")
    try:
        blob = base64.b64decode(b64, validate=True)
    except Exception:
        raise SshAccessError("InvalidArgsException", "SSHPublicKey is not valid base64.")
    if len(blob) < 4 or blob[4:4 + int.from_bytes(blob[:4], "big")].decode("ascii", "replace") != ktype:
        raise SshAccessError("InvalidArgsException", "SSHPublicKey blob does not match its declared key type.")
    return {"type": ktype, "blob": b64, "comment": " ".join(parts[2:])}


def _clean_key(k: dict) -> str:
    return f"{k['type']} {k['blob']}" + (f" {k['comment']}" if k["comment"] else "")


def authorize_command(user: str, key_line: str, ttl: int | None = None) -> str:
    """Shell snippet that idempotently appends a key to a user's authorized_keys (creating the
    dir with correct modes). With ttl the key is auto-removed after ttl seconds, the EC2 Instance
    Connect "key lives 60 seconds" behaviour (the established session is unaffected)."""
    u, k = shlex.quote(user), shlex.quote(key_line)
    home = f"$(getent passwd {u} | cut -d: -f6)"
    sh = (f"H={home}; [ -n \"$H\" ] || exit 3; install -d -m 700 -o {u} -g {u} \"$H/.ssh\"; "
          f"touch \"$H/.ssh/authorized_keys\"; grep -qxF {k} \"$H/.ssh/authorized_keys\" || printf '%s\\n' {k} >> \"$H/.ssh/authorized_keys\"; "
          f"chown {u}:{u} \"$H/.ssh/authorized_keys\"; chmod 600 \"$H/.ssh/authorized_keys\"")
    if ttl:
        sh += (f"; ( sleep {int(ttl)}; grep -vxF {k} \"$H/.ssh/authorized_keys\" > \"$H/.ssh/authorized_keys.tmp\"; "
               f"cat \"$H/.ssh/authorized_keys.tmp\" > \"$H/.ssh/authorized_keys\"; rm -f \"$H/.ssh/authorized_keys.tmp\" ) >/dev/null 2>&1 &")
    return sh


def _need(body: dict, *names: str):
    for n in names:
        if not body.get(n):
            raise SshAccessError("InvalidArgsException", f"{n} is required.")


def _find(instances: dict | None, iid: str) -> dict:
    inst = (instances or {}).get(iid)
    if not inst:
        raise SshAccessError("EC2InstanceNotFoundException", f"Instance {iid} not found.", 404)
    if inst.get("state") != "running":
        raise SshAccessError("EC2InstanceStateInvalidException", f"Instance {iid} is not in the running state.")
    return inst


# ── EC2 Instance Connect ────────────────────────────────────────────────────
def send_ssh_public_key(store: SshAccessStore, body: dict, instances: dict | None, run=None, serial: bool = False) -> dict:
    _need(body, "InstanceId", "SSHPublicKey")
    if not serial:
        _need(body, "InstanceOSUser")
        if not _OS_USER_RE.match(body["InstanceOSUser"]):
            raise SshAccessError("InvalidArgsException", "InstanceOSUser is not a valid OS user name.")
    user = body.get("InstanceOSUser") or "root"
    key = _clean_key(parse_public_key(body["SSHPublicKey"]))
    inst = _find(instances, body["InstanceId"])
    az = body.get("AvailabilityZone")
    if az and inst.get("az") and az != inst["az"]:
        raise SshAccessError("InvalidArgsException", f"AvailabilityZone {az} does not match the instance's zone {inst['az']}.")
    delivered = False
    if run is not None:
        rc, _ = run(body["InstanceId"], authorize_command(user, key, KEY_TTL_SECONDS))
        if rc == 3:
            raise SshAccessError("InvalidArgsException", f"OS user {user} does not exist on {body['InstanceId']}.")
        delivered = rc == 0
    store.pushed_keys.append({"instance_id": body["InstanceId"], "user": user, "key": key, "serial": serial,
                              "at": _now(), "expires": _now() + KEY_TTL_SECONDS, "delivered": delivered})
    del store.pushed_keys[:-200]
    return {"Success": True, "RequestId": str(uuid.uuid4())}


# ── Session Manager ─────────────────────────────────────────────────────────
def start_session(store: SshAccessStore, body: dict, instances: dict | None, who: str = "vyomi-user",
                  region: str = "us-east-1") -> dict:
    _need(body, "Target")
    tgt = body["Target"]
    inst = (instances or {}).get(tgt)
    if not inst or inst.get("state") != "running":
        raise SshAccessError("TargetNotConnected", f"{tgt} is not connected.", 400)
    doc = body.get("DocumentName") or "SSM-SessionManagerRunShell"
    if doc not in ("SSM-SessionManagerRunShell", "AWS-StartSSHSession", "AWS-StartPortForwardingSession", "AWS-StartInteractiveCommand"):
        raise SshAccessError("InvalidDocument", f"Document {doc} does not exist or is not a session document.")
    sid = f"{who}-{uuid.uuid4().hex[:17]}"
    rec = {"SessionId": sid, "Target": tgt, "Status": "Connected", "DocumentName": doc, "Owner": who,
           "StartDate": _now(), "Reason": body.get("Reason", ""), "Details": "", "OutputUrl": {}, "MaxSessionDuration": "60"}
    store.sessions[sid] = rec
    token = uuid.uuid4().hex + uuid.uuid4().hex
    return {"SessionId": sid, "TokenValue": token,
            "StreamUrl": f"wss://ssmmessages.{region}.amazonaws.com/v1/data-channel/{sid}?role=publish_subscribe"}


def _need_session(store: SshAccessStore, sid: str) -> dict:
    s = store.sessions.get(sid)
    if not s:
        raise SshAccessError("DoesNotExistException", f"Session {sid} does not exist.", 400)
    return s


def resume_session(store: SshAccessStore, body: dict, region: str = "us-east-1") -> dict:
    _need(body, "SessionId")
    s = _need_session(store, body["SessionId"])
    if s["Status"] != "Connected":
        raise SshAccessError("DoesNotExistException", f"Session {s['SessionId']} is {s['Status']}.")
    return {"SessionId": s["SessionId"], "TokenValue": uuid.uuid4().hex + uuid.uuid4().hex,
            "StreamUrl": f"wss://ssmmessages.{region}.amazonaws.com/v1/data-channel/{s['SessionId']}?role=publish_subscribe"}


def terminate_session(store: SshAccessStore, body: dict) -> dict:
    _need(body, "SessionId")
    s = _need_session(store, body["SessionId"])
    s["Status"] = "Terminated"
    s["EndDate"] = _now()
    return {"SessionId": s["SessionId"]}


def describe_sessions(store: SshAccessStore, body: dict) -> dict:
    state = body.get("State")
    if state not in ("Active", "History"):
        raise SshAccessError("InvalidFilterKey", "State must be Active or History.")
    out = []
    for s in store.sessions.values():
        if (state == "Active") != (s["Status"] == "Connected"):
            continue
        if any(f.get("key") == "Target" and f.get("value") != s["Target"] for f in body.get("Filters") or []):
            continue
        v = {k: s[k] for k in ("SessionId", "Target", "Status", "DocumentName", "Owner", "Details", "OutputUrl", "MaxSessionDuration")}
        v["StartDate"] = s["StartDate"]
        if s.get("EndDate"):
            v["EndDate"] = s["EndDate"]
        out.append(v)
    return {"Sessions": out}


# ── GCE metadata ssh-keys ───────────────────────────────────────────────────
def parse_gce_ssh_keys(metadata_value: str) -> list:
    """GCE `ssh-keys` metadata: one `USERNAME:ssh-ed25519 AAAA... comment` per line."""
    out = []
    for line in (metadata_value or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            raise SshAccessError("invalid", f"ssh-keys line has no USERNAME: prefix: {line[:30]}")
        user, key = line.split(":", 1)
        if not _OS_USER_RE.match(user):
            raise SshAccessError("invalid", f"Invalid username {user!r} in ssh-keys metadata.")
        out.append({"user": user, "key": _clean_key(parse_public_key(key))})
    return out


def apply_gce_ssh_keys(store: SshAccessStore, name: str, metadata_value: str, run=None) -> dict:
    """Authorize every key in the metadata value in the guest (the GCE guest agent behaviour)."""
    keys = parse_gce_ssh_keys(metadata_value)
    delivered = 0
    for k in keys:
        if run is not None:
            if run(name, "id -u %s >/dev/null 2>&1 || useradd -m -s /bin/bash %s" % (shlex.quote(k["user"]), shlex.quote(k["user"])))[0] == 0 \
               and run(name, authorize_command(k["user"], k["key"]))[0] == 0:
                delivered += 1
    store.gce_keys[name] = keys
    return {"keys": len(keys), "delivered": delivered}


OS_INFO_CMD = ("(. /etc/os-release 2>/dev/null; echo \"NAME=$NAME\"; echo \"VERSION=$VERSION\"; echo \"ID=$ID\"; echo \"PRETTY=$PRETTY_NAME\"); "
               "echo \"KERNEL=$(uname -r)\"; echo \"ARCH=$(uname -m)\"; echo \"HOSTNAME=$(hostname)\"; "
               "echo \"UPTIME=$(cut -d. -f1 /proc/uptime)\"; echo \"MEM_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo)\"; echo \"CPUS=$(nproc)\"; "
               "echo \"PKGS=$(dpkg-query -f '.\\n' -W 2>/dev/null | wc -l)\"")


def parse_os_info(out: str) -> dict:
    d = {}
    for line in (out or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip().lower()] = v.strip().strip('"')
    return d

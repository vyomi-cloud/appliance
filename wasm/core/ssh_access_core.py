# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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


# ── Azure VM guest views: Inventory / Update Manager / Performance diagnostics ───────────────────────────────
# Real reach-in through the same injected `run(instance_id, sh) -> (rc, out)` as the shell features: offline it is
# `docker exec` in the VM's container, so everything below is read from (or done to) the running guest.  Nano has no
# guest runtime here (run is None): the callers say so instead of inventing data.
INVENTORY_CMD = (
    "echo '##os'; cat /etc/os-release 2>/dev/null; echo '##kernel'; uname -sr; echo '##host'; hostname; "
    "echo '##pkgfmt'; "
    "if command -v dpkg-query >/dev/null 2>&1; then echo dpkg; echo '##pkgs'; dpkg-query -W -f='${Package}\\t${Version}\\n' 2>/dev/null; "
    "elif command -v apk >/dev/null 2>&1; then echo apk; echo '##pkgs'; apk info -v 2>/dev/null; "
    "elif command -v rpm >/dev/null 2>&1; then echo rpm; echo '##pkgs'; rpm -qa --qf '%{NAME}\\t%{VERSION}-%{RELEASE}\\n' 2>/dev/null; "
    "else echo none; echo '##pkgs'; fi; echo '##end'")

PERF_CMD = (
    "echo '##load'; cat /proc/loadavg; echo '##cpus'; nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo; "
    "echo '##mem'; grep -E '^(MemTotal|MemAvailable|MemFree|SwapTotal|SwapFree):' /proc/meminfo; "
    "echo '##uptime'; cat /proc/uptime; echo '##disk'; df -Pk / | tail -n 1; "
    "echo '##procs'; for d in /proc/[0-9]*; do p=${d#/proc/}; c=$(cat $d/comm 2>/dev/null); r=$(awk '/VmRSS/{print $2}' $d/status 2>/dev/null); echo \"$p ${r:-0} $c\"; done | sort -k2 -nr | head -n 8; echo '##end'")


def _sections(out: str) -> dict:
    cur, sec = None, {}
    for line in out.splitlines():
        if line.startswith("##"):
            cur = line[2:].strip()
            sec[cur] = []
        elif cur is not None:
            sec[cur].append(line)
    return sec


def parse_inventory(out: str) -> dict:
    s = _sections(out)
    osr = {}
    for ln in s.get("os", []):
        if "=" in ln:
            k, _, v = ln.partition("=")
            osr[k.strip()] = v.strip().strip('"')
    fmt = (s.get("pkgfmt") or ["none"])[0].strip()
    pkgs = []
    for ln in s.get("pkgs", []):
        ln = ln.strip()
        if not ln:
            continue
        if fmt == "apk":
            m = re.match(r"^(.+?)-(\d[^-]*(?:-r\d+)?)$", ln)
            pkgs.append({"name": m.group(1), "version": m.group(2)} if m else {"name": ln, "version": ""})
        else:
            name, _, ver = ln.partition("\t")
            pkgs.append({"name": name, "version": ver})
    pkgs.sort(key=lambda p: p["name"])
    return {"os": {"name": osr.get("PRETTY_NAME") or osr.get("NAME"), "id": osr.get("ID"), "version": osr.get("VERSION_ID"),
                   "kernel": (s.get("kernel") or [""])[0].strip(), "hostname": (s.get("host") or [""])[0].strip()},
            "packageManager": fmt, "packageCount": len(pkgs), "packages": pkgs}


def parse_perf(out: str) -> dict:
    s = _sections(out)
    la = (s.get("load") or ["0 0 0"])[0].split()
    cpus = int(((s.get("cpus") or ["1"])[0] or "1").strip() or 1)
    mem = {}
    for ln in s.get("mem", []):
        m = re.match(r"^(\w+):\s+(\d+)", ln)
        if m:
            mem[m.group(1)] = int(m.group(2)) * 1024
    total = mem.get("MemTotal", 0)
    avail = mem.get("MemAvailable", mem.get("MemFree", 0))
    disk = (s.get("disk") or [""])[0].split()
    disk_pct = int(disk[4].rstrip("%")) if len(disk) >= 5 and disk[4].rstrip("%").isdigit() else None
    procs = [ln.split(None, 2) for ln in (s.get("procs") or []) if ln.strip()]
    up = float((s.get("uptime") or ["0 0"])[0].split()[0] or 0)
    perf = {"loadAvg": [float(x) for x in la[:3]], "cpus": cpus, "memTotalBytes": total, "memAvailableBytes": avail,
            "memUsedPercent": round(100 * (total - avail) / total, 1) if total else None, "diskRootUsedPercent": disk_pct,
            "uptimeSeconds": int(up), "topProcesses": [{"pid": p[0], "rssKb": int(p[1]) if p[1].isdigit() else 0, "command": p[2]} for p in procs if len(p) == 3]}
    findings = []
    if perf["loadAvg"][0] > cpus:
        findings.append({"severity": "Warning", "finding": f"1-minute load average {perf['loadAvg'][0]} exceeds the {cpus} CPU(s)."})
    if perf["memUsedPercent"] is not None and perf["memUsedPercent"] > 90:
        findings.append({"severity": "Warning", "finding": f"{perf['memUsedPercent']}% of memory is in use."})
    if disk_pct is not None and disk_pct > 90:
        findings.append({"severity": "Critical", "finding": f"Root filesystem is {disk_pct}% full."})
    perf["findings"] = findings
    return perf


def updates_command(refresh: bool, install: bool) -> str:
    pre = ("if command -v apt-get >/dev/null 2>&1; then PM=apt; elif command -v apk >/dev/null 2>&1; then PM=apk; "
           "elif command -v dnf >/dev/null 2>&1; then PM=dnf; else PM=none; fi; echo '##pm'; echo $PM; ")
    ref = ("if [ $PM = apt ]; then apt-get update -qq >/dev/null 2>&1; elif [ $PM = apk ]; then apk update >/dev/null 2>&1; fi; " if (refresh or install) else "")
    inst = ("echo '##install'; if [ $PM = apt ]; then DEBIAN_FRONTEND=noninteractive apt-get -y -qq upgrade 2>&1 | tail -n 15; "
            "elif [ $PM = apk ]; then apk upgrade 2>&1 | tail -n 15; fi; echo \"exit=$?\"; " if install else "")
    lst = ("echo '##pending'; if [ $PM = apt ]; then apt-get -s upgrade 2>/dev/null | grep '^Inst' | sed -E 's/^Inst ([^ ]+) \\[([^]]+)\\] \\(([^ ]+).*/\\1\\t\\2\\t\\3/'; "
           "elif [ $PM = apk ]; then apk version -l '<' 2>/dev/null | tail -n +2 | sed -E 's/^(.+)-([0-9][^ ]*) +< +(.+)$/\\1\\t\\2\\t\\3/'; fi; echo '##end'")
    return pre + ref + inst + lst


def parse_updates(out: str) -> dict:
    s = _sections(out)
    pm = (s.get("pm") or ["none"])[0].strip()
    pend = []
    for ln in s.get("pending", []):
        parts = ln.split("\t")
        if len(parts) == 3:
            pend.append({"name": parts[0], "installed": parts[1], "available": parts[2]})
    res = {"packageManager": pm, "pendingCount": len(pend), "pending": pend, "supported": pm != "none"}
    if "install" in s:
        res["installLog"] = "\n".join(s["install"])
    return res

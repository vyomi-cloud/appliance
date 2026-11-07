# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EC2 Instance Connect (service `ec2-instance-connect`, JSON 1.1, X-Amz-Target `AWSEC2InstanceConnectService.*`).

SendSSHPublicKey / SendSerialConsoleSSHPublicKey over the shared EC2/VPC model: the instance must exist and be running, the
Availability Zone (when given) must match, the OS user is validated, and the public key must parse as an OpenSSH public key
(type + base64 blob whose embedded type string agrees). The key is stored on the instance record with the real 60-second
validity window (`eic_keys`, readable through ``keys_for``), so a caller can see exactly what an sshd AuthorizedKeysCommand
would have fetched. Serial-console pushes require the account-level EnableSerialConsoleAccess switch and a Nitro instance.

Substrate-independent (no fastapi / boto3); loads under Pyodide. Honest limit: there is no sshd on the other end of the wire here -
the key is recorded, not installed into a guest."""
from __future__ import annotations

import base64
import re
import struct
import time
import types
import uuid

VALIDITY_S = 60
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.@-]{0,31}$")
_KEY_TYPES = ("ssh-rsa", "ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521", "ssh-dss")


class EicError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _V():
    try:
        from core import vpc_core
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import vpc_core  # type: ignore
    return vpc_core


def _check_key(key: str) -> str:
    parts = key.strip().split()
    if len(parts) < 2 or parts[0] not in _KEY_TYPES:
        raise EicError("InvalidArgsException", "SSHPublicKey must be an OpenSSH public key (e.g. 'ssh-rsa AAAA...').")
    try:
        blob = base64.b64decode(parts[1] + "=" * (-len(parts[1]) % 4), validate=True)
        n = struct.unpack(">I", blob[:4])[0]
        inner = blob[4:4 + n].decode("ascii")
    except Exception:
        raise EicError("InvalidArgsException", "SSHPublicKey is not valid base64 OpenSSH key material.")
    if inner != parts[0]:
        raise EicError("InvalidArgsException", f"SSHPublicKey type '{parts[0]}' does not match the key blob ('{inner}').")
    return parts[0] + " " + parts[1]


def _instance(store, iid, az=None):
    m = _V()._model(store)
    inst = m["instances"].get(iid)
    if inst is None:
        raise EicError("EC2InstanceNotFoundException", f"The instance '{iid}' does not exist.")
    if inst["state"] != "running":
        raise EicError("EC2InstanceStateInvalidException", f"Instance {iid} is {inst['state']}; it must be running.")
    if az and inst["az"] != az:
        raise EicError("InvalidArgsException", f"Instance {iid} is in {inst['az']}, not {az}.")
    return m, inst


def keys_for(store, iid, user=None, now=None):
    """Currently valid pushed keys for an instance (what an AuthorizedKeysCommand would see)."""
    now = now or time.time()
    inst = _V()._model(store)["instances"].get(iid) or {}
    return [k for k in inst.get("eic_keys", []) if k["expires"] > now and (user is None or k["user"] == user)]


def send_ssh_public_key(store, p, now=None):
    for n in ("InstanceId", "InstanceOSUser", "SSHPublicKey"):
        if not p.get(n):
            raise EicError("InvalidArgsException", f"Missing required parameter: {n}")
    if not _USER_RE.match(p["InstanceOSUser"]):
        raise EicError("InvalidArgsException", "InstanceOSUser is not a valid OS user name.")
    key = _check_key(p["SSHPublicKey"])
    m, inst = _instance(store, p["InstanceId"], p.get("AvailabilityZone"))
    now = now or time.time()
    lst = [k for k in inst.setdefault("eic_keys", []) if k["expires"] > now]
    lst.append({"user": p["InstanceOSUser"], "key": key, "pushed": now, "expires": now + VALIDITY_S, "via": "ssh"})
    inst["eic_keys"] = lst
    return {"RequestId": str(uuid.uuid4()), "Success": True}


def send_serial_console_ssh_public_key(store, p, now=None):
    for n in ("InstanceId", "SSHPublicKey"):
        if not p.get(n):
            raise EicError("InvalidArgsException", f"Missing required parameter: {n}")
    port = int(p.get("SerialPort") or 0)
    if port != 0:
        raise EicError("SerialConsoleSessionLimitExceededException" if port > 0 else "InvalidArgsException", "SerialPort must be 0.")
    key = _check_key(p["SSHPublicKey"])
    m, inst = _instance(store, p["InstanceId"])
    if not m["account"].get("serial_console_enabled"):
        raise EicError("SerialConsoleAccessDisabledException", "EC2 Serial Console access is disabled for this account (EnableSerialConsoleAccess).")
    if inst.get("hypervisor", "nitro") != "nitro":
        raise EicError("EC2InstanceTypeInvalidException", "Serial console requires a Nitro-based instance type.")
    now = now or time.time()
    inst["eic_keys"] = [k for k in inst.get("eic_keys", []) if k["expires"] > now] + [
        {"user": "serial-console", "key": key, "pushed": now, "expires": now + VALIDITY_S, "via": "serial"}]
    return {"RequestId": str(uuid.uuid4()), "Success": True}


_OPS = {"SendSSHPublicKey": send_ssh_public_key, "SendSerialConsoleSSHPublicKey": send_serial_console_ssh_public_key}


def dispatch(store, target, payload):
    action = (target or "").rsplit(".", 1)[-1]
    op = _OPS.get(action)
    hdr = {"x-amzn-requestid": str(uuid.uuid4())}
    if op is None:
        return types.SimpleNamespace(status=400, headers=hdr, body={"__type": "UnknownOperationException", "Message": f"The action {action} is not implemented."})
    try:
        return types.SimpleNamespace(status=200, headers=hdr, body=op(store, payload if isinstance(payload, dict) else {}))
    except EicError as e:
        h = dict(hdr, **{"x-amzn-errortype": e.code})
        return types.SimpleNamespace(status=e.status, headers=h, body={"__type": e.code, "Message": e.message})

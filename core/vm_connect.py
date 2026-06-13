"""Cross-provider SSH-Connect provisioning for LXD-backed VM instances.

The same LXD container backs an AWS EC2 instance, a GCP Compute instance,
and an Azure VM (per the heterogeneous-VM-shape memory). Connect-via-SSH
should therefore work identically for all three from the user's terminal:

    ssh -i ~/.ssh/cloudlearn-<id>.pem ubuntu@<vm_ip> -p <port>

This module owns the provisioning steps the first time a user clicks
*Connect* on any VM:

  1. Generate an ed25519 keypair in the instance workspace
       /var/lib/cloudlearn/deployments/<instance_id>/ssh_key{,.pub}
  2. Via the runtime bridge:
       a. `lxc file push` the pubkey into the container's authorized_keys
       b. `lxc exec` installs openssh-server + enables sshd (idempotent)
       c. Allocate a unique TCP port on the VM (12200–12999)
       d. `lxc config device add` a proxy device so VM:<port> → container:22
  3. Resolve the VM's external IP via the runtime bridge.
  4. Return a connect_info dict the SPA renders into the Connect tab.

Provisioning is lazy + idempotent — subsequent calls see existing state
and return the cached info without re-running the LXD operations.

Per-cloud surface:
  - AWS EC2:     /api/aws/ec2/instances/{id}/connect-info  + /private-key.pem
  - GCP Compute: /api/gcp/compute/instances/{id}/connect-info  + /private-key.pem
  - Azure VM:    /api/azure/vm/{id}/connect-info  + /private-key.pem
  (All three forward to this module — only the resolver differs.)
"""
from __future__ import annotations

import json
import os
import secrets
import shlex
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


_BRIDGE_URL = os.environ.get("CLOUDLEARN_RUNTIME_BRIDGE_URL",
                             "http://host.docker.internal:9171").rstrip("/")
_WORKSPACE_ROOT = Path(os.environ.get(
    "CLOUDLEARN_DEPLOY_DIR", "/var/lib/cloudlearn/deployments"))

# Port range for VM-side SSH proxy listeners. Avoids common ports + the
# multipass DHCP range. Each instance gets one unique port; recorded on the
# instance state so we don't double-assign.
_SSH_PORT_MIN = 12200
_SSH_PORT_MAX = 12999


# ── runtime bridge helpers ───────────────────────────────────────────────────

def _bridge_run(backend: str, args: list[str], timeout: int = 60) -> dict:
    """Proxy a CLI call through the runtime bridge. Returns
    {returncode, stdout, stderr}. backend is one of 'lxd', 'multipass', 'host'.
    """
    payload = json.dumps({"backend": backend, "args": args, "timeout": timeout}).encode()
    req = urllib.request.Request(
        f"{_BRIDGE_URL}/run", data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"returncode": e.code, "stdout": "", "stderr": e.read().decode("utf-8", errors="replace")}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": f"{type(e).__name__}: {e}"}


def _vm_external_ip() -> str:
    """Best effort: ask the runtime bridge for the VM's external IP. The
    bridge runs on the VM as a host process so `hostname -I` lists every
    interface; we pick the first non-loopback, non-LXD-bridge address.
    """
    r = _bridge_run("host", ["hostname", "-I"], timeout=5)
    if r.get("returncode") != 0:
        return ""
    candidates = [ip.strip() for ip in (r.get("stdout") or "").split() if ip.strip()]
    for ip in candidates:
        # Skip LXD bridge (10.x.x.1) and docker bridge (172.x); we want the
        # multipass-side IP the user's Mac actually routes to.
        if ip.startswith("127.") or ip.startswith("10.231.") or ip.startswith("172."):
            continue
        return ip
    # Fallback: take the first whatever
    return candidates[0] if candidates else ""


# ── port allocation ─────────────────────────────────────────────────────────

def _claim_ssh_port(state: dict, instance_id: str) -> int:
    """Pick a free port in [_SSH_PORT_MIN, _SSH_PORT_MAX] not yet claimed by
    another instance. Records the claim on `state['vm_connect_ports']` so
    siblings see it. Idempotent — returns the existing port if this
    instance already owns one.
    """
    claims = state.setdefault("vm_connect_ports", {})
    if not isinstance(claims, dict):
        claims = {}
        state["vm_connect_ports"] = claims
    # Already allocated?
    for port, owner in claims.items():
        if owner == instance_id:
            try:
                return int(port)
            except Exception:
                continue
    taken = {int(p) for p in claims.keys() if str(p).isdigit()}
    for port in range(_SSH_PORT_MIN, _SSH_PORT_MAX + 1):
        if port not in taken:
            claims[str(port)] = instance_id
            return port
    raise RuntimeError("vm-connect port pool exhausted")


def release_ssh_port(state: dict, instance_id: str) -> None:
    """Drop the port claim when an instance is terminated. Best-effort —
    silent on miss. Call sites: EC2 terminate, GCP delete, Azure delete.
    """
    claims = state.get("vm_connect_ports") or {}
    if not isinstance(claims, dict):
        return
    for port, owner in list(claims.items()):
        if owner == instance_id:
            claims.pop(port, None)


# ── core provisioning ───────────────────────────────────────────────────────

def _generate_keypair(workspace: Path) -> tuple[Path, Path]:
    """Create ed25519 keypair in the workspace if it doesn't exist already.
    Returns (private_path, public_path)."""
    private = workspace / "ssh_key"
    public = workspace / "ssh_key.pub"
    if private.exists() and public.exists():
        return private, public
    workspace.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(private),
         "-C", f"vyomi-vm-{workspace.name}"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    os.chmod(private, 0o600)
    return private, public


def _provision_container_ssh(container_name: str, workspace: Path,
                             ssh_user: str) -> dict[str, Any]:
    """Run the lxc-side provisioning: install sshd, push authorized_keys,
    enable sshd. Idempotent — re-running has no effect after the first
    successful pass.

    Returns {"ok": bool, "details": [...]} for diagnostics.
    """
    public_key_local = workspace / "ssh_key.pub"
    if not public_key_local.exists():
        return {"ok": False, "details": ["public key missing"]}
    pubkey = public_key_local.read_text().strip()
    if not pubkey:
        return {"ok": False, "details": ["public key empty"]}

    details: list[str] = []

    # 1. Install openssh-server + enable. Run in a single `bash -c` so
    #    we don't pay 5 round trips through the bridge.
    setup_script = (
        "set -e; "
        # Some images already have sshd; the apt install is a no-op then.
        "DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server >/dev/null 2>&1 || "
        "  yum install -y openssh-server >/dev/null 2>&1 || true; "
        f"id -u {ssh_user} >/dev/null 2>&1 || useradd -m -s /bin/bash {ssh_user}; "
        f"mkdir -p /home/{ssh_user}/.ssh; "
        f"chmod 700 /home/{ssh_user}/.ssh; "
        f"touch /home/{ssh_user}/.ssh/authorized_keys; "
        f"chmod 600 /home/{ssh_user}/.ssh/authorized_keys; "
        f"chown -R {ssh_user}:{ssh_user} /home/{ssh_user}/.ssh; "
        "systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd 2>/dev/null || "
        "  service ssh start 2>/dev/null || service sshd start 2>/dev/null || true; "
        # Allow password-less + pubkey logins
        "sed -i 's/^#\\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config; "
        "sed -i 's/^#\\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config; "
        "systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || true"
    )
    r = _bridge_run("lxd", ["exec", container_name, "--", "bash", "-c", setup_script], timeout=120)
    details.append(f"setup rc={r.get('returncode')} stderr={(r.get('stderr') or '')[:200]}")
    if r.get("returncode") != 0:
        return {"ok": False, "details": details}

    # 2. Push our public key into authorized_keys via stdin-driven write.
    inject = (
        f"set -e; printf '%s\\n' {shlex.quote(pubkey)} > /home/{ssh_user}/.ssh/authorized_keys; "
        f"chmod 600 /home/{ssh_user}/.ssh/authorized_keys; "
        f"chown {ssh_user}:{ssh_user} /home/{ssh_user}/.ssh/authorized_keys"
    )
    r = _bridge_run("lxd", ["exec", container_name, "--", "bash", "-c", inject], timeout=30)
    details.append(f"inject rc={r.get('returncode')} stderr={(r.get('stderr') or '')[:200]}")
    if r.get("returncode") != 0:
        return {"ok": False, "details": details}

    return {"ok": True, "details": details}


def _ensure_proxy_device(container_name: str, vm_port: int) -> dict[str, Any]:
    """Add an `lxc proxy` device that forwards VM:<vm_port> → container:22.
    Re-running is safe — lxc errors with 'already exists' which we treat
    as success."""
    # Probe — is there already a device with this name?
    r = _bridge_run("lxd", ["config", "device", "show", container_name], timeout=10)
    if "ssh-vyomi" in (r.get("stdout") or ""):
        return {"ok": True, "existed": True}
    r = _bridge_run("lxd", [
        "config", "device", "add", container_name, "ssh-vyomi", "proxy",
        f"listen=tcp:0.0.0.0:{vm_port}",
        "connect=tcp:127.0.0.1:22",
    ], timeout=15)
    err = (r.get("stderr") or "").lower()
    if r.get("returncode") == 0 or "already exists" in err:
        return {"ok": True, "existed": "already exists" in err}
    return {"ok": False, "stderr": r.get("stderr", "")}


# ── public API ──────────────────────────────────────────────────────────────

def connect_info(state: dict, instance: dict, *, provider: str,
                 force_reprovision: bool = False) -> dict[str, Any]:
    """Compute (and lazily provision) Connect info for a single VM instance.

    Returns a dict with two command lines:
      - ssh.command           : real SSH command runnable from the user's host
      - lxc.command           : `multipass exec ... lxc shell ...` fallback
    Plus metadata: ssh user/host/port, container_name, key_download_url.

    The caller (per-cloud route) decides the key_download_url path —
    different prefixes per provider — by inserting `provider` into the
    URL template. Defaults to `/api/{provider}/instances/{id}/private-key.pem`.

    `provider` is one of "aws" | "gcp" | "azure"; only affects the
    download URL + SSH user inference fallback.
    """
    instance_id = str(instance.get("instance_id")
                      or instance.get("name")
                      or instance.get("id") or "").strip()
    if not instance_id:
        return {"ok": False, "reason": "instance_id missing"}

    container_name = str(
        instance.get("container_name")
        or instance.get("lxd_container")
        or instance.get("container_id") or "").strip()
    if not container_name:
        return {"ok": False, "reason": "container_name missing — backend may not be LXD",
                "instance_id": instance_id}

    # Pick the SSH user. Ubuntu AMIs → ubuntu; CentOS/RHEL/AL2 would be
    # ec2-user. The simulator's AMI catalog is ubuntu-only today, so this
    # is correct for every running instance. Surface as a field for future
    # AMI families.
    ami_name = str(instance.get("ami_name") or instance.get("ami") or "").lower()
    if "centos" in ami_name or "amazon" in ami_name or "amzn" in ami_name:
        ssh_user = "ec2-user"
    else:
        ssh_user = "ubuntu"
    instance["ssh_user"] = ssh_user

    workspace = _WORKSPACE_ROOT / instance_id

    # Provisioning skip-list: state["vm_connect_provisioned"] is a dict of
    # instance_id → True. Subsequent Connect clicks just read cached info.
    provisioned = state.setdefault("vm_connect_provisioned", {})
    is_provisioned = bool(provisioned.get(instance_id)) and not force_reprovision

    if not is_provisioned:
        try:
            _generate_keypair(workspace)
        except Exception as e:
            return {"ok": False, "reason": f"keygen_failed: {e}",
                    "instance_id": instance_id}
        prov = _provision_container_ssh(container_name, workspace, ssh_user)
        if not prov.get("ok"):
            return {"ok": False, "reason": "container_provisioning_failed",
                    "details": prov.get("details"), "instance_id": instance_id}

    # Allocate a port (idempotent — same port returned on subsequent calls)
    try:
        vm_port = _claim_ssh_port(state, instance_id)
    except RuntimeError as e:
        return {"ok": False, "reason": str(e), "instance_id": instance_id}

    proxy = _ensure_proxy_device(container_name, vm_port)
    if not proxy.get("ok"):
        return {"ok": False, "reason": "proxy_device_failed",
                "details": proxy.get("stderr"), "instance_id": instance_id}

    if not is_provisioned:
        provisioned[instance_id] = True

    vm_ip = _vm_external_ip()
    private_key_path = str((workspace / "ssh_key").resolve())

    # Real SSH command — what the user pastes into a terminal.
    # Use a stable local filename so re-downloads overwrite cleanly.
    local_key_filename = f"vyomi-{instance_id}.pem"
    ssh_cmd = (
        f"ssh -i ~/Downloads/{local_key_filename} "
        f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"-p {vm_port} {ssh_user}@{vm_ip or '<appliance-ip>'}"
    )

    # The lxc shell fallback works when the user is on the same machine as
    # the multipass appliance VM (i.e., their dev laptop).
    lxc_cmd = f"multipass exec cloudlearn-appliance -- sudo lxc shell {container_name}"

    # Record on instance so SPA tables can show it without an extra fetch.
    instance["ssh_command"] = ssh_cmd
    instance["ssh_port"] = vm_port
    instance["ssh_host"] = vm_ip or "<appliance-ip>"
    instance["ssh_target"] = f"{ssh_user}@{vm_ip}" if vm_ip else ""

    key_download_url = f"/api/{provider}/instances/{instance_id}/private-key.pem"

    return {
        "ok": True,
        "instance_id": instance_id,
        "provisioned": True,
        "container_name": container_name,
        "ssh": {
            "command": ssh_cmd,
            "user": ssh_user,
            "host": vm_ip or "<appliance-ip>",
            "port": vm_port,
            "key_download_url": key_download_url,
            "key_local_filename": local_key_filename,
        },
        "lxc": {
            "command": lxc_cmd,
            "note": "Works when you're on the same machine running the appliance VM.",
        },
        "note": (
            "First connect provisioned an SSH key + opened a proxy port. "
            "Future connects to this instance reuse them."
        ),
    }


def read_private_key(instance_id: str) -> Optional[bytes]:
    """Return the raw ed25519 private key bytes for download, or None if
    not yet provisioned."""
    private = (_WORKSPACE_ROOT / instance_id / "ssh_key").resolve()
    try:
        return private.read_bytes()
    except Exception:
        return None

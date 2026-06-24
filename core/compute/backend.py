"""Docker-backed compute for Vyomi instances (CloudLite+ / appliance).

Promoted from spikes/docker-instance/backend.py (spike: PASS — create→boot→
shell→DinD→persist→terminate on plain Docker). Adds SSH public-key injection so
`ssh ubuntu@<instance-ip>` works the moment an instance boots — the EC2/VM
"ssh in" UX on a plain Docker container.

The ComputeBackend ABC is the seam server.py calls; mapping onto the LXD funcs
being replaced:
    _ensure_container / _start_lxd_instance   -> create + start
    _start_instance_command / exec            -> exec
    _stop/_reboot/_terminate                  -> stop / reboot / terminate
    _lxd_status / _lxd_container_ipv4         -> status / ipv4
    _multipass_ssh_target / key injection     -> ssh_info / Instance.ssh_pubkey
"""
from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_INSTANCE_IMAGE = os.environ.get("VYOMI_INSTANCE_IMAGE", "vyomi/instance:ubuntu-24.04")


@dataclass
class Instance:
    """Provider-neutral instance record (server.py passes a dict today; only the
    fields the backend needs are modelled here)."""
    instance_id: str
    image: str = DEFAULT_INSTANCE_IMAGE   # the "AMI"
    cpus: float = 1.0                     # instance-type knobs -> cgroup limits
    memory_mb: int = 1024
    privileged: bool = True               # required for docker-in-instance (DinD)
    ssh_pubkey: str | None = None         # injected at create() -> authorized_keys
    network: str | None = None            # attach to a specific docker network
    labels: dict = field(default_factory=dict)

    @property
    def container_name(self) -> str:
        return f"vyomi-i-{self.instance_id}"

    @property
    def root_volume(self) -> str:
        # Named volume = the instance's persistent disk (EBS-like). Survives
        # stop/start AND rm/recreate.
        return f"vyomi-i-{self.instance_id}-root"


class ComputeBackend(ABC):
    """The seam. server.py calls only these methods."""

    @abstractmethod
    def create(self, inst: Instance) -> str: ...
    @abstractmethod
    def start(self, inst: Instance) -> None: ...
    @abstractmethod
    def stop(self, inst: Instance) -> None: ...
    @abstractmethod
    def reboot(self, inst: Instance) -> None: ...
    @abstractmethod
    def terminate(self, inst: Instance) -> None: ...
    @abstractmethod
    def status(self, inst: Instance) -> str: ...
    @abstractmethod
    def ipv4(self, inst: Instance) -> str | None: ...
    @abstractmethod
    def exec(self, inst: Instance, cmd: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess: ...
    @abstractmethod
    def ssh_info(self, inst: Instance) -> dict: ...


class DockerComputeBackend(ComputeBackend):
    """Docker implementation — shells out to the `docker` CLI exactly like the
    LXD code shells out to `lxc`."""

    def __init__(self, docker: str = "docker", default_timeout: int = 900):
        self._docker = docker
        self._timeout = default_timeout

    def _run(self, args: list[str], timeout: int | None = None,
             stdin: bytes | None = None, check: bool = False) -> subprocess.CompletedProcess:
        cp = subprocess.run([self._docker, *args], capture_output=True,
                            input=stdin, timeout=timeout or self._timeout)
        if check and cp.returncode != 0:
            raise RuntimeError(f"docker {' '.join(args)} failed: {cp.stderr.decode(errors='replace')}")
        return cp

    # ── lifecycle ────────────────────────────────────────────────────────────
    def create(self, inst: Instance) -> str:
        self._run(["volume", "create", inst.root_volume], check=True)
        # Idempotent: reuse if it already exists (mirrors _ensure_container).
        if self.status(inst) != "absent":
            self.start(inst)
            return inst.container_name
        args = [
            "run", "-d", "--name", inst.container_name,
            "--label", "vyomi.instance=1",
            "--label", f"vyomi.instance_id={inst.instance_id}",
            "--restart", "unless-stopped",
            # instance-type sizing -> cgroup limits (LXD limits.cpu/limits.memory)
            "--cpus", str(inst.cpus),
            "--memory", f"{inst.memory_mb}m",
            # persistent root/EBS for the inner docker store + user data
            "-v", f"{inst.root_volume}:/var/lib/docker",
        ]
        # SSH key injection: the entrypoint writes this to authorized_keys on
        # boot AND on every `docker start` (env persists), so SSH works out of
        # the box and survives stop/start.
        if inst.ssh_pubkey:
            args += ["-e", f"VYOMI_SSH_PUBKEY={inst.ssh_pubkey}"]
        if inst.network:
            args += ["--network", inst.network]
        if inst.privileged:                 # == LXD security.nesting, for DinD
            args.append("--privileged")
        args.append(inst.image)
        self._run(args, timeout=self._timeout, check=True)
        return inst.container_name

    def start(self, inst: Instance) -> None:
        self._run(["start", inst.container_name], check=True)

    def stop(self, inst: Instance) -> None:
        self._run(["stop", "-t", "10", inst.container_name])

    def reboot(self, inst: Instance) -> None:
        self._run(["restart", "-t", "10", inst.container_name], check=True)

    def terminate(self, inst: Instance) -> None:
        self._run(["rm", "-f", inst.container_name])
        self._run(["volume", "rm", inst.root_volume])   # detach + delete disk

    # ── introspection ────────────────────────────────────────────────────────
    def status(self, inst: Instance) -> str:
        cp = self._run(["inspect", "-f", "{{.State.Status}}", inst.container_name], timeout=30)
        if cp.returncode != 0:
            return "absent"
        # Normalise docker states -> the AWS-ish states the SPA renders.
        raw = cp.stdout.decode().strip()
        return {"running": "running", "created": "stopped", "exited": "stopped",
                "paused": "stopped", "restarting": "pending"}.get(raw, raw)

    def ipv4(self, inst: Instance) -> str | None:
        cp = self._run(["inspect", "-f",
                        "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
                        inst.container_name], timeout=30)
        ip = cp.stdout.decode().strip().split(" ")[0] if cp.stdout else ""
        return ip or None

    def exec(self, inst: Instance, cmd: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
        flags = ["exec", "-i", inst.container_name] if stdin is not None else ["exec", inst.container_name]
        return self._run(flags + cmd, stdin=stdin)

    def ssh_info(self, inst: Instance) -> dict:
        """Connection details for `ssh`. The instance image runs sshd on :22 and
        the public key was injected at launch, so this is host + user only."""
        return {"host": self.ipv4(inst), "port": 22, "user": "ubuntu"}


# ── SSH key management ───────────────────────────────────────────────────────
def ensure_instance_ssh_key(key_dir: str | os.PathLike | None = None) -> tuple[str, Path]:
    """Ensure an ed25519 keypair exists for SSHing into instances; return
    (public_key_text, private_key_path). The public key is injected into
    instances at launch (Instance.ssh_pubkey); the private key is what the user
    / the console's web-SSH connects with.

    Mirrors the intent of the old _multipass_ssh_identity, but backend-neutral.
    """
    base = Path(key_dir or os.environ.get("VYOMI_INSTANCE_KEY_DIR")
                or (Path.home() / ".vyomi" / "instance-keys"))
    base.mkdir(parents=True, exist_ok=True)
    priv = base / "id_ed25519"
    pub = base / "id_ed25519.pub"
    if not priv.exists() or not pub.exists():
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "vyomi-instance",
             "-f", str(priv)],
            check=True, capture_output=True,
        )
        try:
            priv.chmod(0o600)
        except OSError:
            pass
    return pub.read_text().strip(), priv

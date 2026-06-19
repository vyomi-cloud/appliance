"""
SPIKE — throwaway. Docker-backed compute instance, end-to-end.

Goal: prove the LXD/multipass instance lifecycle in server.py can be served by
Docker instead, behind ONE small interface — so the appliance drops LXD +
multipass + the runtime bridge, and so a future in-process / WebVM backend can
slot into the SAME seam (Docker itself does NOT run inside WebVM — the seam is
what's portable, not dockerd).

Maps onto the real functions being replaced:
    _ensure_container / _start_lxd_instance   -> ComputeBackend.create + start
    _start_instance_command / exec            -> ComputeBackend.exec
    _stop_lxd_instance / _reboot / _terminate -> stop / reboot / terminate
    _lxd_status / _lxd_container_ipv4         -> status / ipv4
    _multipass_ssh_target                     -> ssh_info
    _lxd_docker_bootstrap_async (docker-in-VM)-> handled natively (DinD image)

Not wired into server.py. Run via run_spike.sh.
"""
from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Instance:
    """The provider-neutral instance record server.py already passes around
    (a dict today). Only the fields the backend needs are modelled here."""
    instance_id: str
    image: str = "docker:dind"            # the "AMI"; a VM-like base for prod
    cpus: float = 1.0                     # instance-type knobs -> cgroup limits
    memory_mb: int = 1024
    privileged: bool = True               # required for docker-in-instance (DinD)
    labels: dict = field(default_factory=dict)

    @property
    def container_name(self) -> str:
        return f"vyomi-i-{self.instance_id}"

    @property
    def root_volume(self) -> str:
        # Named volume = the instance's persistent disk. Survives stop/start AND
        # rm/recreate, which is the EBS-like semantic LXD gave us for free.
        return f"vyomi-i-{self.instance_id}-root"


class ComputeBackend(ABC):
    """The seam. server.py calls only these; today LXD, tomorrow Docker, later
    possibly an in-process backend for a browser/WebVM 'Lite' build."""

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
    """Docker implementation. Shells out to the `docker` CLI exactly like the
    current code shells out to `lxc` (subprocess + checked runs)."""

    def __init__(self, docker: str = "docker", default_timeout: int = 900):
        self._docker = docker
        self._timeout = default_timeout

    # --- mirror of _lxd_run / _lxd_run_checked --------------------------------
    def _run(self, args: list[str], timeout: int | None = None,
             stdin: bytes | None = None, check: bool = False) -> subprocess.CompletedProcess:
        cp = subprocess.run([self._docker, *args], capture_output=True,
                            input=stdin, timeout=timeout or self._timeout)
        if check and cp.returncode != 0:
            raise RuntimeError(f"docker {' '.join(args)} failed: {cp.stderr.decode(errors='replace')}")
        return cp

    # --- lifecycle ------------------------------------------------------------
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
        if inst.privileged:                 # == LXD security.nesting=true, but for DinD
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

    # --- introspection --------------------------------------------------------
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
                        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                        inst.container_name], timeout=30)
        ip = cp.stdout.decode().strip()
        return ip or None

    def exec(self, inst: Instance, cmd: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
        flags = ["exec", "-i", inst.container_name] if stdin is not None else ["exec", inst.container_name]
        return self._run(flags + cmd, stdin=stdin)

    def ssh_info(self, inst: Instance) -> dict:
        # In prod the VM-like image runs sshd; key injection ports straight from
        # the existing _multipass_ssh_* code. For the spike, `exec` is the shell
        # primitive and SSH is just sshd layered on top of the same container.
        return {"host": self.ipv4(inst), "port": 22, "user": "ubuntu",
                "transport": "sshd-in-container (port from _multipass_ssh_target)"}

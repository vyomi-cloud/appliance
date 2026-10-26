"""Docker-backed ECS task runtime (offline appliance, Pro / Max).

Plugs into `EcsStore.runtime`: when enabled (`VYOMI_ECS_DOCKER=1` and a reachable
docker CLI/socket) every ECS task container really runs on the Docker substrate, so
`RunTask` / a service's tasks serve real traffic on their `hostPort`s. Nano and the
Free / Lite tiers never load this module — there ECS is a control plane only.

`start` raises RuntimeError with the real ECS failure text (e.g. CannotPullContainerError)
when a container cannot start; the engine then stops the task with
stopCode=TaskFailedToStart exactly like the service does.
"""
from __future__ import annotations

import shutil
import subprocess


def available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


class DockerRuntime:
    def __init__(self, docker: str = "docker", pull_timeout: int = 300):
        self._docker, self._timeout = docker, pull_timeout

    def _run(self, args, timeout=None):
        return subprocess.run([self._docker, *args], capture_output=True, text=True, timeout=timeout or self._timeout)

    @staticmethod
    def _name(task: dict, container: dict) -> str:
        return f"vyomi-ecs-{task['taskArn'].rsplit('/', 1)[-1][:12]}-{container['name']}"

    def start(self, cluster: str, task: dict, taskdef: dict) -> None:
        defs = {c["name"]: c for c in taskdef["containerDefinitions"]}
        for c in task["containers"]:
            d = defs[c["name"]]
            cmd = [self._docker, "run", "-d", "--name", self._name(task, c), "--label", f"vyomi.ecs.cluster={cluster}",
                   "--label", f"vyomi.ecs.task={task['taskArn']}"]
            for e in d.get("environment", []):
                cmd += ["-e", f"{e['name']}={e['value']}"]
            if d.get("memory"):
                cmd += ["--memory", f"{d['memory']}m"]
            for pm in d.get("portMappings", []):
                bound = next((b for b in c.get("networkBindings", []) if b["containerPort"] == pm["containerPort"]), None)
                hp = (bound or {}).get("hostPort") or pm.get("hostPort")
                if hp:
                    cmd += ["-p", f"{hp}:{pm['containerPort']}/{pm.get('protocol', 'tcp')}"]
            if d.get("entryPoint"):
                cmd += ["--entrypoint", d["entryPoint"][0]]
            cmd.append(d["image"])
            cmd += list(d.get("command") or []) + list(d["entryPoint"][1:] if d.get("entryPoint") else [])
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
            if cp.returncode:
                self.stop(cluster, task)
                lines = [ln.strip() for ln in (cp.stderr or "").splitlines() if ln.strip()]
                msg = next((ln for ln in lines if "error" in ln.lower() or "unable" in ln.lower()), lines[0] if lines else "container failed to start")
                low = (cp.stderr or "").lower()
                kind = "CannotPullContainerError" if ("pull" in low or "unable to find image" in low or "lookup" in low) else "CannotStartContainerError"
                msg = [msg]
                raise RuntimeError(f"{kind}: {msg[0]}")
            c["runtimeId"] = cp.stdout.strip()

    def stop(self, cluster: str, task: dict) -> None:
        for c in task["containers"]:
            self._run(["rm", "-f", self._name(task, c)], timeout=60)

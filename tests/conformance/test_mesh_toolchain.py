"""Mesh per-instance toolchain: VYOMI_ROLE=mesh + toolchain=all -> the all-languages image; everything else unchanged.
Docker runtime is stubbed (no docker calls)."""
import os
import subprocess
import sys

from core.compute import backend as B

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


class Stub(B.DockerComputeBackend):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _run(self, args, timeout=None, stdin=None, check=False):
        self.calls.append(list(args))
        out = b"absent" if args[:1] == ["inspect"] else b""
        return subprocess.CompletedProcess(args, 1 if args[:1] == ["inspect"] else 0, out, b"")

    def status(self, inst):
        return "absent"


def run_image(image):
    b = Stub()
    b.create(B.Instance(instance_id="i-tc1", image=image))
    run = next(c for c in b.calls if c[:1] == ["run"])
    return run[-1]


for k in ("VYOMI_ROLE", "VYOMI_MESH_LANG_IMAGE"):
    os.environ.pop(k, None)
M = {"toolchain": "all"}
check("non-mesh ignores toolchain=all", B.mesh_toolchain_image(M) is None)

os.environ["VYOMI_ROLE"] = "mesh"
check("mesh + toolchain=all -> default lang image", B.mesh_toolchain_image(M) == "vyomi/mesh-lang:latest", B.mesh_toolchain_image(M))
check("mesh, no toolchain -> None", B.mesh_toolchain_image({}) is None)
check("toolchain=none -> None", B.mesh_toolchain_image({"toolchain": "none"}) is None)
check("label toolchain=all", B.mesh_toolchain_image({"labels": {"toolchain": "all"}}) is not None)
check("EC2 tag list toolchain=all", B.mesh_toolchain_image({"tags": [{"Key": "toolchain", "Value": "all"}]}) is not None)
check("tag dict toolchain=ALL (case-insens)", B.mesh_toolchain_image({"tags": {"toolchain": "ALL"}}) is not None)
os.environ["VYOMI_MESH_LANG_IMAGE"] = "reg.example/lang:9"
check("env override honoured", B.mesh_toolchain_image(M) == "reg.example/lang:9")

# end-to-end through server._docker_instance_obj + stubbed docker run
os.environ.setdefault("CLOUDLEARN_STATE_DIR", __import__("tempfile").mkdtemp(prefix="mesh-tc-"))
import server  # noqa: E402
inst = {"instance_id": "i-tc1", "toolchain": "all"}
check("server: mesh toolchain=all -> lang image in docker run", run_image(server._docker_instance_obj(dict(inst)).image) == "reg.example/lang:9")
check("server: mesh without toolchain -> default image", server._docker_instance_obj({"instance_id": "i-tc2"}).image != "reg.example/lang:9")
os.environ.pop("VYOMI_ROLE")
check("server: non-mesh toolchain=all -> default image", server._docker_instance_obj(dict(inst)).image != "reg.example/lang:9")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

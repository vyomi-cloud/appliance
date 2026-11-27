"""Fixed-slot host profile (VYOMI_MESH_HOST_PROFILE=cloudshell): Mesh compute on a Google Cloud Shell VM.

Numbers under test are the ones MEASURED on a real Cloud Shell session: 4 vCPU, 15,994 MB total RAM. Every instance is
0.5 vCPU / 2048 MB, 4096 MB is held back for Docker + the agent, CPU is an enforced slot budget, no AI bucket.
Hermetic: no Docker, no network. Does NOT prove the Cloud Shell API can start a session (that is the spike script)."""
import os
import sys
import tempfile
import time as _t

os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="mesh-cs-"))
os.environ["VYOMI_HOST_MEM_MB"] = "15994"
os.environ["VYOMI_MESH_CPUS"] = "4"
os.environ.pop("VYOMI_MESH_CAP_MB", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import mesh as B  # noqa: E402
from core import app_context as _ctx  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


_ctx._tier_cache.update({"tier": "max", "verified_at": _t.time(), "ttl": 10 ** 9})
_ctx.STATE["license_claims"] = {"tier": "max"}


def drain():
    for k in ("compute", "ai"):
        for i in list(B._LEDGER[k]):
            B.release(k, i)


def raises_capacity(fn):
    try:
        fn()
    except B.MeshCapacityError as e:
        return e
    return None


# ---- no profile: the normal budget is untouched ---------------------------------------------------------------------
os.environ.pop("VYOMI_MESH_HOST_PROFILE", None)
b0 = B.resource_budget()
check("no profile: budget has no profile block", "profile" not in b0)
check("no profile: AI bucket still exists (50/50 split)", b0["memory_split_mb"]["ai"] > 0, b0["memory_split_mb"])
check("no profile: profile_instance_size() is None", B.profile_instance_size() is None)
check("no profile: capacity() reports profile None", B.capacity()["profile"] is None)

# ---- cloudshell profile ---------------------------------------------------------------------------------------------
os.environ["VYOMI_MESH_HOST_PROFILE"] = "cloudshell"
drain()
b = B.resource_budget()
check("profile: RAM cap = host - 4096 reserve (11898)", b["memory_cap_mb"] == 15994 - 4096, b["memory_cap_mb"])
check("profile: all RAM is compute, AI bucket is 0", b["memory_split_mb"] == {"compute": 11898, "ai": 0}, b["memory_split_mb"])
check("profile: CPU cap = 4 - 1 reserve = 3.0 cores", b["cpu_cap_cores"] == 3.0, b["cpu_cap_cores"])
check("profile: slots = min(RAM 5, CPU 6) = 5", b["profile"]["slots_total"] == 5, b["profile"])
check("profile: instance size 0.5 vCPU / 2048 MB", B.profile_instance_size() == {"cpus": 0.5, "mem_mb": 2048}, B.profile_instance_size())

# server sizing: whatever type is asked for, the container gets the profile size
for t in ("t3.micro", "m5.4xlarge", "n2-standard-32", "Standard_D32s_v5"):
    mem = server._docker_instance_memory_mb({"instance_type": t})
    check(f"profile: {t} is sized 2048 MB", mem == 2048, mem)
check("profile: explicit memory_mb is overridden too", server._docker_instance_memory_mb({"memory_mb": 64}) == 2048)

# admission: 5 fit, the 6th is refused with the cloud's real capacity error
ids = B.reserve_slots("compute", 5, 2048, cloud="aws")
check("profile: 5 slots reserve atomically", len(ids) == 5, ids)
e = raises_capacity(lambda: B.reserve_slots("compute", 1, 2048, cloud="aws"))
check("profile: 6th is InsufficientInstanceCapacity (aws)", e is not None and e.code == "InsufficientInstanceCapacity", e)
e = raises_capacity(lambda: B.allocate("compute", "i-direct", 2048, cloud="gcp"))
check("profile: direct allocate refused too (gcp wire code)", e is not None and e.code == "ZONE_RESOURCE_POOL_EXHAUSTED", e)
cap = B.capacity()
check("capacity(): 5 of 5 slots used, 0 free", cap["slots"] == {"total": 5, "used": 5, "free": 0}, cap["slots"])
check("capacity(): CPU used 2.5 of 3.0 cores", cap["cpu"] == {"cap_cores": 3.0, "used_cores": 2.5}, cap["cpu"])
check("capacity(): RAM used 10240 of 11898", cap["memory"]["used_mb"] == 10240 and cap["memory"]["cap_mb"] == 11898, cap["memory"])
B.release_slots("compute", ids[:2])
check("release frees slots (3 used, 2 free)", B.capacity()["slots"] == {"total": 5, "used": 3, "free": 2}, B.capacity()["slots"])
B.allocate("compute", "i-a", 2048, cloud="aws")
B.allocate("compute", "i-a", 2048, cloud="aws")          # same ident replaces, never double counts
check("re-allocating the same id does not take a second slot", B.capacity()["slots"]["used"] == 4, B.capacity()["slots"])
drain()

# CPU is a real limit: on a 2-vCPU host only (2-1)/0.5 = 2 slots, though RAM would allow more
os.environ["VYOMI_MESH_CPUS"] = "2"
os.environ["VYOMI_HOST_MEM_MB"] = "15994"
check("CPU-bound host: slots = 2", B.resource_budget()["profile"]["slots_total"] == 2, B.resource_budget()["profile"])
two = B.reserve_slots("compute", 2, 2048)
e = raises_capacity(lambda: B.reserve_slots("compute", 1, 2048))
check("CPU-bound host: 3rd refused although RAM is free", e is not None, e)
B.release_slots("compute", two)
os.environ["VYOMI_MESH_CPUS"] = "4"

# env overrides
os.environ["VYOMI_MESH_PROFILE_INSTANCE_MB"] = "1024"
check("override: 1024 MB instances -> CPU-bound 6 slots", B.resource_budget()["profile"]["slots_total"] == 6, B.resource_budget()["profile"])
os.environ["VYOMI_MESH_PROFILE_INSTANCE_MB"] = "garbage"
check("override: bad value ignored (back to 2048)", B.profile_instance_size()["mem_mb"] == 2048)
os.environ.pop("VYOMI_MESH_PROFILE_INSTANCE_MB")

# session clock (nominal) + route
os.environ["VYOMI_MESH_SESSION_STARTED"] = str(_t.time() - 11 * 3600)
s = B.capacity()["session"]
check("session: ~1 h left of 12 h, marked nominal", 3300 <= s["left_s"] <= 3700 and s["max_s"] == 43200 and s["nominal"] is True, s)
os.environ["VYOMI_MESH_SESSION_STARTED"] = str(_t.time() - 13 * 3600)
check("session: past the cap clamps to 0", B.capacity()["session"]["left_s"] == 0)
check("weekly hours are nominal 50", B.capacity()["weekly_hours_nominal"] == 50)
os.environ.pop("VYOMI_MESH_SESSION_STARTED")

c = TestClient(server.app, base_url="http://127.0.0.1:9000")
c.__enter__()
r = c.get("/mesh/capacity")
check("GET /mesh/capacity answers 200 with the slot block", r.status_code == 200 and r.json().get("slots", {}).get("total") == 5,
      (r.status_code, r.text[:200]))
st = c.get("/mesh/status").json()
check("/mesh/status carries the capacity block under the profile", (st.get("capacity") or {}).get("slots", {}).get("total") == 5, st.get("capacity"))
os.environ.pop("VYOMI_MESH_HOST_PROFILE")
check("/mesh/status capacity is null without a profile", c.get("/mesh/status").json().get("capacity") is None)
drain()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

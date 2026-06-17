"""Map a real cloud instance type → host-feasible LXD / multipass container
limits.

The user picks (say) ``m5.8xlarge`` (32 vCPU / 128 GB). Your laptop has 8
cores and 16 GB. We can't honestly hand that to LXD. But the simulator should
still reflect the *relative* choice — bigger SKU → bigger container — within
the host's actual budget.

The mapping:

    tier_score = max(vcpu, ram_in_GB)

    score ≤ 1   → nano    (1 CPU,  256 MB)
    score ≤ 4   → small   (1 CPU,  512 MB)
    score ≤ 16  → medium  (2 CPU, 1024 MB)
    score ≤ 32  → large   (3 CPU, 2048 MB)
    score ≤ 64  → xlarge  (4 CPU, 4096 MB)
    score >  64 → huge    (5 CPU, 6144 MB)

then clamped by host: never more than ``host_cpus // 2`` CPUs or
``host_lxd_memory_mb // 3`` memory on one container, so several coexist.

The caller stores BOTH the requested shape (what the user picked) AND the
provisioned tier (what the container actually got), so the gap is visible in
the SDK / SPA response — e.g.::

    "runtime_sizing": {
        "requested_vcpu": 32, "requested_ram_mb": 131072,
        "cpu": 4, "memory_mb": 4096, "tier": "huge"
    }
"""
from __future__ import annotations


# Tier table: (max_score, tier_name, default_cpu, default_mem_mb).
#
# v2.0.4 (2026-06-17): bumped memory tiers significantly. The old values
# (medium = 1024MB, large = 2048MB) were sized for "demo simulator state
# bookkeeping", not for "user's docker compose stack". With docker
# bundled in (security.nesting=true), users want to spin up a t3.large
# and `docker compose up` their app — for that the container needs
# 3-6 GB realistically. Old values left them stuck at 1 GB which
# crashes anything non-trivial.
#
# Sizing principle now: pick tier values that match the SMALLEST docker
# compose stack the user would reasonably run in that tier. Real cloud
# instance sizes still don't fit on a laptop, but the relative tiering
# is preserved.
_TIERS = (
    (1,     "nano",   1,   256),     # t3.nano  — pure-python, no docker
    (4,     "small",  1,  1024),     # t3.micro/small/medium — 1-2 containers
    (8,     "medium", 2,  3072),     # t3.large — small compose stack (3-4 svc)
    (16,    "large",  3,  4096),     # m5.large — medium compose stack
    (32,    "xlarge", 4,  6144),     # m5.xlarge — full appliance-class stack
    (1 << 30, "huge", 6,  8192),     # m5.2xlarge+ — clamped to host budget
)


def shape_for_instance(instance_type: str, provider: str) -> dict | None:
    """Catalog lookup. `instance_type` is the bare name for AWS/Azure or either
    the bare name or full URL for GCP machineType (we strip to the last path
    segment). Returns None if unknown — caller should fall back to defaults."""
    from core import instance_catalog as cat
    p = (provider or "").strip().lower()
    if not instance_type:
        return None
    if p == "aws":
        shape = cat.AWS.get(instance_type)
    elif p == "gcp":
        name = str(instance_type).rstrip("/").rsplit("/", 1)[-1]
        shape = cat.GCP.get(name)
    elif p == "azure":
        shape = cat.AZURE.get(instance_type)
    else:
        shape = None
    if not shape:
        return None
    return {**shape, "name": instance_type}


def lxd_limits(shape: dict, host_cpus: int, host_mem_mb: int) -> dict:
    """Map a real cloud instance shape → LXD container limits.

    v2.0.4: clamp directly against the host caps passed in. The host_cpus
    and host_mem_mb are ALREADY the per-instance headroom budget
    (computed by host_budget_caps() — host total minus host+sim overhead).
    The old code double-divided those caps (// 2 and // 3) under the
    assumption that multiple instances would coexist, which left even a
    single t3.large with 1 CPU / 2 GB — too small to run docker.

    A user running a few coexisting instances can override with the
    CLOUDLEARN_RUNTIME_CAP_CPU / CLOUDLEARN_RUNTIME_CAP_MEM_MB env vars,
    which feed host_budget_caps() directly.
    """
    vcpu = max(1, int(shape.get("vcpu", 1)))
    ram_mb = max(128, int(shape.get("ram_mb", 1024)))
    score = max(vcpu, ram_mb // 1024 or 1)
    name, cpu, mem = "huge", 6, 8192
    for max_score, tn, tc, tm in _TIERS:
        if score <= max_score:
            name, cpu, mem = tn, tc, tm
            break
    cpu_cap = max(1, int(host_cpus))
    mem_cap = max(256, int(host_mem_mb))
    return {
        "tier": name,
        "cpu": min(cpu, cpu_cap),
        "memory_mb": min(mem, mem_cap),
        "requested_vcpu": vcpu,
        "requested_ram_mb": ram_mb,
        "host_cpu_cap": cpu_cap,
        "host_mem_cap_mb": mem_cap,
    }


def host_budget_caps() -> tuple[int, int]:
    """Per-container ceilings. v2.0.4 rewrite — used to clamp to the
    simulator's *own* budget (30-50% of host), which double-divided and
    left t3.large with 1 CPU / 1 GB. That made docker-in-LXD unusable.

    Now we cap against TOTAL host capacity minus headroom for the host
    OS + the simulator process itself, since the LXD container runs
    alongside (not inside) the simulator's budget.

    Per-instance ceiling = host_cpus - 1   ·  host_memory_mb - 2048
    (leaves 1 CPU + 2 GB free for the host + simulator).

    Override via CLOUDLEARN_RUNTIME_CAP_CPU + _RUNTIME_CAP_MEM_MB for
    deployments that want to dedicate more (e.g. CI machines, single-user
    dogfood appliances).
    """
    import os
    cap_cpu_env = os.environ.get("CLOUDLEARN_RUNTIME_CAP_CPU")
    cap_mem_env = os.environ.get("CLOUDLEARN_RUNTIME_CAP_MEM_MB")
    if cap_cpu_env and cap_mem_env:
        try:
            return max(1, int(cap_cpu_env)), max(256, int(cap_mem_env))
        except ValueError:
            pass
    try:
        import server
        b = server._simulator_budget()
        host_cpu = int(b.get("host_cpu") or 2)
        host_mem = int(b.get("host_memory_mb") or 2048)
        return max(1, host_cpu - 1), max(512, host_mem - 2048)
    except Exception:
        return (os.cpu_count() or 2), 2048


def for_instance_type(instance_type: str, provider: str) -> dict | None:
    """Convenience: catalog lookup + host-aware tier mapping in one call.
    Returns None if the instance_type isn't in the catalog (the caller should
    then launch with no `limits.*` flags, accepting LXD defaults)."""
    shape = shape_for_instance(instance_type, provider)
    if not shape:
        return None
    cpus, mem_mb = host_budget_caps()
    return {
        **lxd_limits(shape, cpus, mem_mb),
        "instance_type": instance_type,
        "family": shape.get("family", "general"),
    }

# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Real cloud instance-type catalog → CloudSim Plus shapes.

Each entry yields ``{vcpu, ram_mb, mips_per_vcpu, family}``. The Python bridge
(`CloudSimBridge.sync_counts`) walks a space's VM records, looks up the real
instance type in this catalog, and sends a deduplicated ``vm_shapes`` array to
the Java engine — which then builds heterogeneous CloudSim Plus VMs (right MIPS
/ PE / RAM per real shape) instead of a fixed "all VMs identical" model.

MIPS-per-vCPU normalization captures relative perf across families (CloudSim
Plus is unitless, so absolute numbers matter less than the ratios):

      burstable < general ≈ memory ≈ storage < compute < gpu(cpu)

Coverage is a curated sample — the most common sizes per family. Unknown sizes
fall back to a sensible default. To extend, just add entries.

Sources:
- AWS:   https://aws.amazon.com/ec2/instance-types/
- GCP:   https://cloud.google.com/compute/docs/machine-resource
- Azure: https://learn.microsoft.com/azure/virtual-machines/sizes
"""
from __future__ import annotations

# Relative MIPS/vCPU across families (CloudSim Plus is unitless).
_MIPS = {
    "burstable": 1000,   # baseline, can burst (we don't model bursting yet)
    "general":   2400,
    "memory":    2400,   # same CPU perf as general; RAM ratio differs
    "storage":   2400,
    "compute":   3400,   # higher clock, compute-optimized
    "gpu":       3000,   # CPU portion; the GPU itself is not modeled
}


def _shape(vcpu: int, ram_mb: int, family: str, *, name: str | None = None) -> dict:
    return {"name": name, "vcpu": int(vcpu), "ram_mb": int(ram_mb),
            "mips_per_vcpu": _MIPS.get(family, 2400), "family": family}


# ──────────────────────────────────────────────────────────────────────────────
# AWS (EC2)
# ──────────────────────────────────────────────────────────────────────────────
AWS: dict[str, dict] = {
    # Burstable t3 — shared cores, low baseline, CPU-credit bursting (uncomodeled)
    "t3.nano":     _shape(2,   512, "burstable"),
    "t3.micro":    _shape(2,  1024, "burstable"),
    "t3.small":    _shape(2,  2048, "burstable"),
    "t3.medium":   _shape(2,  4096, "burstable"),
    "t3.large":    _shape(2,  8192, "burstable"),
    "t3.xlarge":   _shape(4, 16384, "burstable"),
    "t3.2xlarge":  _shape(8, 32768, "burstable"),
    # General-purpose m5 / m6i (1 vCPU : 4 GB)
    "m5.large":    _shape(2,   8192, "general"),
    "m5.xlarge":   _shape(4,  16384, "general"),
    "m5.2xlarge":  _shape(8,  32768, "general"),
    "m5.4xlarge":  _shape(16, 65536, "general"),
    "m5.8xlarge":  _shape(32,131072, "general"),
    "m6i.large":   _shape(2,   8192, "general"),
    "m6i.xlarge":  _shape(4,  16384, "general"),
    # Compute-optimized c5 / c6i (1 vCPU : 2 GB, higher MIPS)
    "c5.large":    _shape(2,   4096, "compute"),
    "c5.xlarge":   _shape(4,   8192, "compute"),
    "c5.2xlarge":  _shape(8,  16384, "compute"),
    "c5.4xlarge":  _shape(16, 32768, "compute"),
    "c6i.large":   _shape(2,   4096, "compute"),
    "c6i.xlarge":  _shape(4,   8192, "compute"),
    # Memory-optimized r5 / r6i (1 vCPU : 8 GB)
    "r5.large":    _shape(2,  16384, "memory"),
    "r5.xlarge":   _shape(4,  32768, "memory"),
    "r5.2xlarge":  _shape(8,  65536, "memory"),
    "r5.4xlarge":  _shape(16,131072, "memory"),
    # Storage-optimized i3 / i4i (local NVMe — we model RAM only)
    "i3.large":    _shape(2,  15360, "storage"),
    "i3.xlarge":   _shape(4,  31232, "storage"),
    "i4i.large":   _shape(2,  16384, "storage"),
    # GPU (CPU portion modeled; GPU not)
    "p3.2xlarge":  _shape(8,  61440, "gpu"),
    "g5.xlarge":   _shape(4,  16384, "gpu"),
}

# ──────────────────────────────────────────────────────────────────────────────
# GCP Compute Engine
# ──────────────────────────────────────────────────────────────────────────────
GCP: dict[str, dict] = {
    # Cost-optimized E2 (shared-core for micro/small/medium)
    "e2-micro":      _shape(2,  1024, "burstable"),
    "e2-small":      _shape(2,  2048, "burstable"),
    "e2-medium":     _shape(2,  4096, "burstable"),
    "e2-standard-2": _shape(2,   8192, "general"),
    "e2-standard-4": _shape(4,  16384, "general"),
    "e2-standard-8": _shape(8,  32768, "general"),
    # General N2 / N2D
    "n2-standard-2":  _shape(2,   8192, "general"),
    "n2-standard-4":  _shape(4,  16384, "general"),
    "n2-standard-8":  _shape(8,  32768, "general"),
    "n2-standard-16": _shape(16, 65536, "general"),
    "n2-standard-32": _shape(32,131072, "general"),
    # Compute-optimized C2
    "c2-standard-4":  _shape(4,  16384, "compute"),
    "c2-standard-8":  _shape(8,  32768, "compute"),
    "c2-standard-16": _shape(16, 65536, "compute"),
    "c2-standard-30": _shape(30,122880, "compute"),
    # High-memory N2
    "n2-highmem-2":  _shape(2,  16384, "memory"),
    "n2-highmem-4":  _shape(4,  32768, "memory"),
    "n2-highmem-8":  _shape(8,  65536, "memory"),
    # Memory-monster M2
    "m2-ultramem-208": _shape(208, 5816320, "memory"),  # 5.5 TB
    # GPU / Accelerator A2 (CPU portion modeled)
    "a2-highgpu-1g":  _shape(12,  89088, "gpu"),
    "a2-highgpu-2g":  _shape(24, 178176, "gpu"),
}

# ──────────────────────────────────────────────────────────────────────────────
# Azure
# ──────────────────────────────────────────────────────────────────────────────
AZURE: dict[str, dict] = {
    # Burstable B
    "Standard_B1s":   _shape(1,  1024, "burstable"),
    "Standard_B1ms":  _shape(1,  2048, "burstable"),
    "Standard_B2s":   _shape(2,  4096, "burstable"),
    "Standard_B2ms":  _shape(2,  8192, "burstable"),
    "Standard_B4ms":  _shape(4, 16384, "burstable"),
    "Standard_B8ms":  _shape(8, 32768, "burstable"),
    # General-purpose D v5 (1 vCPU : 4 GB)
    "Standard_D2s_v5":  _shape(2,   8192, "general"),
    "Standard_D4s_v5":  _shape(4,  16384, "general"),
    "Standard_D8s_v5":  _shape(8,  32768, "general"),
    "Standard_D16s_v5": _shape(16, 65536, "general"),
    "Standard_D32s_v5": _shape(32,131072, "general"),
    # Compute F v2 (1 vCPU : 2 GB)
    "Standard_F2s_v2":  _shape(2,   4096, "compute"),
    "Standard_F4s_v2":  _shape(4,   8192, "compute"),
    "Standard_F8s_v2":  _shape(8,  16384, "compute"),
    "Standard_F16s_v2": _shape(16, 32768, "compute"),
    # Memory E v5 (1 vCPU : 8 GB)
    "Standard_E2s_v5":  _shape(2,  16384, "memory"),
    "Standard_E4s_v5":  _shape(4,  32768, "memory"),
    "Standard_E8s_v5":  _shape(8,  65536, "memory"),
    "Standard_E16s_v5": _shape(16,131072, "memory"),
    # Memory-monster M
    "Standard_M128ms": _shape(128, 3892224, "memory"),  # ~3.8 TB
    # Storage L v3
    "Standard_L8s_v3":  _shape(8,  65536, "storage"),
    # GPU NC (V100 / older)
    "Standard_NC6":   _shape(6,   57344, "gpu"),
    "Standard_NC12":  _shape(12, 114688, "gpu"),
    "Standard_NC24":  _shape(24, 229376, "gpu"),
}


_DEFAULT_GENERAL   = _shape(2,  8192, "general")
_DEFAULT_BURSTABLE = _shape(1,  1024, "burstable")


def _annotate(shape: dict, name: str) -> dict:
    out = dict(shape)
    out["name"] = name
    return out


def lookup_aws(instance_type: str) -> dict:
    if not instance_type:
        return _annotate(_DEFAULT_BURSTABLE, "t3.nano")
    return _annotate(AWS.get(instance_type, _DEFAULT_GENERAL), instance_type)


def lookup_gcp(machine_type: str) -> dict:
    """`machine_type` may be a bare name (``e2-medium``) or a full URL
    (``...zones/X/machineTypes/e2-medium``); we use the last segment."""
    if not machine_type:
        return _annotate(_DEFAULT_BURSTABLE, "e2-micro")
    name = str(machine_type).rstrip("/").rsplit("/", 1)[-1]
    return _annotate(GCP.get(name, _DEFAULT_GENERAL), name)


def lookup_azure(vm_size: str) -> dict:
    if not vm_size:
        return _annotate(_DEFAULT_BURSTABLE, "Standard_B1s")
    return _annotate(AZURE.get(vm_size, _DEFAULT_GENERAL), vm_size)

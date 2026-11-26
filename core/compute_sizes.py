"""Compute sizes each substrate can ACTUALLY run: the one shared source for pickers, describe-* answers and create-time enforcement.

Real size NAMES stay verbatim (t3.micro, e2-medium, Standard_B1s) and the real cloud spec is what the console shows; what changes
per substrate is WHICH names are offered, plus the vCPU / memory the substrate will honour for them.

  Nano  - in-browser v86 VM (wasm/vm/vm-worker.js, wasm/vm/nano-vm-host.js)
          * 1 vCPU always (v86 emulates a single CPU), 32-bit x86 guest, so no arm / 64-bit-only types
          * guest RAM = `memory_size: mem_mb` MiB; the host's own largest tier has always been 1024 MiB (_VM_MEM_MB "large")
          * RAM is also the VM's root disk (no disk image beyond it), so there is nothing more to size
          * each VM is its own Worker + a per-(image, RAM) golden snapshot in IndexedDB; the code has NO concurrency cap, so
            TOTAL_MEM_MB below is an advisory browser budget (shown, not enforced)
  Mesh  - Docker containers (core/compute/backend.py: `docker run --cpus N --memory Mm`) inside the Mesh Codespace
          (4 vCPU / 16 GB by default).  core/mesh.py keeps a ledger: 70% of host RAM is the Mesh cap, split 50/50 compute/AI
          (all compute when the LLM is remote).  A single instance may take at most MESH_MAX_SHARE of the compute bucket so a
          second one still fits; vCPU is capped at the host cores.
  offline (a plain appliance, Free..Max tiers) is not restricted here: it keeps the full catalog and its existing tier caps.

Pure stdlib + core.instance_catalog, so it is vendored to the Nano bundle by wasm/build_cores.py unchanged.
"""
from __future__ import annotations

import os
import sys

try:                                              # host: package import
    from core import instance_catalog as _cat
except ImportError:                               # Pyodide: cores are flat on sys.path
    import instance_catalog as _cat               # type: ignore

# ── limits (the machine-readable source; `python -m core.compute_sizes` prints it as JSON) ─────────────────────────
NANO = {"label": "Nano (browser VM)", "engine": "v86", "vcpu": 1, "max_mem_mb": 1024, "total_mem_mb": 3072,
        "code": "wasm/vm/vm-worker.js (memory_size), wasm/vm/nano-vm-host.js (mem_mb), wasm/providers/registry.py (_VM_MEM_MB)"}
MESH_MAX_SHARE = 0.75      # one instance may use at most this share of the compute bucket (headroom for the appliance + a neighbour)
MESH_HARD_MAX_MB = 8192    # never offered above this even on a huge host
MESH = {"label": "Mesh (Docker)", "engine": "docker", "default_host": {"vcpu": 4, "ram_mb": 16384, "disk_gb": 32},
        "max_share_of_compute_bucket": MESH_MAX_SHARE, "hard_max_mem_mb": MESH_HARD_MAX_MB,
        "code": "core/compute/backend.py (--cpus/--memory), core/mesh.py (resource_budget, 70% cap, 50/50 split), server.py _docker_instance_memory_mb"}
# Families a container / a 32-bit VM can stand in for; GPU, memory-monster and storage shapes are never offered.
_FAMILIES = ("burstable", "general", "compute")
_NANO_FAMILIES = ("burstable",)           # the Nano VM gives the type's full RAM only for the small shared-core sizes
_CATALOG = {"aws": _cat.AWS, "gcp": _cat.GCP, "azure": _cat.AZURE}
_OFF = ("", "offline")


def substrate() -> str:
    """'nano' (Pyodide) | 'mesh' (Mesh mode) | 'offline'. VYOMI_COMPUTE_SUBSTRATE overrides (tests)."""
    env = (os.environ.get("VYOMI_COMPUTE_SUBSTRATE") or "").strip().lower()
    if env in ("nano", "mesh", "offline"):
        return env
    if sys.platform == "emscripten":
        return "nano"
    try:
        from core import mesh
        return "mesh" if mesh.mesh_mode() else "offline"
    except Exception:
        return "offline"


def label(sub: str | None = None) -> str:
    sub = sub or substrate()
    return {"nano": NANO["label"], "mesh": MESH["label"]}.get(sub, "this appliance")


def mesh_limits() -> dict:
    """Per-instance ceilings derived from the live Mesh budget (so a smaller/larger Codespace shrinks/grows the list)."""
    try:
        from core import mesh      # host only (Mesh never runs under Pyodide)
        compute_mb = int(mesh.resource_budget()["memory_split_mb"]["compute"])
        cpus = int(os.environ.get("VYOMI_MESH_CPUS") or 0) or os.cpu_count() or 1
    except Exception:
        compute_mb, cpus = 5734, 4          # the default 4 vCPU / 16 GB Codespace: 70% of 16384 = 11468, half = 5734
    return {"max_mem_mb": int(min(MESH_HARD_MAX_MB, compute_mb * MESH_MAX_SHARE)), "vcpu": max(1, cpus), "compute_bucket_mb": compute_mb}


def limits(sub: str | None = None) -> dict | None:
    sub = sub or substrate()
    if sub == "nano":
        return {"substrate": "nano", "vcpu": NANO["vcpu"], "max_mem_mb": NANO["max_mem_mb"], "total_mem_mb": NANO["total_mem_mb"]}
    if sub == "mesh":
        return {"substrate": "mesh", **mesh_limits()}
    return None


def _fits(shape: dict, sub: str, lim: dict) -> bool:
    if shape["family"] not in (_NANO_FAMILIES if sub == "nano" else _FAMILIES):
        return False
    if shape["ram_mb"] > lim["max_mem_mb"]:
        return False
    return sub == "nano" or shape["vcpu"] <= lim["vcpu"]


def honoured(shape: dict, sub: str, lim: dict) -> dict:
    """What the substrate really gives this size: Nano is always 1 vCPU; RAM is the type's real RAM (fits by construction)."""
    return {"vcpu": min(shape["vcpu"], lim["vcpu"]), "mem_mb": min(shape["ram_mb"], lim["max_mem_mb"])}


def size_table(cloud: str, sub: str | None = None) -> list[dict]:
    """Offered sizes for a cloud on a substrate: [{name, vcpu, mem_mb, run_vcpu, run_mem_mb}] (real spec + what is honoured).
    Empty-restriction substrates (offline) return None-equivalent: every catalog size."""
    sub = sub or substrate()
    cat = _CATALOG[cloud]
    lim = limits(sub)
    out = []
    for name, sh in cat.items():
        if lim is None:
            out.append({"name": name, "vcpu": sh["vcpu"], "mem_mb": sh["ram_mb"], "run_vcpu": sh["vcpu"], "run_mem_mb": sh["ram_mb"]})
        elif _fits(sh, sub, lim):
            h = honoured(sh, sub, lim)
            out.append({"name": name, "vcpu": sh["vcpu"], "mem_mb": sh["ram_mb"], "run_vcpu": h["vcpu"], "run_mem_mb": h["mem_mb"]})
    return sorted(out, key=lambda r: (r["mem_mb"], r["vcpu"], r["name"]))


# ── images (OS / architecture) ──────────────────────────────────────────────────────────────────────────────────────
# The in-browser VM boots ONE guest whatever image the cloud record names: Alpine Linux 3.21 on a 32-bit x86 kernel
# (wasm/vm/build-image.sh: linux-virt i386 + rootfs.cpio.gz; wasm/vm/vm-worker.js: v86). So on Nano the only image each cloud can
# honestly offer is that guest, named per cloud's own conventions. Mesh / offline keep their full catalogs.
NANO_GUEST = {"os": "Alpine Linux 3.21", "bits": 32, "arch": "i386", "engine": "v86", "vcpu": 1,
              "code": "wasm/vm/build-image.sh (image), wasm/vm/vm-worker.js (engine), wasm/vm/nano-vm-host.js (runtime facts)"}
# What the guest image really contains (wasm/vm/build-image.sh PKGS: python3 + py3-pip, apk-tools, git). Every runnable Nano image MUST provide exactly
# these tools (python3, pip, apk, git); tests assert them inside the booted VM per runnable image (consoles/tests/smoke-nano-browservm.mjs).
NANO_TOOLS = ("Python 3", "pip", "apk", "git")
NANO_SUMMARY = "Alpine Linux 3.21, 32-bit x86: " + ", ".join(NANO_TOOLS)
NANO_IMAGES = {
    "aws": {"name": "Alpine Linux 3.21 (i386) - Vyomi Nano", "arch": "i386", "platform": "", "description": NANO_SUMMARY},
    "gcp": {"project": "vyomi-nano-cloud", "family": "alpine-3-21-i386", "name": "alpine-3-21-i386-nano",
            "description": NANO_SUMMARY},
    "azure": {"publisher": "vyomi", "offer": "alpine-nano", "sku": "3.21-i386", "version": "latest",
              "display": "Alpine Linux 3.21 (32-bit x86) - Vyomi Nano", "description": NANO_SUMMARY},
}


def images_restricted() -> bool:
    """Only Nano restricts images (Mesh runs real per-cloud-ish Docker images and keeps the catalog; offline is unrestricted)."""
    return substrate() == "nano"


def image_rejection(cloud: str, what: str) -> str:
    return (f"The image '{what}' cannot run on {label('nano')}: it boots only {NANO_GUEST['os']} (32-bit x86, i386) inside your browser. "
            f"Launch a Mesh for the full image catalog.")


def azure_image_allowed(ref: dict | None) -> bool:
    """True when an imageReference is the Nano guest (or absent / not an image-from-marketplace reference)."""
    if not images_restricted() or not ref:
        return True
    if ref.get("id") or ref.get("sharedGalleryImageId") or ref.get("communityGalleryImageId"):
        return True                                 # a customer image (made from a Nano VM) is not a marketplace reference
    a = NANO_IMAGES["azure"]
    return all(str(ref.get(k) or "").lower() == a[k] for k in ("publisher", "offer", "sku"))


def lists_all(sub: str | None = None) -> bool:
    """Nano still LISTS every size / image (the console shows the whole catalog); what it cannot run is flagged `vyomiRunnable: false`
    so the pickers grey it out. Mesh lists only what it can run; offline is unrestricted."""
    return (sub or substrate()) == "nano"


def restricted(sub: str | None = None) -> bool:
    return (sub or substrate()) not in _OFF


def allowed_names(cloud: str, sub: str | None = None) -> set | None:
    """None = unrestricted (offline)."""
    sub = sub or substrate()
    return None if not restricted(sub) else {r["name"] for r in size_table(cloud, sub)}


def is_allowed(cloud: str, name: str, sub: str | None = None) -> bool:
    names = allowed_names(cloud, sub)
    return True if names is None else str(name or "").rsplit("/", 1)[-1] in names


def rejection(cloud: str, name: str, sub: str | None = None) -> str:
    sub = sub or substrate()
    names = [r["name"] for r in size_table(cloud, sub)]
    return (f"The size '{str(name).rsplit('/', 1)[-1]}' cannot run on {label(sub)}. "
            f"Sizes available here: {', '.join(names)}.")


def nano_vm_mem_mb(name: str) -> int | None:
    """Guest RAM (MiB) for an in-browser VM of this size, or None when the size is not a Nano-offered one (callers keep the legacy mapping)."""
    n = str(name or "").rsplit("/", 1)[-1]
    for cloud in ("aws", "gcp", "azure"):
        sh = _CATALOG[cloud].get(n)
        if sh and _fits(sh, "nano", limits("nano")):
            return int(honoured(sh, "nano", limits("nano"))["mem_mb"])
    return None


def mesh_vcpus(name: str, cloud: str) -> float | None:
    """vCPUs the Docker container for this size is started with (real vCPU, capped at the host cores)."""
    sh = _CATALOG.get(cloud, {}).get(str(name or "").rsplit("/", 1)[-1])
    return None if not sh else float(min(sh["vcpu"], mesh_limits()["vcpu"]))


def export() -> dict:
    return {"nano": {**NANO, "guest": NANO_GUEST, "images": NANO_IMAGES, "sizes": {c: size_table(c, "nano") for c in _CATALOG}},
            "mesh": {**MESH, "limits": mesh_limits(), "sizes": {c: size_table(c, "mesh") for c in _CATALOG}}}


# ── Windows VM images (owner decision 2026-11-26): DISABLED, not removed ─────────────────────────────────────────
# Windows images cannot run on Mesh (Linux Docker containers, no verified KVM) nor on Nano (v86 Alpine only).  They stay in
# every catalog / wizard / console option list, shown disabled with WINDOWS_IMAGES_REASON; launching one is refused with a
# cloud-native 400 instead of silently starting a Linux guest.  Re-enable: flip WINDOWS_IMAGES_ENABLED to True here and
# in consoles/src/common/windowsImages.js.  Docs: docs/architecture/v4.0/branches/disable-windows-images.md
WINDOWS_IMAGES_ENABLED = False
WINDOWS_IMAGES_REASON = "Windows images are not supported yet."


def windows_blocked(is_windows) -> bool:
    """True when a launch/create request for a Windows image must be refused."""
    return bool(is_windows) and not WINDOWS_IMAGES_ENABLED


def windows_rejection(what: str = "Windows images") -> str:
    return f"{what} are not supported yet: Vyomi runs Linux guests only (Windows VM images need a hypervisor this substrate does not have)."


if __name__ == "__main__":
    import json
    print(json.dumps(export(), indent=2))

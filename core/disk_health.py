"""Disk-health monitoring + tier-aware enforcement for the appliance.

Self-hosted appliances run on someone else's hardware with finite disk.
Without active management, a few weeks of normal use will fill the VM's
storage pool and silently break every launch. The user sees instances
stuck "stopped" with no clear cause — exactly the worst-case for a paid
product.

This module implements the contract:
  "We won't promise infinite capacity, but we WILL guarantee you never end
   up in a broken state with no escape hatch."

Architecture:

  1. _DiskMonitor daemon thread samples disk usage every 60s. State stored
     under STATE['runtime']['disk_health'] so any request can read the
     latest snapshot in O(1) without re-shelling out.

  2. Tier-aware thresholds (warn / freeze percentages). Paid tiers get
     tighter warn thresholds (more headroom) so they see warnings earlier.

  3. preflight_launch_check(state, tier, required_gb) — called before
     every VM launch. Raises HTTPException(507) with a structured error
     body when free space < required + safety_margin. The launch never
     even starts, so we don't end up with the half-unpacked-rootfs
     orphans that ate this appliance's disk in the disk-full incident.

  4. cleanup_suggestions(state) — enumerates reclaimable space sources
     (terminated instances, LXD image cache, journald, /tmp, etc).
     Returns enough metadata for the UI to render checkboxes.

  5. run_cleanup(state, categories) — performs the selected cleanups via
     the runtime bridge. Idempotent; safe to re-run.

  6. grow_disk(state, target_gb) — paid-tier escape hatch. Invokes
     multipass set/restart through the bridge. Documented as Linux-only
     for now since the bridge runs in the VM.

Endpoints live in server.py; this module owns the logic + state shape.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


# ── tier-aware thresholds ───────────────────────────────────────────────────
# Paid tiers get tighter warn thresholds (more buffer before crisis).
# Freeze threshold is what triggers refuse-to-launch responses.
_TIER_THRESHOLDS = {
    "free":       {"warn_pct": 80, "freeze_pct": 92, "safety_gb": 2.0},
    "pro":        {"warn_pct": 75, "freeze_pct": 90, "safety_gb": 3.0},
    "max":        {"warn_pct": 70, "freeze_pct": 88, "safety_gb": 5.0},
    "enterprise": {"warn_pct": 65, "freeze_pct": 85, "safety_gb": 8.0},
}

# How much disk a new VM container typically consumes — the LXD rootfs
# (Ubuntu 22.04 base) plus instance.storage_gb plus a slop margin. Used
# as the floor when the caller doesn't pass an explicit required_gb.
_DEFAULT_LAUNCH_REQUIRED_GB = 2.5

_BRIDGE_URL = os.environ.get("CLOUDLEARN_RUNTIME_BRIDGE_URL",
                             "http://host.docker.internal:9171").rstrip("/")
_WORKSPACE_ROOT = Path(os.environ.get(
    "CLOUDLEARN_DEPLOY_DIR", "/var/lib/cloudlearn/deployments"))

_MONITOR_INTERVAL_SECONDS = 60
_TERMINATED_WORKSPACE_TTL_SECONDS = 24 * 3600  # 24h
_MONITOR_THREAD: Optional[threading.Thread] = None


# ── runtime bridge proxy ────────────────────────────────────────────────────

def _bridge_run(backend: str, args: list[str], timeout: int = 30) -> dict:
    """Same shape as vm_connect._bridge_run. We avoid importing it to keep
    these two modules independent."""
    payload = json.dumps({"backend": backend, "args": args, "timeout": timeout}).encode()
    req = urllib.request.Request(
        f"{_BRIDGE_URL}/run", data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 10) as r:
            return json.load(r)
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}


# ── disk sampling ───────────────────────────────────────────────────────────

def _sample_root_disk() -> dict[str, Any]:
    """Return the VM's root-filesystem usage. Asks the runtime bridge to
    run `df -B1 /` so the bytes reflect the multipass VM (not the
    simulator container, which has its own overlay)."""
    r = _bridge_run("host", ["df", "-B1", "--output=size,used,avail,pcent", "/"], timeout=10)
    if r.get("returncode") != 0:
        return {"available": False, "error": (r.get("stderr") or "")[:200]}
    lines = (r.get("stdout") or "").strip().splitlines()
    if len(lines) < 2:
        return {"available": False, "error": "df produced no rows"}
    parts = lines[-1].split()
    try:
        total = int(parts[0])
        used = int(parts[1])
        avail = int(parts[2])
        pct = float(parts[3].rstrip("%"))
    except Exception as e:
        return {"available": False, "error": f"parse_failed: {e}"}
    return {
        "available": True,
        "total_bytes": total,
        "used_bytes": used,
        "avail_bytes": avail,
        "pct_used": pct,
        "total_gb": round(total / 1024 ** 3, 2),
        "used_gb": round(used / 1024 ** 3, 2),
        "avail_gb": round(avail / 1024 ** 3, 2),
    }


def _sample_breakdown() -> dict[str, Any]:
    """Per-category disk usage breakdown for the cleanup UI. Each entry
    is in GB and best-effort — failure is silent (returns 0 for that
    category) so a slow disk doesn't block the monitor."""
    out: dict[str, float] = {}
    # LXD storage pool — usually the biggest consumer
    r = _bridge_run("host", ["du", "-sb", "/var/snap/lxd/common/lxd/storage-pools"], timeout=30)
    if r.get("returncode") == 0:
        try:
            out["lxd_storage_pools_gb"] = round(int(r["stdout"].split()[0]) / 1024 ** 3, 2)
        except Exception:
            out["lxd_storage_pools_gb"] = 0.0
    # LXD image cache
    r = _bridge_run("host", ["du", "-sb", "/var/snap/lxd/common/lxd/images"], timeout=10)
    if r.get("returncode") == 0:
        try:
            out["lxd_image_cache_gb"] = round(int(r["stdout"].split()[0]) / 1024 ** 3, 2)
        except Exception:
            out["lxd_image_cache_gb"] = 0.0
    # CloudLearn workspaces (per-instance dirs)
    r = _bridge_run("host", ["du", "-sb", "/var/lib/cloudlearn/deployments"], timeout=15)
    if r.get("returncode") == 0:
        try:
            out["cloudlearn_workspaces_gb"] = round(int(r["stdout"].split()[0]) / 1024 ** 3, 2)
        except Exception:
            out["cloudlearn_workspaces_gb"] = 0.0
    # journald
    r = _bridge_run("host", ["du", "-sb", "/var/log/journal"], timeout=10)
    if r.get("returncode") == 0:
        try:
            out["journald_gb"] = round(int(r["stdout"].split()[0]) / 1024 ** 3, 2)
        except Exception:
            out["journald_gb"] = 0.0
    # docker overlay2
    r = _bridge_run("host", ["du", "-sb", "/var/lib/docker/overlay2"], timeout=30)
    if r.get("returncode") == 0:
        try:
            out["docker_overlay_gb"] = round(int(r["stdout"].split()[0]) / 1024 ** 3, 2)
        except Exception:
            out["docker_overlay_gb"] = 0.0
    return out


def _count_orphans(state: dict) -> dict[str, Any]:
    """Cross-reference live LXD containers vs simulator-tracked instances.
    Containers in LXD but not in any simulator instance record are
    'orphans' — leftovers from crashes / manual deletes / failed
    launches — and account for measurable disk use that's safe to
    reclaim."""
    live_ids = set()
    spaces = (state.get("spaces") or {}).get("spaces") or {}
    for sid, space in spaces.items():
        if not isinstance(space, dict):
            continue
        for svc_key in ("ec2", "gcp_compute"):
            instances = ((space.get("service_states") or {}).get(svc_key) or {}).get("instances") or {}
            for iid in instances.keys():
                live_ids.add(iid)
        # Azure VMs live in azure_arm.resources keyed by full resource path
        azure_resources = ((space.get("service_states") or {}).get("azure_arm") or {}).get("resources") or {}
        for rid, rec in azure_resources.items():
            if isinstance(rec, dict) and "virtualmachines" in str(rec.get("_type", "")).lower():
                live_ids.add(rec.get("name") or rid.split("/")[-1])

    r = _bridge_run("lxd", ["list", "-c", "n", "--format", "csv"], timeout=15)
    if r.get("returncode") != 0:
        return {"orphans": [], "live": [], "scanned": False}
    orphans: list[str] = []
    live: list[str] = []
    for line in (r.get("stdout") or "").strip().splitlines():
        name = line.strip()
        if not name.startswith("cloudlearn-"):
            continue
        # Strip the runtime-namespacing prefix and the cloud-specific
        # second prefix. cloudlearn-i-xxx → i-xxx; cloudlearn-gce-yyy → yyy;
        # cloudlearn-az-zzz-name → name.
        bare = name[len("cloudlearn-"):]
        matched_id = None
        if bare.startswith("i-"):
            matched_id = bare
        else:
            # Either gce-, az-, or some future prefix — fall back to a
            # suffix match against live_ids.
            for iid in live_ids:
                if iid and iid in bare:
                    matched_id = iid
                    break
        if matched_id and matched_id in live_ids:
            live.append(name)
        else:
            orphans.append(name)
    return {"orphans": orphans, "live": live, "scanned": True}


# ── tier resolution ────────────────────────────────────────────────────────

def _resolve_tier(state: dict) -> str:
    """Best-effort tier lookup. The kernel state mirrors active tier into
    STATE['license']['tier']; falls back to 'free' when no license is
    applied (e.g., fresh appliance)."""
    lic = state.get("license") or {}
    tier = str(lic.get("tier") or "free").lower().strip()
    if tier not in _TIER_THRESHOLDS:
        tier = "free"
    return tier


def thresholds_for_tier(tier: str) -> dict[str, float]:
    return dict(_TIER_THRESHOLDS.get(tier) or _TIER_THRESHOLDS["free"])


# ── public read API ────────────────────────────────────────────────────────

def evaluate_health(state: dict) -> dict[str, Any]:
    """Build the health snapshot consumed by the UI dashboard widget,
    the pre-flight gate, and the cleanup suggestions endpoint.

    Status semantics:
      green  : free space comfortably above the warn threshold
      warn   : approaching freeze threshold; UI should surface a banner
      freeze : pre-flight gate must reject new launches; existing
               workloads still run untouched
    """
    tier = _resolve_tier(state)
    thresh = thresholds_for_tier(tier)
    disk = _sample_root_disk()
    if not disk.get("available"):
        return {
            "available": False,
            "status": "unknown",
            "tier": tier,
            "thresholds": thresh,
            "error": disk.get("error", "no disk sample"),
            "sampled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    pct = float(disk["pct_used"])
    if pct >= thresh["freeze_pct"]:
        status = "freeze"
    elif pct >= thresh["warn_pct"]:
        status = "warn"
    else:
        status = "green"
    return {
        "available": True,
        "status": status,
        "tier": tier,
        "thresholds": thresh,
        "disk": disk,
        "headroom_gb": max(0.0, disk["avail_gb"] - thresh["safety_gb"]),
        "sampled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def cleanup_suggestions(state: dict) -> dict[str, Any]:
    """Enumerate reclaimable space sources. Each entry is renderable as a
    checkbox row in the cleanup modal; selecting and running pipes the
    keys back to run_cleanup()."""
    breakdown = _sample_breakdown()
    orphan_info = _count_orphans(state)
    orphan_count = len(orphan_info.get("orphans") or [])
    suggestions: list[dict[str, Any]] = []

    if orphan_count:
        suggestions.append({
            "key": "lxd_orphans",
            "label": f"Delete {orphan_count} orphan LXD container{'s' if orphan_count != 1 else ''}",
            "detail": "Containers in LXD that no longer have simulator state — leftovers from crashes / manual deletes.",
            "est_reclaim_gb": round(orphan_count * 1.2, 2),  # ~1.2 GB per container
            "safe": True,
        })
    # Workspace dirs of terminated instances
    terminated_dirs = _terminated_workspace_dirs(state)
    if terminated_dirs:
        total_gb = 0.0
        for p in terminated_dirs:
            try:
                total_gb += sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file()) / 1024 ** 3
            except Exception:
                pass
        suggestions.append({
            "key": "terminated_workspaces",
            "label": f"Clean {len(terminated_dirs)} terminated-instance workspace dir{'s' if len(terminated_dirs) != 1 else ''}",
            "detail": f"Per-instance deployment dirs left over after termination ({_TERMINATED_WORKSPACE_TTL_SECONDS // 3600}h old or older).",
            "est_reclaim_gb": round(total_gb, 2),
            "safe": True,
        })
    # LXD image cache (only suggest if > 1 GB)
    lxd_images_gb = breakdown.get("lxd_image_cache_gb", 0.0)
    if lxd_images_gb >= 1.0:
        suggestions.append({
            "key": "lxd_image_cache",
            "label": "Prune unused LXD image cache",
            "detail": "LXD downloads base images (ubuntu:22.04 etc) and keeps them. Prune images with no aliases or no containers.",
            "est_reclaim_gb": round(lxd_images_gb * 0.5, 2),  # estimate 50% reclaimable
            "safe": True,
        })
    # journald
    journald_gb = breakdown.get("journald_gb", 0.0)
    if journald_gb >= 1.0:
        suggestions.append({
            "key": "journald",
            "label": "Vacuum journald logs",
            "detail": "Cap journald retention at 7 days (frees system logs without affecting any apps).",
            "est_reclaim_gb": round(journald_gb * 0.7, 2),
            "safe": True,
        })
    # /tmp + apt
    suggestions.append({
        "key": "tmp_and_apt",
        "label": "Clear /tmp + apt cache",
        "detail": "Empty /tmp (older than 1 day) and run `apt-get clean`. Safe — no side-effects on running containers.",
        "est_reclaim_gb": 0.3,
        "safe": True,
    })
    return {
        "sampled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "breakdown": breakdown,
        "orphans": orphan_info,
        "suggestions": suggestions,
    }


def _terminated_workspace_dirs(state: dict) -> list[str]:
    """Workspace dirs belonging to instances that are terminated AND
    older than _TERMINATED_WORKSPACE_TTL_SECONDS. Safe to delete."""
    keep_ids: set[str] = set()
    spaces = (state.get("spaces") or {}).get("spaces") or {}
    now = time.time()
    for sid, space in spaces.items():
        if not isinstance(space, dict):
            continue
        for svc_key in ("ec2", "gcp_compute"):
            instances = ((space.get("service_states") or {}).get(svc_key) or {}).get("instances") or {}
            for iid, inst in instances.items():
                if inst.get("state") != "terminated":
                    keep_ids.add(iid)
                    continue
                # Compare termination timestamp to TTL
                t = inst.get("terminated_at") or ""
                try:
                    age = now - time.mktime(time.strptime(t.rstrip("Z"), "%Y-%m-%dT%H:%M:%S"))
                except Exception:
                    age = _TERMINATED_WORKSPACE_TTL_SECONDS + 1
                if age < _TERMINATED_WORKSPACE_TTL_SECONDS:
                    keep_ids.add(iid)
    candidates: list[str] = []
    if not _WORKSPACE_ROOT.exists():
        return candidates
    try:
        for entry in _WORKSPACE_ROOT.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in keep_ids:
                continue
            candidates.append(str(entry))
    except Exception:
        pass
    return candidates


# ── public write API: cleanup + grow ───────────────────────────────────────

def run_cleanup(state: dict, categories: list[str]) -> dict[str, Any]:
    """Perform the selected cleanup categories. Returns per-category
    results so the UI can render success/failure inline."""
    results: dict[str, dict] = {}
    if "lxd_orphans" in categories:
        info = _count_orphans(state)
        deleted = 0
        for name in info.get("orphans", []):
            r = _bridge_run("lxd", ["delete", "-f", name], timeout=60)
            if r.get("returncode") == 0:
                deleted += 1
        results["lxd_orphans"] = {"ok": True, "deleted": deleted}
    if "terminated_workspaces" in categories:
        dirs = _terminated_workspace_dirs(state)
        deleted = 0
        for p in dirs:
            try:
                shutil.rmtree(p, ignore_errors=True)
                deleted += 1
            except Exception:
                pass
        results["terminated_workspaces"] = {"ok": True, "deleted": deleted}
    if "lxd_image_cache" in categories:
        # `lxc image list` doesn't expose a direct prune; instead delete
        # cached images with no aliases pointing at them.
        r = _bridge_run("lxd",
                        ["image", "list", "--format", "json"], timeout=15)
        pruned = 0
        if r.get("returncode") == 0:
            try:
                images = json.loads(r.get("stdout") or "[]")
                for img in images:
                    if not img.get("aliases"):
                        fp = img.get("fingerprint")
                        if fp:
                            rd = _bridge_run("lxd", ["image", "delete", fp], timeout=30)
                            if rd.get("returncode") == 0:
                                pruned += 1
            except Exception:
                pass
        results["lxd_image_cache"] = {"ok": True, "pruned": pruned}
    if "journald" in categories:
        r = _bridge_run("host", ["journalctl", "--vacuum-time=7d"], timeout=30)
        results["journald"] = {"ok": r.get("returncode") == 0,
                               "output": (r.get("stdout") or "")[:300]}
    if "tmp_and_apt" in categories:
        # /tmp older than 1d + apt clean
        r1 = _bridge_run("host", ["bash", "-c",
                                  "find /tmp -mindepth 1 -mtime +1 -exec rm -rf {} + 2>/dev/null; true"],
                         timeout=20)
        r2 = _bridge_run("host", ["bash", "-c", "apt-get clean 2>/dev/null; true"], timeout=20)
        results["tmp_and_apt"] = {"ok": True,
                                  "tmp_rc": r1.get("returncode"),
                                  "apt_rc": r2.get("returncode")}
    return {"results": results, "performed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def grow_disk(state: dict, target_gb: int) -> dict[str, Any]:
    """Paid-tier escape hatch. Requests a multipass VM disk resize via
    the runtime bridge. Caller must check tier policy first — this
    function only enforces value bounds and shells out."""
    if target_gb < 30 or target_gb > 500:
        return {"ok": False, "reason": f"target_gb {target_gb} out of [30, 500]"}
    # Multipass disk resize requires the VM to be stopped → restart sequence.
    # The bridge runs INSIDE the VM, so it can't actually issue
    # `multipass set` (that has to come from the Mac/Windows host running
    # multipass). We return a pre-flight result describing what the user
    # needs to run on the host machine. In a future revision we ship a
    # tiny privileged helper on the Mac that can act on these requests.
    cmd = (
        f"multipass set local.cloudlearn-appliance.disk={target_gb}G && "
        "multipass restart cloudlearn-appliance"
    )
    return {
        "ok": True,
        "deferred": True,
        "command": cmd,
        "instructions": (
            "Run the command above on your Mac/Windows host (the machine running multipass). "
            "Resize takes ~30s + restart ~2 min. Existing workloads pause during restart."
        ),
        "target_gb": target_gb,
    }


# ── pre-flight gate (raised by every VM launch) ────────────────────────────

class InsufficientDiskError(Exception):
    """Raised by preflight_launch_check when the VM doesn't have enough
    headroom to safely launch a new container. server.py maps it to
    HTTPException(507, ...) with a structured body."""

    def __init__(self, payload: dict):
        super().__init__(payload.get("reason") or "insufficient disk")
        self.payload = payload


def preflight_launch_check(state: dict, required_gb: Optional[float] = None) -> None:
    """Call this BEFORE any VM-launch code path that materializes a
    container on LXD. If the disk doesn't have enough headroom for the
    new VM + safety margin, raise InsufficientDiskError so the launch
    code can return 507 without ever touching LXD.

    `required_gb` defaults to a conservative 2.5 GB (typical Ubuntu
    rootfs + slop). Callers should pass instance.storage_gb plus image
    base size when they have it.
    """
    health = evaluate_health(state)
    if not health.get("available"):
        # Disk sample failed — log it but don't block launches on a
        # monitoring failure (we'd cause more harm than disk-full).
        return
    tier = health["tier"]
    thresh = health["thresholds"]
    disk = health["disk"]
    req = float(required_gb or _DEFAULT_LAUNCH_REQUIRED_GB)
    safety = float(thresh["safety_gb"])

    # Freeze override: hard freeze when status==freeze, regardless of
    # whether the new VM would technically fit.
    if health["status"] == "freeze":
        raise InsufficientDiskError({
            "code": "disk_freeze",
            "reason": f"Appliance disk at {disk['pct_used']}% — above tier '{tier}' freeze threshold of {thresh['freeze_pct']}%.",
            "free_gb": disk["avail_gb"],
            "required_gb": req,
            "safety_gb": safety,
            "tier": tier,
            "thresholds": thresh,
            "cleanup_url": "/api/runtime/disk-cleanup/suggestions",
        })
    # Headroom check
    if disk["avail_gb"] - req < safety:
        raise InsufficientDiskError({
            "code": "insufficient_disk",
            "reason": (
                f"Need {req:.1f} GB free for this launch (+{safety:.1f} GB tier '{tier}' safety margin) "
                f"but only {disk['avail_gb']:.1f} GB available."
            ),
            "free_gb": disk["avail_gb"],
            "required_gb": req,
            "safety_gb": safety,
            "tier": tier,
            "thresholds": thresh,
            "cleanup_url": "/api/runtime/disk-cleanup/suggestions",
        })


# ── monitor daemon ──────────────────────────────────────────────────────────

def _monitor_loop(state: dict) -> None:
    while True:
        try:
            snap = evaluate_health(state)
            state.setdefault("runtime", {})["disk_health"] = snap
        except Exception as exc:
            state.setdefault("runtime", {})["disk_health_error"] = str(exc)
        time.sleep(_MONITOR_INTERVAL_SECONDS)


def start_disk_health_monitor(state: dict) -> None:
    """Spawn the monitor daemon. Idempotent — safe to call repeatedly."""
    global _MONITOR_THREAD
    if _MONITOR_THREAD and _MONITOR_THREAD.is_alive():
        return
    _MONITOR_THREAD = threading.Thread(
        target=_monitor_loop, args=(state,),
        name="disk-health-monitor", daemon=True,
    )
    _MONITOR_THREAD.start()


# ── post-terminate hook (called by terminate handlers) ─────────────────────

def cleanup_terminated_workspace(instance_id: str) -> bool:
    """Delete the instance's workspace dir after termination. Safe even
    if the dir doesn't exist. Returns True if something was actually
    removed."""
    target = _WORKSPACE_ROOT / instance_id
    if not target.exists():
        return False
    try:
        shutil.rmtree(target, ignore_errors=True)
        return True
    except Exception:
        return False

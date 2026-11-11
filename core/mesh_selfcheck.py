"""Mesh self-check: the basic "did this Mesh come up healthy?" probes, run INSIDE the Codespace.

Why: a Mesh can report `running` while it is unusable (DNS broken so apt-get / package installs fail, no outbound HTTPS, disk full,
appliance or AI runtime not up). The portal asks `GET /mesh/selfcheck` (through the user's tunnel) after the session comes up and only
lets the user JOIN when every check is ok. Each item is {id, label, ok, detail, hint}; `ok` is False only on a real failure
(a check that does not apply on this host is reported ok with detail "not applicable").

Probes are injectable (`run(probes=...)`) so the logic is unit-testable without a network.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import ssl
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout
from typing import Callable, Optional

DNS_HOSTS = ("github.com", "deb.debian.org", "registry-1.docker.io")
EGRESS_URL = "https://github.com"
MIN_DISK_GB = 2.0
MIN_MEM_MB = 700
PROBE_TIMEOUT = 6.0          # per probe
TOTAL_TIMEOUT = 12.0         # whole run


def _item(id_: str, label: str, ok: bool, detail: str = "", hint: str = "") -> dict:
    return {"id": id_, "label": label, "ok": bool(ok), "detail": detail, "hint": "" if ok else hint}


def _resolve(host: str) -> bool:
    try:
        return bool(socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP))
    except OSError:
        return False


def check_dns(resolve: Callable[[str], bool] = _resolve) -> dict:
    bad = [h for h in DNS_HOSTS if not resolve(h)]
    if not bad:
        return _item("dns", "DNS resolution", True, "resolved " + ", ".join(DNS_HOSTS))
    return _item("dns", "DNS resolution", False, "cannot resolve " + ", ".join(bad),
                 "Name resolution is failing inside the Codespace, so apt-get and package installs will fail. Leave the Mesh and start it again.")


def _apt_host(sources: Optional[list[str]] = None) -> Optional[str]:
    paths = sources if sources is not None else ["/etc/apt/sources.list", "/etc/apt/sources.list.d/debian.sources", "/etc/apt/sources.list.d/ubuntu.sources"]
    for p in paths:
        try:
            txt = open(p).read()
        except OSError:
            continue
        m = re.search(r"(?:https?://)([A-Za-z0-9.\-]+)", txt)
        if m:
            return m.group(1)
    return None


def _head(url: str, timeout: float) -> int:
    req = urllib.request.Request(url, method="HEAD", headers={"user-agent": "vyomi-mesh-selfcheck"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.status


def check_apt(head: Callable[[str, float], int] = _head, host: Optional[str] = None) -> dict:
    host = host or _apt_host()
    if not host:
        return _item("apt", "Package mirror (apt)", True, "not applicable (no apt sources)")
    try:
        code = head(f"https://{host}/", PROBE_TIMEOUT)
        return _item("apt", "Package mirror (apt)", code < 500, f"{host} answered {code}", f"{host} is not answering. apt-get will fail.")
    except Exception as e:     # noqa: BLE001 - any failure to reach the mirror is the finding
        # plain http mirrors (common for apt) refuse https: retry over http before calling it a failure
        try:
            code = head(f"http://{host}/", PROBE_TIMEOUT)
            return _item("apt", "Package mirror (apt)", code < 500, f"{host} answered {code}", f"{host} is not answering. apt-get will fail.")
        except Exception:
            return _item("apt", "Package mirror (apt)", False, f"{host}: {type(e).__name__}", f"Cannot reach the package mirror {host}. apt-get will fail.")


def check_egress(head: Callable[[str, float], int] = _head) -> dict:
    try:
        code = head(EGRESS_URL, PROBE_TIMEOUT)
        return _item("egress", "Outbound HTTPS", code < 500, f"{EGRESS_URL} answered {code}", "The Codespace cannot reach the internet over HTTPS.")
    except Exception as e:     # noqa: BLE001
        return _item("egress", "Outbound HTTPS", False, f"{type(e).__name__}", "The Codespace cannot reach the internet over HTTPS.")


def check_disk(path: str = "/", free_gb: Optional[float] = None) -> dict:
    gb = free_gb if free_gb is not None else shutil.disk_usage(path).free / 1e9
    return _item("disk", "Disk space", gb >= MIN_DISK_GB, f"{gb:.1f} GB free", f"Less than {MIN_DISK_GB:.0f} GB free. Services and models cannot be installed.")


def _mem_available_mb() -> Optional[float]:
    try:
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) / 1024
    except OSError:
        pass
    return None


def check_memory(avail_mb: Optional[float] = None) -> dict:
    mb = avail_mb if avail_mb is not None else _mem_available_mb()
    if mb is None:
        return _item("memory", "Memory", True, "not applicable (no /proc/meminfo)")
    return _item("memory", "Memory", mb >= MIN_MEM_MB, f"{mb:.0f} MB available", f"Under {MIN_MEM_MB} MB free. The Mesh will be killed under load.")


def check_appliance() -> dict:
    try:
        from core import mesh
        s = mesh.status()
        ok = bool((s.get("health") or {}).get("ok"))
        return _item("appliance", "Appliance healthy", ok, f"v{s.get('version', '?')} · {(s.get('health') or {}).get('state', '?')}",
                     "The appliance is locked or not in Mesh mode. Check your plan and restart the Mesh.")
    except Exception as e:     # noqa: BLE001
        return _item("appliance", "Appliance healthy", False, type(e).__name__, "The appliance did not answer its own status call.")


def check_ai() -> dict:
    try:
        from core import mesh_ai
        st = mesh_ai.status(recent=0)
        state = st.get("state")
        if state == "ready":
            return _item("ai", "AI runtime", True, st.get("chip") or "ready")
        if state in ("starting",):
            return _item("ai", "AI runtime", True, "model is still loading; AI is available when it finishes")
        if state == "off":
            return _item("ai", "AI runtime", True, "not enabled on this Mesh")
        return _item("ai", "AI runtime", False, f"state: {state}", "The AI runtime refused to start. See the Mesh logs.")
    except Exception as e:     # noqa: BLE001
        return _item("ai", "AI runtime", False, type(e).__name__, "The AI runtime did not answer.")


def _local_get(path: str, timeout: float = 5.0) -> dict:
    import json
    req = urllib.request.Request("http://localhost:9000" + path, headers={"user-agent": "vyomi-mesh-selfcheck"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def check_appliance_http(get: Callable[[str], dict] = _local_get) -> dict:
    """Same question as check_appliance, asked of the LIVE server over loopback (used when this runs as its own process, e.g. from boot-mesh.sh)."""
    try:
        s = get("/mesh/status")
        h = s.get("health") or {}
        return _item("appliance", "Appliance healthy", bool(s.get("mesh")) and bool(h.get("ok")), f"v{s.get('version', '?')} · {h.get('state', '?')}",
                     "The appliance is locked or not in Mesh mode. Check your plan and restart the Mesh.")
    except Exception as e:     # noqa: BLE001
        return _item("appliance", "Appliance healthy", False, type(e).__name__, "The appliance did not answer its own status call.")


def check_ai_http(get: Callable[[str], dict] = _local_get) -> dict:
    try:
        st = get("/mesh/ai/status").get("state")
        if st in ("ready", "off"):
            return _item("ai", "AI runtime", True, "ready" if st == "ready" else "not enabled on this Mesh")
        if st == "starting":
            return _item("ai", "AI runtime", True, "model is still loading; AI is available when it finishes")
        return _item("ai", "AI runtime", False, f"state: {st}", "The AI runtime refused to start. See the Mesh logs.")
    except Exception as e:     # noqa: BLE001
        return _item("ai", "AI runtime", False, type(e).__name__, "The AI runtime did not answer.")


DEFAULT_PROBES: tuple = (check_dns, check_apt, check_egress, check_disk, check_memory, check_appliance, check_ai)


def run(probes: Optional[tuple] = None, now: Callable[[], float] = time.time) -> dict:
    """Run every probe in parallel -> {ok, checked_at, items:[...]}. A probe that raises or hangs is a failed item, never an exception."""
    probes = probes or DEFAULT_PROBES
    t0 = now()
    ex = ThreadPoolExecutor(max_workers=len(probes))
    futs = [(p, ex.submit(p)) for p in probes]
    items = []
    for p, f in futs:
        name = getattr(p, "__name__", "check").replace("check_", "")
        try:
            items.append(f.result(timeout=max(0.5, TOTAL_TIMEOUT - (now() - t0))))
        except _Timeout:
            items.append(_item(name, name, False, "timed out", "This check did not finish in time."))
        except Exception as e:     # noqa: BLE001
            items.append(_item(name, name, False, type(e).__name__, "This check crashed."))
    ex.shutdown(wait=False, cancel_futures=True)
    return {"ok": all(i["ok"] for i in items), "checked_at": int(now()), "items": items}


STANDALONE_PROBES: tuple = (check_dns, check_apt, check_egress, check_disk, check_memory, check_appliance_http, check_ai_http)


if __name__ == "__main__":      # `python3 - < selfcheck.py` inside the simulator container (boot-mesh.sh): print the report as JSON
    import json
    print(json.dumps(run(probes=STANDALONE_PROBES)))

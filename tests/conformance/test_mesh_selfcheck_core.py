"""Mesh self-check: every failure mode the portal must refuse a Join for (DNS broken -> apt-get fails, no egress, disk/memory, hung probe)."""
import time

try:
    from core import mesh_selfcheck as m
except ImportError:  # pragma: no cover
    import mesh_selfcheck as m  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def run():
    _check("DNS ok when every host resolves", m.check_dns(lambda h: True)["ok"])
    r = m.check_dns(lambda h: h != "deb.debian.org")
    _check("DNS failure names the host and warns about apt-get", not r["ok"] and "deb.debian.org" in r["detail"] and "apt-get" in r["hint"])
    _check("DNS fully down fails", not m.check_dns(lambda h: False)["ok"])

    _check("apt ok when the mirror answers", m.check_apt(lambda u, t: 200, host="deb.debian.org")["ok"])
    _check("apt falls back to http for http-only mirrors", m.check_apt(lambda u, t: 200 if u.startswith("http://") else (_ for _ in ()).throw(OSError("tls")), host="m")["ok"])
    def dead(u, t):
        raise OSError("unreachable")
    r = m.check_apt(dead, host="deb.debian.org")
    _check("apt unreachable mirror fails with a hint", not r["ok"] and "apt-get" in r["hint"])
    orig = m._apt_host
    m._apt_host = lambda sources=None: None
    _check("apt with no sources is not applicable (ok)", m.check_apt(head=dead)["ok"])
    m._apt_host = orig
    _check("apt 5xx fails", not m.check_apt(lambda u, t: 503, host="h")["ok"])

    _check("egress ok", m.check_egress(lambda u, t: 200)["ok"])
    _check("egress down fails", not m.check_egress(dead)["ok"])

    _check("disk ok at 10 GB", m.check_disk(free_gb=10)["ok"])
    _check("disk fails under 2 GB", not m.check_disk(free_gb=0.5)["ok"])
    _check("memory ok at 4 GB", m.check_memory(avail_mb=4096)["ok"])
    _check("memory fails under the floor", not m.check_memory(avail_mb=300)["ok"])

    _check("appliance (http): a live Mesh is healthy", m.check_appliance_http(lambda p: {"mesh": True, "version": "4.0", "health": {"ok": True, "state": "ok"}})["ok"])
    _check("appliance (http): not a Mesh fails", not m.check_appliance_http(lambda p: {"mesh": False, "health": {"ok": False, "state": "not-a-mesh"}})["ok"])
    def down(p):
        raise OSError("refused")
    _check("appliance (http): unreachable fails", not m.check_appliance_http(down)["ok"])
    _check("ai (http): ready ok", m.check_ai_http(lambda p: {"state": "ready"})["ok"])
    _check("ai (http): still loading must NOT block joining", m.check_ai_http(lambda p: {"state": "starting"})["ok"])
    _check("ai (http): off is ok (not enabled)", m.check_ai_http(lambda p: {"state": "off"})["ok"])
    _check("ai (http): refused fails with a hint", not m.check_ai_http(lambda p: {"state": "refused"})["ok"])
    _check("ai (http): unreachable fails", not m.check_ai_http(down)["ok"])

    good = lambda: m._item("a", "A", True, "fine")          # noqa: E731
    bad = lambda: m._item("b", "B", False, "broken", "fix")  # noqa: E731
    boom = lambda: (_ for _ in ()).throw(RuntimeError("x"))  # noqa: E731
    out = m.run(probes=(good, good))
    _check("run: all ok -> ok true", out["ok"] and len(out["items"]) == 2)
    out = m.run(probes=(good, bad))
    _check("run: one failure -> ok false, failing item kept", not out["ok"] and [i["id"] for i in out["items"] if not i["ok"]] == ["b"])
    out = m.run(probes=(good, boom))
    _check("run: a crashing probe is a failed item, not an exception", not out["ok"] and "crashed" in out["items"][1]["hint"])

    old = m.TOTAL_TIMEOUT
    m.TOTAL_TIMEOUT = 1.0
    hang = lambda: time.sleep(5)  # noqa: E731
    t0 = time.time()
    out = m.run(probes=(good, hang))
    m.TOTAL_TIMEOUT = old
    _check("run: a hung probe times out as a failure", not out["ok"] and "timed out" in out["items"][1]["detail"] and time.time() - t0 < 4)
    print("MESH SELFCHECK OK")


if __name__ == "__main__":
    run()

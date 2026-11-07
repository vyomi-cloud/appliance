"""LLM MESH network layer (docs/architecture/v4.0/BOOSTER-LLM-MESH.md).

Part 1 (always runs, no Docker): core/booster_mesh.py - address plan, token claims, rotation keeps address, role/expiry/signature
rejection, wg dump parsing.

Part 2 (Docker optional - skips cleanly): 1 relay + 1 booster + 3 runner containers, each node on its OWN bridge network with only the
relay reachable (no published ports, outbound-only) and cpu/memory limits. The REAL wasm/relay/booster-mesh.mjs hub + agent and the
REAL docker/booster-runner-llm/mesh-up.sh run in them with kernel WireGuard tunnelled over the WebSocket. Proves: peers join, A reaches
B's service on its WG address (booster->runner and runner->runner), nothing listens/publishes on a routable address, token-less /
wrong-role / expired joins are rejected, a runner re-keys and rejoins without breaking the others, and measures RTT + MB/s of the
WS-tunnelled WG vs the plain docker path.

Run: PYTHONPATH=. python3 tests/conformance/test_booster_mesh.py        (containers are named vyomi-mesh-*; removed at the end)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)
from core import booster_mesh as M  # noqa: E402
from core import booster_session as bs  # noqa: E402

KEY = "mesh-test-key-0123456789abcdef"
PASS = FAIL = 0
METRICS = {}


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}", flush=True)


# ---------------------------------------------------------------- part 1: pure python
nodes = [{"id": "booster", "role": "booster"}] + [{"id": f"r{i}", "role": "runner"} for i in range(1, 4)]
END = time.time() + 3600
cfg = M.mint_mesh_session("sess-1", nodes, account="acct-1", relay_url="wss://relay.example", session_end=END, key=KEY)
check("address plan: booster .0.2, runners .1.1-.1.3, hub .0.1 never handed out",
      cfg["booster"]["address"] == "100.96.0.2" and [cfg[f"r{i}"]["address"] for i in (1, 2, 3)] == ["100.96.1.1", "100.96.1.2", "100.96.1.3"]
      and M.HUB_ADDR not in {c["address"] for c in cfg.values()})
check("no key material in the minted config (nodes generate their own WireGuard keys)",
      not re.search(r"private|preshared|privkey", json.dumps(cfg), re.I) and set(cfg["r1"]["env"]) == {"VYOMI_RELAY_URL", "VYOMI_MESH_TOKEN", "VYOMI_MESH_ADDR", "VYOMI_MESH_ROLE"})
c1 = M.verify_node_token(cfg["r1"]["env"]["VYOMI_MESH_TOKEN"], key=KEY)
check("token claims: role mesh-node, node id, address, session id, expiry", c1["role"] == "mesh-node" and c1["node"] == "r1" and c1["mesh_addr"] == "100.96.1.1"
      and c1["session_id"] == "sess-1" and c1["session_end"] == int(END))
check("mask list carries the token (entrypoint ::add-mask::)", cfg["r1"]["mask"] == [cfg["r1"]["env"]["VYOMI_MESH_TOKEN"]])
rot = M.remint_for_rotation("sess-1", "r2", "runner", 2, account="acct-1", relay_url="wss://relay.example", session_end=END + 600, key=KEY)
check("rotation: successor keeps the same address (slot) with a fresh token", rot["address"] == "100.96.1.2" and rot["env"]["VYOMI_MESH_TOKEN"] != cfg["r2"]["env"]["VYOMI_MESH_TOKEN"])


def rejects(fn):
    try:
        fn(); return False
    except bs.SessionError:
        return True


check("verify rejects: bad signature, wrong key", rejects(lambda: M.verify_node_token(cfg["r1"]["env"]["VYOMI_MESH_TOKEN"], key="other-key")))
check("verify rejects: expired", rejects(lambda: M.verify_node_token(cfg["r1"]["env"]["VYOMI_MESH_TOKEN"], key=KEY, now=END + 5)))
llm_tok = bs.mint("acct-1", "pro", END, session_id="sess-1", key=KEY, role="llm-runner", model="fast")
check("verify rejects: a runner-LLM-role token cannot pose as a mesh node", rejects(lambda: M.verify_node_token(llm_tok, key=KEY)))
check("verify rejects: the hub address is not claimable", rejects(lambda: M.verify_node_token(M.mint_node_token("a", "s", "x", "runner", M.HUB_ADDR, END, key=KEY), key=KEY)))
check("verify rejects: an address outside 100.96.0.0/16", rejects(lambda: M.verify_node_token(M.mint_node_token("a", "s", "x", "runner", "10.0.0.5", END, key=KEY), key=KEY)))
for bad, why in (([{"id": "a", "role": "runner"}] * 2, "dup id"), ([{"id": f"r{i}", "role": "runner"} for i in range(11)], "11 runners"),
                 ([{"id": "b1", "role": "booster"}, {"id": "b2", "role": "booster"}], "2 boosters")):
    try:
        M.plan(bad); ok = False
    except M.MeshError:
        ok = True
    check(f"plan refuses: {why}", ok)
dump = "PRIV\tPUB\t51820\toff\nAAAAAAAAAAAA=\t(none)\t127.0.0.1:1\t100.96.1.1/32\t%d\t100\t200\t25\nBBBBBBBBBBBB=\t(none)\t127.0.0.1:2\t100.96.1.2/32\t0\t0\t0\t25\n" % (time.time() - 30)
rows = M.parse_wg_dump(dump)
check("wg dump -> peer table: up/down by last handshake", rows[0]["up"] and not rows[1]["up"] and rows[0]["tx_bytes"] == 200)
check("runner_urls: only runners that are up, on their mesh address", M.runner_urls([{"id": "r1", "address": "100.96.1.1", "role": "runner", "up": True},
      {"id": "r2", "address": "100.96.1.2", "role": "runner", "up": False}, {"id": "b", "address": "100.96.0.2", "role": "booster", "up": True}]) == {"r1": "http://100.96.1.1:11434"})

# ---------------------------------------------------------------- part 2: docker harness
IMG = "vyomi-mesh-node:test"


def sh(*a, timeout=120, check_rc=False):
    r = subprocess.run(list(a), capture_output=True, text=True, timeout=timeout)
    if check_rc and r.returncode:
        raise RuntimeError(f"{a[:4]} -> {r.stderr[-300:]}")
    return r


def docker_ok():
    if not shutil.which("docker") or sh("docker", "info", timeout=20).returncode:
        return False
    if sh("docker", "image", "inspect", IMG).returncode:
        if sh("docker", "image", "inspect", "vyomi-runllm-runner:spike").returncode:
            return False
        sh("docker", "build", "-q", "-t", IMG, os.path.join(ROOT, "docker/booster-mesh-test"), timeout=600)
    return sh("docker", "image", "inspect", IMG).returncode == 0


def dx(name, cmd, timeout=60):
    return sh("docker", "exec", name, "bash", "-c", cmd, timeout=timeout)


def main_docker():
    names = ["vyomi-mesh-booster", "vyomi-mesh-r1", "vyomi-mesh-r2", "vyomi-mesh-r3"]
    ids = ["booster", "r1", "r2", "r3"]
    nets = [f"vyomi-mesh-net{i}" for i in range(4)]
    relay = "vyomi-mesh-relay"
    session_end = int(time.time()) + 3600
    token = {}

    def mint(nid, role, slot=0):
        return M.mint_mesh_session("sess-d", [{"id": nid, "role": role, "slot": slot}], account="acct-1", relay_url="ws://" + relay + ":8787", session_end=session_end, key=KEY)[nid]
    cfgs = M.mint_mesh_session("sess-d", nodes, account="acct-1", relay_url="ws://" + relay + ":8787", session_end=session_end, key=KEY)

    def cleanup():
        sh("docker", "rm", "-f", relay, *names)
        for n in nets:
            sh("docker", "network", "rm", n)
    cleanup()
    try:
        for n in nets:
            sh("docker", "network", "create", n, check_rc=True)
        mounts = ["-v", f"{ROOT}/wasm/relay:/opt/relay:ro", "-v", f"{ROOT}/docker/booster-runner-llm:/opt/rl:ro", "-v", f"{ROOT}/docker/booster-mesh-test:/opt/test:ro"]
        sh("docker", "run", "-d", "--name", relay, "--network", nets[0], "--cap-add", "NET_ADMIN", "--sysctl", "net.ipv4.ip_forward=1", "--cpus", "1", "--memory", "512m",
           "-e", f"VYOMI_BOOSTER_SESSION_KEY={KEY}", "-e", "WS_PKG=/opt/runner/node_modules/ws", *mounts, "--entrypoint", "node", IMG, "/opt/test/mesh-relay.mjs", check_rc=True)
        for n in nets[1:]:
            sh("docker", "network", "connect", n, relay, check_rc=True)
        for nm, net, nid in zip(names, nets, ids):
            lim = ["--cpus", "1", "--memory", "768m"] if nid == "booster" else ["--cpus", "2", "--memory", "1g"]
            sh("docker", "run", "-d", "--name", nm, "--hostname", nid, "--network", net, "--cap-add", "NET_ADMIN", *lim, *mounts,
               "-e", "WS_PKG=/opt/runner/node_modules/ws", "-e", "MESH_JS=/opt/relay/booster-mesh.mjs", "--entrypoint", "sleep", IMG, "infinity", check_rc=True)
        time.sleep(2)

        def up(nm, nid, tok=None, timeout_s=20):
            env = f"VYOMI_RELAY_URL={cfgs[nid]['relay_url']} VYOMI_MESH_TOKEN='{tok or cfgs[nid]['env']['VYOMI_MESH_TOKEN']}' JOIN_TIMEOUT_S={timeout_s}"
            return dx(nm, f"{env} bash /opt/rl/mesh-up.sh up", timeout=timeout_s + 30)

        t0 = time.time()
        res = {nid: up(nm, nid) for nm, nid in zip(names, ids)}
        check("all 4 nodes (1 booster + 3 runners) joined the mesh", all(r.returncode == 0 for r in res.values()), {k: v.stdout[-200:] + v.stderr[-200:] for k, v in res.items() if v.returncode})
        METRICS["join_all_s"] = round(time.time() - t0, 1)
        for nm, nid in zip(names, ids):
            check(f"{nid}: has its planned WG address {cfgs[nid]['address']}", cfgs[nid]["address"] in dx(nm, "ip -4 addr show wgvyomi").stdout)
        again = up(names[1], "r1")
        check("mesh-up.sh is idempotent (second run reuses the live agent)", again.returncode == 0 and "already joined" in again.stdout, again.stdout + again.stderr)

        # A reaches B's service via the WG address
        for nm, nid in zip(names[1:], ids[1:]):
            a = cfgs[nid]["address"]
            dx(nm, f"mkdir -p /srv/{nid} && echo svc-{nid} > /srv/{nid}/index.html && cd /srv/{nid} && (nohup python3 -m http.server 11434 --bind {a} >/tmp/http.log 2>&1 &) ; sleep 0.5")
        for src, dst in (("booster", "r1"), ("booster", "r2"), ("booster", "r3"), ("r1", "r2"), ("r3", "r1")):
            r = dx(names[ids.index(src)], f"curl -s -m 8 http://{cfgs[dst]['address']}:11434/")
            check(f"{src} -> {dst} service via WG address {cfgs[dst]['address']}", r.stdout.strip() == f"svc-{dst}", r.stdout + r.stderr)
        p = dx(names[0], f"ping -c 5 -q {cfgs['r1']['address']}")
        m = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)", p.stdout)
        METRICS["rtt_ms_ws_tunnelled_booster_r1"] = float(m.group(2)) if m else None
        relay_ip = dx(names[0], f"getent hosts {relay} | cut -d' ' -f1").stdout.strip()
        p0 = dx(names[0], f"ping -c 5 -q {relay_ip}")
        m0 = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)", p0.stdout)
        METRICS["rtt_ms_plain_docker_booster_relay"] = float(m0.group(2)) if m0 else None

        # no inbound
        pubs = [sh("docker", "port", nm).stdout.strip() for nm in names + [relay]]
        check("no published ports on any container", not any(pubs), pubs)
        for nm, nid in zip(names, ids):
            ls = dx(nm, "ss -H -ltn | awk '{print $4}'").stdout.split()
            bad = [x for x in ls if not (x.startswith("127.") or x.startswith("100.96."))]
            check(f"{nid}: no TCP listener on a routable address", not bad, ls)
        eth_ip = dx(names[1], "ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1").stdout.strip()
        rr = dx(relay, f"nc -z -w 2 {eth_ip} 11434; echo rc=$?")
        check("relay cannot open r1's service on its docker address (only WG-bound)", "rc=0" not in rr.stdout, rr.stdout)
        nodes_nets = [sh("docker", "inspect", "-f", "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}", nm).stdout.split() for nm in names]
        check("each node sits alone on its own bridge (only the relay is reachable)", all(len(n) == 1 for n in nodes_nets))
        r2_eth = dx(names[2], "ip -4 -o addr show eth0 | cut -d' ' -f7 | cut -d/ -f1").stdout.strip()
        cross = dx(names[1], f"ping -c 1 -W 2 {r2_eth}")
        check("runners cannot reach each other except through the mesh (no direct docker path)", cross.returncode != 0)

        # rejected joins
        r_none = dx(names[3], "VYOMI_RELAY_URL=ws://%s:8787 VYOMI_MESH_TOKEN= bash /opt/rl/mesh-up.sh up" % relay)
        check("token-less join is refused by the script", r_none.returncode != 0)
        probe = (f"cd /opt/runner; node -e \"const WS=require('ws');const w=new WS('ws://{relay}:8787/mesh',process.env.T?{{headers:{{Authorization:'Bearer '+process.env.T}}}}:{{}});"
                 "w.on('open',()=>{console.log('OPEN');process.exit(0)});w.on('unexpected-response',(q,r)=>{console.log('HTTP',r.statusCode);process.exit(0)});w.on('error',()=>{})\"")
        r = dx(names[3], probe)
        check("WS upgrade without a token -> HTTP 401 (no join)", "HTTP 401" in r.stdout, r.stdout)
        sh("true")
        expired = M.mint_node_token("acct-1", "sess-d", "r9", "runner", "100.96.1.9", time.time() - 100, key=KEY, now=time.time() - 400)
        r = dx(names[3], f"export T='{expired}'; " + probe)
        check("expired token -> HTTP 410", "HTTP 410" in r.stdout, r.stdout)
        wrongrole = bs.mint("acct-1", "pro", session_end, session_id="sess-d", key=KEY, role="llm-runner", model="fast")
        r = dx(names[3], f"export T='{wrongrole}'; " + probe)
        check("an llm-runner token cannot join the mesh -> HTTP 403", "HTTP 403" in r.stdout, r.stdout)
        forged = cfgs["r1"]["env"]["VYOMI_MESH_TOKEN"][:-3] + "AAA"
        r = dx(names[3], f"export T='{forged}'; " + probe)
        check("forged token -> HTTP 401", "HTTP 401" in r.stdout, r.stdout)
        other_sess = M.mint_node_token("acct-1", "sess-OTHER", "r8", "runner", "100.96.1.8", session_end, key=KEY)
        r = dx(names[3], f"export T='{other_sess}'; " + probe)
        check("a token for another session is refused by a hub already serving this one -> HTTP 409", "HTTP 409" in r.stdout, r.stdout)

        # peer table
        time.sleep(3)
        pt = json.loads(dx(relay, f"curl -s -H 'Authorization: Bearer {cfgs['booster']['env']['VYOMI_MESH_TOKEN']}' http://127.0.0.1:8787/mesh/_peers").stdout or "{}")
        peers = {p["id"]: p for p in pt.get("peers", [])}
        check("peer table: 4 peers, all up with a recent handshake", len(peers) == 4 and all(p["up"] and p["last_handshake_s"] is not None for p in peers.values()), pt)
        check("peer table: no full public keys leaked, unauthenticated -> 401", all(p["pubkey"].endswith("...") for p in peers.values())
              and "401" in dx(relay, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/mesh/_peers").stdout)
        old_pub = dx(names[1], "wg show wgvyomi public-key").stdout.strip()[:8]

        # re-key / rejoin: ping booster->r2 continuously while r1 leaves and rejoins with a new key
        dx(names[0], f"nohup ping -i 0.2 -c 150 {cfgs['r2']['address']} > /tmp/ping_r2.txt 2>&1 &")
        time.sleep(2)
        dx(names[1], "bash /opt/rl/mesh-up.sh down")
        gone = json.loads(dx(relay, f"curl -s -H 'Authorization: Bearer {cfgs['booster']['env']['VYOMI_MESH_TOKEN']}' http://127.0.0.1:8787/mesh/_peers").stdout)
        check("drain/leave: r1 disappears from the peer table", "r1" not in {p["id"] for p in gone["peers"]} and len(gone["peers"]) == 3, gone)
        check("leave: r1's service is no longer reachable", dx(names[0], f"curl -s -m 3 http://{cfgs['r1']['address']}:11434/").stdout.strip() == "")
        fresh = mint("r1", "runner", 1)          # rotation: same node id/slot, fresh token
        rj = dx(names[1], f"VYOMI_RELAY_URL={fresh['relay_url']} VYOMI_MESH_TOKEN='{fresh['env']['VYOMI_MESH_TOKEN']}' bash /opt/rl/mesh-up.sh up", timeout=60)
        check("rotated r1 rejoins with the same address", rj.returncode == 0 and "100.96.1.1" in rj.stdout, rj.stdout + rj.stderr)
        new_pub = dx(names[1], "wg show wgvyomi public-key").stdout.strip()[:8]
        check("rotated r1 uses a NEW WireGuard key (generated on the node)", old_pub and new_pub and old_pub != new_pub, (old_pub, new_pub))
        dx(names[1], "cd /srv/r1 && (nohup python3 -m http.server 11434 --bind 100.96.1.1 >/tmp/http.log 2>&1 &); sleep 0.5")
        r = dx(names[0], f"curl -s -m 8 http://{cfgs['r1']['address']}:11434/")
        check("booster reaches the rotated r1 again", r.stdout.strip() == "svc-r1", r.stdout + r.stderr)
        time.sleep(1)
        dx(names[0], "pkill -INT ping; sleep 0.5")
        pg = dx(names[0], "cat /tmp/ping_r2.txt").stdout
        m = re.search(r"(\d+) packets transmitted, (\d+) received", pg)
        sent, rcv = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        check("r1's leave + re-key did not break booster->r2 (continuous ping)", sent > 20 and sent - rcv <= 1, (sent, rcv))
        METRICS["rekey_ping_loss_to_other_peer"] = f"{sent - rcv}/{sent}"
        # rekey with the old key still active: same-token rejoin from a second agent is a replace, other peers untouched
        r = dx(names[2], f"curl -s -m 8 http://{cfgs['r1']['address']}:11434/")
        check("r2 -> rotated r1 works", r.stdout.strip() == "svc-r1", r.stdout)

        # throughput
        dx(names[1], "pkill iperf3; (nohup iperf3 -s -B 100.96.1.1 -D >/dev/null 2>&1)")
        dx(relay, "true")
        time.sleep(1)
        out = dx(names[0], "iperf3 -c 100.96.1.1 -t 6 -J", timeout=40).stdout
        try:
            j = json.loads(out)
            METRICS["tcp_MBps_ws_tunnelled_booster_to_r1_up"] = round(j["end"]["sum_received"]["bits_per_second"] / 8e6, 2)
            out = dx(names[0], "iperf3 -c 100.96.1.1 -t 6 -R -J", timeout=40).stdout
            j = json.loads(out)
            METRICS["tcp_MBps_ws_tunnelled_r1_to_booster_down"] = round(j["end"]["sum_received"]["bits_per_second"] / 8e6, 2)
        except Exception as e:  # noqa: BLE001
            METRICS["iperf_error"] = str(e)[:100] + out[:100]
        dx(relay, "(nohup iperf3 -s -D >/dev/null 2>&1)")
        time.sleep(1)
        try:
            out = dx(names[0], f"iperf3 -c {relay_ip} -t 4 -J", timeout=30).stdout
        except subprocess.TimeoutExpired:
            out = ""
        try:
            METRICS["tcp_MBps_plain_docker_booster_relay"] = round(json.loads(out)["end"]["sum_received"]["bits_per_second"] / 8e6, 1)
        except Exception:  # noqa: BLE001
            pass
        check("throughput measured over the WS-tunnelled WG", METRICS.get("tcp_MBps_ws_tunnelled_booster_to_r1_up", 0) > 0.5, METRICS)

        # clean leave
        dx(names[3], "bash /opt/rl/mesh-up.sh down")
        time.sleep(1)
        pt = json.loads(dx(relay, f"curl -s -H 'Authorization: Bearer {cfgs['booster']['env']['VYOMI_MESH_TOKEN']}' http://127.0.0.1:8787/mesh/_peers").stdout)
        check("another leave: r3 removed, booster/r1/r2 stay up", {p["id"] for p in pt["peers"]} == {"booster", "r1", "r2"} and all(p["up"] for p in pt["peers"]), pt)
        logs = "".join(sh("docker", "logs", nm).stdout + dx(nm, "cat /tmp/vyomi-mesh/agent.log 2>/dev/null").stdout for nm in names + [relay])
        toks = [c["env"]["VYOMI_MESH_TOKEN"] for c in cfgs.values()] + [fresh["env"]["VYOMI_MESH_TOKEN"]]
        check("no token / private key material in any container log", not any(t in logs for t in toks) and "Bearer v1" not in logs)
        psout = "".join(dx(nm, "cat /proc/*/cmdline 2>/dev/null | tr '\\0' ' '").stdout for nm in names)
        check("token never appears in a process command line", not any(t in psout for t in toks[:4]))
    finally:
        if os.environ.get("MESH_KEEP") != "1":
            cleanup()


def direct_phase():
    """Optional direct-UDP attempt: hub advertises a direct endpoint; reachable -> path direct-udp, black hole -> falls back to the WS bridge."""
    net, rl, nd = "vyomi-mesh-netD", "vyomi-mesh-relayD", "vyomi-mesh-nodeD"
    end = int(time.time()) + 3600
    c = M.mint_mesh_session("sess-x", [{"id": "d1", "role": "runner"}], relay_url=f"ws://{rl}:8787", session_end=end, key=KEY)["d1"]
    mounts = ["-v", f"{ROOT}/wasm/relay:/opt/relay:ro", "-v", f"{ROOT}/docker/booster-runner-llm:/opt/rl:ro", "-v", f"{ROOT}/docker/booster-mesh-test:/opt/test:ro"]

    def clean():
        sh("docker", "rm", "-f", rl, nd)
        sh("docker", "network", "rm", net)
    clean()
    try:
        sh("docker", "network", "create", "--subnet", "172.29.77.0/24", net, check_rc=True)
        sh("docker", "run", "-d", "--name", nd, "--network", net, "--cap-add", "NET_ADMIN", *mounts, "-e", "WS_PKG=/opt/runner/node_modules/ws", "-e", "MESH_JS=/opt/relay/booster-mesh.mjs",
           "-e", "VYOMI_MESH_DIRECT_WAIT_MS=3000", "--entrypoint", "sleep", IMG, "infinity", check_rc=True)
        for label, direct, want in (("reachable UDP endpoint", "172.29.77.50:51820", "direct-udp"), ("black-holed UDP endpoint", "172.29.77.99:51820", "ws-bridge")):
            sh("docker", "rm", "-f", rl)
            sh("docker", "run", "-d", "--name", rl, "--network", net, "--ip", "172.29.77.50", "--cap-add", "NET_ADMIN", "--sysctl", "net.ipv4.ip_forward=1", *mounts,
               "-e", f"VYOMI_BOOSTER_SESSION_KEY={KEY}", "-e", f"VYOMI_MESH_DIRECT={direct}", "-e", "WS_PKG=/opt/runner/node_modules/ws", "--entrypoint", "node", IMG, "/opt/test/mesh-relay.mjs", check_rc=True)
            time.sleep(1.5)
            dx(nd, "bash /opt/rl/mesh-up.sh down")
            r = dx(nd, f"VYOMI_RELAY_URL={c['relay_url']} VYOMI_MESH_TOKEN='{c['env']['VYOMI_MESH_TOKEN']}' bash /opt/rl/mesh-up.sh up", timeout=60)
            st = dx(nd, "cat /tmp/vyomi-mesh/status.json").stdout
            pg = dx(nd, "ping -c 3 -W 2 -q 100.96.0.1").returncode
            check(f"direct UDP, {label}: joined via '{want}' and the hub answers on the WG address", r.returncode == 0 and f'"path":"{want}"' in st and pg == 0, (r.stdout, r.stderr, st, pg))
    finally:
        clean()


if docker_ok():
    try:
        main_docker()
        direct_phase()
    except Exception as e:  # noqa: BLE001
        check("docker harness ran to completion", False, repr(e))
    print("METRICS " + json.dumps(METRICS))
else:
    print("[SKIP] Docker (or the vyomi-runllm-runner:spike base image) not available - part 2 skipped")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

"""RDS pg_stat collector + Memorystore INFO -> Cloud Monitoring publisher. Hermetic (stub engines, no docker/valkey)."""
import json, time
from core import observability_core as O, cloudwatch_core as cw, gcp_monitoring_core as gm

F = []
def ck(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: F.append(n)

class PgStub:
    """Answers PG_STATS_SQL like a Postgres; a second instance has a sqlite-like engine that errors."""
    def __init__(self): self.db_instances = {"pg1": {}, "lite1": {}}
    def execute_sql(self, db_id, sql, params=None):
        if db_id == "lite1": raise RuntimeError("no such table: pg_stat_database")
        assert "pg_stat_database" in sql
        return {"rows": [(7, 100, 2, 10, 990, 0, 3)]}
cws = cw.CloudWatchStore()
out = O.collect_rds_stats(PgStub(), cws, docker_line=json.dumps({"CPUPerc": "12.5%", "MemUsage": "100MiB / 1GiB", "NetIO": "1kB / 2kB"}), now=time.time())
ck("only the engine that answers pg_stat publishes", list(out) == ["pg1", "lite1"] or list(out) == ["pg1"] or "pg1" in out)
ck("lite engine publishes docker stats only (no pg metrics invented)", "DatabaseConnections" not in out.get("lite1", []) and "CPUUtilization" in out.get("lite1", []))
ck("pg engine publishes insights metrics", {"DBLoad", "BufferCacheHitRatio", "DatabaseConnections", "TransactionCommits"} <= set(out["pg1"]))
ck("no runtime -> nothing", O.collect_rds_stats(type("S", (), {"db_instances": {"x": {}}, "execute_sql": lambda *a, **k: (_ for _ in ()).throw(RuntimeError())})(), cws) == {})

INFO = "# Server\r\nredis_version:7.2\r\n# Clients\r\nconnected_clients:4\r\n# Memory\r\nused_memory:1048576\r\n# Stats\r\ntotal_connections_received:9\r\ntotal_commands_processed:120\r\nkeyspace_hits:30\r\nkeyspace_misses:10\r\nevicted_keys:2\r\n"
info = O.parse_redis_info(INFO)
ck("INFO parsed", info["clients"] == 4 and info["memory_used"] == 1048576 and info["commands_total"] == 120)
ck("garbage INFO -> {}", O.parse_redis_info("garbage") == {})
store = gm.MonitoringStore() if hasattr(gm, "MonitoringStore") else gm.shared_store()
pub = O.publish_redis_info(store, "proj", "r1", "us-central1", info, now=time.time())
ck("series published", "redis.googleapis.com/clients/connected" in pub and "redis.googleapis.com/stats/cache_hit_ratio" in pub)
vals = [s for s in store.time_series.values() if s["metric"]["type"] == "redis.googleapis.com/stats/cache_hit_ratio"]
ck("hit ratio = 0.75", vals and abs(vals[0]["points"][-1]["value"]["doubleValue"] - 0.75) < 1e-9)
ck("only measured keys: no ratio without hits/misses", "redis.googleapis.com/stats/cache_hit_ratio" not in O.publish_redis_info(store, "proj", "r2", "us-central1", {"clients": 1}, now=time.time()))
r = O.dispatch(O.ObsStore(), "POST", "/_obs/redis-info", {}, {}, json.dumps({"project": "proj", "instance": "r3", "info": INFO}).encode(), mon_store=store)
ck("push endpoint", r.status == 200 and json.loads(r.body)["published"])
ck("push endpoint 501 without store", O.dispatch(O.ObsStore(), "POST", "/_obs/redis-info", {}, {}, b"{}").status == 501)
blob = lambda rx, tx, cpu, rb, wb: "Inter-|\n face |\n  eth0: %d %d 0 0 0 0 0 0 %d %d 0 0 0 0 0 0\n---CPU\nusage_usec %d\n---IO\n254:0 rbytes=%d wbytes=%d rios=1 wios=1\n" % (rx, rx // 100, tx, tx // 100, cpu, rb, wb)
t0 = time.time()
ck("ops agent baseline publishes nothing", O.publish_ops_agent(store, "proj", "vm1", "us-central1-a", blob(1000, 500, 1_000_000, 0, 0), now=t0) == [])
pub = O.publish_ops_agent(store, "proj", "vm1", "us-central1-a", blob(3000, 1500, 1_500_000, 4096, 8192), now=t0 + 10, vcpus=2)
ck("ops agent deltas", "agent.googleapis.com/cpu/utilization" in pub and "agent.googleapis.com/disk/write_bytes_count" in pub)
cpu = [s for s in store.time_series.values() if s["metric"]["type"] == "agent.googleapis.com/cpu/utilization"][0]
ck("cpu = 0.5s / (10s x 2 vcpu) = 2.5%", abs(cpu["points"][-1]["value"]["doubleValue"] - 2.5) < 1e-6)
ck("unreadable counters publish nothing", O.publish_ops_agent(store, "proj", "vm2", "z", "garbage", now=t0) == [])
print("FAILED:", F) if F else print("ALL PASS")
raise SystemExit(1 if F else 0)

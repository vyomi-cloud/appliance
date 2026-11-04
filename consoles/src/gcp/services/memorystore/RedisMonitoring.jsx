/* Memorystore Overview > Monitoring: real Cloud Monitoring series Vyomi derives from the instance's own state
 * (max memory, uptime, node role). Usage / clients / commands have no data source (no Redis process) and say so. */
import { Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { getProject, useProject } from "../../project.js";

const fmtBytes = (n) => `${(Number(n) / 1024 ** 3).toFixed(0)} GiB`;
const fmtUptime = (s) => { s = Number(s); const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m ${s % 60}s`; };

const q = (type, id) => restJson("GET", `/v3/projects/${encodeURIComponent(getProject())}/timeSeries`, { query: {
  filter: `metric.type="${type}" AND resource.labels.instance_id="${id}"`, "interval.startTime": new Date(Date.now() - 3600e3).toISOString(), "interval.endTime": new Date(Date.now() + 60e3).toISOString() } })
  .then((r) => r.timeSeries || []);

export default function RedisMonitoring({ id }) {
  const project = useProject();
  const { data, loading, error, reload } = useAsync(async () => {
    const [mem, up, role, used, cli, cmds, hit] = await Promise.all([q("redis.googleapis.com/stats/memory/maxmemory", id), q("redis.googleapis.com/server/uptime", id), q("redis.googleapis.com/replication/role", id),
      q("redis.googleapis.com/stats/memory/usage", id), q("redis.googleapis.com/clients/connected", id), q("redis.googleapis.com/commands/calls", id), q("redis.googleapis.com/stats/cache_hit_ratio", id)]);
    const val = (s) => { const p = s.points[0]?.value; return p?.int64Value ?? p?.doubleValue; };
    const nodes = mem.map((s) => s.resource.labels.node_id).sort();
    const find = (arr, n) => arr.find((s) => s.resource.labels.node_id === n);
    const last = (arr, n) => { const s = find(arr, n); return s?.points?.length ? Number(s.points[0].value.int64Value ?? s.points[0].value.doubleValue) : null; };   // newest point first
    const rate = (arr, n) => { const s = find(arr, n); const p = s?.points || []; if (p.length < 2) return null; const a = p[0], b = p[p.length - 1];
      const dt = (new Date(a.interval.endTime) - new Date(b.interval.endTime)) / 1000; return dt > 0 ? Math.max(0, (Number(a.value.int64Value) - Number(b.value.int64Value)) / dt) : null; };
    return nodes.map((n) => ({ node: n, role: find(role, n)?.metric.labels.role || "—", max: fmtBytes(val(find(mem, n))), up: fmtUptime(val(find(up, n))),
      used: last(used, n), clients: last(cli, n), ops: rate(cmds, n), hit: last(hit, n) }));
  }, [project, id]);
  return (
    <CapabilityContainer id="gcp.memorystore.monitoring" title="Monitoring">
      <ResourceTable resourceName="nodes" items={data || []} loading={loading} error={error} onRetry={reload} rowKey={(n) => n.node}
        columns={[
          { id: "n", header: "Node", cell: (n) => n.node },
          { id: "r", header: "Role", cell: (n) => n.role },
          { id: "m", header: "Max memory", cell: (n) => n.max },
          { id: "u", header: "Uptime", cell: (n) => n.up },
          { id: "used", header: "Memory usage", cell: (n) => (n.used == null ? "No data" : `${(n.used / 1048576).toFixed(1)} MiB`) },
          { id: "cl", header: "Connected clients", cell: (n) => (n.clients == null ? "No data" : n.clients) },
          { id: "ops", header: "Commands/sec", cell: (n) => (n.ops == null ? "No data" : n.ops.toFixed(2)) },
          { id: "hit", header: "Cache hit ratio", cell: (n) => (n.hit == null ? "No data" : n.hit.toFixed(2)) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No metrics yet. They appear once the instance is READY.</Typography>} />
      <Typography variant="caption" color="text.secondary">Usage, clients, commands and hit ratio are read from the Valkey data plane's INFO (shared by every instance on this appliance) when it is running; without a data plane (Nano, Free tier) they say "No data" and are never invented.</Typography>
    </CapabilityContainer>
  );
}

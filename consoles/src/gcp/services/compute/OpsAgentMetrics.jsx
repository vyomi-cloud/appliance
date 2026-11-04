/* Ops Agent host metrics for one VM: agent.googleapis.com/* series a runtime measured inside the instance (cgroup cpu.stat, /proc/net/dev,
 * io.stat) and pushed to /_obs/gce-counters. No runtime reading -> "No samples" (nothing is invented). */
import { Box, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { listTimeSeries } from "../monitoring/api.js";

const ROWS = [
  ["agent.googleapis.com/cpu/utilization", "CPU utilization (%)", null],
  ["agent.googleapis.com/interface/traffic", "Network received (B)", "received"],
  ["agent.googleapis.com/interface/traffic", "Network sent (B)", "sent"],
  ["agent.googleapis.com/disk/read_bytes_count", "Disk read (B)", null],
  ["agent.googleapis.com/disk/write_bytes_count", "Disk write (B)", null],
];

export default function OpsAgentMetrics({ inst }) {
  const iid = String(inst.id || inst.name);
  const { data, loading } = useAsync(async () => {
    const end = new Date(Date.now() + 60000).toISOString(), start = new Date(Date.now() - 3600000).toISOString();
    const out = [];
    for (const [type, label, dir] of ROWS) {
      const ts = await listTimeSeries({ filter: `metric.type="${type}" AND resource.labels.instance_id="${iid}"`, startTime: start, endTime: end });
      const s = ts.find((x) => !dir || x.metric?.labels?.direction === dir);
      const pts = s?.points || [];
      const v = (p) => p.value.doubleValue ?? Number(p.value.int64Value);
      out.push({ label, n: pts.length, last: pts.length ? v(pts[0]) : null });   // timeSeries.list returns newest first
    }
    return out;
  }, [iid]);
  return (
    <CapabilityContainer id="gcp.compute.opsagent_metrics" title="Ops Agent metrics">
      <Box sx={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: 14, borderCollapse: "collapse" }} aria-label="Ops Agent metrics">
          <thead><tr>{["Metric", "Latest", "Samples (1 h)"].map((h) => <th key={h} style={{ textAlign: "left", padding: 6, borderBottom: "1px solid #ddd" }}>{h}</th>)}</tr></thead>
          <tbody>
            {(data || []).map((r) => (
              <tr key={r.label} data-testid="opsagent-row"><td style={{ padding: 6 }}>{r.label}</td><td style={{ padding: 6 }}>{r.last == null ? "No samples" : r.last}</td><td style={{ padding: 6 }}>{r.n}</td></tr>
            ))}
            {loading && !data && <tr><td colSpan={3} style={{ padding: 6 }}>Loading...</td></tr>}
          </tbody>
        </table>
      </Box>
      <Typography variant="caption" color="text.secondary">Measured inside the instance by the runtime (cgroup + /proc counters) and pushed to Cloud Monitoring; CPU is reported as cpu_state=used. Memory, process and per-filesystem metrics are not produced.</Typography>
    </CapabilityContainer>
  );
}

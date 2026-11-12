/* System insights — storage/connections/query-throughput, all derived from REAL activity
 * (api.getMetrics -> GET .../instances/{i}/metrics, core/gcp_cloudsql_core.py:_get_metrics):
 * storage used comes from the real engine (sqlite page_count*page_size / pg_database_size),
 * active connections from the real open-transaction count, and the throughput/error series
 * from the real query log Cloud SQL Studio writes. CPU/memory utilization aren't shown — no
 * virtualized compute resource backs a Vyomi instance, so there's no OS process to sample —
 * see core/capabilities/gcp/sql.json: gcp.sql.insights. */
import { Box, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, fmtBytes, KeyValue, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

function Sparkline({ series }) {
  const max = Math.max(1, ...series);
  return (
    <Stack direction="row" spacing={0.5} alignItems="flex-end" sx={{ height: 64 }}>
      {series.map((v, i) => (
        <Box key={i} title={`${v} quer${v === 1 ? "y" : "ies"}`}
          sx={{ width: 14, bgcolor: "primary.main", opacity: 0.75, borderRadius: 0.5, height: `${Math.max(2, (v / max) * 60)}px` }} />
      ))}
    </Stack>
  );
}

export default function SystemInsights({ params }) {
  const name = params.name;
  const metrics = useAsync(() => api.getMetrics(name), [name]);
  const m = metrics.data;
  return (
    <>
      <InstanceNav name={name} active="system-insights" />
      <Typography variant="h2" component="h2" sx={{ fontSize: 20, mb: 1.5 }}>System insights</Typography>
      <ErrorAlert error={metrics.error} title="Failed to load metrics" />
      {m && (
        <Stack spacing={2.5}>
          <CapabilityContainer id="gcp.sql.insights" title="Database summary">
            <KeyValue items={[
              ["Storage used", fmtBytes(m.storageBytes)],
              ["Active connections", m.activeConnections],
              ["Queries (last hour)", m.queryCount1h],
              ["Errors (last hour)", m.errorCount1h],
            ]} />
          </CapabilityContainer>
          <Section title="Query throughput (last hour, 5-minute buckets)">
            <Sparkline series={m.series} />
          </Section>
        </Stack>
      )}
    </>
  );
}

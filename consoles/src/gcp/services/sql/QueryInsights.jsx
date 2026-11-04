/* Query insights — top queries (aggregated client-side) + recent queries, both read from
 * the REAL query log Cloud SQL Studio writes on every run (api.listQueries -> GET
 * .../instances/{i}/queries, core/gcp_cloudsql_core.py:_list_queries / _log_query). Never
 * synthetic rows — see core/capabilities/gcp/sql.json: gcp.sql.insights. */
import { useMemo } from "react";
import { Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, fmtDate, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

function topQueries(items) {
  const byQuery = new Map();
  for (const q of items) {
    const agg = byQuery.get(q.normalized) || { normalized: q.normalized, count: 0, totalMs: 0, lastRun: q.ts };
    agg.count += 1; agg.totalMs += q.durationMs;
    if (q.ts > agg.lastRun) agg.lastRun = q.ts;
    byQuery.set(q.normalized, agg);
  }
  return [...byQuery.values()].sort((a, b) => b.totalMs - a.totalMs);
}

export default function QueryInsights({ params }) {
  const name = params.name;
  const queries = useAsync(() => api.listQueries(name), [name]);
  const items = queries.data || [];
  const top = useMemo(() => topQueries(items), [items]);

  return (
    <>
      <InstanceNav name={name} active="query-insights" />
      <Typography variant="h2" component="h2" sx={{ fontSize: 20, mb: 1.5 }}>Query insights</Typography>
      <ErrorAlert error={queries.error} title="Failed to load queries" />
      <Stack spacing={2.5}>
        <CapabilityContainer id="gcp.sql.insights" title="Top queries">
          <ResourceTable resourceName="top queries" items={top} rowKey={(q) => q.normalized} loading={queries.loading}
            filterPlaceholder="Filter top queries"
            columns={[
              { id: "sql", header: "Query", cell: (q) => q.normalized },
              { id: "count", header: "Executions", cell: (q) => q.count },
              { id: "avg", header: "Avg duration (ms)", cell: (q) => (q.totalMs / q.count).toFixed(1) },
              { id: "total", header: "Total duration (ms)", cell: (q) => q.totalMs.toFixed(1) },
              { id: "last", header: "Last run", cell: (q) => fmtDate(q.lastRun) },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No queries have run yet. Try Cloud SQL Studio.</Typography>} />
        </CapabilityContainer>
        <Section title="Recent queries">
          <ResourceTable resourceName="recent queries" items={items} rowKey={(q) => `${q.epoch}-${q.sql}`} loading={queries.loading}
            filterPlaceholder="Filter recent queries"
            columns={[
              { id: "sql", header: "Query", cell: (q) => q.sql },
              { id: "status", header: "Status", cell: (q) => q.ok ? "OK" : "Error" },
              { id: "dur", header: "Duration (ms)", cell: (q) => q.durationMs },
              { id: "rows", header: "Rows", cell: (q) => q.rowCount },
              { id: "ts", header: "Run at", cell: (q) => fmtDate(q.ts) },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No queries have run yet.</Typography>} />
        </Section>
      </Stack>
    </>
  );
}

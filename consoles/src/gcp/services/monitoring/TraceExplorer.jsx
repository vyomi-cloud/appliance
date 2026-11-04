/* Trace explorer — real Cloud Trace v1 traces.list/get over spans written via v2 batchWrite / SDKs. */
import { useState } from "react";
import { Box, Button, Stack, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const ms = (a, b) => Math.max(0, new Date(b) - new Date(a));

function Waterfall({ trace }) {
  const spans = trace.spans || [];
  if (!spans.length) return null;
  const t0 = Math.min(...spans.map((s) => +new Date(s.startTime)));
  const total = Math.max(1, Math.max(...spans.map((s) => +new Date(s.endTime))) - t0);
  return (
    <Box sx={{ mt: 2 }} data-testid="trace-waterfall">
      <Typography variant="subtitle2">Trace {trace.traceId} — {total} ms, {spans.length} spans</Typography>
      {spans.map((s) => (
        <Stack key={s.spanId} direction="row" alignItems="center" spacing={1} sx={{ my: 0.5 }}>
          <Typography variant="body2" sx={{ width: 220 }} noWrap>{s.parentSpanId ? "  └ " : ""}{s.name}</Typography>
          <Box sx={{ flex: 1, position: "relative", height: 14, bgcolor: "action.hover" }}>
            <Box sx={{ position: "absolute", left: `${((+new Date(s.startTime) - t0) / total) * 100}%`, width: `${Math.max(0.5, (ms(s.startTime, s.endTime) / total) * 100)}%`, height: "100%", bgcolor: "primary.main" }} />
          </Box>
          <Typography variant="caption" sx={{ width: 60 }}>{ms(s.startTime, s.endTime)} ms</Typography>
        </Stack>
      ))}
    </Box>
  );
}

export default function TraceExplorer() {
  const project = useProject();
  const [filter, setFilter] = useState("");
  const [applied, setApplied] = useState("");
  const [open, setOpen] = useState(null);
  const { data, loading, error, reload } = useAsync(() => api.listTraces(applied ? { filter: applied } : {}), [project, applied]);
  return (
    <>
      <PageHeader title="Trace explorer" />
      <CapabilityContainer id="gcp.monitoring.trace-explorer" title="Distributed tracing">
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <TextField size="small" fullWidth label="Filter (span:name, +root:name, label:k:v, latency:100ms)" value={filter} onChange={(e) => setFilter(e.target.value)} inputProps={{ "aria-label": "Trace filter" }} />
          <Button variant="contained" onClick={() => setApplied(filter)}>Apply</Button>
        </Stack>
        <ResourceTable
          resourceName="traces"
          items={data || []}
          loading={loading}
          error={error}
          onRetry={reload}
          rowKey={(t) => t.traceId}
          columns={[
            { id: "id", header: "Trace ID", cell: (t) => <Button size="small" onClick={async () => setOpen(await api.getTrace(t.traceId))}>{t.traceId}</Button> },
            { id: "root", header: "Root span", cell: (t) => t.spans?.[0]?.name || "—" },
            { id: "start", header: "Start", cell: (t) => t.spans?.[0]?.startTime || "—" },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No traces. Spans appear when an app or script writes them with the Cloud Trace API or an OpenTelemetry exporter.</Typography>}
        />
        {open && <Waterfall trace={open} />}
      </CapabilityContainer>
    </>
  );
}

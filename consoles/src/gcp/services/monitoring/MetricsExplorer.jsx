/* Metrics Explorer — the Builder-mode query editor over real stored time series
 * (write_time_series / list_time_series in the core): pick a metric, filter, align,
 * reduce, and see results as a table and a small chart. PromQL mode is a declared gap. */
import { useEffect, useMemo, useState } from "react";
import {
  Box, Button, FormControlLabel, MenuItem, Radio, RadioGroup, Select, Stack, Switch, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const WIDGETS = ["Line chart", "Stacked bar chart", "Heatmap chart", "Table", "Scorecard", "Text", "Alert chart", "Logs panel"];
const ANALYSIS_MODES = ["None", "Rate of change", "Cumulative"];
const COMPARE_MODES = ["None", "Same time yesterday"];
const YSCALES = ["Linear", "Log"];

function Sparkline({ points, scale }) {
  const vals = points.map((p) => Number(p.v));
  if (!vals.length) return null;
  const tx = (v) => (scale === "Log" ? Math.log10(Math.max(v, 1e-9)) : v);
  const min = Math.min(...vals.map(tx)), max = Math.max(...vals.map(tx));
  const norm = (v) => (max === min ? 20 : 40 - ((tx(v) - min) / (max - min)) * 40);
  const d = vals.map((v, i) => `${i === 0 ? "M" : "L"} ${(i / Math.max(vals.length - 1, 1)) * 160} ${norm(v)}`).join(" ");
  return <svg width={160} height={40} aria-hidden><path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} /></svg>;
}

function applyAnalysis(points, mode) {
  if (mode === "Rate of change") return points.map((p, i) => ({ ...p, v: i === 0 ? 0 : p.v - points[i - 1].v }));
  if (mode === "Cumulative") { let s = 0; return points.map((p) => ({ ...p, v: (s += p.v) })); }
  return points;
}

export default function MetricsExplorer() {
  const notify = useNotify();
  const [queryMode, setQueryMode] = useState("Builder");
  const [range, setRange] = useState("5m");
  const [rangeOverride, setRangeOverride] = useState("None");
  const [metrics, setMetrics] = useState([]);
  const [metric, setMetric] = useState("");
  const [filter, setFilter] = useState("");
  const [aligner, setAligner] = useState("ALIGN_NONE");
  const [groupBy, setGroupBy] = useState("None");
  const [autoRun, setAutoRun] = useState(false);
  const [view, setView] = useState("Chart");
  const [breakdown, setBreakdown] = useState(false);
  const [widget, setWidget] = useState("Line chart");
  const [analysis, setAnalysis] = useState("None");
  const [compare, setCompare] = useState("None");
  const [yscale, setYscale] = useState("Linear");
  const [threshold, setThreshold] = useState("");
  const [results, setResults] = useState(null);
  const [compareResults, setCompareResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useMemo(() => { api.listMetricDescriptors().then(setMetrics).catch(() => {}); }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (autoRun && metric) run(); }, [autoRun, metric, filter, aligner, groupBy, range, rangeOverride, compare]);

  const pickMetric = (type) => {
    setMetric(type);
    const builtin = api.BUILTIN_METRICS.find(([t]) => t === type);
    const resourceType = builtin?.[3] || "global";
    setFilter(`metric.type = "${type}" AND resource.type = "${resourceType}"`);
  };

  const run = async () => {
    if (!metric) return;
    setBusy(true); setError(null);
    try {
      const ms = api.rangeToMs(rangeOverride !== "None" ? rangeOverride : range);
      const end = new Date();
      const q = (offsetMs) => api.listTimeSeries({
        filter, startTime: new Date(end - ms - offsetMs).toISOString(), endTime: new Date(end - offsetMs).toISOString(),
        aligner, period: "60s", groupBy: groupBy !== "None" ? [groupBy] : undefined,
      });
      setResults(await q(0));
      setCompareResults(compare === "Same time yesterday" ? await q(86400000) : null);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  const seriesRows = (results || []).map((s, i) => {
    const pts = applyAnalysis((s.points || []).slice().reverse().map((p) => ({ t: p.interval.endTime, v: Number(p.value.doubleValue ?? p.value.int64Value ?? 0) })), analysis);
    const last = pts[pts.length - 1]?.v;
    const over = threshold !== "" && last !== undefined && last > Number(threshold);
    return { key: i, label: s.resource?.labels?.[groupBy.split(".").pop()] || s.metric?.type || `series ${i + 1}`, pts, last, over,
      yesterday: compareResults?.[i]?.points?.[0] ? Number(compareResults[i].points[0].value.doubleValue ?? compareResults[i].points[0].value.int64Value ?? 0) : null };
  });

  return (
    <>
      <PageHeader title="Metrics explorer" actions={<Button disabled={!results} onClick={() => notify.success("Saved to dashboard (choose a dashboard from Dashboards to pin it).")}>Save to dashboard</Button>} />
      <Stack spacing={2.5}>
        <Section title="Query editor" actions={<><Button size="small" disabled>Add query</Button><Button size="small" disabled>Create ratio</Button></>}>
          <Stack spacing={2}>
            <RadioGroup row value={queryMode} onChange={(e) => setQueryMode(e.target.value)} aria-label="Query mode">
              <FormControlLabel value="Builder" control={<Radio size="small" />} label="Builder" />
              <FormControlLabel value="PromQL" control={<Radio size="small" />} label="PromQL" />
            </RadioGroup>
            {queryMode === "PromQL" ? <CapabilityContainer id="gcp.monitoring.metrics-explorer" title="PromQL query mode" /> : (
              <Stack spacing={2} sx={{ maxWidth: 560 }}>
                <Select value={range} onChange={(e) => setRange(e.target.value)} inputProps={{ "aria-label": "Time range" }}>
                  {api.TIME_RANGES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
                </Select>
                <Select value={metric} onChange={(e) => pickMetric(e.target.value)} displayEmpty required
                  renderValue={(v) => v || "Select a metric"} inputProps={{ "aria-label": "Metric" }}>
                  <MenuItem value="" disabled>Select a metric</MenuItem>
                  {metrics.map((m) => <MenuItem key={m.type} value={m.type}>{m.displayName || m.type}</MenuItem>)}
                </Select>
                <TextField label="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} inputProps={{ "aria-label": "Filter" }} />
                <Select value={aligner} onChange={(e) => setAligner(e.target.value)} inputProps={{ "aria-label": "Aggregation" }}>
                  {api.ALIGNERS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
                </Select>
                <Select value={groupBy} onChange={(e) => setGroupBy(e.target.value)} inputProps={{ "aria-label": "by" }}>
                  <MenuItem value="None">None</MenuItem>
                  <MenuItem value="resource.labels.zone">resource.labels.zone</MenuItem>
                  <MenuItem value="resource.labels.project_id">resource.labels.project_id</MenuItem>
                </Select>
                <FormControlLabel control={<Switch checked={autoRun} onChange={(e) => setAutoRun(e.target.checked)} />} label="Auto-Run" />
                <Box><Button variant="contained" disabled={!metric || busy} onClick={run}>{busy ? "Running…" : "Run query"}</Button></Box>
              </Stack>
            )}
          </Stack>
        </Section>
        <ErrorAlert error={error} title="Query failed" />

        <Section title="Results">
          <Stack spacing={2}>
            <RadioGroup row value={view} onChange={(e) => setView(e.target.value)} aria-label="View">
              <FormControlLabel value="Chart" control={<Radio size="small" />} label="Chart" />
              <FormControlLabel value="Table" control={<Radio size="small" />} label="Table" />
              <FormControlLabel value="Both" control={<Radio size="small" />} label="Both" />
            </RadioGroup>
            <FormControlLabel control={<Switch checked={breakdown} onChange={(e) => setBreakdown(e.target.checked)} />} label="Show Breakdown" />
            {!results ? <Typography variant="body2" color="text.secondary">Run a query to see results.</Typography> : !seriesRows.length ? (
              <Typography variant="body2" color="text.secondary">No time series matched this query.</Typography>
            ) : (
              <Table size="small">
                <TableHead><TableRow>
                  <TableCell>Series</TableCell>
                  {(view === "Chart" || view === "Both") && <TableCell>Chart</TableCell>}
                  {(view === "Table" || view === "Both") && <TableCell align="right">Latest value</TableCell>}
                  {compare !== "None" && <TableCell align="right">vs yesterday</TableCell>}
                </TableRow></TableHead>
                <TableBody>
                  {(breakdown ? seriesRows : seriesRows.slice(0, 1)).map((r) => (
                    <TableRow key={r.key} sx={r.over ? { bgcolor: "error.main", "& .MuiTableCell-root": { color: "error.contrastText" } } : undefined}>
                      <TableCell>{r.label}</TableCell>
                      {(view === "Chart" || view === "Both") && <TableCell><Sparkline points={r.pts} scale={yscale} /></TableCell>}
                      {(view === "Table" || view === "Both") && <TableCell align="right">{r.last?.toFixed(3) ?? "—"}</TableCell>}
                      {compare !== "None" && <TableCell align="right">{r.yesterday?.toFixed(3) ?? "—"}</TableCell>}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Stack>
        </Section>

        <Section title="Display">
          <Stack spacing={2} sx={{ maxWidth: 420 }}>
            <Select value={widget} onChange={(e) => setWidget(e.target.value)} inputProps={{ "aria-label": "Widget type" }}>
              {WIDGETS.map((w) => <MenuItem key={w} value={w}>{w}</MenuItem>)}
            </Select>
            <Select value={analysis} onChange={(e) => setAnalysis(e.target.value)} inputProps={{ "aria-label": "Analysis Mode" }}>
              {ANALYSIS_MODES.map((w) => <MenuItem key={w} value={w}>{w}</MenuItem>)}
            </Select>
            <Select value={compare} onChange={(e) => setCompare(e.target.value)} inputProps={{ "aria-label": "Compare to past" }}>
              {COMPARE_MODES.map((w) => <MenuItem key={w} value={w}>{w}</MenuItem>)}
            </Select>
            <TextField label="Threshold Line" type="number" value={threshold} onChange={(e) => setThreshold(e.target.value)} helperText="Rows above this value are highlighted." />
            <Select value={yscale} onChange={(e) => setYscale(e.target.value)} inputProps={{ "aria-label": "Y-axis scale" }}>
              {YSCALES.map((w) => <MenuItem key={w} value={w}>{w}</MenuItem>)}
            </Select>
            <Select value={rangeOverride} onChange={(e) => setRangeOverride(e.target.value)} inputProps={{ "aria-label": "Time Range Override" }}>
              <MenuItem value="None">Use query time range</MenuItem>
              {api.TIME_RANGES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
            </Select>
          </Stack>
        </Section>
      </Stack>
    </>
  );
}

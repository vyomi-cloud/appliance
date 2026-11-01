/* Logs Explorer — query by resource/log name/severity/free text over the real
 * entries:list wire, same filter language core/gcp_logging_core.py parses server-side. */
import { useEffect, useMemo, useState } from "react";
import {
  Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, FormControlLabel,
  FormGroup, IconButton, InputLabel, MenuItem, Select, Stack, Switch, TextField, Tooltip, Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import VisibilityIcon from "@mui/icons-material/esm/Visibility.js";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, fmtDate, NotSimulated, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const EXTRA_FIELDS = [["logName", "Log name"], ["resourceType", "Resource"], ["trace", "Trace"]];

export default function LogsExplorer() {
  const [search, setSearch] = useState("");
  const [range, setRange] = useState("5m");
  const [resourceType, setResourceType] = useState("all");
  const [logName, setLogName] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [showQuery, setShowQuery] = useState(true);
  const [query, setQuery] = useState("");
  const [extra, setExtra] = useState(new Set());
  const [detail, setDetail] = useState(null);
  const { data = [], loading, error, reload } = useAsync(() => api.listEntries({ orderBy: "timestamp desc", pageSize: 1000 }), []);

  // Keep the raw query box in sync with the dropdowns (the console's own two-way sync).
  useEffect(() => { setQuery(api.buildFilter({ resourceType, logName, severity })); }, [resourceType, logName, severity]);

  const resourceTypes = useMemo(() => [...new Set(data.map((e) => e.resource?.type).filter(Boolean))].sort(), [data]);
  const logNames = useMemo(() => [...new Set(data.map((e) => e.logName?.split("/logs/")[1]).filter(Boolean))].sort(), [data]);

  const cutoff = Date.now() - (api.TIME_RANGES.find(([v]) => v === range)?.[2] || 300) * 1000;
  const filtered = useMemo(() => data.filter((en) => {
    if (new Date(en.timestamp).getTime() < cutoff) return false;
    if (search && !JSON.stringify(en).toLowerCase().includes(search.toLowerCase())) return false;
    return api.matchesQuery(en, query);
  }), [data, cutoff, search, query]);

  const buckets = useMemo(() => {
    const n = 24, span = Date.now() - cutoff, out = Array.from({ length: n }, () => ({ count: 0, sev: "DEFAULT" }));
    for (const en of filtered) {
      const i = Math.min(n - 1, Math.max(0, Math.floor((new Date(en.timestamp).getTime() - cutoff) / span * n)));
      out[i].count++;
      if (api.SEVERITY_ORDER[en.severity] > api.SEVERITY_ORDER[out[i].sev]) out[i].sev = en.severity;
    }
    return out;
  }, [filtered, cutoff]);
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));

  const toggleExtra = (id) => setExtra((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const columns = [
    { id: "severity", header: "Severity", sortField: "severity", cell: (en) => <Typography variant="body2" sx={{ color: api.severityColor(en.severity), fontWeight: 500 }}>{en.severity}</Typography> },
    { id: "time", header: "Time", sortField: "timestamp", cell: (en) => fmtDate(en.timestamp) },
    { id: "summary", header: "Summary", wrap: true, cell: (en) => api.summary(en) },
    ...EXTRA_FIELDS.filter(([id]) => extra.has(id)).map(([id, header]) => ({
      id, header, cell: (en) => (id === "resourceType" ? en.resource?.type : id === "trace" ? en.trace : en.logName) || "—",
    })),
    { id: "actions", header: "Actions", cell: (en) => <Tooltip title="View details"><IconButton size="small" aria-label="View details" onClick={() => setDetail(en)}><VisibilityIcon fontSize="inherit" /></IconButton></Tooltip> },
  ];

  return (
    <>
      <PageHeader title="Logs Explorer" actions={<Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>} />
      <Stack spacing={2}>
        <Section title="Query">
          <Stack spacing={2}>
            <Stack useFlexGap direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 2 }}>
              <FormControl sx={{ minWidth: 180 }}>
                <InputLabel id="scope-l">Scope</InputLabel>
                <Select labelId="scope-l" label="Scope" value="project" inputProps={{ "aria-label": "Scope" }}><MenuItem value="project">Project logs</MenuItem></Select>
              </FormControl>
              <TextField label="Search all fields" value={search} onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 220, flex: 1 }} inputProps={{ "aria-label": "Search all fields" }} />
              <FormControl sx={{ minWidth: 180 }}>
                <InputLabel id="range-l">Time range</InputLabel>
                <Select labelId="range-l" label="Time range" value={range} onChange={(e) => setRange(e.target.value)} inputProps={{ "aria-label": "Time range" }}>
                  {api.TIME_RANGES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
                </Select>
              </FormControl>
            </Stack>
            <Stack useFlexGap direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 2 }}>
              <FormControl sx={{ minWidth: 200 }}>
                <InputLabel id="res-l">All resources</InputLabel>
                <Select labelId="res-l" label="All resources" value={resourceType} onChange={(e) => setResourceType(e.target.value)} inputProps={{ "aria-label": "All resources" }}>
                  <MenuItem value="all">All resources</MenuItem>
                  {resourceTypes.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                </Select>
              </FormControl>
              <FormControl sx={{ minWidth: 200 }}>
                <InputLabel id="log-l">All log names</InputLabel>
                <Select labelId="log-l" label="All log names" value={logName} onChange={(e) => setLogName(e.target.value)} inputProps={{ "aria-label": "All log names" }}>
                  <MenuItem value="all">All log names</MenuItem>
                  {logNames.map((n) => <MenuItem key={n} value={n}>{n}</MenuItem>)}
                </Select>
              </FormControl>
              <FormControl sx={{ minWidth: 200 }}>
                <InputLabel id="sev-l">All severities</InputLabel>
                <Select labelId="sev-l" label="All severities" value={severity} onChange={(e) => setSeverity(e.target.value)} inputProps={{ "aria-label": "All severities" }}>
                  <MenuItem value="all">All severities</MenuItem>
                  {api.SEVERITIES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
                </Select>
              </FormControl>
            </Stack>
            <NotSimulated compact feature="Correlate by" note="Groups results by a shared trace ID across multiple log streams; Vyomi records trace IDs on entries but doesn't build this cross-log correlation view." />
            <FormControlLabel control={<Switch size="small" checked={showQuery} onChange={(e) => setShowQuery(e.target.checked)} />} label="Show query" />
            {showQuery && (
              <TextField label="Query" value={query} onChange={(e) => setQuery(e.target.value)} multiline minRows={3} fullWidth
                placeholder='Start writing a query using LQL (Logging query language)' inputProps={{ "aria-label": "Query" }} />
            )}
            <Box><Button variant="contained" onClick={reload}>Run query</Button></Box>
          </Stack>
        </Section>

        <Section title="Fields">
          <FormGroup row aria-label="Fields">
            {EXTRA_FIELDS.map(([id, label]) => (
              <FormControlLabel key={id} control={<Checkbox size="small" checked={extra.has(id)} onChange={() => toggleExtra(id)} />} label={label} />
            ))}
          </FormGroup>
        </Section>

        <Section title="Timeline">
          <Stack direction="row" spacing={0.5} alignItems="flex-end" sx={{ height: 72 }} aria-label="Log volume timeline">
            {buckets.map((b, i) => (
              <Tooltip key={i} title={`${b.count} entries`}>
                <Box sx={{ flex: 1, bgcolor: b.count ? api.severityColor(b.sev) : "action.hover", opacity: b.count ? 0.8 : 0.3, height: `${Math.max(4, (b.count / maxCount) * 100)}%`, borderRadius: 0.5 }} />
              </Tooltip>
            ))}
          </Stack>
        </Section>

        <Section title="Query results">
          <ErrorAlert error={error} title="Failed to query logs" />
          <ResourceTable resourceName="log entries" items={filtered} rowKey={(en) => en.insertId} loading={loading} error={error} onRetry={reload}
            columns={columns} empty={<Typography variant="body2" color="text.secondary">No data found</Typography>} />
        </Section>
      </Stack>
      <Dialog open={!!detail} onClose={() => setDetail(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Log entry</DialogTitle>
        <DialogContent><Box component="pre" sx={{ m: 0, fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{detail ? JSON.stringify(detail, null, 2) : ""}</Box></DialogContent>
        <DialogActions><Button onClick={() => setDetail(null)}>Close</Button></DialogActions>
      </Dialog>
    </>
  );
}

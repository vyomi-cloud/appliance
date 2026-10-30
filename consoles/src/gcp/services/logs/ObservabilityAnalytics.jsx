/* Observability Analytics — a query-builder + small SQL subset over one bucket's log
 * entries (real entries:list data, filtered/sorted/limited client-side). */
import { useEffect, useMemo, useState } from "react";
import {
  Box, Button, Checkbox, FormControl, FormControlLabel, FormGroup, IconButton, InputLabel, MenuItem, Radio,
  RadioGroup, Select, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, fmtDate, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const COLUMNS = [["timestamp", "Timestamp"], ["severity", "Severity"], ["logName", "Log name"], ["textPayload", "Payload"], ["resourceType", "Resource type"]];
const value = (en, col) => (col === "resourceType" ? en.resource?.type : col === "textPayload" ? api.summary(en) : en[col]) ?? "";
const OPS = ["=", "!=", "contains"];

function applySql(entries, sql) {
  const m = sql.match(/select\s+(.+?)\s+from\s+\S+(?:\s+where\s+(.+?))?(?:\s+order\s+by\s+(\S+))?(?:\s+limit\s+(\d+))?\s*;?$/is);
  if (!m) return { rows: [], cols: COLUMNS.map(([c]) => c), error: "Expected: SELECT col, col FROM bucket [WHERE col = \"v\"] [ORDER BY col] [LIMIT n]" };
  const cols = m[1].trim() === "*" ? COLUMNS.map(([c]) => c) : m[1].split(",").map((s) => s.trim());
  let rows = entries;
  if (m[2]) {
    const wm = m[2].match(/^(\w+)\s*(=|!=)\s*"?([^"]*)"?$/);
    if (wm) rows = rows.filter((en) => (String(value(en, wm[1])) === wm[3]) === (wm[2] === "="));
  }
  if (m[3]) rows = [...rows].sort((a, b) => String(value(a, m[3])).localeCompare(String(value(b, m[3]))));
  if (m[4]) rows = rows.slice(0, Number(m[4]));
  return { rows, cols, error: null };
}

export default function ObservabilityAnalytics() {
  const [mode, setMode] = useState("builder");
  const [source, setSource] = useState("");
  const [cols, setCols] = useState(new Set(["timestamp", "severity", "textPayload"]));
  const [filters, setFilters] = useState([]);
  const [sortBy, setSortBy] = useState("timestamp");
  const [limit, setLimit] = useState(50);
  const [sql, setSql] = useState('SELECT timestamp, severity, textPayload FROM `_Default` ORDER BY timestamp LIMIT 50;');
  const buckets = useAsync(() => api.listBuckets(), []);
  const entries = useAsync(() => api.listEntries({ orderBy: "timestamp desc", pageSize: 1000 }), []);

  useEffect(() => { if (!source && buckets.data?.length) setSource(api.bucketId(buckets.data[0].name)); }, [buckets.data, source]);

  const builderResult = useMemo(() => {
    let rows = entries.data || [];
    for (const f of filters) {
      if (!f.field || !f.value) continue;
      rows = rows.filter((en) => f.op === "contains" ? String(value(en, f.field)).toLowerCase().includes(f.value.toLowerCase()) : (String(value(en, f.field)) === f.value) === (f.op === "="));
    }
    rows = [...rows].sort((a, b) => String(value(a, sortBy)).localeCompare(String(value(b, sortBy))));
    return rows.slice(0, Number(limit) || 50);
  }, [entries.data, filters, sortBy, limit]);

  const sqlResult = useMemo(() => applySql(entries.data || [], sql), [entries.data, sql]);
  const shownCols = mode === "sql" ? sqlResult.cols : [...cols];
  const shownRows = mode === "sql" ? sqlResult.rows : builderResult;

  return (
    <>
      <PageHeader title="Observability Analytics" actions={<Button variant="contained" onClick={entries.reload}>Run query</Button>} />
      <Stack spacing={2}>
        <Section title="Query">
          <Stack spacing={2}>
            <RadioGroup row value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Query mode">
              <FormControlLabel value="builder" control={<Radio size="small" />} label="Query Builder" />
              <FormControlLabel value="SQL" control={<Radio size="small" />} label="SQL" />
            </RadioGroup>
            {mode === "builder" ? (
              <>
                <FormControl sx={{ maxWidth: 320 }}>
                  <InputLabel id="src-l">Source</InputLabel>
                  <Select labelId="src-l" label="Source" value={source} onChange={(e) => setSource(e.target.value)} inputProps={{ "aria-label": "Source" }}>
                    {(buckets.data || []).map((b) => <MenuItem key={b.name} value={api.bucketId(b.name)}>{api.bucketId(b.name)}</MenuItem>)}
                  </Select>
                </FormControl>
                <Box>
                  <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Columns</Typography>
                  <FormGroup row aria-label="Columns">
                    {COLUMNS.map(([id, label]) => (
                      <FormControlLabel key={id} control={<Checkbox size="small" checked={cols.has(id)} onChange={() => setCols((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; })} />} label={label} />
                    ))}
                  </FormGroup>
                </Box>
                <Box>
                  <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Filters</Typography>
                  <Stack spacing={1} aria-label="Filters">
                    {filters.map((f, i) => (
                      <Stack key={i} direction="row" spacing={1} alignItems="center">
                        <FormControl sx={{ minWidth: 140 }}><Select value={f.field} onChange={(e) => setFilters(filters.map((x, j) => j === i ? { ...x, field: e.target.value } : x))} displayEmpty>
                          <MenuItem value="" disabled>Field</MenuItem>{COLUMNS.map(([id, l]) => <MenuItem key={id} value={id}>{l}</MenuItem>)}
                        </Select></FormControl>
                        <FormControl sx={{ minWidth: 110 }}><Select value={f.op} onChange={(e) => setFilters(filters.map((x, j) => j === i ? { ...x, op: e.target.value } : x))}>
                          {OPS.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
                        </Select></FormControl>
                        <TextField value={f.value} onChange={(e) => setFilters(filters.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} placeholder="Value" />
                        <IconButton aria-label={`Remove filter ${i + 1}`} onClick={() => setFilters(filters.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
                      </Stack>
                    ))}
                    <Box><Button size="small" startIcon={<AddIcon />} onClick={() => setFilters([...filters, { field: "severity", op: "=", value: "" }])}>Add filter</Button></Box>
                  </Stack>
                </Box>
                <Stack direction="row" spacing={2}>
                  <FormControl sx={{ minWidth: 180 }}>
                    <InputLabel id="sort-l">Sort By</InputLabel>
                    <Select labelId="sort-l" label="Sort By" value={sortBy} onChange={(e) => setSortBy(e.target.value)} inputProps={{ "aria-label": "Sort By" }}>
                      {COLUMNS.map(([id, l]) => <MenuItem key={id} value={id}>{l}</MenuItem>)}
                    </Select>
                  </FormControl>
                  <TextField label="Limit" type="number" value={limit} onChange={(e) => setLimit(e.target.value)} sx={{ width: 140 }} inputProps={{ "aria-label": "Limit" }} />
                </Stack>
              </>
            ) : (
              <TextField label="SQL" value={sql} onChange={(e) => setSql(e.target.value)} multiline minRows={3} fullWidth inputProps={{ "aria-label": "SQL" }}
                helperText={sqlResult.error || "SELECT col, col FROM `bucket` [WHERE col = \"value\"] [ORDER BY col] [LIMIT n]"} />
            )}
          </Stack>
        </Section>

        <Section title="Results">
          <ErrorAlert error={entries.error} title="Failed to load log entries" />
          <Table size="small">
            <TableHead><TableRow>{shownCols.map((c) => <TableCell key={c}>{COLUMNS.find(([id]) => id === c)?.[1] || c}</TableCell>)}</TableRow></TableHead>
            <TableBody>
              {shownRows.map((en, i) => (
                <TableRow key={en.insertId || i}>{shownCols.map((c) => <TableCell key={c}>{c === "timestamp" ? fmtDate(value(en, c)) : String(value(en, c))}</TableCell>)}</TableRow>
              ))}
              {!shownRows.length && <TableRow><TableCell colSpan={shownCols.length || 1}><Typography variant="body2" color="text.secondary">No rows to display</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Section>
      </Stack>
    </>
  );
}

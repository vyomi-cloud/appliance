/* Small MUI helpers shared by the Studio tabs. */
import { Box, Chip, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";

export const Card = ({ title, description, actions, children, ...p }) => (
  <Paper variant="outlined" sx={{ p: 2 }} {...p}>
    <Stack direction="row" spacing={1} alignItems="flex-start" sx={{ mb: 1 }}>
      <Box sx={{ flex: 1 }}><Typography variant="subtitle1">{title}</Typography>{description && <Typography variant="caption" color="text.secondary">{description}</Typography>}</Box>{actions}
    </Stack>
    {children}
  </Paper>
);
/** columns: [{id, header, cell(row), width?}] */
export function Tbl({ columns, rows, empty = "No items.", rowKey = (_, i) => i, ...p }) {
  return (
    <Box sx={{ overflowX: "auto" }} {...p}>
      <Table size="small">
        <TableHead><TableRow>{columns.map((c) => <TableCell key={c.id} sx={{ fontWeight: 600, width: c.width, whiteSpace: "nowrap" }}>{c.header}</TableCell>)}</TableRow></TableHead>
        <TableBody>
          {rows.length === 0 ? <TableRow><TableCell colSpan={columns.length}><Typography variant="body2" color="text.secondary">{empty}</Typography></TableCell></TableRow>
            : rows.map((r, i) => <TableRow key={rowKey(r, i)} hover>{columns.map((c) => <TableCell key={c.id} sx={{ verticalAlign: "top" }}>{c.cell(r, i)}</TableCell>)}</TableRow>)}
        </TableBody>
      </Table>
    </Box>
  );
}
/** Horizontal bars for {label: count}. */
export function Bars({ data, color = "#1a73e8", unit = "" }) {
  const e = Object.entries(data), mx = Math.max(1, ...e.map(([, v]) => v));
  return <Box>{e.map(([k, v]) => <Stack key={k} direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}><Typography variant="caption" sx={{ width: 190, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={k}>{k}</Typography>
    <Box sx={{ flex: 1, bgcolor: "action.hover", height: 10, borderRadius: 5 }}><Box sx={{ width: `${(v / mx) * 100}%`, bgcolor: color, height: 10, borderRadius: 5 }} /></Box><Typography variant="caption" sx={{ width: 56 }}>{v}{unit}</Typography></Stack>)}</Box>;
}
export const Tile = ({ label, value, id }) => <Box sx={{ minWidth: 120 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h5" data-testid={id}>{value}</Typography></Box>;
export const Status = ({ ok, children }) => <Chip size="small" color={ok ? "success" : "error"} variant="outlined" label={children} />;
export const SevChip = ({ s }) => <Chip size="small" color={s === "error" ? "error" : s === "warning" ? "warning" : "info"} variant="outlined" label={s} />;
export const pct = (v) => (v * 100).toFixed(0) + "%";
export const n = (v, d = 3) => (v === null || v === undefined ? "-" : Number(v).toFixed(d));

/* The console's resource list: filter bar, sortable columns, column display options,
 * row selection, pagination, loading / empty / error states. Every list page is this. */
import { useMemo, useState } from "react";
import {
  Box, Button, Checkbox, IconButton, InputAdornment, LinearProgress, Menu, MenuItem, ListItemIcon, ListItemText,
  Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TableSortLabel,
  TextField, Tooltip, Typography,
} from "@mui/material";
import FilterListIcon from "@mui/icons-material/esm/FilterList.js";
import ViewColumnIcon from "@mui/icons-material/esm/ViewColumn.js";
import CheckIcon from "@mui/icons-material/esm/Check.js";

export default function ResourceTable({
  resourceName,              // "buckets"
  items = [],
  columns,                   // [{id, header, cell(item), sortValue?(item) | sortField?, hidden?, width?}]
  rowKey = (it) => it.name,
  loading,
  error,
  onRetry,
  selectable = false,
  selected = [],             // array of keys
  onSelectedChange,
  toolbar,                   // node shown left of the filter (e.g. "Filter by name prefix only")
  filterPlaceholder,
  empty,                     // node
  pageSizes = [25, 50, 100],
  dense,
}) {
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState({ id: columns.find((c) => c.sortValue || c.sortField)?.id, dir: "asc" });
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(pageSizes[0]);
  const [hidden, setHidden] = useState(() => new Set(columns.filter((c) => c.hidden).map((c) => c.id)));
  const [colMenu, setColMenu] = useState(null);
  const cols = columns.filter((c) => !hidden.has(c.id));

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    let xs = f ? items.filter((it) => JSON.stringify(it).toLowerCase().includes(f)) : items;
    const c = columns.find((x) => x.id === sort.id);
    const key = c && (c.sortValue || (c.sortField && ((it) => it[c.sortField])));
    if (key) {
      xs = [...xs].sort((a, b) => String(key(a) ?? "").localeCompare(String(key(b) ?? ""), undefined, { numeric: true }));
      if (sort.dir === "desc") xs.reverse();
    }
    return xs;
  }, [items, filter, sort, columns]);

  const shown = rows.slice(page * size, page * size + size);
  const keys = shown.map(rowKey);
  const allSel = keys.length > 0 && keys.every((k) => selected.includes(k));
  const toggle = (k) => onSelectedChange?.(selected.includes(k) ? selected.filter((x) => x !== k) : [...selected, k]);

  return (
    <Paper variant="outlined" sx={{ borderRadius: 2, overflow: "hidden" }} aria-label={`${resourceName} table`}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 1.5, py: 1, borderBottom: 1, borderColor: "divider" }}>
        {toolbar}
        <TextField
          fullWidth variant="standard" value={filter} placeholder={filterPlaceholder || `Filter ${resourceName}`}
          onChange={(e) => { setFilter(e.target.value); setPage(0); }}
          inputProps={{ "aria-label": filterPlaceholder || `Filter ${resourceName}` }}
          InputProps={{ disableUnderline: true, startAdornment: <InputAdornment position="start"><FilterListIcon fontSize="small" /><Typography variant="body2" sx={{ ml: 1, fontWeight: 500 }}>Filter</Typography></InputAdornment> }}
        />
        <Tooltip title="Column display options">
          <IconButton size="small" aria-label="Column display options" onClick={(e) => setColMenu(e.currentTarget)}><ViewColumnIcon fontSize="small" /></IconButton>
        </Tooltip>
        <Menu anchorEl={colMenu} open={!!colMenu} onClose={() => setColMenu(null)}>
          {columns.map((c, i) => (
            <MenuItem key={c.id} disabled={i === 0} onClick={() => { const h = new Set(hidden); h.has(c.id) ? h.delete(c.id) : h.add(c.id); setHidden(h); }}>
              <ListItemIcon>{!hidden.has(c.id) && <CheckIcon fontSize="small" />}</ListItemIcon>
              <ListItemText>{c.header}</ListItemText>
            </MenuItem>
          ))}
        </Menu>
      </Stack>
      {loading && <LinearProgress sx={{ height: 2 }} />}
      <TableContainer>
        <Table size={dense ? "small" : "medium"} stickyHeader>
          <TableHead>
            <TableRow>
              {selectable && (
                <TableCell padding="checkbox">
                  <Checkbox size="small" checked={allSel} indeterminate={!allSel && keys.some((k) => selected.includes(k))}
                    inputProps={{ "aria-label": "Select all rows" }}
                    onChange={() => onSelectedChange?.(allSel ? selected.filter((k) => !keys.includes(k)) : [...new Set([...selected, ...keys])])} />
                </TableCell>
              )}
              {cols.map((c) => (
                <TableCell key={c.id} sx={{ width: c.width }} sortDirection={sort.id === c.id ? sort.dir : false}>
                  {c.sortValue || c.sortField ? (
                    <TableSortLabel active={sort.id === c.id} direction={sort.id === c.id ? sort.dir : "asc"}
                      onClick={() => setSort({ id: c.id, dir: sort.id === c.id && sort.dir === "asc" ? "desc" : "asc" })}>
                      {c.header}
                    </TableSortLabel>
                  ) : c.header}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {shown.map((it) => {
              const k = rowKey(it);
              const on = selected.includes(k);
              return (
                <TableRow key={k} hover selected={on}>
                  {selectable && (
                    <TableCell padding="checkbox">
                      <Checkbox size="small" checked={on} onChange={() => toggle(k)} inputProps={{ "aria-label": `Select ${k}` }} />
                    </TableCell>
                  )}
                  {cols.map((c) => <TableCell key={c.id} sx={{ whiteSpace: c.wrap ? "normal" : "nowrap" }}>{c.cell(it)}</TableCell>)}
                </TableRow>
              );
            })}
            {!loading && !shown.length && (
              <TableRow>
                <TableCell colSpan={cols.length + (selectable ? 1 : 0)} sx={{ py: 5, textAlign: "center", border: 0 }}>
                  {error ? (
                    <Stack spacing={1} alignItems="center">
                      <Typography color="error" variant="body2"><b>Failed to load {resourceName}</b>: {error.message}</Typography>
                      {onRetry && <Button size="small" onClick={onRetry}>Retry</Button>}
                    </Stack>
                  ) : filter ? (
                    <Typography variant="body2" color="text.secondary">No rows match your filter.</Typography>
                  ) : (empty || <Typography variant="body2" color="text.secondary">No rows to display</Typography>)}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
      <Box sx={{ borderTop: 1, borderColor: "divider" }}>
        <TablePagination component="div" count={rows.length} page={Math.min(page, Math.max(0, Math.ceil(rows.length / size) - 1))}
          onPageChange={(_, p) => setPage(p)} rowsPerPage={size} rowsPerPageOptions={pageSizes}
          onRowsPerPageChange={(e) => { setSize(+e.target.value); setPage(0); }} labelRowsPerPage="Rows per page:" />
      </Box>
    </Paper>
  );
}

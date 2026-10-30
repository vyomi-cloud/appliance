/* The portal's "browse" blade body: command bar (Create, Manage view, Refresh, Export to CSV,
 * Delete, …), filter pills, any-field filter, selectable + sortable grid, record count.
 * Every command here works client-side over the rows the service's native API returned, or
 * calls back into the service (create / delete). */
import { useMemo, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Input, Menu, MenuItem,
  MenuItemRadio, MenuList, MenuPopover, MenuTrigger, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell,
  TableRow, TableSelectionCell, ToolbarButton,
} from "@fluentui/react-components";
import {
  Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Filter20Regular, TableSettings20Regular,
} from "@fluentui/react-icons";
import { downloadCsv } from "./common.jsx";
import DeleteDialog from "./DeleteDialog.jsx";

export default function BrowseGrid({
  resourceName,              // "storage account" (singular, lower)
  items = [],
  columns,                   // [{key, label, render?(row), value?(row), csv?(row), hidden?}]
  rowKey = (r) => r.id,
  loading, error,
  onRefresh, onCreate,
  onDelete,                  // async (rows) => void
  pills = [],                // [{key, label, value(row)}] filter pills over the rows
  subscriptionLabel,         // shown in the always-present Subscription pill
  extraCommands,
  emptyAction,
  csvName = "export.csv",
}) {
  const [filter, setFilter] = useState("");
  const [pillValues, setPillValues] = useState({});
  const [sel, setSel] = useState(new Set());
  const [sort, setSort] = useState({ key: columns[0].key, dir: "ascending" });
  const [visible, setVisible] = useState(() => new Set(columns.filter((c) => !c.hidden).map((c) => c.key)));
  const [editCols, setEditCols] = useState(false);
  const [del, setDel] = useState(false);

  const val = (c, r) => (c.value ? c.value(r) : r[c.key]);
  const shownCols = columns.filter((c) => visible.has(c.key));

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    let xs = items.filter((r) => pills.every((p) => !pillValues[p.key] || p.value(r) === pillValues[p.key]));
    if (f) xs = xs.filter((r) => columns.some((c) => String(val(c, r) ?? "").toLowerCase().includes(f)));
    const c = columns.find((x) => x.key === sort.key);
    if (c) {
      xs = [...xs].sort((a, b) => String(val(c, a) ?? "").localeCompare(String(val(c, b) ?? ""), undefined, { numeric: true }));
      if (sort.dir === "descending") xs.reverse();
    }
    return xs;
  }, [items, filter, pillValues, sort, columns]);

  const selected = rows.filter((r) => sel.has(rowKey(r)));
  const allSel = rows.length > 0 && selected.length === rows.length;
  const toggle = (k) => setSel((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const headerSort = (key) => ({
    sortDirection: sort.key === key ? sort.dir : undefined,
    onClick: () => setSort((s) => ({ key, dir: s.key === key && s.dir === "ascending" ? "descending" : "ascending" })),
  });
  const plural = resourceName.endsWith("s") ? resourceName : `${resourceName}s`;

  return (
    <div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
        {onCreate && <ToolbarButton icon={<Add20Regular />} onClick={onCreate}>Create</ToolbarButton>}
        <Menu>
          <MenuTrigger disableButtonEnhancement>
            <ToolbarButton icon={<TableSettings20Regular />}>Manage view</ToolbarButton>
          </MenuTrigger>
          <MenuPopover>
            <MenuList>
              <MenuItem onClick={() => setEditCols(true)}>Edit columns</MenuItem>
              <MenuItem onClick={() => { setVisible(new Set(columns.filter((c) => !c.hidden).map((c) => c.key))); setSort({ key: columns[0].key, dir: "ascending" }); setFilter(""); setPillValues({}); }}>Reset to default</MenuItem>
            </MenuList>
          </MenuPopover>
        </Menu>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={onRefresh}>Refresh</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => downloadCsv(csvName, shownCols, rows)} disabled={!rows.length}>Export to CSV</ToolbarButton>
        {extraCommands}
        <span className="sep" />
        {onDelete && <ToolbarButton icon={<Delete20Regular />} disabled={!selected.length} onClick={() => setDel(true)}>Delete</ToolbarButton>}
      </div>

      <div className="vy-filters">
        <Input size="small" style={{ width: 260 }} contentBefore={<Filter20Regular />} placeholder="Filter for any field..." value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Filter for any field" />
        {subscriptionLabel && <span className="vy-pill vy-pill-static" title="Vyomi simulates one subscription">Subscription equals <b>{subscriptionLabel}</b></span>}
        {pills.map((p) => {
          const opts = [...new Set(items.map(p.value).filter(Boolean))].sort();
          return (
            <Menu key={p.key} checkedValues={{ [p.key]: [pillValues[p.key] || "__all"] }}
              onCheckedValueChange={(_, d) => setPillValues((v) => ({ ...v, [p.key]: d.checkedItems[0] === "__all" ? undefined : d.checkedItems[0] }))}>
              <MenuTrigger disableButtonEnhancement>
                <Button size="small" className="vy-pill">{p.label} equals <b>{pillValues[p.key] || "all"}</b></Button>
              </MenuTrigger>
              <MenuPopover>
                <MenuList>
                  <MenuItemRadio name={p.key} value="__all">All</MenuItemRadio>
                  {opts.map((o) => <MenuItemRadio key={o} name={p.key} value={o}>{o}</MenuItemRadio>)}
                </MenuList>
              </MenuPopover>
            </Menu>
          );
        })}
      </div>

      <div className="vy-count">{loading ? "Loading..." : `Showing ${rows.length ? 1 : 0} to ${rows.length} of ${rows.length} records.`}</div>
      <Table className="vy-grid" size="small" sortable aria-label={plural}>
        <TableHeader>
          <TableRow>
            <TableSelectionCell checked={allSel ? true : selected.length ? "mixed" : false}
              onClick={() => setSel(allSel ? new Set() : new Set(rows.map(rowKey)))} checkboxIndicator={{ "aria-label": "Select all" }} />
            {shownCols.map((c) => <TableHeaderCell key={c.key} {...headerSort(c.key)}>{c.label}</TableHeaderCell>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => {
            const k = rowKey(r);
            return (
              <TableRow key={k} aria-selected={sel.has(k)}>
                <TableSelectionCell checked={sel.has(k)} onClick={() => toggle(k)} checkboxIndicator={{ "aria-label": `Select ${k}` }} />
                {shownCols.map((c) => <TableCell key={c.key}>{c.render ? c.render(r) : (val(c, r) ?? "--")}</TableCell>)}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {loading && <div style={{ padding: 24 }}><Spinner size="tiny" /></div>}
      {!loading && error && <div className="vy-empty"><h3>Failed to load {plural}</h3><div>{error.message}</div><Button style={{ marginTop: 12 }} onClick={onRefresh}>Retry</Button></div>}
      {!loading && !error && !items.length && (
        <div className="vy-empty">
          <h3>No {plural} to display</h3>
          <div>Create a {resourceName} to get started, or try changing your filters.</div>
          {emptyAction && <div style={{ marginTop: 12 }}>{emptyAction}</div>}
        </div>
      )}

      <Dialog open={editCols} onOpenChange={(_, d) => setEditCols(d.open)}>
        <DialogSurface aria-label="Edit columns">
          <DialogBody>
            <DialogTitle>Edit columns</DialogTitle>
            <DialogContent>
              {columns.map((c, i) => (
                <div key={c.key}><Checkbox label={c.label} disabled={i === 0} checked={visible.has(c.key)}
                  onChange={(_, d) => setVisible((v) => { const n = new Set(v); d.checked ? n.add(c.key) : n.delete(c.key); return n; })} /></div>
              ))}
            </DialogContent>
            <DialogActions><Button appearance="primary" onClick={() => setEditCols(false)}>Save</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {onDelete && (
        <DeleteDialog open={del} onClose={() => setDel(false)} resourceType={resourceName}
          names={selected.map((r) => r.name)} confirmText={selected.length > 1 ? "delete" : undefined}
          onConfirm={async () => { await onDelete(selected); setSel(new Set()); }} />
      )}
    </div>
  );
}

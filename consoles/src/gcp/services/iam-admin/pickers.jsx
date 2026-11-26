/* Real-console-style IAM pickers for the GCP lens, fed from the verbatim catalog (catalog.js):
 *   RolePicker, PrincipalPicker, ConditionPanel (builder + CEL editor), PermissionTable, AddPermissionsDialog,
 *   PermissionAutocomplete, ResourceAutocomplete. */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Autocomplete, Box, Button, ButtonGroup, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, InputAdornment, ListSubheader,
  Menu, MenuItem, Popover, Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/esm/Search.js";
import CloseIcon from "@mui/icons-material/esm/Close.js";
import FilterListIcon from "@mui/icons-material/esm/FilterList.js";
import ViewColumnIcon from "@mui/icons-material/esm/ViewColumn.js";
import ChevronLeftIcon from "@mui/icons-material/esm/ChevronLeft.js";
import ChevronRightIcon from "@mui/icons-material/esm/ChevronRight.js";
import ArrowDropDownIcon from "@mui/icons-material/esm/ArrowDropDown.js";
import ArrowUpwardIcon from "@mui/icons-material/esm/ArrowUpward.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { filterPermissions, searchRoles } from "./catalog.js";
import { atom, celToRows, COND_TYPES, NAME_OPS, rowsToCel, SET_OPS, validateCel } from "./cel.js";

const TINT = "#f0f4f9"; // the real console's popup/dialog surface tint

// ── Role picker ──────────────────────────────────────────────────────────────────────────
export function RolePicker({ value, onChange, roles, usedRoles = [], loading, label = "Select a role" }) {
  const [anchor, setAnchor] = useState(null);
  const [q, setQ] = useState("");
  const [chip, setChip] = useState("all");
  const byId = useMemo(() => new Map(roles.map((r) => [r.id, r])), [roles]);
  const cur = byId.get(value);
  const products = useMemo(() => {
    const n = new Map(); for (const r of roles) if (r.product !== "basic" && r.product !== "custom") n.set(r.product, (n.get(r.product) || 0) + 1);
    return [...n.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([p]) => p);
  }, [roles]);
  let list = roles;
  if (chip === "used") list = roles.filter((r) => usedRoles.includes(r.id));
  else if (chip !== "all") list = roles.filter((r) => r.product === chip);
  const searching = q.trim().length > 0;
  const shown = searching ? searchRoles(list, q) : list;
  const CAP = 80;
  const pick = (r) => { onChange(r.id); setAnchor(null); setQ(""); };
  const item = (r) => (
    <MenuItem key={r.id} onClick={() => pick(r)} selected={r.id === value} data-role-id={r.id} sx={{ display: "block", whiteSpace: "normal", py: 1.25, px: 3 }}>
      <Typography variant="body2" sx={{ fontSize: 15 }}>{r.title}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ fontSize: 13, lineHeight: "18px" }}>{r.desc || r.id}</Typography>
    </MenuItem>
  );
  const groups = searching ? null : [
    ["Currently used", shown.filter((r) => usedRoles.includes(r.id))],
    ["Basic", shown.filter((r) => r.product === "basic")],
    ["All roles", shown.filter((r) => r.product !== "basic")],
  ].filter(([, rs]) => rs.length);
  return (
    <>
      <Box role="button" tabIndex={0} aria-label={label} aria-haspopup="listbox" onClick={(e) => setAnchor(e.currentTarget)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setAnchor(e.currentTarget)}
        sx={{ display: "flex", alignItems: "center", border: 1, borderColor: anchor ? "primary.main" : "#747775", borderRadius: 1, px: 1.5, height: 40, cursor: "pointer", minWidth: 260, bgcolor: "background.paper" }}>
        <Typography variant="body2" sx={{ flex: 1, color: cur ? "text.primary" : "text.secondary" }}>{cur ? cur.title : (value || label)}</Typography>
        <ArrowDropDownIcon />
      </Box>
      <Popover open={!!anchor} anchorEl={anchor} onClose={() => setAnchor(null)} slotProps={{ paper: { sx: { width: 560, maxWidth: "92vw", bgcolor: TINT, borderRadius: 3, mt: -0.5 }, "data-testid": "role-popup" } }}
        anchorOrigin={{ vertical: "top", horizontal: "left" }} transformOrigin={{ vertical: "top", horizontal: "left" }} sx={{ zIndex: 1500 }}>
        <TextField autoFocus fullWidth placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} inputProps={{ "aria-label": "Search roles" }}
          sx={{ "& fieldset": { border: 2, borderColor: "primary.main", borderRadius: 1 }, "& .MuiInputBase-root": { bgcolor: "#dde3ea", height: 52 } }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon /><Typography variant="body2" sx={{ ml: 1 }}>Search</Typography></InputAdornment>,
            endAdornment: q ? <IconButton size="small" aria-label="Clear search" onClick={() => setQ("")}><CloseIcon /></IconButton> : null }} />
        <Stack direction="row" spacing={0.75} sx={{ px: 2, py: 1, flexWrap: "wrap", rowGap: 0.75 }} aria-label="Role filters">
          {[["all", "All"], ["used", "Currently used"], ["basic", "Basic"], ...products.map((p) => [p, p])].map(([id, l]) => (
            <Chip key={id} size="small" label={l} clickable color={chip === id ? "primary" : "default"} variant={chip === id ? "filled" : "outlined"} onClick={() => setChip(id)} />))}
        </Stack>
        <Box sx={{ maxHeight: 340, overflowY: "auto" }} role="listbox" aria-label="Roles">
          {loading && <Typography variant="body2" sx={{ p: 3 }}>Loading roles…</Typography>}
          {!loading && searching && <ListSubheader sx={{ bgcolor: TINT, lineHeight: "36px", fontSize: 15, color: "text.primary", px: 3 }}>Top results</ListSubheader>}
          {!loading && shown.length === 0 && <Typography variant="body2" sx={{ p: 3 }} color="text.secondary">No roles match “{q}”.</Typography>}
          {searching ? shown.slice(0, CAP).map(item) : groups.map(([g, rs]) => (
            <Box key={g}><ListSubheader sx={{ bgcolor: TINT, lineHeight: "36px", fontSize: 15, color: "text.primary", px: 3 }}>{g}</ListSubheader>{rs.slice(0, CAP).map(item)}</Box>))}
          {shown.length > CAP && <Typography variant="caption" color="text.secondary" sx={{ px: 3, py: 1, display: "block" }}>{shown.length - CAP} more — keep typing to narrow the list.</Typography>}
        </Box>
        <Box sx={{ p: 2 }}><Button href="#/iam-admin/roles" target="_blank" sx={{ bgcolor: "#d3e3fd", borderRadius: 5, "&:hover": { bgcolor: "#c2d7f7" } }}>Manage Roles</Button></Box>
      </Popover>
    </>
  );
}

// ── Principal picker ─────────────────────────────────────────────────────────────────────
const MEMBER_RE = /^(user|serviceAccount|group|domain|principal|principalSet):/;
export function normalizeMember(s) {
  s = String(s || "").trim();
  if (!s) return "";
  if (s === "allUsers" || s === "allAuthenticatedUsers" || MEMBER_RE.test(s)) return s;
  if (/@[\w.-]*gserviceaccount\.com$/i.test(s)) return `serviceAccount:${s}`;   // a typed service-account email is a serviceAccount member, never a user
  return s.includes("@") ? `user:${s}` : /\./.test(s) ? `domain:${s}` : `user:${s}`;
}
export function PrincipalPicker({ value, onChange, options, label = "New principals" }) {
  const opts = useMemo(() => [...new Set([...options.map((o) => o.member), "allUsers", "allAuthenticatedUsers"])], [options]);
  const meta = useMemo(() => new Map(options.map((o) => [o.member, o])), [options]);
  return (
    <Autocomplete multiple freeSolo autoHighlight options={opts} value={value} filterSelectedOptions
      onChange={(_, v) => onChange([...new Set(v.map(normalizeMember).filter(Boolean))])}
      groupBy={(m) => meta.get(m)?.group || "Other"}
      getOptionLabel={(m) => (typeof m === "string" ? m : "")}
      renderOption={(props, m) => <li {...props} key={m}><Box><Typography variant="body2">{meta.get(m)?.name || m}</Typography><Typography variant="caption" color="text.secondary">{m}</Typography></Box></li>}
      renderInput={(p) => <TextField {...p} label={label} placeholder="Search or type an email, group, domain or service account" inputProps={{ ...p.inputProps, "aria-label": label }}
        helperText="Pick from this project's users, service accounts and groups, or type a new email / domain." />} />
  );
}

// ── Condition panel ──────────────────────────────────────────────────────────────────────
export const RESOURCE_TYPES = ["storage.googleapis.com/Bucket", "storage.googleapis.com/Object", "compute.googleapis.com/Instance", "compute.googleapis.com/Disk",
  "pubsub.googleapis.com/Topic", "pubsub.googleapis.com/Subscription", "bigquery.googleapis.com/Dataset", "bigquery.googleapis.com/Table", "cloudkms.googleapis.com/CryptoKey",
  "secretmanager.googleapis.com/Secret", "cloudresourcemanager.googleapis.com/Project", "iam.googleapis.com/ServiceAccount"];
const FQDN = { resourcemanager: "cloudresourcemanager", cloudsql: "sqladmin", firebaseauth: "identitytoolkit" };
export const resourceServices = (services) => [...new Set(services.map((s) => `${FQDN[s] || s}.googleapis.com`))];
const kindLabel = (k) => COND_TYPES.flatMap(([, xs]) => xs).find(([id]) => id === k)?.[1] || "";
const newRow = () => ({ kind: "", op: "eq", value: "" });

export function ConditionPanel({ initial, onSave, onCancel, serviceNames = [] }) {
  const [title, setTitle] = useState(initial?.title || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [tab, setTab] = useState("builder");
  const [rows, setRows] = useState(() => (initial?.expression ? celToRows(initial.expression) : [newRow()]) || []);
  const [expr, setExpr] = useState(initial?.expression || "");
  const [builderOk, setBuilderOk] = useState(() => !initial?.expression || celToRows(initial.expression) !== null);
  const [addMenu, setAddMenu] = useState(null);
  const filled = rows.filter((r) => r.kind);
  const check = validateCel(expr);
  const setRowsSync = (next) => { setRows(next); setBuilderOk(true); setExpr(rowsToCel(next)); };
  const upd = (i, patch) => setRowsSync(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const onExpr = (v) => { setExpr(v); const r = celToRows(v); if (r) { setRows(r.length ? r : [newRow()]); setBuilderOk(true); } else setBuilderOk(false); };
  const svcs = resourceServices(serviceNames);
  const ok = title.trim() && expr.trim() && check.ok;
  return (
    <Box role="dialog" aria-label="Add condition" sx={{ position: "fixed", top: 0, right: 0, bottom: 0, width: { xs: "100%", md: 760 }, bgcolor: "background.paper", boxShadow: 8, zIndex: 1400, p: 3, overflowY: "auto" }}>
      <Typography variant="h2" component="h2" sx={{ mb: 3 }}>Add condition</Typography>
      <Stack spacing={2.5}>
        <TextField required label="Title" value={title} onChange={(e) => setTitle(e.target.value)} fullWidth inputProps={{ "aria-label": "Condition title" }} />
        <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} multiline minRows={2} fullWidth inputProps={{ "aria-label": "Condition description" }} />
        <Tabs value={tab} onChange={(_, t) => setTab(t)} aria-label="Condition mode"><Tab value="builder" label="Condition builder" /><Tab value="editor" label="Condition editor" /></Tabs>
        {tab === "builder" && (
          <Stack spacing={1.5}>
            {!builderOk && <Typography variant="body2" color="warning.main" role="status">This expression uses CEL the builder cannot express. Edit it in the Condition editor tab.</Typography>}
            {builderOk && rows.map((r, i) => (
              <Box key={i} data-testid="cond-row">
                {i > 0 && <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>{r.join === "or" ? "OR" : "AND"}</Typography>}
                <Stack direction="row" spacing={1.5} alignItems="flex-start" flexWrap="wrap" rowGap={1}>
                  <Select displayEmpty size="small" sx={{ minWidth: 220 }} value={r.kind} inputProps={{ "aria-label": `Condition type ${i + 1}` }}
                    renderValue={(v) => v ? `${COND_TYPES.find(([, xs]) => xs.some(([id]) => id === v))[0]}: ${kindLabel(v)}` : <span style={{ opacity: 0.7 }}>Condition type {i + 1}</span>}
                    onChange={(e) => upd(i, { kind: e.target.value, op: "eq", value: "", start: "", end: "" })}>
                    {COND_TYPES.flatMap(([g, xs]) => [<ListSubheader key={g}>{g}</ListSubheader>, ...xs.map(([id, l]) => <MenuItem key={id} value={id}>{l}</MenuItem>)])}
                  </Select>
                  {(r.kind === "type" || r.kind === "service" || r.kind === "name") && (
                    <>
                      <Select size="small" value={r.op} onChange={(e) => upd(i, { op: e.target.value })} inputProps={{ "aria-label": "Operator" }}>
                        {(r.kind === "name" ? NAME_OPS : SET_OPS).map(([id, l]) => <MenuItem key={id} value={id}>{l}</MenuItem>)}
                      </Select>
                      <Autocomplete freeSolo size="small" sx={{ minWidth: 300 }} options={r.kind === "type" ? RESOURCE_TYPES : r.kind === "service" ? svcs : []} inputValue={r.value}
                        onInputChange={(_, v) => upd(i, { value: v })} renderInput={(p) => <TextField {...p} placeholder={r.kind === "name" ? "projects/_/buckets/my-bucket" : r.kind === "type" ? "storage.googleapis.com/Bucket" : "storage.googleapis.com"} inputProps={{ ...p.inputProps, "aria-label": `Resource ${r.kind} value` }} />} />
                    </>)}
                  {r.kind === "expiry" && <TextField size="small" type="datetime-local" label="Expires on" InputLabelProps={{ shrink: true }} value={r.end ? r.end.slice(0, 16) : ""} onChange={(e) => upd(i, { end: e.target.value ? new Date(e.target.value).toISOString() : "" })} inputProps={{ "aria-label": "Expiry date and time" }} />}
                  {r.kind === "schedule" && (<>
                    <TextField size="small" type="datetime-local" label="Start" InputLabelProps={{ shrink: true }} value={r.start ? r.start.slice(0, 16) : ""} onChange={(e) => upd(i, { start: e.target.value ? new Date(e.target.value).toISOString() : "" })} inputProps={{ "aria-label": "Schedule start" }} />
                    <TextField size="small" type="datetime-local" label="End" InputLabelProps={{ shrink: true }} value={r.end ? r.end.slice(0, 16) : ""} onChange={(e) => upd(i, { end: e.target.value ? new Date(e.target.value).toISOString() : "" })} inputProps={{ "aria-label": "Schedule end" }} /></>)}
                  <IconButton aria-label={`Remove condition ${i + 1}`} onClick={() => setRowsSync(rows.length > 1 ? rows.filter((_, j) => j !== i) : [newRow()])}><CloseIcon /></IconButton>
                </Stack>
              </Box>))}
            {builderOk && (
              <Box>
                <ButtonGroup variant="outlined" sx={{ "& .MuiButton-root": { borderRadius: 5 } }}>
                  <Button startIcon={<AddIcon />} onClick={() => setRows([...rows, { ...newRow(), join: "and" }])}>Add another condition</Button>
                  <Button size="small" aria-label="Choose how to join" onClick={(e) => setAddMenu(e.currentTarget)}><ArrowDropDownIcon /></Button>
                </ButtonGroup>
                <Menu open={!!addMenu} anchorEl={addMenu} onClose={() => setAddMenu(null)} sx={{ zIndex: 1500 }}>
                  <MenuItem onClick={() => { setRows([...rows, { ...newRow(), join: "and" }]); setAddMenu(null); }}>Add with AND</MenuItem>
                  <MenuItem onClick={() => { setRows([...rows, { ...newRow(), join: "or" }]); setAddMenu(null); }}>Add with OR</MenuItem>
                </Menu>
              </Box>)}
          </Stack>)}
        {tab === "editor" && (
          <TextField multiline minRows={6} fullWidth label="CEL expression" value={expr} onChange={(e) => onExpr(e.target.value)} spellCheck={false}
            inputProps={{ "aria-label": "CEL expression", style: { fontFamily: "monospace", fontSize: 13 } }} />)}
        <Box>
          <Typography variant="caption" color="text.secondary">Expression{filled.length || expr ? "" : " (build a condition above)"}</Typography>
          <Box component="pre" data-testid="cel-preview" sx={{ m: 0, p: 1.5, bgcolor: "#f0f4f9", borderRadius: 1, fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{expr || " "}</Box>
          {expr && !check.ok && <Typography variant="body2" color="error" role="alert" data-testid="cel-error">{check.error}</Typography>}
          {expr && check.ok && <Typography variant="body2" color="success.main" data-testid="cel-ok">Valid CEL (supported by the Vyomi IAM engine).</Typography>}
        </Box>
      </Stack>
      <Stack direction="row" spacing={1} sx={{ mt: 4 }}>
        <Button variant="contained" disabled={!ok} onClick={() => onSave({ title: title.trim(), description: description.trim(), expression: expr.trim() })}>Save</Button>
        <Button variant="outlined" onClick={onCancel}>Cancel</Button>
      </Stack>
    </Box>
  );
}

// ── Permission table (Add permissions dialog + role details) ─────────────────────────────
export function PermissionTable({ all, roleSet, selected, onSelectedChange, pageSize = 10, disabledNames }) {
  const [text, setText] = useState("");
  const [page, setPage] = useState(0);
  const [asc, setAsc] = useState(true);
  const [showStatus, setShowStatus] = useState(true);
  const [colMenu, setColMenu] = useState(null);
  const rows = useMemo(() => { const f = filterPermissions(all, text, roleSet); return asc ? f : [...f].reverse(); }, [all, text, roleSet, asc]);
  useEffect(() => setPage(0), [text, roleSet, asc]);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const cur = rows.slice(page * pageSize, page * pageSize + pageSize);
  const selectable = cur.filter((r) => !disabledNames?.has(r.name));
  const allOn = selectable.length > 0 && selectable.every((r) => selected.has(r.name));
  const toggle = (n) => { const s = new Set(selected); s.has(n) ? s.delete(n) : s.add(n); onSelectedChange(s); };
  const togglePage = () => { const s = new Set(selected); selectable.forEach((r) => (allOn ? s.delete(r.name) : s.add(r.name))); onSelectedChange(s); };
  const cell = { borderBottom: "1px solid #e1e3e1", py: 0.5, fontSize: 14 };
  return (
    <Box data-testid="perm-table" sx={{ bgcolor: "background.paper" }}>
      <Stack direction="row" alignItems="center" sx={{ borderBottom: "1px solid #e1e3e1", px: 1.5, height: 48 }}>
        <FilterListIcon fontSize="small" /><Typography variant="body2" sx={{ mx: 1, fontWeight: 500 }}>Filter</Typography>
        <TextField variant="standard" fullWidth placeholder="Enter property name or value" value={text} onChange={(e) => setText(e.target.value)} InputProps={{ disableUnderline: true }} inputProps={{ "aria-label": "Filter permissions" }} />
        <IconButton size="small" aria-label="Column display options" onClick={(e) => setColMenu(e.currentTarget)}><ViewColumnIcon /></IconButton>
        <Menu open={!!colMenu} anchorEl={colMenu} onClose={() => setColMenu(null)} sx={{ zIndex: 1600 }}>
          <MenuItem disabled><Checkbox checked size="small" />Permission</MenuItem>
          <MenuItem onClick={() => setShowStatus(!showStatus)}><Checkbox checked={showStatus} size="small" />Status</MenuItem>
        </Menu>
      </Stack>
      <Box component="table" sx={{ width: "100%", borderCollapse: "collapse" }} aria-label="Permissions">
        <thead><tr style={{ background: "#e9eef6" }}>
          <Box component="th" sx={{ ...cell, width: 48, pl: 1.5 }}><Checkbox size="small" checked={allOn} indeterminate={!allOn && selectable.some((r) => selected.has(r.name))} onChange={togglePage} inputProps={{ "aria-label": "Select all on page" }} /></Box>
          <Box component="th" sx={{ ...cell, textAlign: "left", fontWeight: 500, cursor: "pointer" }} onClick={() => setAsc(!asc)}>Permission <ArrowUpwardIcon sx={{ fontSize: 16, verticalAlign: "middle", transform: asc ? "none" : "rotate(180deg)" }} /></Box>
          {showStatus && <Box component="th" sx={{ ...cell, textAlign: "left", fontWeight: 500 }}>Status</Box>}
        </tr></thead>
        <tbody>
          {cur.map((r) => (
            <tr key={r.name} data-perm={r.name}>
              <Box component="td" sx={{ ...cell, pl: 1.5 }}><Checkbox size="small" disabled={disabledNames?.has(r.name)} checked={selected.has(r.name) || !!disabledNames?.has(r.name)} onChange={() => toggle(r.name)} inputProps={{ "aria-label": `Select ${r.name}` }} /></Box>
              <Box component="td" sx={cell}>{r.name}</Box>
              {showStatus && <Box component="td" sx={cell}>{r.status}</Box>}
            </tr>))}
          {cur.length === 0 && <tr><Box component="td" colSpan={3} sx={{ ...cell, py: 2, color: "text.secondary" }}>No rows to display</Box></tr>}
        </tbody>
      </Box>
      <Stack direction="row" alignItems="center" justifyContent="flex-end" spacing={1} sx={{ px: 1.5, height: 48 }}>
        {selected.size > 0 && <Typography variant="body2" color="text.secondary" sx={{ mr: "auto" }} data-testid="perm-selected">{selected.size} selected</Typography>}
        <Typography variant="body2" data-testid="perm-range">{rows.length ? `${page * pageSize + 1} – ${Math.min(rows.length, (page + 1) * pageSize)} of ${rows.length}` : "0 of 0"}</Typography>
        <IconButton size="small" aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)}><ChevronLeftIcon /></IconButton>
        <IconButton size="small" aria-label="Next page" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}><ChevronRightIcon /></IconButton>
      </Stack>
    </Box>
  );
}

export function AddPermissionsDialog({ open, onClose, onAdd, catalog, existing = [] }) {
  const [roleId, setRoleId] = useState("");
  const [sel, setSel] = useState(new Set());
  const [anchor, setAnchor] = useState(false);
  const roleSet = useMemo(() => { const r = catalog.roles.find((x) => x.id === roleId); return r ? new Set(r.permissions) : null; }, [roleId, catalog]);
  const done = () => { setSel(new Set()); setRoleId(""); onClose(); };
  return (
    <Dialog open={open} onClose={done} maxWidth="md" fullWidth PaperProps={{ sx: { bgcolor: "#f8fafd", borderRadius: 4 } }}>
      <DialogTitle sx={{ fontSize: 22 }}>Add permissions</DialogTitle>
      <DialogContent>
        <Autocomplete sx={{ mt: 1, mb: 2 }} options={catalog.roles} value={catalog.roles.find((r) => r.id === roleId) || null} getOptionLabel={(r) => r.title}
          onChange={(_, v) => setRoleId(v?.id || "")} isOptionEqualToValue={(a, b) => a.id === b.id} filterOptions={(o, { inputValue }) => searchRoles(o, inputValue).slice(0, 100)}
          renderOption={(p, r) => <li {...p} key={r.id}><Box><Typography variant="body2">{r.title}</Typography><Typography variant="caption" color="text.secondary">{r.id}</Typography></Box></li>}
          renderInput={(p) => <TextField {...p} label="Filter permissions by role" inputProps={{ ...p.inputProps, "aria-label": "Filter permissions by role" }} />} />
        <PermissionTable all={catalog.permissions} roleSet={roleSet} selected={sel} onSelectedChange={setSel} disabledNames={new Set(existing)} />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button variant="outlined" onClick={done}>Cancel</Button>
        <Button variant="contained" disabled={!sel.size} onClick={() => { onAdd([...sel]); done(); }}>Add</Button>
      </DialogActions>
    </Dialog>
  );
}

// ── Effective access pickers ─────────────────────────────────────────────────────────────
export function PermissionAutocomplete({ value, onChange, permissions, label = "Permission" }) {
  return (
    <Autocomplete freeSolo autoHighlight options={permissions.map((p) => p.name)} value={value} inputValue={value} onInputChange={(_, v) => onChange(v)}
      filterOptions={(o, { inputValue }) => { const f = filterPermissions(permissions, inputValue); return f.slice(0, 50).map((p) => p.name); }}
      renderInput={(p) => <TextField {...p} required label={label} helperText="Search all catalog permissions, e.g. storage.objects.get or service:storage" inputProps={{ ...p.inputProps, "aria-label": label }} />} />
  );
}
export function ResourceAutocomplete({ value, onChange, options, label = "Resource" }) {
  return (
    <Autocomplete freeSolo autoHighlight options={options} value={value} inputValue={value} onInputChange={(_, v) => onChange(v)}
      renderInput={(p) => <TextField {...p} required label={label} helperText="Pick a project, service account or bucket from this space, or type a full resource name" inputProps={{ ...p.inputProps, "aria-label": label }} />} />
  );
}

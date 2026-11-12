/* A generic Vertex AI resource list (the console's tables): list / create / row actions / delete over the native
 * aiplatform REST wire. Every Vertex page is a few of these. */
import { useEffect, useState } from "react";
import { Alert, Button, Chip, IconButton, Menu, MenuItem, MenuItem as MI, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { useProject } from "../../project.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { Link } from "../../link.jsx";
import * as api from "./api.js";

const IN_FLIGHT = /_(PENDING|RUNNING|QUEUED|CANCELLING)$/;
const color = (s) => (/SUCCEEDED|ACTIVE|READY|RUNNING|COMPLETE|LIVE/.test(s) ? "success" : /FAILED/.test(s) ? "error" : /CANCEL|STOPPED/.test(s) ? "default" : "info");

export const StateChip = ({ s }) => (s ? <Chip size="small" color={color(s)} variant="outlined" label={api.stateText(s)} /> : "—");

/**
 * props: coll, title, singular, v2, cap (capability id), fields (create form), build(values) -> {body, idKey?, id?, loc?},
 *        columns (extra cells), actions [{label, when?(item), run(item, {notify, reload}) | dialog(item)}], href(item) -> detail link,
 *        parentColl/parentLabel (nested collections: pick a parent first), fixedParent(region) (metadata), poll (job lists),
 *        regionScoped (show a region selector and list only that region), nameOf, filter (client filter on items)
 */
export default function ResourceList(p) {
  const project = useProject();
  const notify = useNotify();
  const [region, setRegion] = useState("us-central1");
  const [parent, setParent] = useState("");
  const [creating, setCreating] = useState(false);
  const [del, setDel] = useState(null);
  const [menu, setMenu] = useState(null);
  const [dlg, setDlg] = useState(null);   // {action, item}
  const parents = useAsync(() => (p.parentColl ? api.list(p.parentColl, { v2: false }) : Promise.resolve([])), [project, p.parentColl]);
  useEffect(() => { if (p.parentColl && !parent && parents.data?.length) setParent(parents.data[0].name); }, [parents.data, parent, p.parentColl]);
  const parentName = p.fixedParent ? p.fixedParent(region, project) : parent;
  const scoped = p.regionScoped || p.fixedParent;
  const { data = [], loading, error, reload, refresh } = useAsync(
    () => ((p.parentColl && !parentName) ? Promise.resolve([]) : api.list(p.coll, { v2: p.v2, parent: parentName || undefined, loc: scoped && !parentName ? region : "-", query: p.query })),
    [project, p.coll, parentName, region]);
  const items = (p.filter ? data.filter(p.filter) : data);
  const pending = p.poll && items.some((i) => IN_FLIGHT.test(i.state || ""));
  useEffect(() => { if (!pending) return undefined; const t = setInterval(refresh, 2000); return () => clearInterval(t); }, [pending, refresh]);

  const nameOf = p.nameOf || ((i) => i.displayName || api.shortId(i.name));
  const loc = (i) => api.pname(i.name).location;
  const done = (msg) => { notify.success(msg); reload(); };

  const createFields = p.fields && [
    ...(p.noRegion ? [] : [{ key: "region", label: p.v2 ? "Zone" : "Region", options: p.v2 ? api.ZONES : api.REGIONS, default: p.v2 ? "us-central1-a" : region }]),
    ...p.fields,
  ];
  const submit = async (v) => {
    const { body, idKey, id, upload } = p.build(v);
    if (upload) await api.uploadModel(body, v.region || region);
    else await api.create(p.coll, body, { loc: v.region || region, parent: parentName || undefined, v2: p.v2, idKey, id });
    notify.success(`Created ${p.singular} "${v.displayName || v.id || ""}"`);
  };

  const cols = [
    { id: "name", header: "Name", sortValue: (i) => nameOf(i), cell: (i) => (p.href ? <Link href={p.href(i)}>{nameOf(i)}</Link> : nameOf(i)) },
    { id: "id", header: "ID", cell: (i) => api.shortId(i.name), hidden: !!p.hideId },
    ...(p.columns || []),
    ...(p.noRegion ? [] : [{ id: "region", header: p.v2 ? "Zone" : "Region", sortValue: loc, cell: loc }]),
    { id: "created", header: "Created", sortValue: (i) => i.createTime || "", cell: (i) => api.when(i.createTime) },
    { id: "actions", header: "Actions", cell: (i) => (
      <IconButton size="small" aria-label={`Actions for ${nameOf(i)}`} onClick={(e) => setMenu({ anchor: e.currentTarget, item: i })}><MoreVertIcon fontSize="small" /></IconButton>) },
  ];
  const visible = (p.actions || []).filter((a) => !menu || !a.when || a.when(menu.item));

  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} alignItems="center" useFlexGap sx={{ flexWrap: "wrap" }}>
        {p.fields && <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreating(true)} disabled={p.parentColl && !parentName}>{p.createLabel || `Create ${p.singular}`}</Button>}
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        {scoped && !p.fixedParent && <TextField select size="small" label="Region" value={region} onChange={(e) => setRegion(e.target.value)} sx={{ minWidth: 170 }}>{api.REGIONS.map((r) => <MI key={r} value={r}>{r}</MI>)}</TextField>}
        {p.fixedParent && <TextField select size="small" label="Region" value={region} onChange={(e) => setRegion(e.target.value)} sx={{ minWidth: 170 }}>{api.REGIONS.map((r) => <MI key={r} value={r}>{r}</MI>)}</TextField>}
        {p.parentColl && (
          <TextField select size="small" label={p.parentLabel} value={parent} onChange={(e) => setParent(e.target.value)} sx={{ minWidth: 240 }}>
            {(parents.data || []).map((x) => <MI key={x.name} value={x.name}>{x.displayName || api.shortId(x.name)} ({loc(x)})</MI>)}
          </TextField>)}
        {p.cap && <CapabilityBadge id={p.cap} />}
      </Stack>
      {p.parentColl && !parents.loading && !parents.data?.length && <Alert severity="info">Create a {p.parentLabel.toLowerCase()} first.</Alert>}
      <ResourceTable
        resourceName={p.title} items={items} rowKey={(i) => i.name} loading={loading} error={error} onRetry={reload} filterPlaceholder="Filter" columns={cols}
        empty={<Stack spacing={1.5} alignItems="center"><Typography variant="body2" color="text.secondary">No {p.title.toLowerCase()} in this project</Typography>
          {p.fields && <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreating(true)} disabled={p.parentColl && !parentName}>{p.createLabel || `Create ${p.singular}`}</Button>}</Stack>}
      />
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => setMenu(null)}>
        {visible.map((a) => <MenuItem key={a.label} onClick={() => {
          const item = menu.item; setMenu(null);
          if (a.dialog) setDlg({ action: a, item });
          else a.run(item, { notify, reload }).then(() => reload()).catch((e) => notify.error(e));
        }}>{a.label}</MenuItem>)}
        <MenuItem onClick={() => { setDel(menu.item); setMenu(null); }}>Delete</MenuItem>
      </Menu>
      {createFields && <FormDialog open={creating} title={p.createLabel || `Create ${p.singular}`} fields={createFields} onClose={(ok) => { setCreating(false); if (ok) reload(); }} onSubmit={submit} />}
      {dlg && dlg.action.dialog({ item: dlg.item, onClose: (ok) => { setDlg(null); if (ok) reload(); }, notify })}
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title={`Delete ${p.singular}?`} confirmText={del ? nameOf(del) : ""} warning="This can't be undone."
        onConfirm={async () => { await api.del(del.name, p.v2); notify.success(`Deleted ${p.singular} "${nameOf(del)}"`); reload(); }}>
        <Typography variant="body2">{p.singular[0].toUpperCase() + p.singular.slice(1)} <b>{del ? nameOf(del) : ""}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </Stack>
  );
}

export function Tabbed({ tabs, query }) {
  const [tab, setTab] = useState(query?.tab && tabs.some((t) => t.id === query.tab) ? query.tab : tabs[0].id);
  const cur = tabs.find((t) => t.id === tab);
  return (
    <>
      <Stack direction="row" spacing={0.5} sx={{ borderBottom: 1, borderColor: "divider", mb: 2 }} role="tablist">
        {tabs.map((t) => <Button key={t.id} role="tab" aria-selected={t.id === tab} onClick={() => setTab(t.id)} sx={{ borderRadius: 0, borderBottom: 2, borderColor: t.id === tab ? "primary.main" : "transparent", color: t.id === tab ? "primary.main" : "text.secondary" }}>{t.label}</Button>)}
      </Stack>
      <div key={cur.id}>{cur.render()}</div>
    </>
  );
}

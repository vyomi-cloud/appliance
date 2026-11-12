/* Secret Manager — Secrets list: the console's two tabs. "Secrets" (global, automatic /
 * user-managed replication) and "Regional secrets" — a distinct resource
 * (projects/{p}/locations/{l}/secrets/...) scoped to one location picked on the tab,
 * with its own create flow (CreateRegionalSecretDialog, no replication policy to pick).
 * Both: filterable table, multi-select delete, a per-row action menu. */
import { useState } from "react";
import {
  Box, Button, Chip, FormControl, IconButton, InputLabel, Menu, MenuItem, Select, Stack, Tab, Tabs, Tooltip, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteDialog from "../../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../../kit/common.jsx";
import { Link, hashHref } from "../../../link.jsx";
import { useProject } from "../../../project.js";
import { CreateRegionalSecretDialog, EditSecretDialog } from "./Shared.jsx";
import * as api from "./api.js";

const secretHref = (name) => hashHref("security", "secret-manager", "secret", name);
const regionalHref = (location, name) => hashHref("security", "secret-manager", "regional", location, name);

export default function Secrets({ query = {} }) {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState(query.tab === "regional" ? "regional" : "secrets");
  const [location, setLocation] = useState(api.LOCATIONS.includes(query.location) ? query.location : api.LOCATIONS[0]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [edit, setEdit] = useState(null);
  const [create, setCreate] = useState(false);
  const [menu, setMenu] = useState(null);
  const regional = tab === "regional";
  const { data = [], loading, error, reload } = useAsync(
    () => (regional ? api.listSecrets(location) : api.listSecrets()), [project, regional, location]);

  const labels = (s) => {
    const ls = Object.entries(s.labels || {});
    if (!ls.length) return "—";
    return <Stack direction="row" spacing={0.5}>{ls.slice(0, 2).map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}{ls.length > 2 && <Tooltip title={ls.slice(2).map(([k, v]) => `${k}: ${v}`).join(", ")}><Chip size="small" label={`+${ls.length - 2}`} /></Tooltip>}</Stack>;
  };
  const rowHref = (s) => (regional ? regionalHref(location, api.shortName(s.name)) : secretHref(api.shortName(s.name)));

  return (
    <>
      <PageHeader title="Secret Manager" actions={<>
        <Button startIcon={<AddIcon />} href={regional ? undefined : hashHref("security", "secret-manager", "create")}
          onClick={regional ? () => setCreate(true) : undefined}>Create secret</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>}>
        <Tabs value={tab} onChange={(_, v) => { setTab(v); setSel([]); }} sx={{ borderBottom: 1, borderColor: "divider" }} aria-label="Secret Manager tabs">
          <Tab value="secrets" label="Secrets" />
          <Tab value="regional" label="Regional secrets" />
        </Tabs>
      </PageHeader>
      {regional && (
        <FormControl size="small" sx={{ mb: 2, minWidth: 220 }}>
          <InputLabel id="region-l">Region</InputLabel>
          <Select labelId="region-l" label="Region" value={location} onChange={(e) => { setLocation(e.target.value); setSel([]); }}>
            {api.LOCATIONS.map((l) => <MenuItem key={l} value={l}>{l}</MenuItem>)}
          </Select>
        </FormControl>
      )}
      <ResourceTable
        resourceName="secrets"
        items={data}
        rowKey={(s) => s.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortValue: (s) => api.shortName(s.name), cell: (s) => <Link href={rowHref(s)}>{api.shortName(s.name)}</Link> },
          { id: "location", header: "Location", sortValue: api.locationLabel, cell: api.locationLabel },
          { id: "encryption", header: "Encryption", sortValue: api.encryptionLabel, cell: api.encryptionLabel },
          { id: "labels", header: "Labels", cell: labels },
          { id: "created", header: "Created", sortField: "createTime", cell: (s) => fmtDate(s.createTime) },
          { id: "expiration", header: "Expiration", sortValue: (s) => s.expireTime || "", cell: (s) => (s.expireTime ? fmtDate(s.expireTime) : "Never") },
          { id: "actions", header: "Actions", cell: (s) => (
            <IconButton size="small" aria-label={`Actions for ${api.shortName(s.name)}`} onClick={(e) => setMenu({ anchor: e.currentTarget, secret: s })}>
              <MoreVertIcon fontSize="small" />
            </IconButton>
          ) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">{regional ? `There are no secrets in ${location}.` : "There are no secrets in this project."}</Typography>
            <Button variant="contained" startIcon={<AddIcon />}
              href={regional ? undefined : hashHref("security", "secret-manager", "create")}
              onClick={regional ? () => setCreate(true) : undefined}>Create secret</Button>
          </Stack>
        }
      />
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => setMenu(null)}>
        <MenuItem component="a" href={menu ? rowHref(menu.secret) : undefined} onClick={() => setMenu(null)}>View secret details</MenuItem>
        <MenuItem component="a" href={menu ? rowHref(menu.secret) + "?action=new-version" : undefined} onClick={() => setMenu(null)}>Add new version</MenuItem>
        <MenuItem onClick={() => { setEdit(menu.secret); setMenu(null); }}>Edit secret</MenuItem>
        <MenuItem onClick={() => { setSel([menu.secret.name]); setMenu(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      {edit && <EditSecretDialog secret={edit} location={regional ? location : undefined} onClose={() => setEdit(null)} onSaved={reload} notify={notify} />}
      {create && <CreateRegionalSecretDialog location={location} onClose={() => setCreate(false)} onCreated={reload} notify={notify} />}
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete secret?" : `Delete ${sel.length} secrets?`}
        confirmText={sel.length === 1 ? api.shortName(sel[0]) : "DELETE"}
        warning="All versions of the secret are deleted as well. This can't be undone."
        onConfirm={async () => {
          for (const name of sel) await api.deleteSecret(api.shortName(name), regional ? location : undefined);
          notify.success(sel.length === 1 ? `Deleted secret "${api.shortName(sel[0])}"` : `Deleted ${sel.length} secrets`);
          setSel([]);
          reload();
        }}
      >
        <Box><Typography variant="body2">{sel.length === 1 ? <>Secret <b>{api.shortName(sel[0])}</b> will be permanently deleted.</> : <>{sel.map(api.shortName).join(", ")} will be permanently deleted.</>}</Typography></Box>
      </DeleteDialog>
    </>
  );
}

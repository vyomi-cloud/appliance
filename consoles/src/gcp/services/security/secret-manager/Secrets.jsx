/* Secret Manager — Secrets list: the console's two tabs (global "Secrets", "Regional
 * secrets"), filterable table, multi-select delete and a per-row action menu. */
import { useState } from "react";
import { Box, Button, Chip, IconButton, Menu, MenuItem, Stack, Tab, Tabs, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteDialog from "../../../kit/DeleteDialog.jsx";
import { fmtDate, NotSimulatedContainer, PageHeader } from "../../../kit/common.jsx";
import { CapabilityContainer } from "../../../kit/Capability.jsx";
import { Link, hashHref } from "../../../link.jsx";
import { useProject } from "../../../project.js";
import { EditSecretDialog } from "./Shared.jsx";
import * as api from "./api.js";

const secretHref = (name) => hashHref("security", "secret-manager", "secret", name);

export default function Secrets() {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState("secrets");
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [edit, setEdit] = useState(null);
  const [menu, setMenu] = useState(null);
  const { data = [], loading, error, reload } = useAsync(api.listSecrets, [project]);

  const labels = (s) => {
    const ls = Object.entries(s.labels || {});
    if (!ls.length) return "—";
    return <Stack direction="row" spacing={0.5}>{ls.slice(0, 2).map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}{ls.length > 2 && <Tooltip title={ls.slice(2).map(([k, v]) => `${k}: ${v}`).join(", ")}><Chip size="small" label={`+${ls.length - 2}`} /></Tooltip>}</Stack>;
  };

  return (
    <>
      <PageHeader title="Secret Manager" actions={<>
        <Button startIcon={<AddIcon />} href={hashHref("security", "secret-manager", "create")}>Create secret</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ borderBottom: 1, borderColor: "divider" }} aria-label="Secret Manager tabs">
          <Tab value="secrets" label="Secrets" />
          <Tab value="regional" label="Regional secrets" />
        </Tabs>
      </PageHeader>
      {tab === "regional" ? (
        <CapabilityContainer id="gcp.secret-manager.regional-secrets" title="Regional secrets" />
      ) : (
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
            { id: "name", header: "Name", sortValue: (s) => api.shortName(s.name), cell: (s) => <Link href={secretHref(api.shortName(s.name))}>{api.shortName(s.name)}</Link> },
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
              <Typography variant="body2" color="text.secondary">There are no secrets in this project.</Typography>
              <Button variant="contained" startIcon={<AddIcon />} href={hashHref("security", "secret-manager", "create")}>Create secret</Button>
            </Stack>
          }
        />
      )}
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => setMenu(null)}>
        <MenuItem component="a" href={secretHref(api.shortName(menu?.secret?.name || ""))} onClick={() => setMenu(null)}>View secret details</MenuItem>
        <MenuItem component="a" href={secretHref(api.shortName(menu?.secret?.name || "")) + "?action=new-version"} onClick={() => setMenu(null)}>Add new version</MenuItem>
        <MenuItem onClick={() => { setEdit(menu.secret); setMenu(null); }}>Edit secret</MenuItem>
        <MenuItem onClick={() => { setSel([menu.secret.name]); setMenu(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      {edit && <EditSecretDialog secret={edit} onClose={() => setEdit(null)} onSaved={reload} notify={notify} />}
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete secret?" : `Delete ${sel.length} secrets?`}
        confirmText={sel.length === 1 ? api.shortName(sel[0]) : "DELETE"}
        warning="All versions of the secret are deleted as well. This can't be undone."
        onConfirm={async () => {
          for (const name of sel) await api.deleteSecret(api.shortName(name));
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

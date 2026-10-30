/* Users — instance-scoped user accounts (add / change password / delete). */
import { useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

export default function Users({ params }) {
  const name = params.name;
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listUsers(name), [name]);
  const [menu, setMenu] = useState(null);
  const [del, setDel] = useState(null);
  const [pwdFor, setPwdFor] = useState(null);
  const [pwd, setPwd] = useState("");

  return (
    <>
      <InstanceNav name={name} active="users" />
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="h2" component="h2" sx={{ flex: 1, fontSize: 20 }}>Users</Typography>
        <Button startIcon={<AddIcon />} href={`#/sql/instances/${encodeURIComponent(name)}/users/add`}>Add user account</Button>
      </Stack>
      <ResourceTable
        resourceName="users"
        items={data}
        rowKey={(u) => `${u.name}@${u.host}`}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter users"
        columns={[
          { id: "name", header: "User name", sortField: "name", cell: (u) => u.name },
          { id: "host", header: "Host name", sortField: "host", cell: (u) => u.host || "%" },
          { id: "auth", header: "Authentication", cell: (u) => u.type === "CLOUD_IAM_USER" ? "Cloud IAM" : "Built-in authentication" },
          { id: "pwd", header: "Password status", cell: () => "Set" },
          { id: "actions", header: "Actions", cell: (u) => <IconButton size="small" aria-label={`Actions for ${u.name}`} onClick={(e) => setMenu({ anchor: e.currentTarget, user: u })}><MoreVertIcon fontSize="small" /></IconButton> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No user accounts on this instance.</Typography>}
      />
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => setMenu(null)}>
        <MenuItem onClick={() => { setPwdFor(menu.user); setPwd(""); setMenu(null); }}>Change password</MenuItem>
        <MenuItem onClick={() => { setDel(menu.user); setMenu(null); }}>Delete</MenuItem>
      </Menu>
      <Dialog open={!!pwdFor} onClose={() => setPwdFor(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Change password for {pwdFor?.name}</DialogTitle>
        <DialogContent><TextField autoFocus fullWidth sx={{ mt: 1 }} type="password" label="New password" value={pwd} onChange={(e) => setPwd(e.target.value)} /></DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setPwdFor(null)}>Cancel</Button>
          <Button variant="contained" disabled={!pwd} onClick={async () => {
            try { await api.updateUser(name, pwdFor.name, pwdFor.host, { password: pwd }); notify.success(`Updated password for "${pwdFor.name}"`); setPwdFor(null); reload(); }
            catch (e) { notify.error(e); }
          }}>Save</Button>
        </DialogActions>
      </Dialog>
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title={`Delete user "${del?.name}"?`} confirmText={del?.name}
        onConfirm={async () => { await api.deleteUser(name, del.name, del.host); notify.success(`Deleted user "${del.name}"`); reload(); }}>
        <Box><Typography variant="body2">User <b>{del?.name}</b> will be permanently deleted.</Typography></Box>
      </DeleteDialog>
    </>
  );
}

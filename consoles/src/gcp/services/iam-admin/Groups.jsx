/* Groups (Cloud Identity) — real org-scoped group CRUD + membership management
 * (native Cloud Identity Groups v1 under the project's backing organization). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function Groups() {
  const notify = useNotify();
  const list = useAsync(() => api.listGroups(), []);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(null);
  const [members, setMembers] = useState(null);

  return (
    <>
      <PageHeader title="Groups" actions={
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create group</Button>} />
      <CapabilityContainer id="gcp.iam-admin.groups" title="Groups">
        <ErrorAlert error={list.error} title="Failed to load groups" />
        <ResourceTable resourceName="groups" items={list.data || []} rowKey={(g) => g.name} loading={list.loading} onRetry={list.reload}
          filterPlaceholder="Filter" empty="No groups yet"
          columns={[
            { id: "email", header: "Group email", sortField: "groupKey.id", cell: (g) => g.groupKey.id },
            { id: "name", header: "Name", cell: (g) => g.displayName || "—" },
            { id: "description", header: "Description", cell: (g) => g.description || "—" },
            {
              id: "actions", header: "", cell: (g) => (
                <Stack direction="row" spacing={1}>
                  <Button size="small" onClick={() => setMembers(g)}>Members</Button>
                  <Button size="small" color="error" onClick={() => setDel(g)}>Delete</Button>
                </Stack>
              ),
            },
          ]} />
      </CapabilityContainer>
      {create && <CreateGroupDialog onClose={() => setCreate(false)} onCreated={() => { notify.success("Created group"); list.reload(); }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title={`Delete ${del?.groupKey.id}?`} actionLabel="Delete"
        onConfirm={async () => { await api.deleteGroup(del.name); notify.success("Deleted group"); list.reload(); }} />
      {members && <MembersDialog group={members} onClose={() => setMembers(null)} />}
    </>
  );
}

function CreateGroupDialog({ onClose, onCreated }) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[^@]+@[^@]+\.[^@]+$/.test(email);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create group</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Group email" value={email} onChange={(e) => setEmail(e.target.value.trim())} helperText="e.g. eng-team@example.com" />
          <TextField label="Group name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createGroup(email, displayName || email.split("@")[0]); onCreated(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function MembersDialog({ group, onClose }) {
  const notify = useNotify();
  const list = useAsync(() => api.listGroupMemberships(group.name), [group.name]);
  const [member, setMember] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Members of {group.groupKey.id}</DialogTitle>
      <DialogContent>
        <ErrorAlert error={list.error} />
        <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
          <TextField fullWidth size="small" label="Add member" value={member} onChange={(e) => setMember(e.target.value.trim())}
            helperText="e.g. user:alice@example.com" />
          <Button disabled={!member || busy} onClick={async () => {
            setBusy(true);
            try { await api.addGroupMembership(group.name, member); setMember(""); list.reload(); }
            catch (e) { notify.error(e); } finally { setBusy(false); }
          }}>Add</Button>
        </Stack>
        <ResourceTable resourceName="members" items={list.data || []} rowKey={(m) => m.name} loading={list.loading}
          empty="No members yet"
          columns={[
            { id: "member", header: "Member", cell: (m) => m.preferredMemberKey.id },
            { id: "roles", header: "Roles", cell: (m) => (m.roles || []).map((r) => r.name).join(", ") },
            { id: "actions", header: "", cell: (m) => <Button size="small" color="error" onClick={async () => { await api.removeGroupMembership(m.name); list.reload(); }}>Remove</Button> },
          ]} />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

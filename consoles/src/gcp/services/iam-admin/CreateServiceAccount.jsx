/* Create service account — 3-step form (details, permissions, principals with access).
 * Permissions/principals steps grant project-level IAM roles right after creation, on the
 * same native wire the Allow tab uses. */
import { useState } from "react";
import { Box, Button, Divider, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import { getProject } from "../../project.js";
import * as api from "./api.js";

function Step({ n, title, children }) {
  return (
    <Box component="section" aria-label={title} sx={{ display: "grid", gridTemplateColumns: "32px 1fr", columnGap: 2, py: 2.5 }}>
      <Box sx={{ width: 28, height: 28, borderRadius: "50%", bgcolor: "primary.main", color: "primary.contrastText", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 500 }}>{n}</Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h3" component="h2" sx={{ mb: 2, lineHeight: "28px" }}>{title}</Typography>
        <Stack spacing={2.5}>{children}</Stack>
      </Box>
    </Box>
  );
}

const ROLE_CHOICES = Object.entries(api.PREDEFINED_ROLE_TITLES);

export default function CreateServiceAccount() {
  const notify = useNotify();
  const project = getProject();
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [description, setDescription] = useState("");
  const [role, setRole] = useState("");
  const [users, setUsers] = useState("");
  const [admins, setAdmins] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const idErr = idTouched && !/^[a-z][a-z0-9-]{5,29}$/.test(id) ? "6-30 characters: lowercase letters, numbers and hyphens." : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setIdTouched(true);
    if (!/^[a-z][a-z0-9-]{5,29}$/.test(id)) return;
    setBusy(true); setError(null);
    try {
      const sa = await api.createServiceAccount(id, { displayName: name, description });
      if (role) {
        const pol = await api.getIamPolicy();
        const bs = (pol.bindings || []).map((b) => ({ ...b, members: [...b.members] }));
        const hit = bs.find((b) => b.role === role);
        const member = `serviceAccount:${sa.email}`;
        if (hit) hit.members.push(member); else bs.push({ role, members: [member] });
        await api.setIamPolicy({ ...pol, bindings: bs });
      }
      const extra = [...users.split(",").map((m) => m.trim()).filter(Boolean).map((m) => ["roles/iam.serviceAccountUser", m]),
        ...admins.split(",").map((m) => m.trim()).filter(Boolean).map((m) => ["roles/iam.serviceAccountAdmin", m])];
      if (extra.length) {
        const resource = `projects/${project}/serviceAccounts/${sa.email}`;
        const cur = await api.getIamPolicy(resource).catch(() => ({ bindings: [] }));
        const bs2 = (cur.bindings || []).map((b) => ({ ...b, members: [...b.members] }));
        for (const [r, m] of extra) {
          const principal = /^(user|serviceAccount|group|domain):/.test(m) ? m : `user:${m}`;
          const hit = bs2.find((b) => b.role === r);
          if (hit) { if (!hit.members.includes(principal)) hit.members.push(principal); } else bs2.push({ role: r, members: [principal] });
        }
        await api.setIamPolicy({ ...cur, bindings: bs2 }, resource);
      }
      notify.success(`Created service account "${sa.email}"`);
      location.hash = hashHref("iam-admin", "serviceaccounts", "details", sa.email).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 760 }}>
      <PageHeader title="Create service account" back={<IconButton aria-label="Back" href="#/iam-admin/serviceaccounts"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create service account" />
      <Step n={1} title="Service account details">
        <TextField label="Service account name" value={name} onChange={(e) => setName(e.target.value)}
          helperText="Display name for this service account" />
        <TextField required label="Service account ID" value={id} onChange={(e) => setId(e.target.value.trim())} onBlur={() => setIdTouched(true)}
          error={!!idErr} helperText={idErr || `Email address: ${id || "<id>"}@${project}.iam.gserviceaccount.com`} />
        <TextField label="Service account description" multiline minRows={2} placeholder="Describe what this service account will do"
          value={description} onChange={(e) => setDescription(e.target.value)} />
      </Step>
      <Divider />
      <Step n={2} title="Permissions (optional)">
        <Typography variant="body2" color="text.secondary">Grant this service account access to the project so it can perform specific actions on project resources.</Typography>
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="csa-role-l">Select a role</InputLabel>
          <Select labelId="csa-role-l" label="Select a role" value={role} onChange={(e) => setRole(e.target.value)} inputProps={{ "aria-label": "Select a role" }}>
            <MenuItem value="">None</MenuItem>
            {ROLE_CHOICES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <Box><Button disabled startIcon={<AddIcon />}>Add another role</Button></Box>
      </Step>
      <Divider />
      <Step n={3} title="Principals with access (optional)">
        <Typography variant="body2" color="text.secondary">Grant users and groups permission to use and manage this service account.</Typography>
        <TextField label="Service account users role" value={users} onChange={(e) => setUsers(e.target.value)} helperText="Comma-separated principals, e.g. user:dev@example.com" />
        <TextField label="Service account admins role" value={admins} onChange={(e) => setAdmins(e.target.value)} helperText="Comma-separated principals" />
      </Step>
      <Divider />
      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Done"}</Button>
        <Button href="#/iam-admin/serviceaccounts">Cancel</Button>
      </Stack>
    </Box>
  );
}

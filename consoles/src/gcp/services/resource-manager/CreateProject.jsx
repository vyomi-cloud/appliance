/* New Project — a native Resource Manager v3 projects.create call; "Location" browses the
 * organization + folder hierarchy (LocationPicker) and sends it as the project's parent. */
import { useState } from "react";
import { Box, Button, IconButton, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { setProject } from "../../project.js";
import * as api from "./api.js";
import LocationPicker from "./LocationPicker.jsx";

export default function CreateProject() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [parent, setParent] = useState("");
  const [browse, setBrowse] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const slug = (name || "").toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+/, "").slice(0, 30);
  const effectiveId = idTouched ? id : slug;
  const idErr = api.validProjectId(effectiveId);

  const submit = async (ev) => {
    ev.preventDefault();
    setIdTouched(true);
    if (api.validProjectId(effectiveId)) return;
    setBusy(true); setError(null);
    try {
      await api.createProjectIn(effectiveId, name || effectiveId, parent || undefined);
      notify.success(`Created project "${effectiveId}"`);
      setProject(effectiveId);
      location.hash = "/resource-manager";
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 640 }}>
      <PageHeader title="New Project" back={<IconButton aria-label="Back" href="#/resource-manager"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create project" />
      <Typography variant="h3" component="h2" sx={{ mb: 2 }}>Project details</Typography>
      <Stack spacing={2.5}>
        <TextField label="Project name" value={name} onChange={(e) => setName(e.target.value)}
          helperText="This is the name of your project, and it will help you identify it." inputProps={{ "aria-label": "Project name" }} />
        <TextField label="Project ID" required value={effectiveId} onChange={(e) => { setIdTouched(true); setId(e.target.value.trim()); }}
          onBlur={() => setIdTouched(true)} error={!!idErr} inputProps={{ "aria-label": "Project ID" }}
          helperText={idErr || "ID can't be changed later."} />
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Location</Typography>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" color="text.secondary">{parent || "Default organization"}</Typography>
            <Button size="small" onClick={() => setBrowse((b) => !b)}>Browse</Button>
          </Stack>
        </Box>
        {browse && <LocationPicker value={parent} onChange={setParent} />}
      </Stack>
      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/resource-manager">Cancel</Button>
      </Stack>
    </Box>
  );
}

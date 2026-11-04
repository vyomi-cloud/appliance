/* Autokey: a real, enforced per-project singleton AutokeyConfig (key project + state) and
 * KeyHandle provisioning. Once enabled, "Create key handle" really creates an
 * "autokey-{location}" key ring and a brand-new CryptoKey in the configured key project —
 * see core/gcp_kms_core.py for the simplification notes (project-scoped, no folder/org). */
import { useState } from "react";
import { Autocomplete, Box, Button, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { useProject } from "../../../project.js";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../../kit/Capability.jsx";
import { ErrorAlert, KeyValue, Section } from "../../../kit/common.jsx";
import * as api from "./api.js";

const MULTI = ["global", "us", "europe", "asia"];
const REGIONS = api.LOCATIONS.filter(([v]) => !MULTI.includes(v));

export default function Autokey() {
  const project = useProject();
  const notify = useNotify();
  const cfg = useAsync(api.getAutokeyConfig, [project]);
  const handles = useAsync(() => api.listKeyHandles(), [project, cfg.data?.state]);
  const [setupOpen, setSetupOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const disable = async () => {
    try { await api.setAutokeyConfig({ state: "DISABLED" }, ["state"]); notify.success("Autokey disabled"); cfg.reload(); }
    catch (e) { notify.error(e); }
  };

  return (
    <CapabilityContainer id="gcp.kms.autokey" title="Autokey"
      description="Autokey automatically provisions a key ring and key the first time a resource that supports CMEK is created in this project.">
      {cfg.error && <ErrorAlert error={cfg.error} title="Failed to load Autokey configuration" />}
      {cfg.data && cfg.data.state !== "ACTIVE" && (
        <Section title="Set up Autokey" description="Choose a key project to hold the keys Autokey provisions on your behalf.">
          <Button variant="contained" onClick={() => setSetupOpen(true)}>Set up Autokey</Button>
        </Section>
      )}
      {cfg.data && cfg.data.state === "ACTIVE" && (
        <Stack spacing={2}>
          <Section title="Autokey status" actions={<Button onClick={disable}>Disable Autokey</Button>}>
            <KeyValue items={[["Status", "Enabled"], ["Key project", cfg.data.keyProject]]} />
          </Section>
          <Section title="Key handles" description="Each key handle provisioned a key ring and key in the key project above."
            actions={<>
              <Button startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create key handle</Button>
              <Button startIcon={<RefreshIcon />} onClick={handles.reload}>Refresh</Button>
            </>}>
            <ResourceTable
              resourceName="key handles"
              items={handles.data || []}
              rowKey={(h) => h.name}
              loading={handles.loading}
              error={handles.error}
              onRetry={handles.reload}
              filterPlaceholder="Filter"
              columns={[
                { id: "name", header: "Name", sortField: "id", cell: (h) => api.parseKeyHandleName(h.name).id },
                { id: "location", header: "Location", sortField: "location", cell: (h) => api.parseKeyHandleName(h.name).location },
                { id: "selector", header: "Resource type selector", cell: (h) => h.resourceTypeSelector },
                { id: "kmsKey", header: "KMS key", cell: (h) => <Typography variant="body2" sx={{ fontFamily: "monospace", fontSize: 12 }}>{h.kmsKey || "—"}</Typography> },
              ]}
              empty={<Typography variant="body2" color="text.secondary">No key handles have been created in this project.</Typography>}
            />
          </Section>
        </Stack>
      )}
      {setupOpen && <SetupDialog onClose={() => setSetupOpen(false)} onSave={async (keyProject) => {
        await api.setAutokeyConfig({ keyProject, state: "ACTIVE" }, ["keyProject", "state"]);
        notify.success("Autokey is now enabled for this project"); cfg.reload();
      }} />}
      {createOpen && <CreateKeyHandleDialog onClose={() => setCreateOpen(false)} onSave={async (loc, selector) => {
        await api.createKeyHandle(loc, selector);
        notify.success("Created key handle"); handles.reload();
      }} />}
    </CapabilityContainer>
  );
}

function SaveDialog({ title, onClose, onSave, children, saveLabel = "Save" }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Box role="dialog" aria-label={title} sx={{ position: "fixed", inset: 0, bgcolor: "rgba(0,0,0,.4)", display: "grid", placeItems: "center", zIndex: 1300 }} onClick={onClose}>
      <Box sx={{ bgcolor: "background.paper", borderRadius: 2, p: 3, minWidth: 360, maxWidth: 480 }} onClick={(e) => e.stopPropagation()}>
        <Typography variant="h3" component="h2" sx={{ mb: 2 }}>{title}</Typography>
        <Stack spacing={2}>{children}{error && <ErrorAlert error={error} />}</Stack>
        <Stack direction="row" spacing={1} sx={{ mt: 3, justifyContent: "flex-end" }}>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={async () => { setBusy(true); setError(null); try { await onSave(); onClose(); } catch (e) { setError(e); } finally { setBusy(false); } }}>{busy ? "Saving…" : saveLabel}</Button>
        </Stack>
      </Box>
    </Box>
  );
}

function SetupDialog({ onClose, onSave }) {
  const [keyProject, setKeyProject] = useState("");
  const ok = /^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(keyProject);
  return (
    <SaveDialog title="Set up Autokey" onClose={onClose} saveLabel="Enable"
      onSave={() => (ok ? onSave(keyProject) : Promise.reject(new Error("Enter a valid project ID.")))}>
      <TextField label="Key project" required value={keyProject} onChange={(e) => setKeyProject(e.target.value.trim())}
        helperText="The project where Autokey creates key rings and keys on your behalf." inputProps={{ "aria-label": "Key project" }} />
    </SaveDialog>
  );
}

function CreateKeyHandleDialog({ onClose, onSave }) {
  const [loc, setLoc] = useState(REGIONS[0][0]);
  const [selector, setSelector] = useState("");
  const ok = /^[a-z][a-z0-9.-]*\.googleapis\.com\/[A-Za-z][A-Za-z0-9]*$/.test(selector);
  return (
    <SaveDialog title="Create key handle" onClose={onClose}
      onSave={() => (ok ? onSave(loc, selector) : Promise.reject(new Error("Enter a resource type selector like 'compute.googleapis.com/Disk'.")))}>
      <FormControl>
        <InputLabel id="autokey-loc-l">Location</InputLabel>
        <Select labelId="autokey-loc-l" label="Location" value={loc} onChange={(e) => setLoc(e.target.value)} inputProps={{ "aria-label": "Location" }}>
          {REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
        </Select>
      </FormControl>
      <Autocomplete freeSolo options={api.RESOURCE_TYPE_SELECTORS} value={selector}
        onInputChange={(_, v) => setSelector(v.trim())}
        renderInput={(params) => <TextField {...params} label="Resource type selector" helperText="e.g. compute.googleapis.com/Disk" inputProps={{ ...params.inputProps, "aria-label": "Resource type selector" }} />} />
    </SaveDialog>
  );
}

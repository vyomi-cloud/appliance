/* Create a repository — the console's single form with Repository / Encryption / Immutable
 * image tags / Cleanup policies / Artifact Analysis sections, one native repositories.create
 * call. Settings Vyomi stores but doesn't enforce carry their capability badge inline. */
import { useState } from "react";
import {
  Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControl, FormControlLabel,
  FormHelperText, IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";

const location_ = window.location;

const Sub = ({ title, children, help }) => (
  <Box>
    <Typography variant="body2" sx={{ fontWeight: 500, mb: help ? 0.25 : 1 }}>{title}</Typography>
    {help && <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{help}</Typography>}
    {children}
  </Box>
);
const Section = ({ title, children }) => (
  <Box sx={{ py: 2.5 }}>
    <Typography variant="h3" component="h2" sx={{ mb: 2 }}>{title}</Typography>
    <Stack spacing={2.5}>{children}</Stack>
  </Box>
);

export default function CreateRepository() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [format, setFormat] = useState("DOCKER");
  const [mode, setMode] = useState("STANDARD_REPOSITORY");
  const [locType, setLocType] = useState("region");
  const [location, setLocation] = useState(api.REGIONS[0]);
  const [description, setDescription] = useState("");
  const [labels, setLabels] = useState([]);
  const [encryption, setEncryption] = useState("google");
  const [kmsKey, setKmsKey] = useState("");
  const [immutableTags, setImmutableTags] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [policies, setPolicies] = useState([]);
  const [addPolicy, setAddPolicy] = useState(false);
  const [vulnScanning, setVulnScanning] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validRepoId(name) : null;
  const labelErr = labels.some((l) => !/^[a-z][a-z0-9_-]{0,62}$/.test(l.key)) ? "Label keys must start with a lowercase letter and contain only lowercase letters, numbers, underscores and dashes." : null;
  const kmsErr = encryption === "cmek" && !kmsKey.trim() ? "Enter the customer-managed key's resource name." : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validRepoId(name) || labelErr || kmsErr) return;
    setBusy(true); setError(null);
    const body = {
      format, mode, description,
      ...(labels.length ? { labels: Object.fromEntries(labels.map((l) => [l.key, l.value])) } : {}),
      ...(encryption === "cmek" ? { kmsKeyName: kmsKey.trim() } : {}),
      ...(format === "DOCKER" ? { dockerConfig: { immutableTags } } : {}),
      ...(policies.length ? { cleanupPolicies: Object.fromEntries(policies.map((p) => [p.id, { action: p.action, condition: p.condition }])), cleanupPolicyDryRun: dryRun } : {}),
      vulnerabilityScanningConfig: { enablementConfig: vulnScanning ? "INHERITED" : "DISABLED" },
    };
    try {
      await api.createRepository(name, location, body);
      notify.success(`Created repository "${name}"`);
      location_.hash = hashHref("artifacts", "repo", location, name).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Create repository" back={<IconButton aria-label="Back" href="#/artifacts"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create repository" />

      <Section title="Repository">
        <TextField label="Name" required value={name} onChange={(ev) => setName(ev.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} inputProps={{ "aria-label": "Name" }} sx={{ maxWidth: 480 }}
          helperText={nameErr || "Use lowercase letters, numbers and hyphens."} />

        <Sub title="Format">
          <RadioGroup value={format} onChange={(ev) => setFormat(ev.target.value)} aria-label="Format">
            {Object.entries(api.FORMAT_LABEL).map(([v, l]) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={l} />)}
          </RadioGroup>
        </Sub>

        <Sub title="Mode">
          <RadioGroup value={mode} onChange={(ev) => setMode(ev.target.value)} aria-label="Mode">
            {Object.entries(api.MODE_LABEL).map(([v, l]) => (
              <FormControlLabel key={v} value={v} control={<Radio size="small" />}
                label={v === "STANDARD_REPOSITORY" ? l : <Stack direction="row" spacing={1} alignItems="center"><span>{l}</span><CapabilityBadge id="gcp.artifacts.repository-mode" /></Stack>} />
            ))}
          </RadioGroup>
          {mode === "VIRTUAL_REPOSITORY" && (
            <Typography variant="body2" color="text.secondary">
              Add upstream repositories to aggregate from the repository's details page once it's created.
            </Typography>
          )}
        </Sub>

        <Sub title="Location type">
          <RadioGroup value={locType} onChange={(ev) => { const t = ev.target.value; setLocType(t); setLocation(t === "region" ? api.REGIONS[0] : api.MULTI_REGIONS[0]); }} aria-label="Location type">
            <FormControlLabel value="region" control={<Radio size="small" />} label="Region" />
            <FormControlLabel value="multi-region" control={<Radio size="small" />} label="Multi-region" />
          </RadioGroup>
        </Sub>
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="region-label">Region</InputLabel>
          <Select labelId="region-label" label="Region" value={location} onChange={(ev) => setLocation(ev.target.value)} inputProps={{ "aria-label": "Region" }}>
            {(locType === "region" ? api.REGIONS : api.MULTI_REGIONS).map((v) => <MenuItem key={v} value={v}>{v}</MenuItem>)}
          </Select>
        </FormControl>

        <TextField label="Description" value={description} onChange={(ev) => setDescription(ev.target.value)} multiline minRows={2} sx={{ maxWidth: 560 }} />

        <Sub title="Labels">
          <Stack spacing={1}>
            {labels.map((l, i) => (
              <Stack key={i} direction="row" spacing={1} alignItems="center">
                <TextField label={`Key ${i + 1}`} value={l.key} onChange={(ev) => setLabels(labels.map((x, j) => j === i ? { ...x, key: ev.target.value } : x))} />
                <TextField label={`Value ${i + 1}`} value={l.value} onChange={(ev) => setLabels(labels.map((x, j) => j === i ? { ...x, value: ev.target.value } : x))} />
                <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setLabels(labels.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
            {labelErr && <FormHelperText error>{labelErr}</FormHelperText>}
            <Box><Button startIcon={<AddIcon />} onClick={() => setLabels([...labels, { key: "", value: "" }])}>Add label</Button></Box>
          </Stack>
        </Sub>
      </Section>
      <Divider />

      <Section title="Encryption">
        <RadioGroup value={encryption} onChange={(ev) => setEncryption(ev.target.value)} aria-label="Encryption">
          <FormControlLabel value="google" control={<Radio size="small" />} label="Google-managed encryption key" />
          <FormControlLabel value="cmek" control={<Radio size="small" />} label={<Stack direction="row" spacing={1} alignItems="center"><span>Customer-managed encryption key (CMEK)</span><CapabilityBadge id="gcp.artifacts.encryption" /></Stack>} />
        </RadioGroup>
        {encryption === "cmek" && (
          <TextField label="Customer-managed key" value={kmsKey} onChange={(ev) => setKmsKey(ev.target.value)} error={!!kmsErr} sx={{ maxWidth: 560 }}
            helperText={kmsErr || "projects/{project}/locations/{location}/keyRings/{ring}/cryptoKeys/{key}"} />
        )}
      </Section>
      <Divider />

      {format === "DOCKER" && (
        <>
          <Section title="Immutable image tags">
            <RadioGroup value={immutableTags ? "enabled" : "disabled"} onChange={(ev) => setImmutableTags(ev.target.value === "enabled")} aria-label="Immutable image tags">
              <FormControlLabel value="enabled" control={<Radio size="small" />} label="Enabled" />
              <FormControlLabel value="disabled" control={<Radio size="small" />} label="Disabled" />
            </RadioGroup>
          </Section>
          <Divider />
        </>
      )}

      <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Cleanup policies</span><CapabilityBadge id="gcp.artifacts.cleanup-policies" /></Stack>}>
        <RadioGroup value={dryRun ? "dry-run" : "delete"} onChange={(ev) => setDryRun(ev.target.value === "dry-run")} aria-label="Cleanup policies">
          <FormControlLabel value="delete" control={<Radio size="small" />} label="Delete artifacts" />
          <FormControlLabel value="dry-run" control={<Radio size="small" />} label="Dry run" />
        </RadioGroup>
        {policies.map((p, i) => (
          <Stack key={i} direction="row" spacing={1} alignItems="center">
            <Typography variant="body2">{describeCleanupPolicy(p)}</Typography>
            <IconButton aria-label={`Remove cleanup policy ${p.id}`} size="small" onClick={() => setPolicies(policies.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
          </Stack>
        ))}
        <Box><Button startIcon={<AddIcon />} onClick={() => setAddPolicy(true)}>Add a cleanup policy</Button></Box>
      </Section>
      <Divider />

      <Section title="Artifact Analysis">
        <Sub title={<Stack direction="row" spacing={1} alignItems="center"><span>Vulnerability scanning</span><CapabilityBadge id="gcp.artifacts.vulnerability-scanning" /></Stack>}>
          <RadioGroup value={vulnScanning ? "enabled" : "disabled"} onChange={(ev) => setVulnScanning(ev.target.value === "enabled")} aria-label="Vulnerability scanning">
            <FormControlLabel value="enabled" control={<Radio size="small" />} label="Enabled" />
            <FormControlLabel value="disabled" control={<Radio size="small" />} label="Disabled" />
          </RadioGroup>
        </Sub>
      </Section>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/artifacts">Cancel</Button>
      </Stack>

      {addPolicy && <CleanupPolicyDialog existingIds={policies.map((p) => p.id)} onClose={() => setAddPolicy(false)} onSave={(p) => { setPolicies([...policies, p]); setAddPolicy(false); }} />}
    </Box>
  );
}

// Pretty-print a stored CleanupPolicy ({id, action, condition}) for the summary list.
export function describeCleanupPolicy(p) {
  const bits = [p.action === "DELETE" ? "Delete" : "Keep"];
  if (p.condition?.tagState && p.condition.tagState !== "ANY") bits.push(p.condition.tagState.toLowerCase());
  const days = api.durationToDays(p.condition?.olderThan);
  if (days) bits.push(`older than ${days}d`);
  return `${p.id} — ${bits.join(", ")}`;
}

export function CleanupPolicyDialog({ onClose, onSave, existingIds = [] }) {
  const [id, setId] = useState("");
  const [action, setAction] = useState("DELETE");
  const [tagState, setTagState] = useState("ANY");
  const [olderThanDays, setOlderThanDays] = useState("30");
  const idOk = /^[a-z][a-z0-9-]{0,62}$/.test(id) && !existingIds.includes(id);
  const days = parseInt(olderThanDays, 10);
  const daysOk = olderThanDays === "" || (Number.isFinite(days) && days >= 0);
  return (
    <ConfirmDialog title="Add a cleanup policy" onClose={onClose} disabled={!idOk || !daysOk} onSave={() => {
      const condition = {};
      if (tagState !== "ANY") condition.tagState = tagState;
      if (days > 0) condition.olderThan = api.daysToDuration(days);
      onSave({ id, action, condition });
    }}>
      <TextField label="Policy name" value={id} onChange={(ev) => setId(ev.target.value.trim())}
        error={!!id && !idOk} helperText="Lowercase letters, numbers and hyphens; must be unique." autoFocus />
      <RadioGroup row value={action} onChange={(ev) => setAction(ev.target.value)} aria-label="Policy action">
        <FormControlLabel value="DELETE" control={<Radio size="small" />} label="Delete artifacts" />
        <FormControlLabel value="KEEP" control={<Radio size="small" />} label="Keep artifacts" />
      </RadioGroup>
      <RadioGroup row value={tagState} onChange={(ev) => setTagState(ev.target.value)} aria-label="Tag status">
        <FormControlLabel value="ANY" control={<Radio size="small" />} label="Any tag status" />
        <FormControlLabel value="TAGGED" control={<Radio size="small" />} label="Tagged" />
        <FormControlLabel value="UNTAGGED" control={<Radio size="small" />} label="Untagged" />
      </RadioGroup>
      <TextField label="Older than (days)" type="number" value={olderThanDays} error={!daysOk}
        onChange={(ev) => setOlderThanDays(ev.target.value)} helperText="0 to match regardless of age." />
    </ConfirmDialog>
  );
}

function ConfirmDialog({ title, onClose, onSave, disabled, children }) {
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth aria-label={title}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>{children}</Stack></DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={disabled} onClick={onSave}>Add</Button>
      </DialogActions>
    </Dialog>
  );
}

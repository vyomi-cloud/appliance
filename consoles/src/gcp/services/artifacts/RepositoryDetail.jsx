/* Repository details: summary + packages list, Setup instructions / Edit / Delete / Refresh,
 * all on the native Artifact Registry API. "Push sample image/package" is Vyomi's own
 * quickstart (see api.js) since there's no real AR method that creates package data. */
import { useState } from "react";
import {
  Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, FormControlLabel, IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, TextField, Tooltip, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import MenuBookIcon from "@mui/icons-material/esm/MenuBook.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtDate, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";
import { CleanupPolicyDialog, describeCleanupPolicy } from "./CreateRepository.jsx";

export default function RepositoryDetail({ params }) {
  const { location, name } = params;
  const notify = useNotify();
  const project = useProject();
  const [del, setDel] = useState(false);
  const [edit, setEdit] = useState(false);
  const [setup, setSetup] = useState(false);
  const [push, setPush] = useState(false);
  const [sel, setSel] = useState([]);
  const repo = useAsync(() => api.getRepository(location, name), [project, location, name]);
  const pkgs = useAsync(async () => repo.data ? api.listPackages(location, name) : [], [project, location, name, repo.data]);

  return (
    <>
      <PageHeader title="Repository details" back={<IconButton aria-label="Back to repositories" href="#/artifacts"><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<MenuBookIcon />} onClick={() => setSetup(true)} disabled={!repo.data}>Setup instructions</Button>
          <Button startIcon={<EditIcon />} onClick={() => setEdit(true)} disabled={!repo.data}>Edit repository</Button>
          <Button startIcon={<DeleteIcon />} onClick={() => setDel(true)} disabled={!repo.data}>Delete</Button>
          <Button startIcon={<RefreshIcon />} onClick={() => { repo.reload(); pkgs.reload(); }}>Refresh</Button>
        </>} />
      <ErrorAlert error={repo.error} title="Failed to load repository" />
      {!repo.data && !repo.error && <CircularProgress size={24} />}
      {repo.data && (
        <>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
            <Typography variant="h2" component="h2" sx={{ fontSize: 22 }}>{name}</Typography>
            <Tooltip title="Copy repository name"><IconButton size="small" aria-label="Copy repository name" onClick={() => navigator.clipboard?.writeText(name).catch(() => {})}><ContentCopyIcon fontSize="inherit" /></IconButton></Tooltip>
          </Stack>
          <Stack useFlexGap direction="row" spacing={4} sx={{ mb: 3, flexWrap: "wrap", rowGap: 1 }} aria-label="Repository summary">
            {[["Format", api.FORMAT_LABEL[repo.data.format] || repo.data.format], ["Mode", api.MODE_LABEL[repo.data.mode] || repo.data.mode],
              ["Location", `${location} (${api.locationTypeLabel(location)})`], ["Encryption", api.encryptionLabel(repo.data)],
              ["Description", repo.data.description || "—"]].map(([k, v]) => (
              <Box key={k}><Typography variant="caption" color="text.secondary">{k}</Typography><Typography variant="body2">{v}</Typography></Box>
            ))}
          </Stack>

          {repo.data.mode === "VIRTUAL_REPOSITORY" && (
            <UpstreamRepositoriesSection location={location} name={name} repo={repo.data} onChange={repo.reload} />
          )}

          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
            <Typography variant="h3" component="h2" sx={{ flex: 1 }}>{repo.data.format === "DOCKER" ? "Images" : "Packages"}</Typography>
            {repo.data.mode !== "VIRTUAL_REPOSITORY" && (
              <>
                <Button startIcon={<AddIcon />} onClick={() => setPush(true)}>{repo.data.format === "DOCKER" ? "Push sample image" : "Push sample package"}</Button>
                <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={async () => {
                  try { for (const p of sel) await api.deletePackage(location, name, p); notify.success(`Deleted ${sel.length} package${sel.length === 1 ? "" : "s"}`); setSel([]); pkgs.reload(); }
                  catch (e) { notify.error(e); }
                }}>Delete</Button>
              </>
            )}
          </Stack>
          {repo.data.mode === "VIRTUAL_REPOSITORY" && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Aggregated live from the upstream repositories above — read-only here.
            </Typography>
          )}
          <ResourceTable
            resourceName={repo.data.format === "DOCKER" ? "images" : "packages"}
            items={pkgs.data || []}
            rowKey={api.pkgIdOf}
            loading={pkgs.loading}
            error={pkgs.error}
            onRetry={pkgs.reload}
            selectable={repo.data.mode !== "VIRTUAL_REPOSITORY"}
            selected={sel}
            onSelectedChange={setSel}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", sortField: "displayName", cell: (p) => <Link href={hashHref("artifacts", "repo", location, name, "package", api.pkgIdOf(p))}>{p.displayName}</Link> },
              { id: "created", header: "Created", sortField: "createTime", cell: (p) => fmtDate(p.createTime) },
              { id: "updated", header: "Updated", sortField: "updateTime", cell: (p) => fmtDate(p.updateTime) },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No {repo.data.format === "DOCKER" ? "images" : "packages"} in this repository yet.</Typography>}
          />
        </>
      )}

      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete repository?" confirmText={name}
        warning="All packages, versions and tags in the repository are deleted as well. This can't be undone."
        onConfirm={async () => { await api.deleteRepository(location, name); notify.success(`Deleted repository "${name}"`); location_hash("#/artifacts"); }}>
        <Typography variant="body2">Repository <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>

      {edit && repo.data && <EditRepositoryDialog repo={repo.data} onClose={() => setEdit(false)} onSave={async (body, mask) => {
        await api.patchRepository(location, name, body, mask); notify.success("Updated repository");
        repo.reload(); pkgs.reload();   // a cleanup policy change can delete versions the packages list already cached
      }} />}

      {setup && repo.data && <SetupInstructionsDialog repo={repo.data} project={project} location={location} name={name} onClose={() => setSetup(false)} />}

      {push && repo.data && <PushSampleDialog docker={repo.data.format === "DOCKER"} onClose={() => setPush(false)} onSave={async (body) => {
        await api.pushSample(location, name, body); notify.success("Pushed sample " + (repo.data.format === "DOCKER" ? "image" : "package")); setPush(false); pkgs.reload();
      }} />}
    </>
  );
}
const location_hash = (h) => { window.location.hash = h.slice(1); };

function SaveDialog({ title, onClose, onSave, children, disabled }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label={title}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>{children}{error && <Alert severity="error">{error.message}</Alert>}</Stack></DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || disabled} onClick={async () => { setBusy(true); setError(null); try { await onSave(); onClose(); } catch (e) { setError(e); } finally { setBusy(false); } }}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}

function EditRepositoryDialog({ repo, onClose, onSave }) {
  const [description, setDescription] = useState(repo.description || "");
  const [labels, setLabels] = useState(Object.entries(repo.labels || {}).map(([key, value]) => ({ key, value })));
  const [immutableTags, setImmutableTags] = useState(!!repo.dockerConfig?.immutableTags);
  const [dryRun, setDryRun] = useState(!!repo.cleanupPolicyDryRun);
  const [policies, setPolicies] = useState(Object.entries(repo.cleanupPolicies || {}).map(([id, p]) => ({ id, ...p })));
  const [addPolicy, setAddPolicy] = useState(false);
  const canCleanup = repo.mode !== "VIRTUAL_REPOSITORY";
  const bad = labels.some((l) => !/^[a-z][a-z0-9_-]{0,62}$/.test(l.key));
  return (
    <SaveDialog title="Edit repository" onClose={onClose} disabled={bad} onSave={() => {
      const body = {
        description, labels: Object.fromEntries(labels.map((l) => [l.key, l.value])),
        ...(repo.format === "DOCKER" ? { dockerConfig: { immutableTags } } : {}),
        ...(canCleanup ? {
          cleanupPolicies: Object.fromEntries(policies.map((p) => [p.id, { action: p.action, condition: p.condition }])),
          cleanupPolicyDryRun: dryRun,
        } : {}),
      };
      const mask = ["description", "labels", ...(repo.format === "DOCKER" ? ["dockerConfig"] : []),
        ...(canCleanup ? ["cleanupPolicies", "cleanupPolicyDryRun"] : [])].join(",");
      return onSave(body, mask);
    }}>
      <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} multiline minRows={2} />
      <Typography variant="body2" sx={{ fontWeight: 500 }}>Labels</Typography>
      {labels.map((l, i) => (
        <Stack key={i} direction="row" spacing={1} alignItems="center">
          <TextField label={`Key ${i + 1}`} value={l.key} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
          <TextField label={`Value ${i + 1}`} value={l.value} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
          <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setLabels(labels.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
        </Stack>
      ))}
      <Box><Button startIcon={<AddIcon />} onClick={() => setLabels([...labels, { key: "", value: "" }])}>Add label</Button></Box>
      {repo.format === "DOCKER" && (
        <>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Immutable image tags</Typography>
          <RadioGroup row value={immutableTags ? "enabled" : "disabled"} onChange={(e) => setImmutableTags(e.target.value === "enabled")}>
            <FormControlLabel value="enabled" control={<Radio size="small" />} label="Enabled" />
            <FormControlLabel value="disabled" control={<Radio size="small" />} label="Disabled" />
          </RadioGroup>
        </>
      )}
      {canCleanup && (
        <>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Cleanup policies</Typography>
          <RadioGroup row value={dryRun ? "dry-run" : "delete"} onChange={(e) => setDryRun(e.target.value === "dry-run")}>
            <FormControlLabel value="delete" control={<Radio size="small" />} label="Delete artifacts" />
            <FormControlLabel value="dry-run" control={<Radio size="small" />} label="Dry run" />
          </RadioGroup>
          {policies.map((p, i) => (
            <Stack key={p.id} direction="row" spacing={1} alignItems="center">
              <Typography variant="body2">{describeCleanupPolicy(p)}</Typography>
              <IconButton aria-label={`Remove cleanup policy ${p.id}`} size="small" onClick={() => setPolicies(policies.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
          <Box><Button startIcon={<AddIcon />} onClick={() => setAddPolicy(true)}>Add a cleanup policy</Button></Box>
          {addPolicy && <CleanupPolicyDialog existingIds={policies.map((p) => p.id)} onClose={() => setAddPolicy(false)}
            onSave={(p) => { setPolicies([...policies, p]); setAddPolicy(false); }} />}
        </>
      )}
    </SaveDialog>
  );
}

function UpstreamRepositoriesSection({ location, name, repo, onChange }) {
  const notify = useNotify();
  const [addOpen, setAddOpen] = useState(false);
  const policies = repo.virtualRepositoryConfig?.upstreamPolicies || [];
  const save = async (next, msg) => {
    try { await api.patchRepository(location, name, { virtualRepositoryConfig: { upstreamPolicies: next } }, "virtualRepositoryConfig"); notify.success(msg); onChange(); }
    catch (e) { notify.error(e); }
  };
  return (
    <CapabilityContainer id="gcp.artifacts.repository-mode" title="Upstream repositories"
      description="Packages, versions and tags are aggregated live from these repositories; the highest-priority repository wins on a name collision."
      actions={<Button startIcon={<AddIcon />} onClick={() => setAddOpen(true)}>Add repository</Button>}>
      {policies.length === 0
        ? <Typography variant="body2" color="text.secondary">No upstream repositories configured yet.</Typography>
        : (
          <Stack spacing={1}>
            {[...policies].sort((a, b) => (b.priority || 0) - (a.priority || 0)).map((p) => (
              <Stack key={p.id} direction="row" spacing={1} alignItems="center">
                <Typography variant="body2" sx={{ flex: 1 }}>{p.repository.split("/repositories/").pop()} — priority {p.priority ?? 0}</Typography>
                <IconButton aria-label={`Remove upstream repository ${p.repository.split("/repositories/").pop()}`} size="small"
                  onClick={() => save(policies.filter((x) => x.id !== p.id), "Removed upstream repository")}><DeleteIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
          </Stack>
        )}
      {addOpen && <AddUpstreamDialog location={location} existing={policies} onClose={() => setAddOpen(false)}
        onSave={(p) => { setAddOpen(false); save([...policies, p], "Added upstream repository"); }} />}
    </CapabilityContainer>
  );
}

function AddUpstreamDialog({ location, existing, onClose, onSave }) {
  const repos = useAsync(() => api.listRepositories(), []);
  const [repository, setRepository] = useState("");
  const [priority, setPriority] = useState("10");
  const candidates = (repos.data || []).filter((r) => r.location === location && r.mode !== "VIRTUAL_REPOSITORY"
    && !existing.some((e) => e.repository === r.name));
  const n = Number(priority);
  const ok = !!repository && /^\d+$/.test(priority) && n >= 0 && n <= 100;
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth aria-label="Add upstream repository">
      <DialogTitle>Add upstream repository</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {repos.loading
            ? <CircularProgress size={20} />
            : candidates.length === 0
              ? <Typography variant="body2" color="text.secondary">No eligible standard or remote repositories in {location}.</Typography>
              : (
                <FormControl fullWidth>
                  <InputLabel id="upstream-repo-label">Repository</InputLabel>
                  <Select labelId="upstream-repo-label" label="Repository" value={repository} onChange={(e) => setRepository(e.target.value)}>
                    {candidates.map((r) => <MenuItem key={r.name} value={r.name}>{r.id}</MenuItem>)}
                  </Select>
                </FormControl>
              )}
          <TextField label="Priority" type="number" value={priority} onChange={(e) => setPriority(e.target.value)}
            helperText="0-100; the highest-priority upstream wins on a name collision." />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!ok} onClick={() => onSave({ id: `up-${repository.split("/repositories/").pop()}`, repository, priority: n })}>Add</Button>
      </DialogActions>
    </Dialog>
  );
}

function PushSampleDialog({ docker, onClose, onSave }) {
  const [image, setImage] = useState(docker ? "sample-app" : "sample-package");
  const [tag, setTag] = useState(docker ? "latest" : "1.0.0");
  return (
    <SaveDialog title={docker ? "Push sample image" : "Push sample package"} onClose={onClose} onSave={() => onSave({ image, tag })}>
      <Typography variant="body2" color="text.secondary">
        {`Vyomi can't run docker/mvn/npm for you — this creates a sample ${docker ? "image" : "package"} and version so you can explore the repository.`}
      </Typography>
      <TextField label={docker ? "Image name" : "Package name"} value={image} onChange={(e) => setImage(e.target.value.trim())} />
      <TextField label={docker ? "Tag" : "Version"} value={tag} onChange={(e) => setTag(e.target.value.trim())} />
    </SaveDialog>
  );
}

function SetupInstructionsDialog({ repo, project, location, name, onClose }) {
  const host = `${location}-docker.pkg.dev`;
  const lines = repo.format === "DOCKER"
    ? [`gcloud auth configure-docker ${host}`, `docker tag my-image ${host}/${project}/${name}/my-image:latest`, `docker push ${host}/${project}/${name}/my-image:latest`]
    : repo.format === "NPM"
      ? [`gcloud artifacts print-settings npm --project=${project} --repository=${name} --location=${location}`]
      : [`gcloud artifacts print-settings ${repo.format.toLowerCase()} --project=${project} --repository=${name} --location=${location}`];
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth aria-label="Setup instructions">
      <DialogTitle>Setup instructions</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5}>
          <Typography variant="body2" color="text.secondary">Run these commands to configure your client for this repository.</Typography>
          <Box component="pre" sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 1, overflowX: "auto", fontSize: 13, m: 0 }}>{lines.join("\n")}</Box>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}

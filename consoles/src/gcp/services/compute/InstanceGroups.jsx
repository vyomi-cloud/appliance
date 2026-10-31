/* Instance groups — unmanaged groups (free-form membership) and managed instance groups
 * (fixed-size pool stamped out of an instance template; resize creates/deletes real
 * instances) — per core/capabilities/gcp/compute.json. Both list across all zones in one
 * table, matching the real console's merged "Instance groups" page. */
import { useEffect, useState } from "react";
import {
  Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, FormControlLabel,
  FormGroup, IconButton, InputLabel, Menu, MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const ALL_ZONES = Object.values(api.ZONES_BY_REGION).flat();

function CreateDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [kind, setKind] = useState("unmanaged");
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [zone, setZone] = useState(api.DEFAULT_ZONE);
  const [instances, setInstances] = useState([]);
  const [picked, setPicked] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [template, setTemplate] = useState("");
  const [targetSize, setTargetSize] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setKind("unmanaged"); setName(""); setTouched(false); setError(null); setZone(api.DEFAULT_ZONE); setPicked([]); setTargetSize(1);
    api.listInstancesAllZones().then(setInstances).catch(() => setInstances([]));
    api.listInstanceTemplates().then((ts) => { setTemplates(ts); setTemplate(ts[0]?.name || ""); }).catch(() => setTemplates([]));
  }, [open]);

  const nameErr = touched ? api.validResourceName(name) : null;
  const candidates = instances.filter((i) => i._zoneScope === zone);

  const submit = async () => {
    setTouched(true);
    if (api.validResourceName(name)) return;
    setBusy(true); setError(null);
    try {
      if (kind === "managed") {
        await api.insertInstanceGroupManager(zone, { name, baseInstanceName: name, instanceTemplate: template, targetSize: Number(targetSize) });
      } else {
        await api.insertInstanceGroup(zone, { name });
        if (picked.length) await api.addGroupInstances(zone, name, picked);
      }
      notify.success(`Created instance group "${name}"`);
      onCreated();
      onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create instance group</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
          <FormControl>
            <RadioGroup row value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Group type">
              <FormControlLabel value="unmanaged" control={<Radio size="small" />} label="New unmanaged instance group" />
              <FormControlLabel value="managed" control={<Radio size="small" />} label="New managed instance group" />
            </RadioGroup>
          </FormControl>
          <TextField label="Name" required autoFocus value={name} onChange={(e) => setName(e.target.value.trim())}
            onBlur={() => setTouched(true)} error={!!nameErr} helperText={nameErr || " "} inputProps={{ "aria-label": "Name" }} />
          <FormControl fullWidth>
            <InputLabel id="ig-zone-l">Zone</InputLabel>
            <Select labelId="ig-zone-l" label="Zone" value={zone} onChange={(e) => { setZone(e.target.value); setPicked([]); }}>
              {ALL_ZONES.map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
            </Select>
          </FormControl>
          {kind === "managed" ? (
            <>
              <FormControl fullWidth>
                <InputLabel id="ig-tpl-l">Instance template</InputLabel>
                <Select labelId="ig-tpl-l" label="Instance template" value={template} onChange={(e) => setTemplate(e.target.value)}>
                  {templates.map((t) => <MenuItem key={t.name} value={t.name}>{t.name}</MenuItem>)}
                </Select>
                {!templates.length && <FormHelperTextLink />}
              </FormControl>
              <TextField label="Number of instances" type="number" value={targetSize} onChange={(e) => setTargetSize(e.target.value)} inputProps={{ min: 0, "aria-label": "Number of instances" }} />
            </>
          ) : (
            <Stack>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Add instances in {zone} (optional)</Typography>
              {candidates.length ? (
                <FormGroup sx={{ maxHeight: 180, overflow: "auto" }}>
                  {candidates.map((i) => (
                    <FormControlLabel key={i.name} control={<Checkbox size="small" checked={picked.includes(i.name)}
                      onChange={() => setPicked((p) => p.includes(i.name) ? p.filter((n) => n !== i.name) : [...p, i.name])} />} label={i.name} />
                  ))}
                </FormGroup>
              ) : <Typography variant="body2" color="text.secondary">No instances in this zone.</Typography>}
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || (kind === "managed" && !template)} onClick={submit}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function FormHelperTextLink() {
  return <Typography variant="caption" color="text.secondary">No instance templates yet — create one on the Instance templates page first.</Typography>;
}

function ResizeDialog({ group, onClose, onResized }) {
  const notify = useNotify();
  const [size, setSize] = useState(group?.size ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { setSize(group?.size ?? 0); setError(null); }, [group]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.resizeInstanceGroupManager(group._zoneScope, group.name, Number(size));
      notify.success(`Resized "${group.name}" to ${size} instance${Number(size) === 1 ? "" : "s"}`);
      onResized();
      onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={!!group} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Edit group size</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
          <Typography variant="body2" color="text.secondary">Resizing creates or deletes instances from the group's template to match the number of instances.</Typography>
          <TextField label="Number of instances" type="number" autoFocus value={size} onChange={(e) => setSize(e.target.value)} inputProps={{ min: 0, "aria-label": "Number of instances" }} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={submit}>{busy ? "Resizing…" : "Resize"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function UpdateTemplateDialog({ group, onClose, onUpdated }) {
  const notify = useNotify();
  const [templates, setTemplates] = useState([]);
  const [template, setTemplate] = useState("");
  const [rollout, setRollout] = useState("new-only");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!group) return;
    setRollout("new-only"); setError(null);
    api.listInstanceTemplates().then((ts) => { setTemplates(ts); setTemplate(api.last(group.instanceTemplate)); }).catch(() => setTemplates([]));
  }, [group]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const body = { instanceTemplate: template };
      if (rollout === "all-now") body.updatePolicy = { type: "PROACTIVE", minimalAction: "REPLACE", maxSurge: { fixed: 1 }, maxUnavailable: { fixed: 0 } };
      await api.patchInstanceGroupManager(group._zoneScope, group.name, body);
      notify.success(rollout === "all-now"
        ? `Rolling-replaced every instance in "${group.name}" onto "${template}"`
        : `Updated the instance template for "${group.name}" — new instances only`);
      onUpdated();
      onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={!!group} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Change instance template</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
          <FormControl fullWidth>
            <InputLabel id="ig-ut-tpl-l">Instance template</InputLabel>
            <Select labelId="ig-ut-tpl-l" label="Instance template" value={template} onChange={(e) => setTemplate(e.target.value)}>
              {templates.map((t) => <MenuItem key={t.name} value={t.name}>{t.name}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl>
            <RadioGroup value={rollout} onChange={(e) => setRollout(e.target.value)} aria-label="Apply to">
              <FormControlLabel value="new-only" control={<Radio size="small" />} label="New VM instances only" />
              <FormControlLabel value="all-now" control={<Radio size="small" />} label="All VM instances now (rolling replace)" />
            </RadioGroup>
          </FormControl>
          {rollout === "all-now" && (
            <Typography variant="body2" color="text.secondary">
              Every instance in the group is recreated from the new template, one at a time (max surge 1, max unavailable 0).
            </Typography>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !template} onClick={submit}>{busy ? "Updating…" : "Update"}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function InstanceGroups() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const [resize, setResize] = useState(null);
  const [updateTpl, setUpdateTpl] = useState(null);
  const [menu, setMenu] = useState(null);
  const { data = [], loading, error, reload } = useAsync(async () => {
    const [unmanaged, managed] = await Promise.all([api.listInstanceGroupsAllZones(), api.listInstanceGroupManagersAllZones()]);
    return [
      ...unmanaged.map((g) => ({ ...g, _kind: "unmanaged" })),
      ...managed.map((g) => ({ ...g, _kind: "managed", size: g.targetSize })),
    ];
  }, [project]);

  const byKey = (k) => data.find((g) => `${g._zoneScope}/${g.name}` === k);

  return (
    <>
      <PageHeader title={<>Instance groups <CapabilityBadge id="gcp.compute.instance_groups.crud" /></>} actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create instance group</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="instance groups"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        rowKey={(g) => `${g._zoneScope}/${g.name}`}
        filterPlaceholder="Enter property name or value"
        columns={[
          { id: "status", header: "Status", cell: () => "Up to date" },
          { id: "name", header: "Name", sortField: "name", cell: (g) => g.name },
          { id: "instances", header: "Instances", sortField: "size", cell: (g) => g.size },
          { id: "template", header: "Template", cell: (g) => g._kind === "managed" ? api.last(g.instanceTemplate) : "—" },
          { id: "type", header: "Group type", cell: (g) => g._kind === "managed" ? "Managed" : "Unmanaged" },
          { id: "created", header: "Creation time", sortField: "creationTimestamp", cell: (g) => fmtDate(g.creationTimestamp) },
          { id: "location", header: "Location", sortField: "_zoneScope", cell: (g) => g._zoneScope },
          { id: "autoscaling", header: "Autoscaling", cell: () => "Off" },
          { id: "inuse", header: "In use by", cell: () => "—" },
          {
            id: "actions", header: "", width: 48,
            cell: (g) => g._kind === "managed"
              ? <IconButton size="small" aria-label={`Actions for ${g.name}`} onClick={(e) => setMenu({ el: e.currentTarget, group: g })}><MoreVertIcon fontSize="small" /></IconButton>
              : null,
          },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no instance groups in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create instance group</Button>
          </Stack>
        }
      />
      <CreateDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
      <Menu anchorEl={menu?.el} open={!!menu} onClose={() => setMenu(null)}>
        <MenuItem onClick={() => { setResize(menu.group); setMenu(null); }}>Edit group size</MenuItem>
        <MenuItem onClick={() => { setUpdateTpl(menu.group); setMenu(null); }}>Change instance template</MenuItem>
        <MenuItem onClick={() => { setSel([`${menu.group._zoneScope}/${menu.group.name}`]); setMenu(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <ResizeDialog group={resize} onClose={() => setResize(null)} onResized={reload} />
      <UpdateTemplateDialog group={updateTpl} onClose={() => setUpdateTpl(null)} onUpdated={reload} />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete instance group?" : `Delete ${sel.length} instance groups?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.name : "DELETE"}
        warning="This can't be undone."
        onConfirm={async () => {
          for (const k of sel) {
            const g = byKey(k);
            if (!g) continue;
            if (g._kind === "managed") await api.deleteInstanceGroupManager(g._zoneScope, g.name);
            else await api.deleteInstanceGroup(g._zoneScope, g.name);
          }
          notify.success(sel.length === 1 ? `Deleted instance group "${byKey(sel[0])?.name}"` : `Deleted ${sel.length} instance groups`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Instance group <b>{byKey(sel[0])?.name}</b> will be permanently deleted.</> : <>{sel.length} instance groups will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}

/* Subscription details: Metrics / Details / Messages / Snapshots tabs, all on the native
 * subscriptions.get/patch/delete + pull/acknowledge/seek + snapshots list calls. */
import { useState } from "react";
import {
  Box, Button, Checkbox, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, FormControlLabel, IconButton, InputLabel, MenuItem, Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import CameraAltIcon from "@mui/icons-material/esm/CameraAlt.js";
import ReplayIcon from "@mui/icons-material/esm/Replay.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import DownloadIcon from "@mui/icons-material/esm/Download.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function SubscriptionDetail({ params }) {
  const id = params.name;
  const notify = useNotify();
  const [tab, setTab] = useState("details");
  const [del, setDel] = useState(false);
  const [edit, setEdit] = useState(false);
  const [snap, setSnap] = useState(false);
  const [replay, setReplay] = useState(false);
  const s = useAsync(() => api.getSubscription(id), [id]);

  if (s.loading) return <Box sx={{ textAlign: "center", py: 8 }}><CircularProgress /></Box>;
  if (s.error) return <ErrorAlert error={s.error} title="Failed to load subscription" />;
  const sub = s.data;

  return (
    <>
      <PageHeader title={id} back={<IconButton aria-label="Back to subscriptions" href="#/pubsub/subscriptions"><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<EditIcon />} onClick={() => setEdit(true)}>Edit</Button>
          <Button startIcon={<CameraAltIcon />} onClick={() => setSnap(true)}>Create snapshot</Button>
          <Button startIcon={<ReplayIcon />} onClick={() => setReplay(true)}>Replay messages</Button>
          <Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button>
        </>} />

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Subscription tabs">
        <Tab value="metrics" label="Metrics" />
        <Tab value="details" label="Details" />
        <Tab value="messages" label="Messages" />
        <Tab value="snapshots" label="Snapshots" />
      </Tabs>
      {tab === "metrics" && <CapabilityContainer id="gcp.pubsub.metrics" title="Metrics" />}
      {tab === "details" && <DetailsTab sub={sub} />}
      {tab === "messages" && <MessagesTab id={id} />}
      {tab === "snapshots" && <SnapshotsTab sub={sub} />}

      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete subscription?" confirmText={id} warning="This can't be undone."
        onConfirm={async () => { await api.deleteSubscription(id); notify.success(`Deleted subscription "${id}"`); location.hash = "/pubsub/subscriptions"; }}>
        <Typography variant="body2">Subscription <b>{id}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
      <EditSubscriptionDialog open={edit} onClose={() => setEdit(false)} id={id} onSaved={() => { s.reload(); notify.success("Subscription updated"); }} />
      <CreateSnapshotDialog open={snap} onClose={() => setSnap(false)} subId={id} onCreated={() => notify.success("Snapshot created")} />
      <ReplayDialog open={replay} onClose={() => setReplay(false)} sub={sub} onReplayed={() => notify.success("Messages replayed from snapshot")} />
    </>
  );
}

function DetailsTab({ sub }) {
  return (
    <Section title="Subscription details">
      <KeyValue items={[
        ["Subscription name", sub.name],
        ["Topic name", sub.topic],
        ["Delivery type", api.deliveryTypeText(sub)],
        ["Ack deadline", `${sub.ackDeadlineSeconds}s`],
        ["Message retention duration", api.retentionText(sub)],
        ["Expiration", api.expirationText(sub)],
        ["Exactly once delivery", api.exactlyOnceText(sub)],
        ["Message ordering", api.orderingText(sub)],
        ["Dead lettering", sub.deadLetterPolicy ? `${api.shortId(sub.deadLetterPolicy.deadLetterTopic)} after ${sub.deadLetterPolicy.maxDeliveryAttempts} attempts` : "Disabled"],
        ["Retry policy", sub.retryPolicy ? "Retry after exponential backoff delay" : "Retry immediately"],
        ["Labels", api.labelsText(sub.labels)],
      ]} />
    </Section>
  );
}

function MessagesTab({ id }) {
  const notify = useNotify();
  const [autoAck, setAutoAck] = useState(false);
  const [received, setReceived] = useState([]);
  const [busy, setBusy] = useState(false);

  const doPull = async () => {
    setBusy(true);
    try {
      const r = await api.pull(id, 10);
      const msgs = r.receivedMessages || [];
      if (autoAck && msgs.length) await api.acknowledge(id, msgs.map((m) => m.ackId));
      setReceived(msgs.map((m) => ({ ...m, acked: autoAck })));
      if (!msgs.length) notify.info("No messages available to pull.");
    } catch (e) { notify.error(e); }
    finally { setBusy(false); }
  };
  const ack = async (ackId) => {
    try { await api.acknowledge(id, [ackId]); setReceived((xs) => xs.map((m) => m.ackId === ackId ? { ...m, acked: true } : m)); }
    catch (e) { notify.error(e); }
  };

  return (
    <Section title="Messages" actions={<Button startIcon={<DownloadIcon />} disabled={busy} onClick={doPull}>{busy ? "Pulling…" : "Pull"}</Button>}>
      <FormControlLabel sx={{ mb: 1.5 }} control={<Checkbox checked={autoAck} onChange={(e) => setAutoAck(e.target.checked)} />} label="Enable ack messages" />
      <ResourceTable
        resourceName="messages"
        items={received}
        rowKey={(m) => m.ackId}
        columns={[
          { id: "time", header: "Publish time", cell: (m) => m.message.publishTime },
          { id: "attrs", header: "Attribute keys", cell: (m) => Object.keys(m.message.attributes || {}).join(", ") || "—" },
          { id: "body", header: "Message body", cell: (m) => api.decode(m.message.data) },
          { id: "ack", header: "Ack", cell: (m) => m.acked ? "Acked" : <Button size="small" onClick={() => ack(m.ackId)}>Ack</Button> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">Pull to fetch available messages.</Typography>}
      />
    </Section>
  );
}

function SnapshotsTab({ sub }) {
  const { data = [], loading, error, reload } = useAsync(() => api.listSnapshots(), [sub.name]);
  const mine = data.filter((s) => s.subscription === sub.name);
  return (
    <Section title="Snapshots">
      <ResourceTable
        resourceName="snapshots"
        items={mine}
        rowKey={(s) => s.name}
        loading={loading}
        error={error}
        onRetry={reload}
        columns={[
          { id: "id", header: "Snapshot ID", cell: (s) => api.shortId(s.name) },
          { id: "topic", header: "Topic name", cell: (s) => s.topic },
          { id: "expiration", header: "Expiration", cell: (s) => s.expireTime },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No snapshots taken from this subscription.</Typography>}
      />
    </Section>
  );
}

function EditSubscriptionDialog({ open, onClose, id, onSaved }) {
  const [ackDeadline, setAckDeadline] = useState("");
  const [labels, setLabels] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try {
      const fields = {}; const mask = [];
      if (ackDeadline.trim()) { fields.ackDeadlineSeconds = Number(ackDeadline); mask.push("ackDeadlineSeconds"); }
      if (labels.trim()) { fields.labels = Object.fromEntries(labels.split(",").map((p) => p.split(":").map((x) => x.trim())).filter((p) => p[0])); mask.push("labels"); }
      if (mask.length) await api.patchSubscription(id, fields, mask.join(","));
      onSaved(); onClose(); setAckDeadline(""); setLabels("");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="edit-sub-title">
      <DialogTitle id="edit-sub-title">Edit subscription</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to update subscription" />
          <TextField label="Acknowledgement deadline (seconds)" type="number" value={ackDeadline} onChange={(e) => setAckDeadline(e.target.value)} />
          <TextField label="Labels" placeholder="env:prod, team:core" value={labels} onChange={(e) => setLabels(e.target.value)} helperText="comma-separated key:value pairs" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={go}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function CreateSnapshotDialog({ open, onClose, subId, onCreated }) {
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try { await api.createSnapshot(id, api.subName(subId)); onCreated(); onClose(); setId(""); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="create-snap2-title">
      <DialogTitle id="create-snap2-title">Create a snapshot</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to create snapshot" />
          <TextField label="Snapshot ID" autoFocus value={id} onChange={(e) => setId(e.target.value.trim())} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !id} onClick={go}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function ReplayDialog({ open, onClose, sub, onReplayed }) {
  const { data = [] } = useAsync(() => (open ? api.listSnapshots() : Promise.resolve([])), [open, sub?.name]);
  const mine = data.filter((s) => s.subscription === sub?.name);
  const [snapshot, setSnapshot] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try { await api.seek(api.shortId(sub.name), { snapshot }); onReplayed(); onClose(); setSnapshot(""); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="replay-title">
      <DialogTitle id="replay-title">Replay messages</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to replay messages" />
          <FormControl>
            <InputLabel id="replay-snap-l">From snapshot</InputLabel>
            <Select labelId="replay-snap-l" label="From snapshot" value={snapshot} onChange={(e) => setSnapshot(e.target.value)}>
              {mine.map((s) => <MenuItem key={s.name} value={s.name}>{api.shortId(s.name)}</MenuItem>)}
            </Select>
          </FormControl>
          {!mine.length && <Typography variant="body2" color="text.secondary">No snapshots taken from this subscription yet.</Typography>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !snapshot} onClick={go}>{busy ? "Replaying…" : "Replay"}</Button>
      </DialogActions>
    </Dialog>
  );
}

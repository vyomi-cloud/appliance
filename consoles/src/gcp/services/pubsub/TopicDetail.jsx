/* Topic details: Topic card + Subscriptions / Snapshots / Metrics / Details / Messages
 * tabs, all on the native topics.get/patch/delete + subscriptions/snapshots list calls. */
import { useEffect, useState } from "react";
import {
  Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  IconButton, InputLabel, MenuItem, Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import CameraAltIcon from "@mui/icons-material/esm/CameraAlt.js";
import SendIcon from "@mui/icons-material/esm/Send.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityBadge, CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function TopicDetail({ params }) {
  const id = params.name;
  const notify = useNotify();
  const [tab, setTab] = useState("subscriptions");
  const [del, setDel] = useState(false);
  const [edit, setEdit] = useState(false);
  const [snap, setSnap] = useState(false);
  const t = useAsync(() => api.getTopic(id), [id]);

  if (t.loading) return <Box sx={{ textAlign: "center", py: 8 }}><CircularProgress /></Box>;
  if (t.error) return <ErrorAlert error={t.error} title="Failed to load topic" />;
  const topic = t.data;

  return (
    <>
      <PageHeader title={id} back={<IconButton aria-label="Back to topics" href="#/pubsub/topics"><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<EditIcon />} onClick={() => setEdit(true)}>Edit</Button>
          <Button startIcon={<AddIcon />} href={`#/pubsub/subscriptions/create?topic=${encodeURIComponent(id)}`}>Create subscription</Button>
          <Button startIcon={<CameraAltIcon />} onClick={() => setSnap(true)}>Create snapshot</Button>
          <Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button>
        </>} />

      <Section title="Topic">
        <KeyValue items={[
          ["Topic name", topic.name],
          ["Encryption key", api.encryptionText(topic)],
          ["Retention", api.durationText(topic.messageRetentionDuration), <CapabilityBadge key="ret" id="gcp.pubsub.topics.config" />],
        ]} />
      </Section>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ borderBottom: 1, borderColor: "divider", my: 2.5 }} aria-label="Topic tabs">
        <Tab value="subscriptions" label="Subscriptions" />
        <Tab value="snapshots" label="Snapshots" />
        <Tab value="metrics" label="Metrics" />
        <Tab value="details" label="Details" />
        <Tab value="messages" label="Messages" />
      </Tabs>
      {tab === "subscriptions" && <SubscriptionsTab id={id} />}
      {tab === "snapshots" && <SnapshotsTab id={id} />}
      {tab === "metrics" && <CapabilityContainer id="gcp.pubsub.metrics" title="Metrics" />}
      {tab === "details" && <DetailsTab topic={topic} />}
      {tab === "messages" && <MessagesTab id={id} />}

      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete topic?" confirmText={id}
        warning="This can't be undone. Attached subscriptions are detached, not deleted."
        onConfirm={async () => { await api.deleteTopic(id); notify.success(`Deleted topic "${id}"`); location.hash = "/pubsub/topics"; }}>
        <Typography variant="body2">Topic <b>{id}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
      <EditTopicDialog open={edit} onClose={() => setEdit(false)} topic={topic} onSaved={() => { t.reload(); notify.success("Topic updated"); }} />
      <CreateSnapshotDialog open={snap} onClose={() => setSnap(false)} topicId={id} onCreated={() => notify.success("Snapshot created")} />
    </>
  );
}

function SubscriptionsTab({ id }) {
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(() => api.subscriptionsOfTopic(id), [id]);
  return (
    <Section title="Subscriptions" actions={<Button startIcon={<AddIcon />} href={`#/pubsub/subscriptions/create?topic=${encodeURIComponent(id)}`}>Create subscription</Button>}>
      <ResourceTable
        resourceName="subscriptions"
        items={data}
        rowKey={(s) => s.name}
        loading={loading}
        error={error}
        onRetry={reload}
        columns={[
          { id: "id", header: "Subscription ID", cell: (s) => <Link href={hashHref("pubsub", "subscriptions", api.shortId(s.name))}>{api.shortId(s.name)}</Link> },
          { id: "name", header: "Subscription name", cell: (s) => s.name },
          { id: "project", header: "Project", cell: () => project },
          { id: "delivery", header: "Delivery type", cell: (s) => api.deliveryTypeText(s) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">This topic has no subscriptions.</Typography>}
      />
    </Section>
  );
}

function SnapshotsTab({ id }) {
  const { data = [], loading, error, reload } = useAsync(() => api.listSnapshots(), [id]);
  const mine = data.filter((s) => s.topic === api.topicName(id));
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
          { id: "sub", header: "Subscription", cell: (s) => api.shortId(s.subscription) },
          { id: "expiration", header: "Expiration", cell: (s) => s.expireTime },
        ]}
        empty={<Typography variant="body2" color="text.secondary">This topic has no snapshots.</Typography>}
      />
    </Section>
  );
}

function DetailsTab({ topic }) {
  return (
    <Section title="Details">
      <KeyValue items={[
        ["Topic name", topic.name],
        ["Encryption key", api.encryptionText(topic)],
        ["Retention", api.durationText(topic.messageRetentionDuration), <CapabilityBadge key="ret" id="gcp.pubsub.topics.config" />],
        ["Schema", topic.schemaSettings ? `${api.shortId(topic.schemaSettings.schema)} (${topic.schemaSettings.encoding || "JSON"})` : "None",
          topic.schemaSettings ? <CapabilityBadge key="sch" id="gcp.pubsub.topics.schema" /> : null],
        ["Labels", api.labelsText(topic.labels)],
      ]} />
    </Section>
  );
}

function MessagesTab({ id }) {
  const [sent, setSent] = useState(() => api.readSentMessages(id));
  useEffect(() => { setSent(api.readSentMessages(id)); }, [id]);
  return (
    <Section title="Messages" actions={<Button startIcon={<SendIcon />} href={`#/pubsub/topics/${encodeURIComponent(id)}/publish`}>Publish message</Button>}>
      <ResourceTable
        resourceName="messages"
        items={sent}
        rowKey={(m) => m.messageId}
        columns={[
          { id: "time", header: "Publish time", cell: (m) => m.publishTime },
          { id: "attrs", header: "Attribute keys", cell: (m) => Object.keys(m.attributes || {}).join(", ") || "—" },
          { id: "body", header: "Message body", cell: (m) => api.decode(m.data) },
          { id: "ordering", header: "Ordering key", cell: (m) => m.orderingKey || "—" },
        ]}
        empty={<Typography variant="body2" color="text.secondary">Messages you publish from this page appear here. Pub/Sub doesn't let topics replay history, so reloading clears this list.</Typography>}
      />
    </Section>
  );
}

function EditTopicDialog({ open, onClose, topic, onSaved }) {
  const [labels, setLabels] = useState("");
  const [retDays, setRetDays] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const id = topic ? api.shortId(topic.name) : "";
  const go = async () => {
    setBusy(true); setError(null);
    try {
      const fields = {};
      const mask = [];
      if (labels.trim()) { fields.labels = Object.fromEntries(labels.split(",").map((p) => p.split(":").map((x) => x.trim())).filter((p) => p[0])); mask.push("labels"); }
      if (retDays.trim()) { fields.messageRetentionDuration = `${Number(retDays) * 86400}s`; mask.push("messageRetentionDuration"); }
      if (mask.length) await api.patchTopic(id, fields, mask.join(","));
      onSaved(); onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="edit-topic-title">
      <DialogTitle id="edit-topic-title">Edit topic</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to update topic" />
          <TextField label="Labels" placeholder="env:prod, team:core" value={labels} onChange={(e) => setLabels(e.target.value)} helperText="comma-separated key:value pairs" />
          <TextField label="Message retention duration (days)" type="number" value={retDays} onChange={(e) => setRetDays(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={go}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function CreateSnapshotDialog({ open, onClose, topicId, onCreated }) {
  const subs = useAsync(() => (open ? api.subscriptionsOfTopic(topicId) : Promise.resolve([])), [open, topicId]);
  const [id, setId] = useState("");
  const [sub, setSub] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try { await api.createSnapshot(id, sub); onCreated(); onClose(); setId(""); setSub(""); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="create-snap-title">
      <DialogTitle id="create-snap-title">Create a snapshot</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to create snapshot" />
          <TextField label="Snapshot ID" autoFocus value={id} onChange={(e) => setId(e.target.value.trim())} />
          <FormControl>
            <InputLabel id="snap-sub-l">Subscription</InputLabel>
            <Select labelId="snap-sub-l" label="Subscription" value={sub} onChange={(e) => setSub(e.target.value)}>
              {(subs.data || []).map((s) => <MenuItem key={s.name} value={s.name}>{api.shortId(s.name)}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !id || !sub} onClick={go}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

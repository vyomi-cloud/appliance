/* Trigger details: configuration, event filters, destination and the delivery history of real CloudEvents. */
import { useEffect, useState } from "react";
import { Box, Button, CircularProgress, IconButton, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function TriggerDetail({ params }) {
  const { region, name } = params;
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.getTrigger(region, name), [region, name]);
  const d = useAsync(() => api.deliveries(region, name).catch(() => ({ deliveries: [], delivered: 0, failed: 0 })), [region, name]);

  // while a delivery is retrying, poll so the attempt history advances without a manual refresh
  const retrying = d.data?.retrying || 0;
  useEffect(() => { if (!retrying) return undefined; const h = setInterval(() => d.reload(), 2000); return () => clearInterval(h); }, [retrying]);

  if (t.loading) return <Box sx={{ textAlign: "center", py: 8 }}><CircularProgress /></Box>;
  if (t.error) return <ErrorAlert error={t.error} title="Failed to load trigger" />;
  const trg = t.data, dest = api.destinationOf(trg), dl = d.data || { deliveries: [], delivered: 0, failed: 0 };
  const reload = () => { t.reload(); d.reload(); };

  return (
    <>
      <PageHeader title={name} back={<IconButton aria-label="Back to triggers" href="#/eventarc"><ArrowBackIcon /></IconButton>}
        actions={<><Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button><Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button></>} />
      <Section title="Trigger details">
        <KeyValue items={[
          ["Name", name], ["Region", region], ["Event type", api.eventType(trg)],
          ["Destination", `${dest.kind}: ${dest.name}`], ["Service account", trg.serviceAccount || "—"],
          ["Pub/Sub topic", trg.transport?.pubsub?.topic || "—"],
          ["Retry policy", trg.retryPolicy ? `max ${trg.retryPolicy.maxAttempts ?? 5} attempts, ${trg.retryPolicy.minRetryDelay || "1s"} to ${trg.retryPolicy.maxRetryDelay || "60s"} exponential backoff` : "default: 5 attempts, 1s to 60s exponential backoff"],
          ["Dead-letter topic", trg.deadLetterTopic || "none (events are dropped after the last attempt)"], ["Created", fmtDate(trg.createTime)], ["Last updated", fmtDate(trg.updateTime)],
        ]} />
      </Section>
      <Section title="Event filters">
        <ResourceTable resourceName="event filters" items={trg.eventFilters || []} rowKey={(f) => f.attribute + f.value}
          columns={[{ id: "a", header: "Attribute", cell: (f) => f.attribute }, { id: "o", header: "Operator", cell: (f) => f.operator || "=" }, { id: "v", header: "Value", cell: (f) => f.value }]} />
      </Section>
      <Section title={`Deliveries (${dl.delivered} delivered, ${dl.retrying || 0} retrying, ${dl.deadLettered || 0} dead-lettered, ${dl.failed} failed)`}>
        <ResourceTable resourceName="deliveries" items={dl.deliveries || []} rowKey={(x, i) => `${x.time}-${i}`}
          columns={[{ id: "time", header: "Time", cell: (x) => fmtDate(x.time) }, { id: "type", header: "Event", cell: (x) => x.type || x.eventType || "—" },
            { id: "st", header: "Result", cell: (x) => x.status ?? x.result ?? "—" },
            { id: "at", header: "Attempts", cell: (x) => (x.attemptCount != null ? `${x.attemptCount} / ${x.maxAttempts}` : "—") },
            { id: "nx", header: "Next attempt", cell: (x) => (x.nextAttemptTime ? fmtDate(x.nextAttemptTime) : "—") },
            { id: "er", header: "Last error", cell: (x) => x.error || "—" },
            { id: "hist", header: "Attempt history", cell: (x) => (x.attempts || []).map((a) => `#${a.attempt} ${a.ok ? "ok" : "failed"}${a.status ? ` (${a.status})` : ""}`).join(", ") || "—" },
            { id: "ok", header: "Ordering key", cell: (x) => x.orderingKey || "—" }]}
          empty={<Typography variant="body2" color="text.secondary">No events delivered yet.</Typography>} />
      </Section>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete trigger?" confirmText={name} warning="This can't be undone."
        onConfirm={async () => { await api.deleteTrigger(region, name); notify.success(`Deleted trigger "${name}"`); location.hash = "/eventarc"; }}>
        <Typography variant="body2">Trigger <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

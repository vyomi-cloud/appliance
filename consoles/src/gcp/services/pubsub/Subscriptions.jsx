/* Subscriptions — the console's cross-topic subscriptions table. */
import { useState } from "react";
import { Button, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Subscriptions() {
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(() => api.listSubscriptions(), [project]);
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  const deleteSelected = async () => {
    let ok = 0, fail = 0;
    for (const name of sel) { try { await api.deleteSubscription(api.shortId(name)); ok++; } catch { fail++; } }
    if (ok) notify.success(`Deleted ${ok} subscription${ok === 1 ? "" : "s"}`);
    if (fail) notify.error(`${fail} subscription${fail === 1 ? "" : "s"} failed to delete`);
    setSel([]); reload();
  };

  return (
    <>
      <PageHeader title="Subscriptions" actions={<>
        <Button startIcon={<AddIcon />} href="#/pubsub/subscriptions/create">Create subscription</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="subscriptions"
        items={data}
        rowKey={(s) => s.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "id", header: "Subscription ID", sortValue: (s) => api.shortId(s.name), cell: (s) => <Link href={hashHref("pubsub", "subscriptions", api.shortId(s.name))}>{api.shortId(s.name)}</Link> },
          { id: "delivery", header: "Delivery type", cell: (s) => api.deliveryTypeText(s) },
          { id: "topic", header: "Topic name", cell: (s) => s.topic },
          { id: "name", header: "Subscription name", cell: (s) => s.name },
          { id: "ack", header: "Ack deadline", cell: (s) => `${s.ackDeadlineSeconds}s` },
          { id: "retention", header: "Retention", cell: (s) => api.retentionText(s) },
          { id: "ordering", header: "Message ordering", cell: (s) => api.orderingText(s) },
          { id: "eo", header: "Exactly once delivery", cell: (s) => api.exactlyOnceText(s) },
          { id: "expiration", header: "Expiration", cell: (s) => api.expirationText(s) },
          { id: "labels", header: "Labels", cell: (s) => api.labelsText(s.labels) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">No subscriptions to display.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/pubsub/subscriptions/create">Create subscription</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete subscription?" : `Delete ${sel.length} subscriptions?`}
        confirmText={sel.length === 1 ? api.shortId(sel[0]) : "DELETE"}
        warning="This can't be undone."
        onConfirm={deleteSelected}
      >
        <Typography variant="body2">{sel.map(api.shortId).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

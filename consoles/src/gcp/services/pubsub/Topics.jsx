/* Topics — the console's Pub/Sub landing table: topics.list plus create/delete. */
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

export default function Topics() {
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(() => api.listTopics(), [project]);
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  const deleteSelected = async () => {
    let ok = 0, fail = 0;
    for (const name of sel) { try { await api.deleteTopic(api.shortId(name)); ok++; } catch { fail++; } }
    if (ok) notify.success(`Deleted ${ok} topic${ok === 1 ? "" : "s"}`);
    if (fail) notify.error(`${fail} topic${fail === 1 ? "" : "s"} failed to delete`);
    setSel([]); reload();
  };

  return (
    <>
      <PageHeader title="Topics" actions={<>
        <Button startIcon={<AddIcon />} href="#/pubsub/topics/create">Create topic</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="topics"
        items={data}
        rowKey={(t) => t.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "id", header: "Topic ID", sortValue: (t) => api.shortId(t.name), cell: (t) => <Link href={hashHref("pubsub", "topics", api.shortId(t.name))}>{api.shortId(t.name)}</Link> },
          { id: "enc", header: "Encryption key", cell: (t) => api.encryptionText(t) },
          { id: "name", header: "Topic name", cell: (t) => t.name },
          { id: "retention", header: "Retention", cell: (t) => api.durationText(t.messageRetentionDuration) },
          { id: "labels", header: "Labels", cell: (t) => api.labelsText(t.labels) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">No topics to display.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/pubsub/topics/create">Create topic</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete topic?" : `Delete ${sel.length} topics?`}
        confirmText={sel.length === 1 ? api.shortId(sel[0]) : "DELETE"}
        warning="This can't be undone. Attached subscriptions are detached, not deleted."
        onConfirm={deleteSelected}
      >
        <Typography variant="body2">{sel.map(api.shortId).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

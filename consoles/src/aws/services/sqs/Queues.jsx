import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import SnsSubscribeModal from "./SnsSubscribeModal.jsx";
import * as api from "./api.js";

export const queueTypeOf = api.queueType;
export const encryptionLabel = api.encryptionOf;

export default function Queues() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const q = useAsync(() => api.listQueues(), []);
  const [subModal, setSubModal] = useState(false);

  const one = sel[0];
  return (
    <SpaceBetween size="l">
      <ResourceTable
        resourceName="Queues"
        items={q.data || []}
        loading={q.loading}
        error={q.error}
        onRefresh={q.reload}
        trackBy="url"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search queues by prefix"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (r) => <Link href={href("sqs", "queues", r.name)} onFollow={follow}>{r.name}</Link> },
          { id: "type", header: "Type", cell: (r) => api.queueType(r.attrs) },
          { id: "created", header: "Created", cell: (r) => fmtDate(Number(r.attrs.CreatedTimestamp) * 1000) },
          { id: "avail", header: "Messages available", cell: (r) => r.attrs.ApproximateNumberOfMessages ?? "0" },
          { id: "flight", header: "Messages in flight", cell: (r) => r.attrs.ApproximateNumberOfMessagesNotVisible ?? "0" },
          { id: "enc", header: "Encryption", cell: (r) => api.encryptionOf(r.attrs) },
          { id: "dedup", header: "Content-based deduplication", cell: (r) => (api.queueType(r.attrs) === "FIFO" ? (String(r.attrs.ContentBasedDeduplication).toLowerCase() === "true" ? "Enabled" : "Disabled") : "-") },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} href={one ? href("sqs", "queues", one.name, "edit") : undefined} onFollow={follow}>Edit</Button>
            <Button disabled={sel.length !== 1} href={one ? href("sqs", "queues", one.name, "delete") : undefined} onFollow={follow}>Delete</Button>
            <Button disabled={sel.length !== 1} href={one ? href("sqs", "queues", one.name, "send-receive") : undefined} onFollow={follow}>Send and receive messages</Button>
            <ButtonDropdown
              disabled={sel.length !== 1}
              items={[
                { id: "view", text: "View/Edit" },
                { id: "sendrecv", text: "Send and receive messages" },
                { id: "purge", text: "Purge" },
                { id: "delete", text: "Delete" },
                { id: "dlq-redrive", text: "Start DLQ redrive" },
                { id: "subscribe-sns", text: "Subscribe to Amazon SNS topic" },
                { id: "lambda-trigger", text: "Configure Lambda function trigger" },
              ]}
              onItemClick={({ detail }) => {
                if (!one) return;
                if (detail.id === "view") navigate("sqs", "queues", one.name);
                else if (detail.id === "sendrecv") navigate("sqs", "queues", one.name, "send-receive");
                else if (detail.id === "purge") navigate("sqs", "queues", one.name, "purge");
                else if (detail.id === "delete") navigate("sqs", "queues", one.name, "delete");
                else if (detail.id === "subscribe-sns") setSubModal(true);
                else if (detail.id === "dlq-redrive") notify.info("Dead-letter queue redrive tasks aren't simulated by Vyomi — receive and re-send messages directly from Send and receive messages.", "Start DLQ redrive");
                else if (detail.id === "lambda-trigger") notify.info("Lambda event source mappings aren't simulated by Vyomi.", "Configure Lambda function trigger");
              }}
            >Actions</ButtonDropdown>
            <Button variant="primary" href={href("sqs", "create-queue")} onFollow={follow}>Create queue</Button>
          </SpaceBetween>
        }
        empty={{ title: "No queues", action: <Button href={href("sqs", "create-queue")} onFollow={follow}>Create queue</Button> }}
      />
      <SnsSubscribeModal visible={subModal} queueArn={one?.attrs?.QueueArn} onDismiss={() => setSubModal(false)} onDone={() => notify.success(`Subscribed ${one.name} to the topic.`)} />
    </SpaceBetween>
  );
}

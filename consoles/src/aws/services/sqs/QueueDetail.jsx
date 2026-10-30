import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert, KeyValue, NotSimulated } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import SnsSubscribeModal from "./SnsSubscribeModal.jsx";
import * as api from "./api.js";

export default function QueueDetail({ params }) {
  const name = params.name;
  const t = useAsync(async () => {
    const url = await api.getQueueUrl(name);
    return { url, attrs: await api.getQueueAttributes(url) };
  }, [name]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const { url, attrs } = t.data;

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
          <Button href={href("sqs", "queues", name, "edit")} onFollow={follow}>Edit</Button>
          <Button href={href("sqs", "queues", name, "purge")} onFollow={follow}>Purge</Button>
          <Button href={href("sqs", "queues", name, "delete")} onFollow={follow}>Delete</Button>
          <Button variant="primary" href={href("sqs", "queues", name, "send-receive")} onFollow={follow}>Send and receive messages</Button>
        </SpaceBetween>
      }>{name}</Header>
    }>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={3} items={[
          ["Name", name], ["Type", api.queueType(attrs)], ["ARN", attrs.QueueArn],
          ["Encryption", api.encryptionOf(attrs)], ["URL", url],
          ["Dead-letter queue", api.redrivePolicy(attrs)?.deadLetterTargetArn ? api.nameFromUrl(api.redrivePolicy(attrs).deadLetterTargetArn.replace(/^arn:aws:sqs:[^:]+:[^:]+:/, "")) : "-"],
        ]} />
        <Tabs tabs={[
          { id: "sns", label: "SNS subscriptions", content: <SnsSubscriptionsTab queueArn={attrs.QueueArn} /> },
          { id: "lambda", label: "Lambda triggers", content: <CapabilityContainer id="sqs.lambda-triggers" title="Lambda triggers" /> },
          { id: "pipes", label: "EventBridge Pipes", content: <CapabilityContainer id="sqs.eventbridge-pipes" title="EventBridge Pipes" /> },
          { id: "dlq", label: "Dead-letter queue", content: <DlqTab name={name} attrs={attrs} /> },
          { id: "monitor", label: "Monitoring", content: <MonitoringTab attrs={attrs} /> },
          { id: "tags", label: "Tagging", content: <TaggingTab name={name} url={url} /> },
          { id: "policy", label: "Access policy", content: <AccessPolicyTab name={name} attrs={attrs} /> },
          { id: "encryption", label: "Encryption", content: <EncryptionTab name={name} attrs={attrs} /> },
          { id: "redrive-tasks", label: "Dead-letter queue redrive tasks", content: <CapabilityContainer id="sqs.dlq.redrive-task" title="Dead-letter queue redrive tasks" /> },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}

function SnsSubscriptionsTab({ queueArn }) {
  const notify = useNotify();
  const subs = useAsync(() => api.listSubscriptionsForQueue(queueArn), [queueArn]);
  const [modal, setModal] = useState(false);
  return (
    <SpaceBetween size="l">
      <Table
        variant="container"
        items={subs.data || []}
        loading={subs.loading}
        trackBy="SubscriptionArn"
        header={<Header variant="h2" counter={`(${(subs.data || []).length})`} actions={<Button onClick={() => setModal(true)}>Subscribe to Amazon SNS topic</Button>}>SNS subscriptions</Header>}
        columnDefinitions={[
          { id: "sub", header: "Subscription ARN", cell: (s) => s.SubscriptionArn },
          { id: "topic", header: "Topic ARN", cell: (s) => s.TopicArn },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No subscriptions</b></Box>}
      />
      <SnsSubscribeModal visible={modal} queueArn={queueArn} onDismiss={() => setModal(false)} onDone={() => { notify.success("Subscribed to the topic."); subs.reload(); }} />
    </SpaceBetween>
  );
}

function DlqTab({ name, attrs }) {
  const policy = api.redrivePolicy(attrs);
  const dlqArn = policy?.deadLetterTargetArn;
  const dlqName = dlqArn ? dlqArn.split(":").pop() : null;
  return (
    <KeyValue title="Dead-letter queue" actions={<Button href={href("sqs", "queues", name, "edit")} onFollow={follow}>Edit</Button>} columns={2} items={[
      ["Dead-letter queue", dlqName || "-"],
      ["Maximum receives", policy?.maxReceiveCount ?? "-"],
    ]} />
  );
}

function MonitoringTab({ attrs }) {
  return (
    <Box>
      <KeyValue title="CloudWatch metrics" columns={2} items={[
        ["Approximate number of messages visible", attrs.ApproximateNumberOfMessages ?? "0"],
        ["Approximate number of messages not visible", attrs.ApproximateNumberOfMessagesNotVisible ?? "0"],
      ]} />
      <Box padding={{ top: "l" }}>
        <NotSimulated feature="Historical CloudWatch metrics"
          note="Number of messages sent, Number of messages received, Number of messages deleted and Approximate age of oldest message are historical CloudWatch time-series metrics; Vyomi reports live queue depth above but does not aggregate metric history." />
      </Box>
    </Box>
  );
}

function TaggingTab({ name, url }) {
  const tags = useAsync(() => api.listQueueTags(url), [url]);
  const rows = Object.entries(tags.data || {}).map(([Key, Value]) => ({ Key, Value }));
  return (
    <Table
      variant="container"
      items={rows}
      loading={tags.loading}
      header={<Header variant="h2" counter={`(${rows.length})`} actions={<Button href={href("sqs", "queues", name, "edit")} onFollow={follow}>Edit</Button>}>Tags</Header>}
      columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.Key }, { id: "v", header: "Value", cell: (r) => r.Value || "-" }]}
      empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>}
    />
  );
}

function AccessPolicyTab({ name, attrs }) {
  return (
    <CapabilityContainer id="sqs.queue.attributes" title="Access policy (Permissions)" actions={<Button href={href("sqs", "queues", name, "edit")} onFollow={follow}>Edit</Button>}>
      <Textarea readOnly rows={8} value={attrs.Policy || "No policy attached. Only the queue owner can send and receive messages."} ariaLabel="Policy" />
    </CapabilityContainer>
  );
}

function EncryptionTab({ name, attrs }) {
  return (
    <KeyValue title="Encryption" actions={<Button href={href("sqs", "queues", name, "edit")} onFollow={follow}>Edit</Button>} columns={2} items={[
      ["Server-side encryption", api.encryptionOf(attrs) === "None" ? "Disabled" : "Enabled"],
      ["Encryption key type", api.encryptionOf(attrs)],
    ]} />
  );
}

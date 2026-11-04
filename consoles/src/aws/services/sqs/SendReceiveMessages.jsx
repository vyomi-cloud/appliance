import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Textarea from "@cloudscape-design/components/textarea";
import Table from "@cloudscape-design/components/table";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Grid from "@cloudscape-design/components/grid";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function SendReceiveMessages({ params }) {
  const name = params.name;
  const notify = useNotify();
  const q = useAsync(async () => {
    const url = await api.getQueueUrl(name);
    return { url, attrs: await api.getQueueAttributes(url) };
  }, [name]);
  if (q.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (q.error) return <ErrorAlert error={q.error} />;
  const { url, attrs } = q.data;
  const fifo = api.queueType(attrs) === "FIFO";

  return (
    <ContentLayout header={
      <Header variant="h1" actions={<Button href={href("sqs", "queues", name, "purge")} onFollow={follow}>Purge</Button>}>Send and receive messages</Header>
    }>
      <SpaceBetween size="l">
        <SendMessagePanel url={url} fifo={fifo} notify={notify} />
        <ReceivePanel url={url} />
      </SpaceBetween>
    </ContentLayout>
  );
}

function SendMessagePanel({ url, fifo, notify }) {
  const [body, setBody] = useState("");
  const [delayVal, setDelayVal] = useState("0"); const [delayUnit, setDelayUnit] = useState("Seconds");
  const [groupId, setGroupId] = useState(""); const [dedupId, setDedupId] = useState("");
  const [attrs, setAttrs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const clear = () => { setBody(""); setDelayVal("0"); setGroupId(""); setDedupId(""); setAttrs([]); setError(null); };
  const send = async () => {
    setBusy(true); setError(null);
    try {
      const MessageAttributes = Object.fromEntries(attrs.filter((a) => a.name).map((a) => [a.name, { DataType: a.type || "String", StringValue: a.value || "" }]));
      await api.sendMessage(url, {
        MessageBody: body,
        DelaySeconds: fifo ? 0 : delayVal * (delayUnit === "Minutes" ? 60 : 1),
        ...(fifo ? { MessageGroupId: groupId, ...(dedupId ? { MessageDeduplicationId: dedupId } : {}) } : {}),
        ...(Object.keys(MessageAttributes).length ? { MessageAttributes } : {}),
      });
      notify.success("Message sent.");
      clear();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Container header={<Header variant="h2" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={clear}>Clear content</Button>
        <Button variant="primary" loading={busy} disabled={!body || (fifo && !groupId)} onClick={send}>Send message</Button>
      </SpaceBetween>
    }>Send message</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Message body"><Textarea rows={6} value={body} onChange={({ detail }) => setBody(detail.value)} ariaLabel="Message body" /></FormField>
        <FormField label="Delivery delay" constraintText={fifo ? "FIFO queues don't support a per-message delivery delay." : undefined}>
          <Grid gridDefinition={[{ colspan: 8 }, { colspan: 4 }]}>
            <Input type="number" disabled={fifo} value={fifo ? "0" : delayVal} onChange={({ detail }) => setDelayVal(detail.value)} ariaLabel="Delivery delay" />
            <Select disabled={fifo} selectedOption={{ value: delayUnit, label: delayUnit }} onChange={({ detail }) => setDelayUnit(detail.selectedOption.value)} options={[{ value: "Seconds", label: "Seconds" }, { value: "Minutes", label: "Minutes" }]} ariaLabel="Delivery delay unit" />
          </Grid>
        </FormField>
        {fifo && <FormField label="Message group ID"><Input value={groupId} onChange={({ detail }) => setGroupId(detail.value)} ariaLabel="Message group ID" /></FormField>}
        {fifo && <FormField label="Message deduplication ID"><Input value={dedupId} onChange={({ detail }) => setDedupId(detail.value)} ariaLabel="Message deduplication ID" /></FormField>}
        <Table
          variant="embedded"
          items={attrs}
          header={<Header variant="h3" actions={<Button onClick={() => setAttrs([...attrs, { name: "", type: "String", value: "" }])}>Add new attribute</Button>}>Message attributes</Header>}
          columnDefinitions={[
            { id: "n", header: "Name", cell: (a, i) => <Input value={a.name} onChange={({ detail }) => setAttrs(attrs.map((x, j) => (j === i ? { ...x, name: detail.value } : x)))} ariaLabel="Attribute name" /> },
            { id: "t", header: "Type", cell: (a, i) => <Select selectedOption={{ value: a.type, label: a.type }} onChange={({ detail }) => setAttrs(attrs.map((x, j) => (j === i ? { ...x, type: detail.selectedOption.value } : x)))} options={["String", "Number", "Binary"].map((v) => ({ value: v, label: v }))} ariaLabel="Attribute type" /> },
            { id: "v", header: "Value", cell: (a, i) => <Input value={a.value} onChange={({ detail }) => setAttrs(attrs.map((x, j) => (j === i ? { ...x, value: detail.value } : x)))} ariaLabel="Attribute value" /> },
            { id: "rm", header: "", cell: (a, i) => <Button onClick={() => setAttrs(attrs.filter((_, j) => j !== i))}>Remove</Button> },
          ]}
          empty={<Box textAlign="center" color="inherit">No message attributes</Box>}
        />
      </SpaceBetween>
    </Container>
  );
}

function ReceivePanel({ url }) {
  const [polling, setPolling] = useState(false);
  const [messages, setMessages] = useState([]);
  const [sel, setSel] = useState([]);
  const [viewing, setViewing] = useState(null);
  const [visible, setVisible] = useState(null);

  const poll = async () => {
    setPolling(true);
    try {
      const got = await api.receiveMessage(url, { MaxNumberOfMessages: 10 });
      setMessages(got);
      const attrs = await api.getQueueAttributes(url);
      setVisible(attrs.ApproximateNumberOfMessages);
    } finally { setPolling(false); }
  };

  return (
    <Container header={<Header variant="h2" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button disabled>Edit poll settings</Button>
        <Button disabled={!polling} onClick={() => setPolling(false)}>Stop polling</Button>
        <Button variant="primary" loading={polling} onClick={poll}>Poll for messages</Button>
      </SpaceBetween>
    }>Receive messages</Header>}>
      <SpaceBetween size="l">
        <Grid gridDefinition={[{ colspan: 3 }, { colspan: 3 }, { colspan: 3 }, { colspan: 3 }]}>
          <FormField label="Messages available"><Box>{visible ?? "-"}</Box></FormField>
          <FormField label="Polling duration"><Box>20</Box></FormField>
          <FormField label="Maximum message count"><Box>10</Box></FormField>
          <FormField label="Polling progress"><Box>{polling ? "In progress" : "Idle"}</Box></FormField>
        </Grid>
        <Table
          variant="container"
          items={messages}
          trackBy="MessageId"
          selectionType="multi"
          selectedItems={sel}
          onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          header={<Header variant="h3" counter={`(${messages.length})`} actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button disabled={sel.length !== 1} onClick={() => setViewing(sel[0])}>View details</Button>
              <Button disabled={!sel.length} onClick={async () => {
                for (const m of sel) await api.deleteMessage(url, m.ReceiptHandle);
                setMessages(messages.filter((m) => !sel.includes(m))); setSel([]);
              }}>Delete</Button>
            </SpaceBetween>
          }>Messages</Header>}
          columnDefinitions={[
            { id: "id", header: "ID", cell: (m) => m.MessageId },
            { id: "sent", header: "Sent", cell: () => "just now" },
            { id: "size", header: "Size", cell: (m) => `${m.Body?.length ?? 0} bytes` },
            { id: "rc", header: "Receive count", cell: (m) => m.Attributes?.ApproximateReceiveCount ?? "1" },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No messages</b></Box>}
        />
      </SpaceBetween>
      <Modal visible={!!viewing} onDismiss={() => setViewing(null)} header="Message details" size="large">
        {viewing && <Textarea readOnly rows={8} value={viewing.Body} ariaLabel="Message body" />}
      </Modal>
    </Container>
  );
}

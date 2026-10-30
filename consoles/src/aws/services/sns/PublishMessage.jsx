import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import Table from "@cloudscape-design/components/table";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const TYPES = ["String", "Number", "Binary"];

export default function PublishMessage({ params }) {
  const name = params.name;
  const notify = useNotify();
  const t = useAsync(async () => { const arn = await api.topicByName(name); return { arn, attrs: await api.getTopicAttributes(arn) }; }, [name]);
  const [subject, setSubject] = useState("");
  const [groupId, setGroupId] = useState("");
  const [dedupId, setDedupId] = useState("");
  const [structure, setStructure] = useState("identical");
  const [body, setBody] = useState("");
  const [attrs, setAttrs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (t.loading) return <Box padding="xxl" textAlign="center">Loading…</Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const fifo = t.data.attrs.FifoTopic === "true";

  const submit = async () => {
    if (!body || (fifo && !groupId)) return;
    setBusy(true); setError(null);
    try {
      await api.publish({
        topicArn: t.data.arn, message: body, subject: subject || undefined,
        messageStructure: structure === "custom" ? "json" : undefined,
        messageGroupId: fifo ? groupId : undefined, messageDeduplicationId: fifo && dedupId ? dedupId : undefined,
        attributes: attrs.filter((a) => a.name),
      });
      notify.success(`Successfully published message to "${name}".`);
      navigate("sns", "topics", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Publish message to topic</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={href("sns", "topics", name)} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Publish message</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Message details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Topic ARN"><Box>{t.data.arn}</Box></FormField>
                <FormField label="Subject - optional"><Input value={subject} placeholder="Enter the message subject" onChange={({ detail }) => setSubject(detail.value)} ariaLabel="Subject" /></FormField>
                <FormField label="Message group ID" errorText={fifo && !groupId ? "Message group ID is required for FIFO topics." : null}>
                  <Input value={groupId} disabled={!fifo} onChange={({ detail }) => setGroupId(detail.value)} ariaLabel="Message group ID" /></FormField>
                <FormField label="Message deduplication ID - optional"><Input value={dedupId} disabled={!fifo} onChange={({ detail }) => setDedupId(detail.value)} ariaLabel="Message deduplication ID" /></FormField>
              </SpaceBetween>
            </Container>

            <NotSimulatedContainer title="Time to Live (TTL) - optional" note="Amazon SNS's native Publish API has no message TTL parameter for topic deliveries." />

            <Container header={<Header variant="h2">Message body</Header>}>
              <SpaceBetween size="l">
                <FormField label="Message structure">
                  <RadioGroup value={structure} onChange={({ detail }) => setStructure(detail.value)} items={[
                    { value: "identical", label: "Identical payload for all delivery protocols." },
                    { value: "custom", label: "Custom payload for each delivery protocol." },
                  ]} />
                </FormField>
                <FormField label="Message body to send to the endpoint" stretch
                  constraintText={structure === "custom" ? 'JSON object with a "default" key, e.g. {"default":"hi","sqs":"hi via sqs"}' : undefined}>
                  <Textarea rows={10} value={body} onChange={({ detail }) => setBody(detail.value)} ariaLabel="Message body" />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Message attributes</Header>}>
              <Table
                items={attrs}
                columnDefinitions={[
                  { id: "type", header: "Type", cell: (a, i) => <Select selectedOption={{ label: a.type, value: a.type }} options={TYPES.map((v) => ({ label: v, value: v }))}
                      onChange={({ detail }) => setAttrs(attrs.map((x, j) => j === i ? { ...x, type: detail.selectedOption.value } : x))} /> },
                  { id: "name", header: "Name", cell: (a, i) => <Input value={a.name} onChange={({ detail }) => setAttrs(attrs.map((x, j) => j === i ? { ...x, name: detail.value } : x))} ariaLabel="Attribute name" /> },
                  { id: "value", header: "Value", cell: (a, i) => <Input value={a.value} onChange={({ detail }) => setAttrs(attrs.map((x, j) => j === i ? { ...x, value: detail.value } : x))} ariaLabel="Attribute value" /> },
                  { id: "remove", header: "", cell: (a, i) => <Button variant="icon" iconName="remove" ariaLabel="Remove" onClick={() => setAttrs(attrs.filter((_, j) => j !== i))} /> },
                ]}
                footer={<Button onClick={() => setAttrs([...attrs, { type: "String", name: "", value: "" }])}>Add another attribute</Button>}
                empty={<Box textAlign="center" color="inherit">No message attributes</Box>}
              />
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}

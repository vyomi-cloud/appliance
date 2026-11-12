import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
import Toggle from "@cloudscape-design/components/toggle";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Textarea from "@cloudscape-design/components/textarea";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const PROTOCOLS = ["Amazon Data Firehose", "Amazon SQS", "AWS Lambda", "Email", "Email-JSON", "HTTP", "HTTPS", "Platform application endpoint", "SMS"];
const WIRE_PROTOCOL = { "Amazon Data Firehose": "firehose", "Amazon SQS": "sqs", "AWS Lambda": "lambda", Email: "email", "Email-JSON": "email-json", HTTP: "http", HTTPS: "https", "Platform application endpoint": "application", SMS: "sms" };
const RAW_ELIGIBLE = ["Amazon SQS", "HTTP", "HTTPS", "Amazon Data Firehose"];

export default function CreateSubscription({ query }) {
  const notify = useNotify();
  const topics = useAsync(async () => Promise.all((await api.listTopics()).map(async (arn) => ({ arn, name: api.topicName(arn) }))), []);
  const [topicArn, setTopicArn] = useState(null);
  const [protocol, setProtocol] = useState(null);
  const [endpoint, setEndpoint] = useState("");
  const [raw, setRaw] = useState(false);
  const [filterOn, setFilterOn] = useState(false);
  const [filterScope, setFilterScope] = useState("Message attributes");
  const [filterJson, setFilterJson] = useState("{\n  \n}");
  const [dlqOn, setDlqOn] = useState(false);
  const [dlqArn, setDlqArn] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (!topicArn && !topics.loading && topics.data?.length) {
    const preselected = topics.data.find((t) => t.name === query?.topic);
    setTopicArn((preselected || topics.data[0]).arn);
  }
  const selectedTopic = { label: topics.data?.find((t) => t.arn === topicArn)?.name || "", value: topicArn };

  const submit = async () => {
    setTouched(true);
    if (!topicArn || !protocol || (protocol !== "SMS" && !endpoint)) return;
    setBusy(true); setError(null);
    try {
      const attrs = {};
      if (RAW_ELIGIBLE.includes(protocol) && raw) attrs.RawMessageDelivery = "true";
      if (filterOn && filterJson.trim()) { attrs.FilterPolicy = filterJson; attrs.FilterPolicyScope = filterScope === "Message body" ? "MessageBody" : "MessageAttributes"; }
      if (dlqOn && dlqArn) attrs.RedrivePolicy = JSON.stringify({ deadLetterTargetArn: dlqArn });
      const arn = await api.subscribe(topicArn, WIRE_PROTOCOL[protocol], endpoint, attrs);
      notify.success("Subscription created.");
      navigate("sns", "subscriptions", api.subId(arn));
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create subscription</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={href("sns", "subscriptions")} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create subscription</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Topic ARN" errorText={touched && !topicArn ? "Choose a topic." : null} description="Searchable autosuggest of topic ARNs">
                  <Select selectedOption={topicArn ? selectedTopic : null} placeholder="MyTopic" statusType={topics.loading ? "loading" : "finished"}
                    options={(topics.data || []).map((t) => ({ label: t.name, value: t.arn }))}
                    onChange={({ detail }) => setTopicArn(detail.selectedOption.value)} />
                </FormField>
                <FormField label="Protocol" errorText={touched && !protocol ? "Choose a protocol." : null} description="The type of endpoint to subscribe">
                  <Select selectedOption={protocol ? { label: protocol, value: protocol } : null} placeholder="Select protocol"
                    options={PROTOCOLS.map((p) => ({ label: p, value: p }))} onChange={({ detail }) => setProtocol(detail.selectedOption.value)} />
                </FormField>
                <FormField label="Endpoint" errorText={touched && protocol !== "SMS" && !endpoint ? "Enter an endpoint." : null}
                  description="Select for SQS/Lambda/Firehose; text for email, HTTP/S, SMS">
                  <Input value={endpoint} onChange={({ detail }) => setEndpoint(detail.value)} ariaLabel="Endpoint" />
                </FormField>
                <Checkbox checked={raw} disabled={!RAW_ELIGIBLE.includes(protocol)} onChange={({ detail }) => setRaw(detail.checked)}>Enable raw message delivery</Checkbox>
              </SpaceBetween>
            </Container>

            <ExpandableSection headerText="Subscription filter policy - optional" variant="container">
              <SpaceBetween size="l">
                <FormField label="Subscription filter policy" description="This policy filters the messages that a subscriber receives.">
                  <Toggle checked={filterOn} onChange={({ detail }) => setFilterOn(detail.checked)}>{filterOn ? "Enabled" : "Disabled"}</Toggle>
                </FormField>
                <FormField label="Filter policy scope">
                  <RadioGroup value={filterScope} disabled={!filterOn} onChange={({ detail }) => setFilterScope(detail.value)}
                    items={[{ value: "Message attributes", label: "Message attributes" }, { value: "Message body", label: "Message body" }]} />
                </FormField>
                <FormField label="JSON editor">
                  <Textarea rows={8} value={filterJson} disabled={!filterOn} onChange={({ detail }) => setFilterJson(detail.value)} spellcheck={false} />
                </FormField>
              </SpaceBetween>
            </ExpandableSection>

            <ExpandableSection headerText="Redrive policy (dead-letter queue) - optional" variant="container">
              <SpaceBetween size="l">
                <FormField label="Redrive policy (dead-letter queue)" description="Send undeliverable messages to a dead-letter queue.">
                  <Toggle checked={dlqOn} onChange={({ detail }) => setDlqOn(detail.checked)}>{dlqOn ? "Enabled" : "Disabled"}</Toggle>
                </FormField>
                <FormField label="Dead-letter queue">
                  <Input value={dlqArn} disabled={!dlqOn} placeholder="arn:aws:sqs:us-east-1:123456789012:my-dlq" onChange={({ detail }) => setDlqArn(detail.value)} ariaLabel="Dead-letter queue ARN" />
                </FormField>
              </SpaceBetween>
            </ExpandableSection>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}

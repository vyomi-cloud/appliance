/* Create topic / Edit topic — one long form, like the console. Type and Name become
 * read-only in edit mode (SNS can't rename a topic or convert Standard <-> FIFO). */
import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Checkbox from "@cloudscape-design/components/checkbox";
import Toggle from "@cloudscape-design/components/toggle";
import Select from "@cloudscape-design/components/select";
import Textarea from "@cloudscape-design/components/textarea";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import TagEditor from "@cloudscape-design/components/tag-editor";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulatedContainer } from "../../kit/common.jsx";
import { saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const ACCOUNT_ID = "123456789012";
const DEFAULT_POLICY = (arn) => JSON.stringify({
  Version: "2008-10-17", Id: "__default_policy_ID",
  Statement: [{ Sid: "__default_statement_ID", Effect: "Allow", Principal: { AWS: "*" },
    Action: ["SNS:GetTopicAttributes", "SNS:SetTopicAttributes", "SNS:AddPermission", "SNS:RemovePermission",
             "SNS:DeleteTopic", "SNS:Subscribe", "SNS:ListSubscriptionsByTopic", "SNS:Publish"],
    Resource: arn, Condition: { StringEquals: { "AWS:SourceOwner": ACCOUNT_ID } } }],
}, null, 2);

export default function CreateTopic({ params, query }) {
  const notify = useNotify();
  const editing = !!params?.name;
  const prefillName = query?.name || "";
  const [fifo, setFifo] = useState(false);
  const [name, setName] = useState(prefillName);
  const [throughput, setThroughput] = useState("group");
  const [displayName, setDisplayName] = useState("");
  const [dedup, setDedup] = useState(false);
  const [encryption, setEncryption] = useState(false);
  const [kmsKey, setKmsKey] = useState({ label: "(Default) alias/aws/sns", value: "alias/aws/sns" });
  const [accessMethod, setAccessMethod] = useState("Basic");
  const [publishers, setPublishers] = useState("Only the topic owner");
  const [policyJson, setPolicyJson] = useState(DEFAULT_POLICY("arn:aws:sns:us-east-1:123456789012:topic"));
  const [archivePolicy, setArchivePolicy] = useState(false);
  const [retentionDays, setRetentionDays] = useState("365");
  const [feedbackSqs, setFeedbackSqs] = useState(false);
  const [tracing, setTracing] = useState(false);
  const [tags, setTags] = useState([]);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const existing = useAsync(async () => {
    if (!editing) return null;
    const arn = await api.topicByName(params.name);
    const attrs = await api.getTopicAttributes(arn);
    return { arn, attrs };
  }, [editing, params?.name]);

  if (editing && existing.loading) return <Box padding="xxl" textAlign="center">Loading…</Box>;
  if (editing && existing.error) return <ErrorAlert error={existing.error} />;
  if (editing && existing.data && !touched) {
    const a = existing.data.attrs;
    if (a.FifoTopic === "true" && !fifo) setFifo(true);
    if (a.DisplayName && displayName === "") setDisplayName(a.DisplayName);
    if (a.ContentBasedDeduplication === "true" && !dedup) setDedup(true);
    if (a.KmsMasterKeyId && !encryption) { setEncryption(true); setKmsKey({ label: a.KmsMasterKeyId, value: a.KmsMasterKeyId }); }
    if (a.Policy) setPolicyJson(a.Policy);
    if (a.ArchivePolicy && !archivePolicy) setArchivePolicy(true);
    setTouched(true);
  }

  const nameErr = touched && !editing && (!name || (fifo && !/^[A-Za-z0-9_-]{1,251}$/.test(name)) || (!fifo && !/^[A-Za-z0-9_-]{1,256}$/.test(name)))
    ? "Enter a valid topic name." : null;

  const submit = async () => {
    setTouched(true);
    if (!editing && (!name || nameErr)) return;
    setBusy(true); setError(null);
    try {
      let arn;
      const fullName = fifo && !name.endsWith(".fifo") ? `${name}.fifo` : name;
      if (editing) {
        arn = existing.data.arn;
      } else {
        const attrs = {};
        if (fifo) { attrs.FifoTopic = "true"; attrs.ContentBasedDeduplication = dedup ? "true" : "false"; attrs.FifoThroughputScope = throughput === "group" ? "MessageGroup" : "Topic"; }
        if (displayName) attrs.DisplayName = displayName;
        arn = await api.createTopic(fullName, attrs, tags.filter((t) => !t.markedForRemoval && t.key).map(({ key, value }) => ({ key, value })));
      }
      if (editing) {
        await api.setTopicAttribute(arn, "DisplayName", displayName);
        if (fifo) await api.setTopicAttribute(arn, "ContentBasedDeduplication", dedup ? "true" : "false");
      }
      await api.setTopicAttribute(arn, "KmsMasterKeyId", encryption ? kmsKey.value : "");
      await api.setTopicAttribute(arn, "Policy", accessMethod === "Advanced" ? policyJson : DEFAULT_POLICY(arn));
      await api.setTopicAttribute(arn, "ArchivePolicy", archivePolicy ? JSON.stringify({ MessageRetentionPeriod: Number(retentionDays) || 365 }) : "");
      await api.setTopicAttribute(arn, "TracingConfig", tracing ? "Active" : "PassThrough");
      await api.setTopicAttribute(arn, "SQSSuccessFeedbackRoleArn", feedbackSqs ? `arn:aws:iam::${ACCOUNT_ID}:role/SNSSuccessFeedback` : "");
      if (feedbackSqs) await api.setTopicAttribute(arn, "SQSSuccessFeedbackSampleRate", "100");
      notify.success(`Successfully ${editing ? "updated" : "created"} topic "${api.topicName(arn)}".`);
      navigate("sns", "topics", api.topicName(arn));
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">{editing ? `Edit ${params.name}` : "Create topic"}</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button formAction="none" variant="link" href={editing ? href("sns", "topics", params.name) : href("sns", "topics")} onFollow={follow}>Cancel</Button>
              <Button variant="primary" loading={busy}>{editing ? "Save changes" : "Create topic"}</Button>
            </SpaceBetween>
          }
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Type" stretch description="Topic type cannot be modified after topic is created">
                  <RadioGroup value={fifo ? "fifo" : "standard"} onChange={({ detail }) => setFifo(detail.value === "fifo")} readOnly={editing}
                    items={[{ value: "fifo", label: "FIFO (first-in, first-out)" }, { value: "standard", label: "Standard" }]} />
                </FormField>
                <FormField label="Name" errorText={nameErr} constraintText="Maximum 256 characters. Alphanumerics, hyphens (-) and underscores (_). FIFO names must end with &quot;.fifo&quot;.">
                  <SpaceBetween direction="horizontal" size="xs">
                    <Input value={name} placeholder="MyTopic" disabled={editing} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" />
                    {fifo && <Box>.fifo</Box>}
                  </SpaceBetween>
                </FormField>
                {fifo && (
                  <FormField label="High throughput" description="Once enabled, this configuration cannot be modified.">
                    <RadioGroup value={throughput} onChange={({ detail }) => setThroughput(detail.value)} readOnly={editing}
                      items={[{ value: "group", label: "Message group scope (Recommended for highest throughput)" }, { value: "topic", label: "Topic scope" }]} />
                  </FormField>
                )}
                <FormField label="Display name - optional" constraintText="Maximum 100 characters." description="Only the first 10 characters are displayed in an SMS message.">
                  <Input value={displayName} placeholder="My Topic" onChange={({ detail }) => setDisplayName(detail.value)} ariaLabel="Display name" />
                </FormField>
                {fifo && (
                  <FormField label="Content-based message deduplication">
                    <Checkbox checked={dedup} onChange={({ detail }) => setDedup(detail.checked)}>Turn on message deduplication</Checkbox>
                  </FormField>
                )}
              </SpaceBetween>
            </Container>

            <NotSimulatedContainer title="Maximum message size" note="Amazon SNS doesn't let you configure a topic's maximum message size — it's fixed at 256 KiB." />

            <ExpandableSection headerText="Encryption - optional" variant="container" defaultExpanded={encryption}>
              <SpaceBetween size="l">
                <FormField label="Encryption" description="Adds at-rest (server-side) encryption to your topic.">
                  <Toggle checked={encryption} onChange={({ detail }) => setEncryption(detail.checked)}>{encryption ? "Enabled" : "Disabled"}</Toggle>
                </FormField>
                <FormField label="AWS KMS key">
                  <Select selectedOption={kmsKey} disabled={!encryption} onChange={({ detail }) => setKmsKey(detail.selectedOption)}
                    options={[{ label: "(Default) alias/aws/sns", value: "alias/aws/sns" }]} />
                </FormField>
              </SpaceBetween>
            </ExpandableSection>

            <ExpandableSection headerText="Access policy - optional" variant="container">
              <SpaceBetween size="l">
                <FormField label="Choose method">
                  <RadioGroup value={accessMethod} onChange={({ detail }) => setAccessMethod(detail.value)} items={[{ value: "Basic", label: "Basic" }, { value: "Advanced", label: "Advanced" }]} />
                </FormField>
                {accessMethod === "Basic" ? (
                  <>
                    <FormField label="Publishers" description="Specify who can publish messages to the topic.">
                      <Select selectedOption={{ label: publishers, value: publishers }} onChange={({ detail }) => setPublishers(detail.selectedOption.value)}
                        options={["Only the topic owner", "Everyone", "Only the specified AWS accounts"].map((v) => ({ label: v, value: v }))} />
                    </FormField>
                    <FormField label="Subscribers" description="Specify who can subscribe to this topic.">
                      <Select selectedOption={{ label: "Only the topic owner", value: "Only the topic owner" }} onChange={() => {}}
                        options={["Only the topic owner", "Everyone", "Only the specified AWS accounts", "Only requesters with certain endpoints"].map((v) => ({ label: v, value: v }))} />
                    </FormField>
                    <FormField label="JSON preview">
                      <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{DEFAULT_POLICY("arn:aws:sns:us-east-1:123456789012:" + (name || "topic"))}</pre></Box>
                    </FormField>
                  </>
                ) : (
                  <FormField label="JSON preview" description="Vyomi stores and returns this document exactly as written; it is never evaluated to allow or deny a request.">
                    <Textarea rows={12} value={policyJson} onChange={({ detail }) => setPolicyJson(detail.value)} spellcheck={false} />
                  </FormField>
                )}
              </SpaceBetween>
            </ExpandableSection>

            <ExpandableSection headerText="Archive policy - new, optional" variant="container">
              <SpaceBetween size="l">
                <FormField label="Archive policy" description="Activate archive policy and select the desired retention period.">
                  <Toggle checked={archivePolicy} onChange={({ detail }) => setArchivePolicy(detail.checked)}>{archivePolicy ? "Enabled" : "Disabled"}</Toggle>
                </FormField>
                {archivePolicy && (
                  <FormField label="Message retention period (days)">
                    <Input type="number" value={retentionDays} onChange={({ detail }) => setRetentionDays(detail.value)} ariaLabel="Message retention period" />
                  </FormField>
                )}
              </SpaceBetween>
            </ExpandableSection>

            <ExpandableSection headerText="Message delivery status logging - optional" variant="container">
              <SpaceBetween size="l">
                <FormField label="Choose protocols for log delivery status" description="Standard topics also list AWS Lambda, HTTP/S, Data Firehose, Platform application endpoint.">
                  <Checkbox checked={feedbackSqs} onChange={({ detail }) => setFeedbackSqs(detail.checked)}>Amazon SQS</Checkbox>
                </FormField>
                <Box variant="small" color="text-body-secondary">{saveNotice("sns.topic.delivery-status-logging") || "Vyomi stores the success/failure feedback role and sample rate exactly as configured, but never emits the CloudWatch logs."}</Box>
              </SpaceBetween>
            </ExpandableSection>

            <Container header={<Header variant="h2" counter={`(${tags.filter((t) => !t.markedForRemoval).length})`}>Tags - optional</Header>}>
              <FormField label="Tags" description="No tags associated with the resource. You can add up to 50 tags.">
                <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={{ keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo", undoPrompt: "This tag will be removed upon saving changes", loading: "Loading tags", keyPlaceholder: "Enter key", valuePlaceholder: "Enter value", emptyTags: "No tags associated with the resource.", tooManyKeysSuggestion: "", tooManyValuesSuggestion: "", keysSuggestionLoading: "", keysSuggestionError: "", valuesSuggestionLoading: "", valuesSuggestionError: "", emptyKeyError: "You must specify a tag key", maxKeyCharLengthError: "", maxValueCharLengthError: "", duplicateKeyError: "You must specify a unique tag key.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:", tagLimit: () => "You can add up to 50 tags.", tagLimitReached: () => "You have reached the limit of 50 tags.", tagLimitExceeded: () => "You have exceeded the limit of 50 tags." }} />
              </FormField>
            </Container>

            <ExpandableSection headerText="Active tracing - optional" variant="container">
              <FormField label="Active tracing">
                <RadioGroup value={tracing ? "on" : "off"} onChange={({ detail }) => setTracing(detail.value === "on")}
                  items={[{ value: "on", label: "Use active tracing" }, { value: "off", label: "Don't use active tracing" }]} />
              </FormField>
            </ExpandableSection>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}

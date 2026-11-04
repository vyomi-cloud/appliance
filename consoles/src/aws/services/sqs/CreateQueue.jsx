/* Create queue / Edit queue — single-page form, same sections as the real console.
 * All attributes round-trip through SetQueueAttributes/GetQueueAttributes exactly as typed
 * (core/capabilities/aws/sqs.json: sqs.queue.attributes, sqs.queue.tags). */
import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Toggle from "@cloudscape-design/components/toggle";
import Textarea from "@cloudscape-design/components/textarea";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Grid from "@cloudscape-design/components/grid";
import Box from "@cloudscape-design/components/box";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Multiselect from "@cloudscape-design/components/multiselect";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

function NumberUnit({ label, help, constraintText, value, onValueChange, unit, onUnitChange, units, disabled }) {
  return (
    <FormField label={label} description={help} constraintText={constraintText}>
      <Grid gridDefinition={units ? [{ colspan: 8 }, { colspan: 4 }] : [{ colspan: 12 }]}>
        <Input type="number" value={value} disabled={disabled} onChange={({ detail }) => onValueChange(detail.value)} ariaLabel={label} />
        {units && (
          <Select selectedOption={{ value: unit, label: unit }} disabled={disabled}
            onChange={({ detail }) => onUnitChange(detail.selectedOption.value)}
            options={units.map((u) => ({ value: u, label: u }))} ariaLabel={`${label} unit`} />
        )}
      </Grid>
    </FormField>
  );
}

const UNIT_SECONDS = { Seconds: 1, Minutes: 60, Hours: 3600, Days: 86400 };
const toSeconds = (v, unit) => Math.round(Number(v || 0) * UNIT_SECONDS[unit]);

const defaultPolicy = (arn, sendArns, receiveArns) => {
  const stmts = [];
  if (sendArns) stmts.push({ Sid: "SendMessages", Effect: "Allow", Principal: { AWS: sendArns.split(",").map((s) => s.trim()).filter(Boolean) }, Action: "sqs:SendMessage", Resource: arn });
  if (receiveArns) stmts.push({ Sid: "ReceiveMessages", Effect: "Allow", Principal: { AWS: receiveArns.split(",").map((s) => s.trim()).filter(Boolean) }, Action: ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource: arn });
  if (!stmts.length) return "";
  return JSON.stringify({ Version: "2012-10-17", Id: `${arn}/SQSDefaultPolicy`, Statement: stmts }, null, 2);
};

export default function CreateQueue({ params }) {
  const isEdit = !!params?.name;
  const existing = useAsync(async () => {
    if (!isEdit) return null;
    const url = await api.getQueueUrl(params.name);
    return { url, attrs: await api.getQueueAttributes(url) };
  }, [params?.name]);

  if (isEdit && existing.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (isEdit && existing.error) return <ErrorAlert error={existing.error} />;
  // A fresh child per queue, mounted only once its data (for edit) is ready — so every
  // useState below initializes from the real loaded attributes exactly once, cleanly.
  return <QueueForm isEdit={isEdit} initialName={params?.name || ""} existing={existing.data} />;
}

function QueueForm({ isEdit, initialName, existing }) {
  const notify = useNotify();
  const a = existing?.attrs || {};

  const [type, setType] = useState(isEdit ? (String(a.FifoQueue).toLowerCase() === "true" ? "FIFO" : "Standard") : "Standard");
  const [name, setName] = useState(initialName);
  const fifo = type === "FIFO";

  const [visVal, setVisVal] = useState(String(a.VisibilityTimeout ?? 30)); const [visUnit, setVisUnit] = useState("Seconds");
  const [retVal, setRetVal] = useState(a.MessageRetentionPeriod ? String(Math.round(a.MessageRetentionPeriod / 86400)) : "4"); const [retUnit, setRetUnit] = useState("Days");
  const [delayVal, setDelayVal] = useState(String(a.DelaySeconds ?? 0)); const [delayUnit, setDelayUnit] = useState("Seconds");
  const [maxSize, setMaxSize] = useState(a.MaximumMessageSize ? String(Math.round(a.MaximumMessageSize / 1024)) : "1024");
  const [waitTime, setWaitTime] = useState(String(a.ReceiveMessageWaitTimeSeconds ?? 0));
  const [contentDedup, setContentDedup] = useState(String(a.ContentBasedDeduplication).toLowerCase() === "true");
  const [highThroughput, setHighThroughput] = useState(a.FifoThroughputLimit === "perMessageGroupId");

  const [sse, setSse] = useState(a.SqsManagedSseEnabled === undefined ? "Enabled" : (String(a.SqsManagedSseEnabled).toLowerCase() === "false" && !a.KmsMasterKeyId ? "Disabled" : "Enabled"));
  const [keyType, setKeyType] = useState(a.KmsMasterKeyId ? "AWS Key Management Service key (SSE-KMS)" : "Amazon SQS key (SSE-SQS)");
  const [cmk, setCmk] = useState(a.KmsMasterKeyId || "(Default) alias/aws/sqs");
  const [reuseVal, setReuseVal] = useState(a.KmsDataKeyReusePeriodSeconds ? String(Math.round(a.KmsDataKeyReusePeriodSeconds / 60)) : "5"); const [reuseUnit, setReuseUnit] = useState("Minutes");

  const [policyMethod, setPolicyMethod] = useState("Basic");
  const [sendWho, setSendWho] = useState("Only the queue owner");
  const [receiveWho, setReceiveWho] = useState("Only the queue owner");
  const [sendArns, setSendArns] = useState(""); const [receiveArns, setReceiveArns] = useState("");
  const [policyJson, setPolicyJson] = useState(a.Policy || "");

  const allowPolicy = (() => { try { return a.RedriveAllowPolicy ? JSON.parse(a.RedriveAllowPolicy) : null; } catch { return null; } })();
  const [allowEnabled, setAllowEnabled] = useState(!!allowPolicy);
  const [allowPermission, setAllowPermission] = useState(allowPolicy?.redrivePermission === "byQueue" ? "By queue" : allowPolicy?.redrivePermission === "denyAll" ? "Deny all" : "Allow all");
  const [allowSourceArns, setAllowSourceArns] = useState(allowPolicy?.redrivePermission === "byQueue" ? (allowPolicy.sourceQueueArns || []) : []);

  const redrive = (() => { try { return a.RedrivePolicy ? JSON.parse(a.RedrivePolicy) : null; } catch { return null; } })();
  const [dlqEnabled, setDlqEnabled] = useState(!!redrive);
  const [dlqArn, setDlqArn] = useState(redrive?.deadLetterTargetArn || "");
  const [maxReceives, setMaxReceives] = useState(String(redrive?.maxReceiveCount ?? 10));
  const otherQueues = useAsync(() => api.listQueues(), []);

  const [tags, setTags] = useState([]);
  const existingTags = useAsync(() => (isEdit && existing ? api.listQueueTags(existing.url) : Promise.resolve({})), [isEdit, existing?.url]);
  const loadedTags = existingTags.data ? Object.entries(existingTags.data).map(([key, value]) => ({ key, value })) : [];

  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched && !/^[a-zA-Z0-9_-]{1,80}$/.test(name.replace(/\.fifo$/, "")) ? "Queue name can only contain alphanumeric characters, hyphens and underscores, up to 80 characters." : null;
  const fifoSuffix = fifo && name && !name.endsWith(".fifo");

  const submit = async () => {
    setTouched(true);
    if (!name || nameErr) return;
    setBusy(true); setError(null);
    const finalName = fifo && !name.endsWith(".fifo") ? `${name}.fifo` : name;
    const policy = policyMethod === "Advanced" ? policyJson : defaultPolicy(`arn:aws:sqs:us-east-1:*:${finalName}`, sendWho !== "Only the queue owner" ? sendArns : "", receiveWho !== "Only the queue owner" ? receiveArns : "");
    const attrs = {
      VisibilityTimeout: String(toSeconds(visVal, visUnit)),
      MessageRetentionPeriod: String(toSeconds(retVal, retUnit)),
      DelaySeconds: String(toSeconds(delayVal, delayUnit)),
      MaximumMessageSize: String(Number(maxSize || 0) * 1024),
      ReceiveMessageWaitTimeSeconds: String(waitTime),
      ...(fifo ? { FifoQueue: "true", ContentBasedDeduplication: String(contentDedup), FifoThroughputLimit: highThroughput ? "perMessageGroupId" : "perQueue", DeduplicationScope: highThroughput ? "messageGroup" : "queue" } : {}),
      SqsManagedSseEnabled: String(sse === "Enabled" && keyType !== "AWS Key Management Service key (SSE-KMS)"),
      ...(sse === "Enabled" && keyType === "AWS Key Management Service key (SSE-KMS)" ? { KmsMasterKeyId: cmk, KmsDataKeyReusePeriodSeconds: String(toSeconds(reuseVal, reuseUnit)) } : {}),
      ...(policy ? { Policy: policy } : {}),
      ...(allowEnabled ? { RedriveAllowPolicy: JSON.stringify({
        redrivePermission: allowPermission === "By queue" ? "byQueue" : allowPermission === "Deny all" ? "denyAll" : "allowAll",
        ...(allowPermission === "By queue" ? { sourceQueueArns: allowSourceArns } : {}),
      }) } : {}),
      ...(dlqEnabled && dlqArn ? { RedrivePolicy: JSON.stringify({ deadLetterTargetArn: dlqArn, maxReceiveCount: Number(maxReceives) }) } : {}),
    };
    const finalTags = Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value || ""]));
    try {
      if (isEdit) {
        await api.setQueueAttributes(existing.url, attrs);
        const before = existingTags.data || {};
        const removed = Object.keys(before).filter((k) => !(k in finalTags));
        if (removed.length) await api.untagQueue(existing.url, removed);
        if (Object.keys(finalTags).length) await api.tagQueue(existing.url, finalTags);
        notify.success(`Queue "${finalName}" updated.${saveNotice("sqs.queue.attributes")}`);
        navigate("sqs", "queues", finalName);
      } else {
        await api.createQueue({ QueueName: finalName, Attributes: attrs, tags: finalTags });
        notify.success(`Queue "${finalName}" created.`);
        navigate("sqs", "queues", finalName);
      }
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">{isEdit ? `Edit ${initialName}` : "Create queue"}</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={isEdit ? href("sqs", "queues", initialName) : href("sqs", "queues")} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>{isEdit ? "Save" : "Create queue"}</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Type" stretch>
                  <RadioGroup value={type} disabled={isEdit} onChange={({ detail }) => setType(detail.value)} items={[
                    { value: "Standard", label: "Standard", description: "Choose the queue type for your application or cloud infrastructure." },
                    { value: "FIFO", label: "FIFO" },
                  ]} />
                </FormField>
                <FormField label="Name" errorText={nameErr} constraintText={fifo ? "FIFO queue name must end with the .fifo suffix" : "Case-sensitive, up to 80 characters: alphanumeric, hyphens (-), underscores (_)"}>
                  <Input value={name} disabled={isEdit} onChange={({ detail }) => setName(detail.value)} placeholder="MyQueue" ariaLabel="Name" />
                </FormField>
                {fifoSuffix && <Box variant="small" color="text-body-secondary">Will be created as <b>{name}.fifo</b></Box>}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Configuration</Header>}>
              <SpaceBetween size="l">
                <NumberUnit label="Visibility timeout" help="The length of time a message received from the queue will be invisible to other consumers." constraintText="Should be between 0 seconds and 12 hours." value={visVal} onValueChange={setVisVal} unit={visUnit} onUnitChange={setVisUnit} units={["Seconds", "Minutes", "Hours"]} />
                <NumberUnit label="Message retention period" help="The amount of time messages will be kept." constraintText="Should be between 1 minute and 14 days." value={retVal} onValueChange={setRetVal} unit={retUnit} onUnitChange={setRetUnit} units={["Minutes", "Hours", "Days"]} />
                <NumberUnit label="Delivery delay" help="The time in seconds that the delivery of all messages in the queue is delayed." constraintText="Should be between 0 seconds and 15 minutes." value={delayVal} onValueChange={setDelayVal} unit={delayUnit} onUnitChange={setDelayUnit} units={["Seconds", "Minutes"]} />
                <NumberUnit label="Maximum message size" help="Unit: KiB" constraintText="Should be between 1 KiB and 1024 KiB." value={maxSize} onValueChange={setMaxSize} />
                <NumberUnit label="Receive message wait time" help="Unit: Seconds" constraintText="Should be between 0 and 20 seconds." value={waitTime} onValueChange={setWaitTime} />
                {fifo && <Toggle checked={contentDedup} onChange={({ detail }) => setContentDedup(detail.checked)}>Content-based deduplication</Toggle>}
                {fifo && <Toggle checked={highThroughput} onChange={({ detail }) => setHighThroughput(detail.checked)}>High throughput FIFO queue</Toggle>}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Encryption</Header>}>
              <SpaceBetween size="l">
                <FormField label="Server-side encryption">
                  <RadioGroup value={sse} onChange={({ detail }) => setSse(detail.value)} items={[{ value: "Disabled", label: "Disabled" }, { value: "Enabled", label: "Enabled" }]} />
                </FormField>
                {sse === "Enabled" && (
                  <FormField label="Encryption key type">
                    <RadioGroup value={keyType} onChange={({ detail }) => setKeyType(detail.value)} items={[
                      { value: "Amazon SQS key (SSE-SQS)", label: "Amazon SQS key (SSE-SQS)" },
                      { value: "AWS Key Management Service key (SSE-KMS)", label: "AWS Key Management Service key (SSE-KMS)" },
                    ]} />
                  </FormField>
                )}
                {sse === "Enabled" && keyType === "AWS Key Management Service key (SSE-KMS)" && (
                  <>
                    <FormField label="Customer master key"><Input value={cmk} onChange={({ detail }) => setCmk(detail.value)} ariaLabel="Customer master key" /></FormField>
                    <NumberUnit label="Data key reuse period" value={reuseVal} onValueChange={setReuseVal} unit={reuseUnit} onUnitChange={setReuseUnit} units={["Minutes", "Hours"]} />
                  </>
                )}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Access policy</Header>}>
              <SpaceBetween size="l">
                <FormField label="Choose method">
                  <RadioGroup value={policyMethod} onChange={({ detail }) => setPolicyMethod(detail.value)} items={[{ value: "Basic", label: "Basic" }, { value: "Advanced", label: "Advanced" }]} />
                </FormField>
                {policyMethod === "Basic" ? (
                  <>
                    <FormField label="Define who can send messages to the queue">
                      <RadioGroup value={sendWho} onChange={({ detail }) => setSendWho(detail.value)} items={[{ value: "Only the queue owner", label: "Only the queue owner" }, { value: "Only the specified AWS accounts, IAM users and roles", label: "Only the specified AWS accounts, IAM users and roles" }]} />
                    </FormField>
                    {sendWho !== "Only the queue owner" && <FormField label="Sender ARNs"><Input value={sendArns} onChange={({ detail }) => setSendArns(detail.value)} placeholder="arn:aws:iam::111111111111:root, ..." ariaLabel="Sender ARNs" /></FormField>}
                    <FormField label="Define who can receive messages from the queue">
                      <RadioGroup value={receiveWho} onChange={({ detail }) => setReceiveWho(detail.value)} items={[{ value: "Only the queue owner", label: "Only the queue owner" }, { value: "Only the specified AWS accounts, IAM users and roles", label: "Only the specified AWS accounts, IAM users and roles" }]} />
                    </FormField>
                    {receiveWho !== "Only the queue owner" && <FormField label="Receiver ARNs"><Input value={receiveArns} onChange={({ detail }) => setReceiveArns(detail.value)} placeholder="arn:aws:iam::111111111111:root, ..." ariaLabel="Receiver ARNs" /></FormField>}
                    <FormField label="JSON (read-only)"><Textarea readOnly rows={8} value={defaultPolicy("arn:aws:sqs:us-east-1:*:" + (name || "queue"), sendWho !== "Only the queue owner" ? sendArns : "", receiveWho !== "Only the queue owner" ? receiveArns : "") || "{}"} ariaLabel="Policy JSON" /></FormField>
                  </>
                ) : (
                  <FormField label="JSON" description="Edit the access policy document directly."><Textarea rows={10} value={policyJson} onChange={({ detail }) => setPolicyJson(detail.value)} ariaLabel="Policy JSON" /></FormField>
                )}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Redrive allow policy - Optional</Header>}>
              <SpaceBetween size="l">
                <FormField label="Select which source queues can use this queue as the dead-letter queue.">
                  <RadioGroup value={allowEnabled ? "Enabled" : "Disabled"} onChange={({ detail }) => setAllowEnabled(detail.value === "Enabled")} items={[{ value: "Disabled", label: "Disabled" }, { value: "Enabled", label: "Enabled" }]} />
                </FormField>
                {allowEnabled && (
                  <FormField label="Redrive permission">
                    <RadioGroup value={allowPermission} onChange={({ detail }) => setAllowPermission(detail.value)} items={[{ value: "Allow all", label: "Allow all" }, { value: "By queue", label: "By queue" }, { value: "Deny all", label: "Deny all" }]} />
                  </FormField>
                )}
                {allowEnabled && allowPermission === "By queue" && (
                  <FormField label="Source queues" description="Select which queues can use this queue as the dead-letter queue.">
                    <Multiselect
                      selectedOptions={allowSourceArns.map((arn) => ({ value: arn, label: (otherQueues.data || []).find((q) => q.attrs.QueueArn === arn)?.name || arn }))}
                      onChange={({ detail }) => setAllowSourceArns(detail.selectedOptions.map((o) => o.value))}
                      options={(otherQueues.data || []).filter((q) => q.name !== name).map((q) => ({ value: q.attrs.QueueArn, label: q.name }))}
                      placeholder="Choose source queues" ariaLabel="Source queues" />
                  </FormField>
                )}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Dead-letter queue - Optional</Header>}>
              <SpaceBetween size="l">
                <FormField label="Set this queue to receive undeliverable messages.">
                  <RadioGroup value={dlqEnabled ? "Enabled" : "Disabled"} onChange={({ detail }) => setDlqEnabled(detail.value === "Enabled")} items={[{ value: "Disabled", label: "Disabled" }, { value: "Enabled", label: "Enabled" }]} />
                </FormField>
                {dlqEnabled && (
                  <>
                    <FormField label="Choose queue">
                      <Select selectedOption={dlqArn ? { value: dlqArn, label: (otherQueues.data || []).find((q) => q.attrs.QueueArn === dlqArn)?.name || dlqArn } : null}
                        onChange={({ detail }) => setDlqArn(detail.selectedOption.value)}
                        placeholder="Choose a queue"
                        options={(otherQueues.data || []).filter((q) => q.name !== name).map((q) => ({ value: q.attrs.QueueArn, label: q.name }))} ariaLabel="Choose queue" />
                    </FormField>
                    <FormField label="Maximum receives" constraintText="Should be between 1 and 1000."><Input type="number" value={maxReceives} onChange={({ detail }) => setMaxReceives(detail.value)} ariaLabel="Maximum receives" /></FormField>
                  </>
                )}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2" description="You can add 49 more tags.">Tags - Optional</Header>}>
              <TagEditor tags={tags.length || !loadedTags.length ? tags : loadedTags} onChange={({ detail }) => setTags(detail.tags)}
                i18nStrings={{ keyHeader: "Key", valueHeader: "Value - optional", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo", undoPrompt: "This tag will be removed upon saving changes", loading: "Loading tags", keyPlaceholder: "Enter key", valuePlaceholder: "Enter value", emptyTags: "No tags are associated with the resource.", tooManyKeysSuggestion: "", tooManyValuesSuggestion: "", keysSuggestionLoading: "", keysSuggestionError: "", valuesSuggestionLoading: "", valuesSuggestionError: "", emptyKeyError: "You must specify a tag key", maxKeyCharLengthError: "The maximum number of characters you can use in a tag key is 128.", maxValueCharLengthError: "The maximum number of characters you can use in a tag value is 256.", duplicateKeyError: "You must specify a unique tag key.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:", tagLimit: (n) => `You can add up to ${n} more tags.`, tagLimitReached: () => "You have reached the limit of 50 tags.", tagLimitExceeded: () => "You have exceeded the limit of 50 tags." }} />
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}

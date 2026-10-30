import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Checkbox from "@cloudscape-design/components/checkbox";
import Toggle from "@cloudscape-design/components/toggle";
import Link from "@cloudscape-design/components/link";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import DeleteModal from "../../kit/DeleteModal.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function TopicDetail({ params, query }) {
  const name = params.name;
  const notify = useNotify();
  const [tab, setTab] = useState(query.tab || "subscriptions");
  const [del, setDel] = useState(false);
  const t = useAsync(async () => {
    const arn = await api.topicByName(name);
    return { arn, attrs: await api.getTopicAttributes(arn) };
  }, [name]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const { arn, attrs } = t.data;
  const fifo = attrs.FifoTopic === "true";

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
        <Button href={href("sns", "topics", name, "edit")} onFollow={follow}>Edit</Button>
        <Button onClick={() => setDel(true)}>Delete</Button>
        <Button variant="primary" href={href("sns", "topics", name, "publish")} onFollow={follow}>Publish message</Button>
      </SpaceBetween>
    }>{name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={3} items={[
          ["Name", name], ["ARN", arn], ["Type", fifo ? "FIFO" : "Standard"],
          ["Display name", attrs.DisplayName || "-"], ["Topic owner", attrs.Owner],
          ...(fifo ? [["Content-based message deduplication", attrs.ContentBasedDeduplication === "true" ? "Enabled" : "Disabled"]] : []),
        ]} />
        <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
          { id: "subscriptions", label: "Subscriptions", content: <SubscriptionsTab arn={arn} name={name} /> },
          { id: "access-policy", label: "Access policy", content: <AccessPolicyTab arn={arn} attrs={attrs} reload={t.reload} /> },
          { id: "data-protection-policy", label: "Data protection policy", content: <DataProtectionTab arn={arn} reload={t.reload} /> },
          { id: "delivery-policy", label: "Delivery policy (HTTP/S)", content: <DeliveryPolicyTab arn={arn} attrs={attrs} reload={t.reload} /> },
          { id: "delivery-status-logging", label: "Delivery status logging", content: <DeliveryStatusTab arn={arn} attrs={attrs} reload={t.reload} /> },
          { id: "encryption", label: "Encryption", content: <EncryptionTab arn={arn} attrs={attrs} reload={t.reload} /> },
          { id: "tags", label: "Tags", content: <TagsTab arn={arn} /> },
          { id: "integrations", label: "Integrations", content: <NotSimulatedContainer title="Integrations" feature="SNS console service integrations (CloudWatch, EventBridge Pipes, …)" /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={del} resourceType="topic" names={[name]} confirmText="delete me" onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteTopic(arn); notify.success(`"${name}" deleted.`); navigate("sns", "topics"); }} />
    </ContentLayout>
  );
}

function SubscriptionsTab({ arn, name }) {
  const notify = useNotify();
  const s = useAsync(() => api.listSubscriptionsByTopic(arn), [arn]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const data = (s.data || []).map((sub) => ({ ...sub, id: sub.pending ? "PendingConfirmation" : api.subId(sub.arn), key: `${sub.topicArn}|${sub.protocol}|${sub.endpoint}` }));
  return (
    <>
      <ResourceTable
        resourceName="Subscriptions"
        items={data}
        trackBy="key"
        loading={s.loading}
        error={s.error}
        onRefresh={s.reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        columns={[
          { id: "id", header: "ID", isRowHeader: true, cell: (x) => x.pending ? x.id : <Link href={href("sns", "subscriptions", x.id)} onFollow={follow}>{x.id}</Link> },
          { id: "endpoint", header: "Endpoint", cell: (x) => x.endpoint },
          { id: "status", header: "Status", cell: (x) => <StatusIndicator type={x.pending ? "pending" : "success"}>{x.pending ? "Pending confirmation" : "Confirmed"}</StatusIndicator> },
          { id: "protocol", header: "Protocol", cell: (x) => x.protocol },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1 || sel[0].pending} href={sel.length === 1 && !sel[0].pending ? href("sns", "subscriptions", sel[0].id) : undefined} onFollow={follow}>Edit</Button>
            <Button disabled={!sel.length || sel.some((x) => x.pending)} onClick={() => setDel(true)}>Delete</Button>
            <Button disabled={sel.length !== 1} onClick={async () => { try { await api.subscribe(sel[0].topicArn, sel[0].protocol, sel[0].endpoint); notify.success("Requested a new confirmation message."); } catch (e) { notify.error(e); } }}>Request confirmation</Button>
            <Button disabled={sel.length !== 1} onClick={() => setConfirmOpen(true)}>Confirm subscription</Button>
            <Button variant="primary" href={`${href("sns", "create-subscription")}?topic=${encodeURIComponent(name)}`} onFollow={follow}>Create subscription</Button>
          </SpaceBetween>
        }
        empty={{ title: "No subscriptions found", action: <Button href={`${href("sns", "create-subscription")}?topic=${encodeURIComponent(name)}`} onFollow={follow}>Create subscription</Button> }}
      />
      <DeleteModal visible={del} resourceType="subscription" names={sel.map((x) => x.id)} confirmText="delete me" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const x of sel) await api.unsubscribe(x.arn); notify.success("Subscription deleted."); setSel([]); s.reload(); }} />
      <Modal visible={confirmOpen} onDismiss={() => setConfirmOpen(false)} header="Confirm subscription"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true); setError(null);
            try { await api.confirmSubscription(arn, token); notify.success("Subscription confirmed."); setConfirmOpen(false); setToken(""); s.reload(); }
            catch (e) { setError(e); } finally { setBusy(false); }
          }}>Confirm subscription</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Confirmation token" description="The Token from the subscription confirmation message sent to the endpoint.">
            <Input value={token} onChange={({ detail }) => setToken(detail.value)} ariaLabel="Confirmation token" />
          </FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
}

function AccessPolicyTab({ arn, attrs, reload }) {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(attrs.Policy || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <CapabilityContainer id="sns.topic.access-policy" title="Access policy" actions={
      editing ? null : <Button onClick={() => { setVal(attrs.Policy || ""); setEditing(true); }}>Edit</Button>
    }>
      {editing ? (
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Access policy" description="JSON policy document">
            <Textarea rows={14} value={val} onChange={({ detail }) => setVal(detail.value)} spellcheck={false} />
          </FormField>
          <SpaceBetween direction="horizontal" size="xs">
            <Button loading={busy} variant="primary" onClick={async () => {
              setBusy(true); setError(null);
              try { await api.setTopicAttribute(arn, "Policy", val); notify.success(`Access policy updated.${saveNotice("sns.topic.access-policy")}`); setEditing(false); reload(); }
              catch (e) { setError(e); } finally { setBusy(false); }
            }}>Save changes</Button>
            <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          </SpaceBetween>
        </SpaceBetween>
      ) : (
        <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{attrs.Policy}</pre></Box>
      )}
    </CapabilityContainer>
  );
}

function DataProtectionTab({ arn, reload }) {
  const notify = useNotify();
  const d = useAsync(() => api.getDataProtectionPolicy(arn), [arn]);
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (d.loading) return <Spinner />;
  return (
    <CapabilityContainer id="sns.topic.data-protection-policy" title="Data protection policy" actions={
      editing ? null : <Button onClick={() => { setVal(d.data || JSON.stringify({ Name: "data-protection-policy", Version: "2021-06-01", Statement: [] }, null, 2)); setEditing(true); }}>Edit</Button>
    }>
      {editing ? (
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Data protection policy">
            <Textarea rows={12} value={val} onChange={({ detail }) => setVal(detail.value)} spellcheck={false} />
          </FormField>
          <SpaceBetween direction="horizontal" size="xs">
            <Button loading={busy} variant="primary" onClick={async () => {
              setBusy(true); setError(null);
              try { await api.putDataProtectionPolicy(arn, val); notify.success(`Data protection policy updated.${saveNotice("sns.topic.data-protection-policy")}`); setEditing(false); d.reload(); reload(); }
              catch (e) { setError(e); } finally { setBusy(false); }
            }}>Save changes</Button>
            <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          </SpaceBetween>
        </SpaceBetween>
      ) : (
        <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{d.data || "No data protection policy configured."}</pre></Box>
      )}
    </CapabilityContainer>
  );
}

function DeliveryPolicyTab({ arn, attrs, reload }) {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <CapabilityContainer id="sns.topic.delivery-policy" title="Delivery policy (HTTP/S)" actions={
      editing ? null : <Button onClick={() => { setVal(attrs.DeliveryPolicy || JSON.stringify(JSON.parse(attrs.EffectiveDeliveryPolicy || "{}").http || {}, null, 2)); setEditing(true); }}>Edit</Button>
    }>
      {editing ? (
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Delivery policy" description="Retry policy JSON for HTTP/S endpoints">
            <Textarea rows={12} value={val} onChange={({ detail }) => setVal(detail.value)} spellcheck={false} />
          </FormField>
          <SpaceBetween direction="horizontal" size="xs">
            <Button loading={busy} variant="primary" onClick={async () => {
              setBusy(true); setError(null);
              try { await api.setTopicAttribute(arn, "DeliveryPolicy", JSON.stringify({ http: JSON.parse(val) })); notify.success(`Delivery policy updated.${saveNotice("sns.topic.delivery-policy")}`); setEditing(false); reload(); }
              catch (e) { setError(e); } finally { setBusy(false); }
            }}>Save changes</Button>
            <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          </SpaceBetween>
        </SpaceBetween>
      ) : (
        <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(JSON.parse(attrs.EffectiveDeliveryPolicy || "{}").http || {}, null, 2)}</pre></Box>
      )}
    </CapabilityContainer>
  );
}

function DeliveryStatusTab({ arn, attrs, reload }) {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const [sqs, setSqs] = useState(!!attrs.SQSSuccessFeedbackRoleArn);
  const [busy, setBusy] = useState(false);
  const logged = ["SQS", "Lambda", "HTTP", "Firehose", "Application"].filter((p) => attrs[`${p}SuccessFeedbackRoleArn`]);
  return (
    <CapabilityContainer id="sns.topic.delivery-status-logging" title="Delivery status logging" actions={
      editing ? null : <Button onClick={() => { setSqs(!!attrs.SQSSuccessFeedbackRoleArn); setEditing(true); }}>Edit</Button>
    }>
      {editing ? (
        <SpaceBetween size="m">
          <Checkbox checked={sqs} onChange={({ detail }) => setSqs(detail.checked)}>Amazon SQS</Checkbox>
          <SpaceBetween direction="horizontal" size="xs">
            <Button loading={busy} variant="primary" onClick={async () => {
              setBusy(true);
              try {
                await api.setTopicAttribute(arn, "SQSSuccessFeedbackRoleArn", sqs ? "arn:aws:iam::123456789012:role/SNSSuccessFeedback" : "");
                if (sqs) { await api.setTopicAttribute(arn, "SQSSuccessFeedbackSampleRate", "100"); await api.setTopicAttribute(arn, "SQSFailureFeedbackRoleArn", "arn:aws:iam::123456789012:role/SNSFailureFeedback"); }
                else { await api.setTopicAttribute(arn, "SQSFailureFeedbackRoleArn", ""); }
                notify.success(`Delivery status logging updated.${saveNotice("sns.topic.delivery-status-logging")}`); setEditing(false); reload();
              } finally { setBusy(false); }
            }}>Save changes</Button>
            <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          </SpaceBetween>
        </SpaceBetween>
      ) : (
        <KeyValue columns={1} items={[["Logged protocols", logged.length ? logged.join(", ") : "None"]]} />
      )}
    </CapabilityContainer>
  );
}

function EncryptionTab({ arn, attrs, reload }) {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const [on, setOn] = useState(!!attrs.KmsMasterKeyId);
  const [busy, setBusy] = useState(false);
  return (
    <CapabilityContainer id="sns.topic.encryption" title="Encryption" actions={
      editing ? null : <Button onClick={() => { setOn(!!attrs.KmsMasterKeyId); setEditing(true); }}>Edit</Button>
    }>
      {editing ? (
        <SpaceBetween size="m">
          <Toggle checked={on} onChange={({ detail }) => setOn(detail.checked)}>{on ? "Enabled" : "Disabled"}</Toggle>
          <SpaceBetween direction="horizontal" size="xs">
            <Button loading={busy} variant="primary" onClick={async () => {
              setBusy(true);
              try { await api.setTopicAttribute(arn, "KmsMasterKeyId", on ? "alias/aws/sns" : ""); notify.success(`Encryption updated.${saveNotice("sns.topic.encryption")}`); setEditing(false); reload(); }
              finally { setBusy(false); }
            }}>Save changes</Button>
            <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          </SpaceBetween>
        </SpaceBetween>
      ) : (
        <KeyValue columns={2} items={[["Encryption", attrs.KmsMasterKeyId ? "Configured" : "Not configured"], ["AWS KMS key", attrs.KmsMasterKeyId || "-"]]} />
      )}
    </CapabilityContainer>
  );
}

function TagsTab({ arn }) {
  const notify = useNotify();
  const t = useAsync(() => api.listTagsForResource(arn), [arn]);
  const [open, setOpen] = useState(false);
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  if (t.loading) return <Spinner />;
  const rows = t.data || [];
  return (
    <>
      <Table variant="container" items={rows}
        header={<Header variant="h2" counter={`(${rows.length})`} actions={<Button onClick={() => { setTags(rows.map((x) => ({ key: x.Key, value: x.Value }))); setOpen(true); }}>Manage tags</Button>}>Tags</Header>}
        columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.Key }, { id: "v", header: "Value", cell: (x) => x.Value || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      <Modal visible={open} onDismiss={() => setOpen(false)} header="Manage tags" size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true);
            try {
              const kept = tags.filter((x) => !x.markedForRemoval && x.key);
              const removed = rows.map((x) => x.Key).filter((k) => !kept.some((x) => x.key === k));
              if (removed.length) await api.untagResource(arn, removed);
              if (kept.length) await api.tagResource(arn, kept);
              notify.success("Tags updated."); setOpen(false); t.reload();
            } finally { setBusy(false); }
          }}>Save</Button>
        </SpaceBetween></Box>}>
        <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} />
      </Modal>
    </>
  );
}

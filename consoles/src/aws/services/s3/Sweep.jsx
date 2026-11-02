/* S3 sweep-A sections: event notifications, EventBridge, CloudWatch-backed metrics panels. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Textarea from "@cloudscape-design/components/textarea";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtBytes, KeyValue } from "../../kit/common.jsx";
import { LineChart } from "../cloudwatch/common.jsx";
import * as api from "./api.js";
import * as sw from "./sweepApi.js";

const EVENT_OPTIONS = [
  { value: "s3:ObjectCreated:*", label: "All object create events" },
  { value: "s3:ObjectRemoved:*", label: "All object removal events" },
  { value: "s3:ObjectCreated:Put", label: "Put" },
  { value: "s3:ObjectCreated:Copy", label: "Copy" },
  { value: "s3:ObjectCreated:CompleteMultipartUpload", label: "Multipart upload completed" },
  { value: "s3:ObjectRemoved:Delete", label: "Permanently deleted" },
  { value: "s3:ObjectRemoved:DeleteMarkerCreated", label: "Delete marker created" },
];

export function EventNotificationsSection({ bucket }) {
  const notify = useNotify();
  const n = useAsync(() => sw.getNotification(bucket), [bucket]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const rules = n.data?.rules || [];
  const save = async (next) => { const cur = await sw.getNotification(bucket); await sw.putNotification(bucket, { rules: next, eventBridge: cur.eventBridge }); n.reload(); };
  return (
    <CapabilityContainer id="s3.bucket.notification" title="Event notifications" counter={`(${rules.length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={async () => {
          try { await save(rules.filter((r) => !sel.includes(r))); notify.success("Successfully deleted event notification."); setSel([]); } catch (e) { notify.error(e); }
        }}>Delete</Button>
        <Button onClick={() => setCreate({ id: "", kind: "queue", arn: "", prefix: "", suffix: "", events: ["s3:ObjectCreated:*"] })}>Create event notification</Button>
      </SpaceBetween>}>
      {n.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : n.error ? <ErrorAlert error={n.error} />
        : <Table variant="embedded" items={rules} selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)} trackBy="id"
            columnDefinitions={[
              { id: "name", header: "Name", cell: (r) => r.id },
              { id: "types", header: "Event types", cell: (r) => r.events.join(", ") },
              { id: "filters", header: "Filters", cell: (r) => [r.prefix && `prefix ${r.prefix}`, r.suffix && `suffix ${r.suffix}`].filter(Boolean).join(", ") || "-" },
              { id: "dest", header: "Destination type", cell: (r) => sw.NOTIFICATION_KINDS.find((k) => k.kind === r.kind).label },
              { id: "arn", header: "Destination", cell: (r) => r.arn },
            ]}
            empty={<Box textAlign="center" color="inherit"><b>No event notifications</b></Box>} />}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create event notification"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.arn || !create?.events.length} onClick={async () => {
            setSaving(true);
            try {
              await save([...rules, { ...create, id: create.id || `notif-${Date.now()}` }]);
              notify.success(`Successfully created event notification.${saveNotice("s3.bucket.notification")}`);
              setCreate(null);
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Event name"><Input value={create.id} onChange={({ detail }) => setCreate({ ...create, id: detail.value })} /></FormField>
          <FormField label="Prefix"><Input value={create.prefix} onChange={({ detail }) => setCreate({ ...create, prefix: detail.value })} /></FormField>
          <FormField label="Suffix"><Input value={create.suffix} onChange={({ detail }) => setCreate({ ...create, suffix: detail.value })} /></FormField>
          <FormField label="Event types">
            <SpaceBetween size="xxs">
              {EVENT_OPTIONS.map((o) => (
                <Checkbox key={o.value} checked={create.events.includes(o.value)}
                  onChange={({ detail }) => setCreate({ ...create, events: detail.checked ? [...create.events, o.value] : create.events.filter((e) => e !== o.value) })}>{o.label}</Checkbox>
              ))}
            </SpaceBetween>
          </FormField>
          <FormField label="Destination">
            <Select selectedOption={{ value: create.kind, label: sw.NOTIFICATION_KINDS.find((k) => k.kind === create.kind).label }}
              options={sw.NOTIFICATION_KINDS.map((k) => ({ value: k.kind, label: k.label }))}
              onChange={({ detail }) => setCreate({ ...create, kind: detail.selectedOption.value })} />
          </FormField>
          <FormField label="Destination ARN" description="The ARN of an existing SQS queue, SNS topic or Lambda function in this Vyomi environment.">
            <Input value={create.arn} onChange={({ detail }) => setCreate({ ...create, arn: detail.value })} />
          </FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

export function EventBridgeSection({ bucket }) {
  const notify = useNotify();
  const n = useAsync(() => sw.getNotification(bucket), [bucket]);
  const on = !!n.data?.eventBridge;
  return (
    <CapabilityContainer id="s3.bucket.eventbridge" title="Amazon EventBridge"
      description="Send notifications to Amazon EventBridge for all events in this bucket."
      actions={<Button ariaLabel="Edit Amazon EventBridge notifications" disabled={!n.data} onClick={async () => {
        try {
          const cur = await sw.getNotification(bucket);
          await sw.putNotification(bucket, { rules: cur.rules, eventBridge: !cur.eventBridge });
          notify.success(`Successfully ${on ? "turned off" : "turned on"} Amazon EventBridge notifications.${saveNotice("s3.bucket.eventbridge")}`);
          n.reload();
        } catch (e) { notify.error(e); }
      }}>Edit</Button>}>
      {n.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : n.error ? <ErrorAlert error={n.error} />
        : <SpaceBetween size="xxs"><Box variant="awsui-key-label">Send notifications to Amazon EventBridge for all events in this bucket</Box>
            <div data-testid="s3-eventbridge-state">{on ? "On" : "Off"}</div></SpaceBetween>}
    </CapabilityContainer>
  );
}

function Series({ title, series, format = (v) => String(v) }) {
  const last = series?.length ? series[series.length - 1].v : null;
  return (
    <SpaceBetween size="xxs">
      <Box variant="h3">{title}</Box>
      <Box variant="small" color="text-body-secondary">Latest: <span data-testid={`metric-${title}`}>{last === null ? "no data" : format(last)}</span></Box>
      <LineChart series={series} />
    </SpaceBetween>
  );
}

export function StorageMetricsSection({ bucket }) {
  const m = useAsync(async () => ({
    size: await sw.metricSeries("AWS/S3", "BucketSizeBytes", [{ Name: "BucketName", Value: bucket }, { Name: "StorageType", Value: "StandardStorage" }]),
    count: await sw.metricSeries("AWS/S3", "NumberOfObjects", [{ Name: "BucketName", Value: bucket }, { Name: "StorageType", Value: "AllStorageTypes" }]),
  }), [bucket]);
  return (
    <CapabilityContainer id="s3.bucket.storage-metrics" title="Bucket metrics" description="Daily storage metrics for the bucket, published to CloudWatch (last 3 hours)."
      actions={<Button iconName="refresh" onClick={m.reload}>Refresh</Button>}>
      {m.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : m.error ? <ErrorAlert error={m.error} />
        : <SpaceBetween size="l">
            <Series title="Total bucket size" series={m.data.size} format={fmtBytes} />
            <Series title="Total number of objects" series={m.data.count} />
          </SpaceBetween>}
    </CapabilityContainer>
  );
}

export function ReplicationMetricsSection({ bucket }) {
  const m = useAsync(async () => {
    const rep = await api.getReplication(bucket);
    const rules = (rep.rules || []).filter((r) => r.metrics);
    const out = [];
    for (const r of rules) {
      out.push({ rule: r, latency: await sw.metricSeries("AWS/S3", "ReplicationLatency", [
        { Name: "SourceBucket", Value: bucket }, { Name: "DestinationBucket", Value: r.destination }, { Name: "RuleId", Value: r.id }], { statistic: "Average" }) });
    }
    return out;
  }, [bucket]);
  return (
    <CapabilityContainer id="s3.bucket.replication-metrics" title="Replication metrics" description="CloudWatch metrics for replication rules that have replication metrics enabled."
      actions={<Button iconName="refresh" onClick={m.reload}>Refresh</Button>}>
      {m.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : m.error ? <ErrorAlert error={m.error} />
        : !m.data.length ? <Box color="text-body-secondary">No replication rule on this bucket has replication metrics enabled.</Box>
        : <SpaceBetween size="l">{m.data.map((x) => <Series key={x.rule.id} title={`Replication latency (seconds) - ${x.rule.id}`} series={x.latency} />)}</SpaceBetween>}
    </CapabilityContainer>
  );
}

export function DataTransferSection({ bucket }) {
  const m = useAsync(async () => {
    const cfg = await api.getMetricsConfigs(bucket);
    const out = [];
    for (const c of cfg.configs) {
      const dims = [{ Name: "BucketName", Value: bucket }, { Name: "FilterId", Value: c.id }];
      out.push({ cfg: c,
        down: await sw.metricSeries("AWS/S3", "BytesDownloaded", dims, { statistic: "Sum" }),
        up: await sw.metricSeries("AWS/S3", "BytesUploaded", dims, { statistic: "Sum" }) });
    }
    return out;
  }, [bucket]);
  return (
    <CapabilityContainer id="s3.bucket.metrics" title="Data transfer metrics" description="Bytes uploaded and downloaded through each request metrics filter (last 3 hours)."
      actions={<Button iconName="refresh" onClick={m.reload}>Refresh</Button>}>
      {m.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : m.error ? <ErrorAlert error={m.error} />
        : !m.data.length ? <Box color="text-body-secondary">Create a request metrics filter below to start recording bytes uploaded and downloaded.</Box>
        : <SpaceBetween size="l">{m.data.map((x) => (
            <SpaceBetween key={x.cfg.id} size="s">
              <Box variant="h3">Filter {x.cfg.id}</Box>
              <Series title={`Bytes downloaded - ${x.cfg.id}`} series={x.down} format={fmtBytes} />
              <Series title={`Bytes uploaded - ${x.cfg.id}`} series={x.up} format={fmtBytes} />
            </SpaceBetween>))}</SpaceBetween>}
    </CapabilityContainer>
  );
}

export function AccountSnapshot({ buckets, loading }) {
  const snap = useAsync(() => sw.accountSnapshot(buckets.map((b) => b.name)), [buckets.map((b) => b.name).join(",")]);
  const d = snap.data;
  return (
    <CapabilityContainer id="s3.account.snapshot" title="Account snapshot" description="Storage and object totals across all general purpose buckets in this environment."
      actions={<Button iconName="refresh" onClick={snap.reload}>Refresh</Button>}>
      {loading || snap.loading ? <StatusIndicator type="loading">Calculating</StatusIndicator>
        : snap.error ? <ErrorAlert error={snap.error} />
        : <SpaceBetween size="s">
            <KeyValue columns={4} items={[
              ["Total storage", <span data-testid="snapshot-storage">{fmtBytes(d.bytes)}</span>],
              ["Object count", <span data-testid="snapshot-objects">{d.objects}</span>],
              ["Average object size", d.objects ? fmtBytes(Math.round(d.bytes / d.objects)) : "-"],
              ["General purpose buckets", <span data-testid="snapshot-buckets">{d.buckets}</span>],
            ]} />
            {d.truncated && <Box color="text-body-secondary">Very large buckets were counted up to the first {50 * 1000} objects.</Box>}
          </SpaceBetween>}
    </CapabilityContainer>
  );
}

export function ObjectManagementOverview({ bucket, objectKey, head }) {
  const m = useAsync(async () => ({
    versioning: await api.getVersioning(bucket), replication: await api.getReplication(bucket), lifecycle: await api.getLifecycle(bucket),
  }), [bucket, objectKey]);
  const applies = (r) => !r.prefix || objectKey.startsWith(r.prefix);
  const repl = (m.data?.replication?.rules || []).filter((r) => r.status === "Enabled" && applies(r));
  const life = (m.data?.lifecycle?.rules || []).filter((r) => r.status === "Enabled" && applies(r));
  return (
    <CapabilityContainer id="s3.object.management-overview" title="Object management overview"
      description="The bucket management configurations that are in effect for this object.">
      {m.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : m.error ? <ErrorAlert error={m.error} />
        : <KeyValue columns={3} items={[
            ["Bucket Versioning", m.data.versioning?.status || "Disabled"],
            ["Replication rules", repl.length ? repl.map((r) => `${r.id} -> ${r.destination}`).join(", ") : "None apply to this object"],
            ["Replication status", head?.replicationStatus || (repl.length ? "-" : "Not replicated")],
            ["Lifecycle rules", life.length ? life.map((r) => r.id).join(", ") : "None apply to this object"],
            ["Current storage class", head?.storageClass],
          ]} />}
    </CapabilityContainer>
  );
}

export function AccessPointsSection({ bucket: fixedBucket }) {
  const [pickBucket, setPickBucket] = useState("");
  const bucket = fixedBucket;
  const notify = useNotify();
  const aps = useAsync(() => sw.listAccessPoints(bucket), [bucket]);
  const targetBucket = bucket || pickBucket;
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [policy, setPolicy] = useState(null);
  const [saving, setSaving] = useState(false);
  const rows = aps.data || [];
  return (
    <CapabilityContainer id="s3.bucket.access-points" title="Access Points" counter={`(${rows.length})`}
      description="Named network endpoints attached to this bucket, each with its own policy."
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={sel.length !== 1} onClick={async () => setPolicy({ name: sel[0].name, text: await sw.getAccessPointPolicy(sel[0].name) })}>Edit policy</Button>
        <Button disabled={!sel.length} onClick={async () => {
          try { for (const a of sel) await sw.deleteAccessPoint(a.name); notify.success("Successfully deleted access point."); setSel([]); aps.reload(); } catch (e) { notify.error(e); }
        }}>Delete</Button>
        <Button variant="primary" onClick={() => setCreate({ name: "", vpcId: "", blockPublic: true })}>Create access point</Button>
      </SpaceBetween>}>
      {aps.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : aps.error ? <ErrorAlert error={aps.error} />
        : <Table variant="embedded" items={rows} trackBy="name" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "name", header: "Name", cell: (a) => a.name },
              ...(bucket ? [] : [{ id: "bucket", header: "Bucket", cell: (a) => a.bucket }]),
              { id: "origin", header: "Network origin", cell: (a) => a.networkOrigin + (a.vpcId ? ` (${a.vpcId})` : "") },
              { id: "alias", header: "Access point alias", cell: (a) => a.alias },
              { id: "arn", header: "Access point ARN", cell: (a) => a.arn },
            ]}
            empty={<Box textAlign="center" color="inherit"><b>No access points</b><Box variant="p" color="inherit">The alias of an access point works anywhere a bucket name is accepted.</Box></Box>} />}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create access point"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.name || !targetBucket} onClick={async () => {
            setSaving(true);
            try {
              await sw.createAccessPoint(targetBucket, create.name, create);
              notify.success(`Successfully created access point ${create.name}.${saveNotice("s3.bucket.access-points")}`);
              setCreate(null); aps.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create access point</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          {!bucket && <FormField label="Bucket name" description="The existing bucket this access point serves."><Input value={pickBucket} onChange={({ detail }) => setPickBucket(detail.value)} /></FormField>}
          <FormField label="Access point name" description="3-50 characters: lowercase letters, numbers and hyphens."><Input value={create.name} onChange={({ detail }) => setCreate({ ...create, name: detail.value })} /></FormField>
          <FormField label="VPC ID" description="Optional. Leave blank for an Internet network origin."><Input value={create.vpcId} onChange={({ detail }) => setCreate({ ...create, vpcId: detail.value })} /></FormField>
          <Checkbox checked={create.blockPublic} onChange={({ detail }) => setCreate({ ...create, blockPublic: detail.checked })}>Block all public access</Checkbox>
        </SpaceBetween>}
      </Modal>
      <Modal visible={!!policy} onDismiss={() => setPolicy(null)} header={policy ? `Access point policy - ${policy.name}` : ""} size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={async () => { try { await sw.deleteAccessPointPolicy(policy.name); notify.success("Successfully deleted access point policy."); setPolicy(null); } catch (e) { notify.error(e); } }}>Delete policy</Button>
          <Button variant="primary" onClick={async () => { try { await sw.putAccessPointPolicy(policy.name, policy.text); notify.success("Successfully edited access point policy."); setPolicy(null); } catch (e) { notify.error(e); } }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {policy && <FormField label="Policy (JSON)"><Textarea rows={12} value={policy.text} onChange={({ detail }) => setPolicy({ ...policy, text: detail.value })} /></FormField>}
      </Modal>
    </CapabilityContainer>
  );
}

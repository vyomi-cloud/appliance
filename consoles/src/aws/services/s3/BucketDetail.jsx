import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Link from "@cloudscape-design/components/link";
import Box from "@cloudscape-design/components/box";
import Container from "@cloudscape-design/components/container";
import Table from "@cloudscape-design/components/table";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";
import TagsContainer from "./TagsContainer.jsx";
import Permissions from "./Permissions.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { WIRE_BASE } from "../../../common/wire.js";

const arn = (b) => `arn:aws:s3:::${b}`;

export default function BucketDetail({ params, query }) {
  const bucket = params.name;
  const [tab, setTab] = useState(query.tab || "objects");
  return (
    <ContentLayout header={<Header variant="h1" info={<Link variant="info">Info</Link>}>{bucket}</Header>}>
      <Tabs
        activeTabId={tab}
        onChange={({ detail }) => setTab(detail.activeTabId)}
        tabs={[
          { id: "objects", label: "Objects", content: <Objects bucket={bucket} prefix={query.prefix || ""} /> },
          { id: "metadata", label: "Metadata", content: <NotSimulatedContainer title="Metadata configuration" note="S3 Metadata (the queryable metadata table for a bucket) isn't modeled in Vyomi." /> },
          { id: "properties", label: "Properties", content: <Properties bucket={bucket} /> },
          { id: "permissions", label: "Permissions", content: <Permissions bucket={bucket} /> },
          { id: "metrics", label: "Metrics", content: <Metrics bucket={bucket} /> },
          { id: "management", label: "Management", content: <Management bucket={bucket} /> },
          { id: "access-points", label: "Access Points", content: <NotSimulatedContainer title="Access Points" feature="S3 Access Points" /> },
        ]}
      />
    </ContentLayout>
  );
}

function Objects({ bucket, prefix }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data, loading, error, reload } = useAsync(() => api.listObjects(bucket, prefix), [bucket, prefix]);
  const items = data ? [...data.folders, ...data.objects] : [];
  const crumbs = prefix.split("/").filter(Boolean);
  const withPrefix = (base) => prefix ? `${base}?prefix=${encodeURIComponent(prefix)}` : base;

  return (
    <>
      <ResourceTable
        variant="container"
        resourceName="Objects"
        description={crumbs.length ? <span><Link href={href("s3", "buckets", bucket)} onFollow={follow}>{bucket}</Link>{crumbs.map((c, i) => <span key={i}> / <Link href={`${href("s3", "buckets", bucket)}?prefix=${encodeURIComponent(crumbs.slice(0, i + 1).join("/") + "/")}`} onFollow={follow}>{c}</Link></span>)}</span>
          : "Objects are the fundamental entities stored in Amazon S3."}
        items={items}
        trackBy="key"
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find objects by prefix"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (o) => o.folder
            ? <Link href={`${href("s3", "buckets", bucket)}?prefix=${encodeURIComponent(o.key)}`} onFollow={follow}>{o.name}</Link>
            : <Link href={`${href("s3", "object", bucket)}?prefix=${encodeURIComponent(o.key)}`} onFollow={follow}>{o.name}</Link> },
          { id: "type", header: "Type", cell: (o) => o.folder ? "Folder" : (o.name.includes(".") ? o.name.split(".").pop() : "-") },
          { id: "modified", header: "Last modified", sortingField: "modified", cell: (o) => o.folder ? "-" : fmtDate(o.modified) },
          { id: "size", header: "Size", sortingField: "size", cell: (o) => o.folder ? "-" : fmtBytes(o.size) },
          { id: "storageClass", header: "Storage class", cell: (o) => o.folder ? "-" : o.storageClass },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button href={withPrefix(href("s3", "bucket", bucket, "create", "folder"))} onFollow={follow}>Create folder</Button>
            <Button variant="primary" iconName="upload" href={withPrefix(href("s3", "upload", bucket))} onFollow={follow}>Upload</Button>
          </SpaceBetween>
        }
        empty={{ title: "No objects", subtitle: "You don't have any objects in this bucket.", action: <Button iconName="upload" href={withPrefix(href("s3", "upload", bucket))} onFollow={follow}>Upload</Button> }}
      />
      <DeleteModal
        visible={del}
        resourceType="object"
        names={sel.map((o) => o.key)}
        confirmText="permanently delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => {
          for (const o of sel) {
            if (o.folder) {
              const inner = await api.listObjects(bucket, o.key);
              for (const x of inner.objects) await api.deleteObject(bucket, x.key);
            }
            await api.deleteObject(bucket, o.key);
          }
          notify.success(`Successfully deleted ${sel.length} object${sel.length === 1 ? "" : "s"}`);
          setSel([]); reload();
        }}
      />
    </>
  );
}

function SubSetting({ title, state, render }) {
  if (state.loading) return <Container header={<Header variant="h2">{title}</Header>}><StatusIndicator type="loading">Loading</StatusIndicator></Container>;
  if (state.data?.unsupported) return <NotSimulatedContainer title={title} />;
  if (state.data?.error) return <Container header={<Header variant="h2">{title}</Header>}><ErrorAlert error={state.data.error} /></Container>;
  if (state.error) return <Container header={<Header variant="h2">{title}</Header>}><ErrorAlert error={state.error} /></Container>;
  return render(state.data);
}

function Properties({ bucket }) {
  const notify = useNotify();
  const region = useAsync(() => api.bucketRegion(bucket), [bucket]);
  const created = useAsync(async () => (await api.listBuckets()).find((b) => b.name === bucket)?.created, [bucket]);
  const ver = useAsync(() => api.getVersioning(bucket), [bucket]);
  const tags = useAsync(() => api.getTags(bucket), [bucket]);
  const enc = useAsync(() => api.getEncryption(bucket), [bucket]);
  return (
    <SpaceBetween size="l">
      <KeyValue title="Bucket overview" items={[["AWS Region", region.data], ["Amazon Resource Name (ARN)", arn(bucket)], ["Creation date", fmtDate(created.data)]]} />
      <SubSetting title="Bucket Versioning" state={ver} render={(d) => (
        <KeyValue title="Bucket Versioning" columns={1}
          actions={<Button onClick={async () => { try { await api.putVersioning(bucket, d.status !== "Enabled"); notify.success("Successfully edited Bucket Versioning."); ver.reload(); } catch (e) { notify.error(e); } }}>{d.status === "Enabled" ? "Suspend" : "Enable"}</Button>}
          items={[["Bucket Versioning", d.status]]} />
      )} />
      <TagsContainer state={tags} save={(t) => api.putTags(bucket, t)} />
      <Encryption bucket={bucket} state={enc} />
      <IntelligentTieringSection bucket={bucket} />
      <LoggingSection bucket={bucket} />
      <NotSimulatedContainer title="AWS CloudTrail data events" />
      <CapabilityContainer id="s3.bucket.notification" title="Event notifications" />
      <NotSimulatedContainer title="Amazon EventBridge" />
      <CapabilityContainer id="s3.bucket.accelerate" title="Transfer acceleration" />
      <ObjectLockSection bucket={bucket} />
      <RequestPaymentSection bucket={bucket} />
      <WebsiteSection bucket={bucket} />
    </SpaceBetween>
  );
}

const ENC_TYPES = [
  { value: "AES256", label: "Server-side encryption with Amazon S3 managed keys (SSE-S3)" },
  { value: "aws:kms", label: "Server-side encryption with AWS Key Management Service keys (SSE-KMS)" },
  { value: "aws:kms:dsse", label: "Dual-layer server-side encryption with AWS Key Management Service keys (DSSE-KMS)" },
];

function Encryption({ bucket, state }) {
  const notify = useNotify();
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  return (
    <CapabilityContainer id="s3.bucket.encryption" title="Default encryption"
      actions={<Button onClick={() => setEdit({ algorithm: state.data?.algorithm || "AES256", kmsKey: state.data?.kmsKey || "", bucketKey: !!state.data?.bucketKey })}>Edit</Button>}>
      {state.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : state.error ? <ErrorAlert error={state.error} />
        : <SpaceBetween size="s">
            <div><Box variant="awsui-key-label">Encryption type</Box><div>{ENC_TYPES.find((t) => t.value === (state.data.absent ? "AES256" : state.data.algorithm))?.label || state.data.algorithm}</div></div>
            <div><Box variant="awsui-key-label">Bucket Key</Box><div>{state.data.bucketKey ? "Enabled" : "Disabled"}</div></div>
            {state.data.kmsKey && <div><Box variant="awsui-key-label">Encryption key ARN</Box><div>{state.data.kmsKey}</div></div>}
          </SpaceBetween>}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit default encryption"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              await api.putEncryption(bucket, edit.algorithm, edit.algorithm === "AES256" ? null : edit.kmsKey, edit.algorithm !== "AES256" && edit.bucketKey);
              notify.success(`Successfully edited Default encryption.${saveNotice("s3.bucket.encryption")}`);
              setEdit(null); state.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <SpaceBetween size="m">
          <FormField label="Encryption type">
            <RadioGroup value={edit.algorithm} onChange={({ detail }) => setEdit({ ...edit, algorithm: detail.value })}
              items={ENC_TYPES.map(({ value, label }) => ({ value, label }))} />
          </FormField>
          {edit.algorithm !== "AES256" && <FormField label="AWS KMS key ARN"><Input value={edit.kmsKey} onChange={({ detail }) => setEdit({ ...edit, kmsKey: detail.value })} /></FormField>}
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function ObjectLockSection({ bucket }) {
  const notify = useNotify();
  const lock = useAsync(() => api.getObjectLock(bucket), [bucket]);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  return (
    <CapabilityContainer id="s3.bucket.object-lock" title="Object Lock"
      description="Object Lock can only be enabled when a bucket is created; it permanently allows objects in this bucket to be locked."
      actions={lock.data?.enabled && <Button onClick={() => setEdit({
        enabled: !!lock.data.defaultRetention, mode: lock.data.defaultRetention?.mode || "GOVERNANCE",
        period: String(lock.data.defaultRetention?.days || lock.data.defaultRetention?.years || "1"),
        unit: lock.data.defaultRetention?.years ? "Years" : "Days",
      })}>Edit default retention</Button>}>
      {lock.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : lock.error ? <ErrorAlert error={lock.error} />
        : <SpaceBetween size="s">
            <div><Box variant="awsui-key-label">Object Lock</Box><div>{lock.data?.enabled ? "Enabled" : "Disabled"}</div></div>
            {lock.data?.enabled && <div><Box variant="awsui-key-label">Default retention</Box>
              <div>{lock.data.defaultRetention
                ? `${lock.data.defaultRetention.mode} mode, ${lock.data.defaultRetention.days || lock.data.defaultRetention.years} ${lock.data.defaultRetention.days ? "days" : "years"}`
                : "None"}</div></div>}
          </SpaceBetween>}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit default retention"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              if (edit.enabled) await api.putObjectLockDefaultRetention(bucket, edit.mode, edit.period, edit.unit);
              else await api.clearObjectLockDefaultRetention(bucket);
              notify.success(`Successfully edited default retention.${saveNotice("s3.bucket.object-lock")}`);
              setEdit(null); lock.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <SpaceBetween size="m">
          <FormField label="Default retention">
            <RadioGroup value={edit.enabled ? "enabled" : "disabled"} onChange={({ detail }) => setEdit({ ...edit, enabled: detail.value === "enabled" })}
              items={[{ value: "disabled", label: "None" }, { value: "enabled", label: "Enabled" }]} />
          </FormField>
          {edit.enabled && <>
            <FormField label="Retention mode">
              <RadioGroup value={edit.mode} onChange={({ detail }) => setEdit({ ...edit, mode: detail.value })}
                items={[{ value: "GOVERNANCE", label: "Governance mode" }, { value: "COMPLIANCE", label: "Compliance mode" }]} />
            </FormField>
            <FormField label="Retention period">
              <SpaceBetween direction="horizontal" size="xs">
                <Input type="number" value={edit.period} onChange={({ detail }) => setEdit({ ...edit, period: detail.value })} />
                <RadioGroup value={edit.unit} onChange={({ detail }) => setEdit({ ...edit, unit: detail.value })}
                  items={[{ value: "Days", label: "Days" }, { value: "Years", label: "Years" }]} />
              </SpaceBetween>
            </FormField>
          </>}
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function WebsiteSection({ bucket }) {
  const notify = useNotify();
  const site = useAsync(() => api.getWebsite(bucket), [bucket]);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  return (
    <CapabilityContainer id="s3.bucket.website" title="Static website hosting"
      actions={<Button onClick={() => setEdit({ enabled: !!site.data?.config, indexDocument: site.data?.config?.indexDocument || "index.html", errorDocument: site.data?.config?.errorDocument || "" })}>Edit</Button>}>
      {site.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : site.data?.error ? <ErrorAlert error={site.data.error} />
        : <SpaceBetween size="xs">
            <div><Box variant="awsui-key-label">Static website hosting</Box><div>{site.data.config ? "Enabled" : "Disabled"}</div></div>
            {site.data.config && <div><Box variant="awsui-key-label">Bucket website endpoint</Box>
              <Link href={`${WIRE_BASE}/__s3_website__/${bucket}/`} external>{`${WIRE_BASE}/__s3_website__/${bucket}/`}</Link></div>}
          </SpaceBetween>}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit static website hosting"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              if (edit.enabled) await api.putWebsite(bucket, edit.indexDocument, edit.errorDocument);
              else await api.deleteWebsite(bucket);
              notify.success(`Successfully edited Static website hosting.${saveNotice("s3.bucket.website")}`);
              setEdit(null); site.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <SpaceBetween size="m">
          <FormField label="Static website hosting">
            <RadioGroup value={edit.enabled ? "enabled" : "disabled"} onChange={({ detail }) => setEdit({ ...edit, enabled: detail.value === "enabled" })}
              items={[{ value: "disabled", label: "Disable" }, { value: "enabled", label: "Enable" }]} />
          </FormField>
          {edit.enabled && <>
            <FormField label="Index document"><Input value={edit.indexDocument} onChange={({ detail }) => setEdit({ ...edit, indexDocument: detail.value })} /></FormField>
            <FormField label="Error document"><Input value={edit.errorDocument} onChange={({ detail }) => setEdit({ ...edit, errorDocument: detail.value })} /></FormField>
          </>}
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function LoggingSection({ bucket }) {
  const notify = useNotify();
  const log = useAsync(() => api.getLogging(bucket), [bucket]);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  return (
    <CapabilityContainer id="s3.bucket.logging" title="Server access logging"
      actions={<Button onClick={() => setEdit({ enabled: !!log.data?.enabled, targetBucket: log.data?.targetBucket || "", targetPrefix: log.data?.targetPrefix || "" })}>Edit</Button>}>
      {log.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : log.error ? <ErrorAlert error={log.error} />
        : <div><Box variant="awsui-key-label">Server access logging</Box><div>{log.data.enabled ? `Enabled — target: ${log.data.targetBucket}` : "Disabled"}</div></div>}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit server access logging"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              await api.putLogging(bucket, edit.enabled ? edit.targetBucket : "", edit.enabled ? edit.targetPrefix : "");
              notify.success(`Successfully edited Server access logging.${saveNotice("s3.bucket.logging")}`);
              setEdit(null); log.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <SpaceBetween size="m">
          <FormField label="Server access logging">
            <RadioGroup value={edit.enabled ? "enabled" : "disabled"} onChange={({ detail }) => setEdit({ ...edit, enabled: detail.value === "enabled" })}
              items={[{ value: "disabled", label: "Disable" }, { value: "enabled", label: "Enable" }]} />
          </FormField>
          {edit.enabled && <>
            <FormField label="Target bucket"><Input value={edit.targetBucket} onChange={({ detail }) => setEdit({ ...edit, targetBucket: detail.value })} /></FormField>
            <FormField label="Target prefix"><Input value={edit.targetPrefix} onChange={({ detail }) => setEdit({ ...edit, targetPrefix: detail.value })} /></FormField>
          </>}
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function RequestPaymentSection({ bucket }) {
  const notify = useNotify();
  const pay = useAsync(() => api.getRequestPayment(bucket), [bucket]);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  return (
    <CapabilityContainer id="s3.bucket.request-payment" title="Requester pays"
      actions={<Button onClick={() => setEdit({ payer: pay.data?.payer || "BucketOwner" })}>Edit</Button>}>
      {pay.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : pay.error ? <ErrorAlert error={pay.error} />
        : <div><Box variant="awsui-key-label">Requester pays</Box><div>{pay.data.payer === "Requester" ? "Enabled" : "Disabled"}</div></div>}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit requester pays"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              await api.putRequestPayment(bucket, edit.payer);
              notify.success(`Successfully edited Requester pays.${saveNotice("s3.bucket.request-payment")}`);
              setEdit(null); pay.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <FormField label="Requester pays">
          <RadioGroup value={edit.payer} onChange={({ detail }) => setEdit({ ...edit, payer: detail.value })}
            items={[{ value: "BucketOwner", label: "Disable" }, { value: "Requester", label: "Enable" }]} />
        </FormField>}
      </Modal>
    </CapabilityContainer>
  );
}

function IntelligentTieringSection({ bucket }) {
  const notify = useNotify();
  const it = useAsync(() => api.getIntelligentTiering(bucket), [bucket]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const configs = it.data?.configs || [];
  return (
    <CapabilityContainer id="s3.bucket.intelligent-tiering" title="Intelligent-Tiering Archive configurations" counter={`(${configs.length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={async () => {
          for (const c of sel) await api.deleteIntelligentTiering(bucket, c.id);
          notify.success("Successfully deleted configuration.");
          setSel([]); it.reload();
        }}>Delete</Button>
        <Button onClick={() => setCreate({ id: "", days: "90" })}>Create configuration</Button>
      </SpaceBetween>}>
      {it.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : it.error ? <ErrorAlert error={it.error} />
        : <Table variant="embedded" items={configs} selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)} trackBy="id"
            columnDefinitions={[{ id: "id", header: "Configuration ID", cell: (c) => c.id }, { id: "status", header: "Status", cell: (c) => c.status }]}
            empty={<Box textAlign="center" color="inherit"><b>No configurations</b></Box>} />}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create configuration"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              await api.putIntelligentTiering(bucket, create.id, "Enabled", [{ accessTier: "ARCHIVE_ACCESS", days: Number(create.days) || 90 }]);
              notify.success(`Successfully created configuration.${saveNotice("s3.bucket.intelligent-tiering")}`);
              setCreate(null); it.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Configuration ID"><Input value={create.id} onChange={({ detail }) => setCreate({ ...create, id: detail.value })} /></FormField>
          <FormField label="Days until archive access tier" description="Days of no access before this configuration moves objects to the Archive Access tier.">
            <Input type="number" value={create.days} onChange={({ detail }) => setCreate({ ...create, days: detail.value })} />
          </FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function MetricsConfigSection({ bucket }) {
  const notify = useNotify();
  const met = useAsync(() => api.getMetricsConfigs(bucket), [bucket]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const configs = met.data?.configs || [];
  return (
    <CapabilityContainer id="s3.bucket.metrics" title="Request metrics" counter={`(${configs.length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={async () => {
          for (const c of sel) await api.deleteMetricsConfig(bucket, c.id);
          notify.success("Successfully deleted metrics filter.");
          setSel([]); met.reload();
        }}>Delete</Button>
        <Button onClick={() => setCreate({ id: "", prefix: "" })}>Create filter</Button>
      </SpaceBetween>}>
      {met.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : met.error ? <ErrorAlert error={met.error} />
        : <Table variant="embedded" items={configs} selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)} trackBy="id"
            columnDefinitions={[{ id: "name", header: "Filter name", cell: (c) => c.id }, { id: "scope", header: "Scope", cell: (c) => c.prefix ? `Prefix ${c.prefix}` : "Entire bucket" }]}
            empty={<Box textAlign="center" color="inherit"><b>No request metrics filters</b></Box>} />}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create filter"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              await api.putMetricsConfig(bucket, create.id, create.prefix);
              notify.success(`Successfully created filter.${saveNotice("s3.bucket.metrics")}`);
              setCreate(null); met.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Filter name"><Input value={create.id} onChange={({ detail }) => setCreate({ ...create, id: detail.value })} /></FormField>
          <FormField label="Prefix" description="Limit this filter to keys starting with this prefix. Leave blank to apply to the entire bucket.">
            <Input value={create.prefix} onChange={({ detail }) => setCreate({ ...create, prefix: detail.value })} />
          </FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function Metrics({ bucket }) {
  return (
    <SpaceBetween size="l">
      <NotSimulatedContainer title="Bucket metrics" feature="CloudWatch storage metrics for S3" />
      <NotSimulatedContainer title="Storage Lens metrics" />
      <MetricsConfigSection bucket={bucket} />
      <NotSimulatedContainer title="Replication metrics" />
      <NotSimulatedContainer title="Data transfer metrics" />
    </SpaceBetween>
  );
}

function ReplicationSection({ bucket }) {
  const notify = useNotify();
  const rep = useAsync(() => api.getReplication(bucket), [bucket]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const rules = rep.data?.rules || [];
  return (
    <CapabilityContainer id="s3.bucket.replication" title="Replication rules" counter={`(${rules.length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={async () => {
          try {
            await api.putReplicationRules(bucket, rules.filter((r) => !sel.includes(r)));
            notify.success("Successfully deleted replication rule.");
            setSel([]); rep.reload();
          } catch (e) { notify.error(e); }
        }}>Delete</Button>
        <Button onClick={() => setCreate({ id: "", prefix: "", destination: "" })}>Create replication rule</Button>
      </SpaceBetween>}>
      {rep.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : rep.data?.error ? <ErrorAlert error={rep.data.error} />
        : <Table variant="embedded" items={rules} selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)} trackBy="id"
            columnDefinitions={[{ id: "id", header: "Replication rule name", cell: (r) => r.id }, { id: "status", header: "Status", cell: (r) => r.status },
              { id: "dest", header: "Destination bucket", cell: (r) => r.destination }, { id: "scope", header: "Scope", cell: (r) => r.prefix ? `Prefix ${r.prefix}` : "Entire bucket" }]}
            empty={<Box textAlign="center" color="inherit"><b>No replication rules</b><Box variant="p" color="inherit">Bucket Versioning must be Enabled before a replication rule can be created.</Box></Box>} />}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create replication rule"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              const rule = { id: create.id || `rule-${Date.now()}`, status: "Enabled", prefix: create.prefix, destination: create.destination };
              await api.putReplicationRules(bucket, [...rules, rule]);
              notify.success(`Successfully created replication rule.${saveNotice("s3.bucket.replication")}`);
              setCreate(null); rep.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create rule</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Replication rule name"><Input value={create.id} onChange={({ detail }) => setCreate({ ...create, id: detail.value })} /></FormField>
          <FormField label="Destination bucket" description="Must be an existing bucket in this Vyomi appliance.">
            <Input value={create.destination} onChange={({ detail }) => setCreate({ ...create, destination: detail.value })} />
          </FormField>
          <FormField label="Prefix" description="Limit the scope of this rule to keys starting with this prefix. Leave blank to apply to the entire bucket.">
            <Input value={create.prefix} onChange={({ detail }) => setCreate({ ...create, prefix: detail.value })} />
          </FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function InventorySection({ bucket }) {
  const notify = useNotify();
  const inv = useAsync(() => api.getInventory(bucket), [bucket]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const configs = inv.data?.configs || [];
  return (
    <CapabilityContainer id="s3.bucket.inventory" title="Inventory configurations" counter={`(${configs.length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={async () => {
          for (const c of sel) await api.deleteInventory(bucket, c.id);
          notify.success("Successfully deleted inventory configuration.");
          setSel([]); inv.reload();
        }}>Delete</Button>
        <Button onClick={() => setCreate({ id: "", destinationBucket: "" })}>Create inventory configuration</Button>
      </SpaceBetween>}>
      {inv.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : inv.error ? <ErrorAlert error={inv.error} />
        : <Table variant="embedded" items={configs} selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)} trackBy="id"
            columnDefinitions={[{ id: "name", header: "Name", cell: (c) => c.id }, { id: "dest", header: "Destination", cell: (c) => c.destination },
              { id: "freq", header: "Frequency", cell: (c) => c.frequency }, { id: "format", header: "Format", cell: (c) => c.format }]}
            empty={<Box textAlign="center" color="inherit"><b>No inventory configurations</b></Box>} />}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create inventory configuration"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              await api.putInventory(bucket, { id: create.id, destinationBucket: create.destinationBucket });
              notify.success(`Successfully created inventory configuration.${saveNotice("s3.bucket.inventory")}`);
              setCreate(null); inv.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Name"><Input value={create.id} onChange={({ detail }) => setCreate({ ...create, id: detail.value })} /></FormField>
          <FormField label="Destination bucket" description="Must be an existing bucket in this Vyomi appliance.">
            <Input value={create.destinationBucket} onChange={({ detail }) => setCreate({ ...create, destinationBucket: detail.value })} />
          </FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function Management({ bucket }) {
  const notify = useNotify();
  const lc = useAsync(() => api.getLifecycle(bucket), [bucket]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const rules = lc.data?.rules || [];
  return (
    <SpaceBetween size="l">
      <SubSetting title="Lifecycle rules" state={lc} render={(d) => (
        <Table variant="container"
          header={<Header variant="h2" counter={`(${d.rules.length})`} description="Use lifecycle rules to define actions you want Amazon S3 to take during an object's lifetime."
            actions={<SpaceBetween direction="horizontal" size="xs">
              <Button disabled={!sel.length} onClick={async () => {
                try { await api.putLifecycleRules(bucket, rules.filter((r) => !sel.includes(r))); notify.success("Successfully deleted lifecycle rule."); setSel([]); lc.reload(); }
                catch (e) { notify.error(e); }
              }}>Delete</Button>
              <Button onClick={() => setCreate({ id: "", prefix: "", mode: "days", expirationDays: "30", expirationDate: "" })}>Create lifecycle rule</Button>
            </SpaceBetween>}>Lifecycle rules</Header>}
          items={d.rules} selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          trackBy="id"
          columnDefinitions={[{ id: "id", header: "Lifecycle rule name", cell: (r) => r.id }, { id: "status", header: "Status", cell: (r) => r.status }, { id: "scope", header: "Scope", cell: (r) => r.prefix ? `Prefix ${r.prefix}` : "Entire bucket" }]}
          empty={<Box textAlign="center" color="inherit"><b>No lifecycle rules</b><Box variant="p" color="inherit">There are no lifecycle rules for this bucket.</Box></Box>} />
      )} />
      <ReplicationSection bucket={bucket} />
      <InventorySection bucket={bucket} />
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create lifecycle rule"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              const rule = { id: create.id || `rule-${Date.now()}`, status: "Enabled", prefix: create.prefix,
                expirationDays: create.mode === "days" ? Number(create.expirationDays) || null : null,
                expirationDate: create.mode === "date" ? create.expirationDate : null };
              await api.putLifecycleRules(bucket, [...rules, rule]);
              notify.success("Successfully created lifecycle rule.");
              setCreate(null); lc.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create rule</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Lifecycle rule name"><Input value={create.id} onChange={({ detail }) => setCreate({ ...create, id: detail.value })} /></FormField>
          <FormField label="Prefix" description="Limit the scope of this rule to keys starting with this prefix. Leave blank to apply to the entire bucket.">
            <Input value={create.prefix} onChange={({ detail }) => setCreate({ ...create, prefix: detail.value })} />
          </FormField>
          <FormField label="Expire current version of objects">
            <RadioGroup value={create.mode} onChange={({ detail }) => setCreate({ ...create, mode: detail.value })}
              items={[{ value: "days", label: "Days after object creation" }, { value: "date", label: "On a specific date" }]} />
          </FormField>
          {create.mode === "days"
            ? <FormField label="Days after creation"><Input type="number" value={create.expirationDays} onChange={({ detail }) => setCreate({ ...create, expirationDays: detail.value })} /></FormField>
            : <FormField label="Expiration date" description="ISO 8601, e.g. 2026-12-31T00:00:00.000Z">
                <Input value={create.expirationDate} onChange={({ detail }) => setCreate({ ...create, expirationDate: detail.value })} placeholder="2026-12-31T00:00:00.000Z" />
              </FormField>}
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

const pretty = (s) => { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; } };
export { NotSimulated };

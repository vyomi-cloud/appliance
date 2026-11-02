/* Object detail — Properties come from a real HeadObject; Versions from a real
 * ListObjectVersions (the version chain Vyomi already keeps per key). ACL, server-side
 * encryption and Object Lock legal hold/retention are real round trips through the
 * native API (capability-gated); per-object tagging and additional checksums aren't
 * modeled, so they render as declared gaps rather than fake success. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Link from "@cloudscape-design/components/link";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Tiles from "@cloudscape-design/components/tiles";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { WIRE_BASE } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";
import TagsContainer from "./TagsContainer.jsx";

export default function ObjectDetail({ params, query }) {
  const bucket = params.bucket;
  const objectKey = query.prefix || "";
  const notify = useNotify();
  const [tab, setTab] = useState("properties");
  const head = useAsync(() => api.headObject(bucket, objectKey), [bucket, objectKey]);
  const region = useAsync(() => api.bucketRegion(bucket), [bucket]);
  const url = WIRE_BASE + api.objectUrl(bucket, objectKey);

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          info={<Link variant="info">Info</Link>}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={async () => { try { await navigator.clipboard.writeText(`s3://${bucket}/${objectKey}`); notify.success("S3 URI copied"); } catch { notify.info(`s3://${bucket}/${objectKey}`, "S3 URI"); } }}>Copy S3 URI</Button>
              <Button href={url} target="_blank" iconName="download">Download</Button>
              <Button href={url} target="_blank" iconName="external">Open</Button>
            </SpaceBetween>
          }
        >
          {objectKey}
        </Header>
      }
    >
      {head.error ? <ErrorAlert error={head.error} /> : (
        <Tabs
          activeTabId={tab}
          onChange={({ detail }) => setTab(detail.activeTabId)}
          tabs={[
            { id: "properties", label: "Properties", content: <Properties bucket={bucket} objectKey={objectKey} head={head} region={region.data} url={url} /> },
            { id: "permissions", label: "Permissions", content: <ObjectAcl bucket={bucket} objectKey={objectKey} /> },
            { id: "versions", label: "Versions", content: <Versions bucket={bucket} objectKey={objectKey} /> },
          ]}
        />
      )}
    </ContentLayout>
  );
}

function Properties({ bucket, objectKey, head, region, url }) {
  const d = head.data;
  const lock = useAsync(() => api.getObjectLock(bucket), [bucket]);
  const tags = useAsync(() => api.getObjectTags(bucket, objectKey), [bucket, objectKey]);
  return (
    <SpaceBetween size="l">
      <KeyValue title="Object overview" items={[
        ["Owner", "simulator (cloudlearn-simulator)"],
        ["AWS Region", region],
        ["Last modified", d && fmtDate(d.lastModified)],
        ["Size", d && fmtBytes(d.size)],
        ["Type", d?.contentType],
        ["Key", objectKey],
        ["S3 URI", `s3://${bucket}/${objectKey}`],
        ["Amazon Resource Name (ARN)", `arn:aws:s3:::${bucket}/${objectKey}`],
        ["Entity tag (Etag)", d?.etag],
        ["Object URL", <Link href={url} external>{url}</Link>],
      ]} />
      <NotSimulatedContainer title="Object management overview" />
      <KeyValue title="Storage class" items={[["Storage class", d?.storageClass]]} />
      <CapabilityContainer id="s3.bucket.encryption" title="Server-side encryption settings">
        <SpaceBetween size="s">
          <div><Box variant="awsui-key-label">Encryption type</Box><div>{{ AES256: "Server-side encryption with Amazon S3 managed keys (SSE-S3)", "aws:kms": "Server-side encryption with AWS Key Management Service keys (SSE-KMS)", "aws:kms:dsse": "Dual-layer server-side encryption with AWS Key Management Service keys (DSSE-KMS)" }[d?.encryption] || d?.encryption}</div></div>
          {d?.kmsKeyId && <div><Box variant="awsui-key-label">AWS KMS key</Box><div>{d.kmsKeyId}</div></div>}
        </SpaceBetween>
      </CapabilityContainer>
      <KeyValue title="Additional checksums" columns={3} items={d?.checksum
        ? [["Checksum function", d.checksum.algorithm], ["Checksum type", d.checksum.type === "FULL_OBJECT" ? "Full object" : "Composite"], ["Checksum value", d.checksum.value]]
        : [["Checksum function", "-"], ["Checksum value", "No additional checksum was stored when this object was uploaded."]]} />
      <TagsContainer state={tags} save={(t) => api.putObjectTags(bucket, objectKey, t)} limit={10} />
      <Table
        variant="container"
        header={<Header variant="h2" counter={`(${Object.keys(d?.metadata || {}).length})`}>Metadata</Header>}
        items={Object.entries(d?.metadata || {}).map(([k, v]) => ({ k, v }))}
        columnDefinitions={[{ id: "type", header: "Type", cell: () => "System-defined" }, { id: "key", header: "Key", cell: (r) => `x-amz-meta-${r.k}` }, { id: "value", header: "Value", cell: (r) => r.v }]}
        empty={<Box textAlign="center" color="inherit"><b>No metadata</b></Box>}
      />
      <LegalHold bucket={bucket} objectKey={objectKey} lockLoading={lock.loading} lockEnabled={!!lock.data?.enabled} />
      <Retention bucket={bucket} objectKey={objectKey} lockLoading={lock.loading} lockEnabled={!!lock.data?.enabled} />
    </SpaceBetween>
  );
}

function ObjectAcl({ bucket, objectKey }) {
  const notify = useNotify();
  const acl = useAsync(() => api.getObjectAcl(bucket, objectKey), [bucket, objectKey]);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  return (
    <CapabilityContainer id="s3.bucket.acl" title="Access control list (ACL)" description="Grant basic read/write permissions to other AWS accounts for this object."
      actions={<Button onClick={() => { setError(null); setEdit("private"); }}>Edit</Button>}>
      {acl.loading ? <StatusIndicator type="loading">Loading</StatusIndicator>
        : acl.data?.error ? <ErrorAlert error={acl.data.error} />
        : <Table variant="embedded" items={acl.data?.grants || []}
            columnDefinitions={[{ id: "g", header: "Grantee", cell: (g) => g.grantee }, { id: "t", header: "Type", cell: (g) => g.type }, { id: "p", header: "Permission", cell: (g) => g.permission }]}
            empty={<Box textAlign="center">No grants</Box>} />}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit access control list (ACL)"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try { await api.putObjectAcl(bucket, objectKey, edit); notify.success(`Successfully edited access control list (ACL).${saveNotice("s3.bucket.acl")}`); setEdit(null); acl.reload(); }
            catch (e) { setError(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          <Tiles value={edit} onChange={({ detail }) => setEdit(detail.value)} columns={1} items={[
            { value: "private", label: "Private" }, { value: "public-read", label: "Public read" },
            { value: "public-read-write", label: "Public read/write" }, { value: "authenticated-read", label: "Authenticated read" },
          ]} />
          {error && <ErrorAlert error={error} />}
        </SpaceBetween>
      </Modal>
    </CapabilityContainer>
  );
}

function LegalHold({ bucket, objectKey, lockLoading, lockEnabled }) {
  const notify = useNotify();
  const st = useAsync(() => lockEnabled ? api.getLegalHold(bucket, objectKey) : Promise.resolve({ unsupported: true }), [bucket, objectKey, lockEnabled]);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  if (lockLoading || st.loading) return <CapabilityContainer id="s3.bucket.object-lock" title="Object Lock legal hold"><StatusIndicator type="loading">Loading</StatusIndicator></CapabilityContainer>;
  if (st.data?.unsupported) return <NotSimulatedContainer title="Object Lock legal hold" note="Object Lock is disabled for this bucket." />;
  return (
    <CapabilityContainer id="s3.bucket.object-lock" title="Object Lock legal hold"
      actions={<Button onClick={() => setEdit(st.data?.status === "ON" ? "OFF" : "ON")}>Edit</Button>}>
      {st.data?.error ? <ErrorAlert error={st.data.error} />
        : <div><Box variant="awsui-key-label">Legal hold</Box><div>{st.data?.status === "ON" ? "On" : "Off"}</div></div>}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit legal hold"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try { await api.putLegalHold(bucket, objectKey, edit); notify.success("Successfully edited legal hold."); setEdit(null); st.reload(); }
            catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        Set legal hold status to <b>{edit === "ON" ? "On" : "Off"}</b>?
      </Modal>
    </CapabilityContainer>
  );
}

function Retention({ bucket, objectKey, lockLoading, lockEnabled }) {
  const notify = useNotify();
  const st = useAsync(() => lockEnabled ? api.getRetention(bucket, objectKey) : Promise.resolve({ unsupported: true }), [bucket, objectKey, lockEnabled]);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  if (lockLoading || st.loading) return <CapabilityContainer id="s3.bucket.object-lock" title="Object Lock retention"><StatusIndicator type="loading">Loading</StatusIndicator></CapabilityContainer>;
  if (st.data?.unsupported) return <NotSimulatedContainer title="Object Lock retention" note="Object Lock is disabled for this bucket." />;
  return (
    <CapabilityContainer id="s3.bucket.object-lock" title="Object Lock retention"
      actions={<Button onClick={() => { setError(null); setEdit({ mode: st.data?.mode || "GOVERNANCE", date: (st.data?.retainUntil || "").slice(0, 10) }); }}>Edit</Button>}>
      {st.data?.error ? <ErrorAlert error={st.data.error} />
        : st.data?.mode
          ? <ColumnLayout columns={2}><div><Box variant="awsui-key-label">Retention mode</Box><div>{st.data.mode}</div></div><div><Box variant="awsui-key-label">Retain until date</Box><div>{fmtDate(st.data.retainUntil)}</div></div></ColumnLayout>
          : <Box color="text-body-secondary">No retention period set.</Box>}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit retention"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try { await api.putRetention(bucket, objectKey, edit.mode, `${edit.date}T00:00:00.000Z`); notify.success("Successfully edited retention."); setEdit(null); st.reload(); }
            catch (e) { setError(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <SpaceBetween size="m">
          <FormField label="Retention mode">
            <Tiles value={edit.mode} onChange={({ detail }) => setEdit({ ...edit, mode: detail.value })} columns={2}
              items={[{ value: "GOVERNANCE", label: "Governance" }, { value: "COMPLIANCE", label: "Compliance" }]} />
          </FormField>
          <FormField label="Retain until date"><Input type="date" value={edit.date} onChange={({ detail }) => setEdit({ ...edit, date: detail.value })} /></FormField>
          {error && <ErrorAlert error={error} />}
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function Versions({ bucket, objectKey }) {
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listObjectVersions(bucket, objectKey), [bucket, objectKey]);
  return (
    <Table
      variant="container"
      loading={loading}
      header={<Header variant="h2" counter={`(${data.length})`} actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={reload} />}>Versions</Header>}
      items={data}
      trackBy="versionId"
      columnDefinitions={[
        { id: "id", header: "Version ID", cell: (v) => v.versionId },
        { id: "type", header: "Type", cell: (v) => v.deleteMarker ? "Delete marker" : v.isLatest ? "Latest version" : "Previous version" },
        { id: "modified", header: "Last modified", cell: (v) => fmtDate(v.modified) },
        { id: "size", header: "Size", cell: (v) => v.deleteMarker ? "-" : fmtBytes(v.size) },
        { id: "storageClass", header: "Storage class", cell: (v) => v.deleteMarker ? "-" : v.storageClass },
        { id: "actions", header: "", cell: (v) => !v.deleteMarker && (
          <SpaceBetween direction="horizontal" size="xs">
            <Link href={WIRE_BASE + api.objectUrl(bucket, objectKey) + `?versionId=${encodeURIComponent(v.versionId)}`} external>Download</Link>
            <Button variant="inline-link" onClick={async () => { try { await api.deleteObject(bucket, objectKey, v.versionId); notify.success("Successfully deleted version."); reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
          </SpaceBetween>
        ) },
      ]}
      empty={error ? <ErrorAlert error={error} /> : <Box textAlign="center" color="inherit"><b>No versions</b></Box>}
    />
  );
}

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
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";
import Permissions from "./Permissions.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { vy } from "../../../common/VyomiMark.jsx";

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
          { id: "metadata", label: "Metadata", content: <NotSimulatedContainer title="Metadata configuration" note={vy("S3 Metadata (the queryable metadata table for a bucket) isn't modeled in Vyomi.")} /> },
          { id: "properties", label: "Properties", content: <Properties bucket={bucket} /> },
          { id: "permissions", label: "Permissions", content: <Permissions bucket={bucket} /> },
          { id: "metrics", label: "Metrics", content: <Metrics /> },
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
      <SubSetting title="Tags" state={tags} render={(d) => (
        <Container header={<Header variant="h2" counter={`(${d.tags.length})`}>Tags</Header>}>
          <Table variant="embedded" items={d.tags} columnDefinitions={[{ id: "k", header: "Key", cell: (t) => t.key }, { id: "v", header: "Value", cell: (t) => t.value || "-" }]}
            empty={<Box textAlign="center" color="inherit"><b>No tags</b><Box variant="p" color="inherit">There are no tags associated with this resource.</Box></Box>} />
        </Container>
      )} />
      <SubSetting title="Default encryption" state={enc} render={(d) => (
        <KeyValue title="Default encryption" items={[
          ["Encryption type", d.absent ? "Server-side encryption with Amazon S3 managed keys (SSE-S3)" : { AES256: "Server-side encryption with Amazon S3 managed keys (SSE-S3)", "aws:kms": "Server-side encryption with AWS Key Management Service keys (SSE-KMS)", "aws:kms:dsse": "Dual-layer server-side encryption with AWS Key Management Service keys (DSSE-KMS)" }[d.algorithm] || d.algorithm],
          ["Bucket Key", d.bucketKey ? "Enabled" : "Disabled"],
          ...(d.kmsKey ? [["Encryption key ARN", d.kmsKey]] : []),
        ]} />
      )} />
      <CapabilityContainer id="s3.bucket.intelligent-tiering" title="Intelligent-Tiering Archive configurations" />
      <CapabilityContainer id="s3.bucket.logging" title="Server access logging" />
      <NotSimulatedContainer title="AWS CloudTrail data events" />
      <CapabilityContainer id="s3.bucket.notification" title="Event notifications" />
      <NotSimulatedContainer title="Amazon EventBridge" />
      <CapabilityContainer id="s3.bucket.accelerate" title="Transfer acceleration" />
      <CapabilityContainer id="s3.bucket.object-lock" title="Object Lock" />
      <CapabilityContainer id="s3.bucket.request-payment" title="Requester pays" />
      <CapabilityContainer id="s3.bucket.website" title="Static website hosting" />
    </SpaceBetween>
  );
}

function Metrics() {
  return (
    <SpaceBetween size="l">
      <NotSimulatedContainer title="Bucket metrics" feature="CloudWatch storage metrics for S3" />
      <NotSimulatedContainer title="Storage Lens metrics" />
      <NotSimulatedContainer title="Request metrics" />
      <NotSimulatedContainer title="Replication metrics" />
      <NotSimulatedContainer title="Data transfer metrics" />
    </SpaceBetween>
  );
}

function Management({ bucket }) {
  const lc = useAsync(() => api.getLifecycle(bucket), [bucket]);
  return (
    <SpaceBetween size="l">
      <SubSetting title="Lifecycle rules" state={lc} render={(d) => (
        <Table variant="container" header={<Header variant="h2" counter={`(${d.rules.length})`} description="Use lifecycle rules to define actions you want Amazon S3 to take during an object's lifetime.">Lifecycle rules</Header>}
          items={d.rules} columnDefinitions={[{ id: "id", header: "Lifecycle rule name", cell: (r) => r.id }, { id: "status", header: "Status", cell: (r) => r.status }, { id: "scope", header: "Scope", cell: (r) => r.prefix ? `Prefix ${r.prefix}` : "Entire bucket" }]}
          empty={<Box textAlign="center" color="inherit"><b>No lifecycle rules</b><Box variant="p" color="inherit">There are no lifecycle rules for this bucket.</Box></Box>} />
      )} />
      <CapabilityContainer id="s3.bucket.replication" title="Replication rules" />
      <CapabilityContainer id="s3.bucket.inventory" title="Inventory configurations" />
    </SpaceBetween>
  );
}

const pretty = (s) => { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; } };
export { NotSimulated };

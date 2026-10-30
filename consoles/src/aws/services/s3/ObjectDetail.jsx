/* Object detail — Properties come from a real HeadObject; Versions from a real
 * ListObjectVersions (the version chain Vyomi already keeps per key). ACL, per-object
 * tagging, additional checksums and Object Lock legal hold/retention aren't modeled by
 * the backend, so they render as declared gaps rather than fake success. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Link from "@cloudscape-design/components/link";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import { WIRE_BASE } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

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
            { id: "permissions", label: "Permissions", content: <NotSimulatedContainer title="Access control list (ACL)" /> },
            { id: "versions", label: "Versions", content: <Versions bucket={bucket} objectKey={objectKey} /> },
          ]}
        />
      )}
    </ContentLayout>
  );
}

function Properties({ bucket, objectKey, head, region, url }) {
  const d = head.data;
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
      <NotSimulatedContainer title="Server-side encryption settings" />
      <NotSimulatedContainer title="Additional checksums" />
      <NotSimulatedContainer title="Tags" />
      <Table
        variant="container"
        header={<Header variant="h2" counter={`(${Object.keys(d?.metadata || {}).length})`}>Metadata</Header>}
        items={Object.entries(d?.metadata || {}).map(([k, v]) => ({ k, v }))}
        columnDefinitions={[{ id: "type", header: "Type", cell: () => "System-defined" }, { id: "key", header: "Key", cell: (r) => `x-amz-meta-${r.k}` }, { id: "value", header: "Value", cell: (r) => r.v }]}
        empty={<Box textAlign="center" color="inherit"><b>No metadata</b></Box>}
      />
      <NotSimulatedContainer title="Object Lock legal hold" />
      <NotSimulatedContainer title="Object Lock retention" />
    </SpaceBetween>
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

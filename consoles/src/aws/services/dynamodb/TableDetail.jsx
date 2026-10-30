import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert, fmtDate, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { attrType, capacity, keyOf, statusOf } from "./Tables.jsx";
import * as api from "./api.js";

export default function TableDetail({ params, query }) {
  const name = params.name;
  const [tab, setTab] = useState(query.tab || "overview");
  const t = useAsync(() => api.describeTable(name), [name]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const d = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={t.reload} iconName="refresh" ariaLabel="Refresh" />
        <Button variant="primary" href={href("dynamodb", "tables", name, "items")} onFollow={follow}>Explore table items</Button>
      </SpaceBetween>
    }>{name}</Header>}>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "overview", label: "Overview", content: <Overview d={d} /> },
        { id: "indexes", label: "Indexes", content: <Indexes d={d} /> },
        { id: "monitor", label: "Monitor", content: <NotSimulatedContainer title="CloudWatch metrics" feature="DynamoDB CloudWatch metrics" /> },
        { id: "global-tables", label: "Global tables", content: <NotSimulatedContainer title="Replicas" feature="Global tables (multi-Region replicas)" /> },
        { id: "backups", label: "Backups", content: <Backups name={name} /> },
        { id: "exports", label: "Exports and streams", content: <KeyValue title="DynamoDB stream details" columns={2} items={[["Stream status", d.StreamSpecification?.StreamEnabled ? "On" : "Off"], ["View type", d.StreamSpecification?.StreamViewType]]} /> },
        { id: "permissions", label: "Permissions", content: <NotSimulatedContainer title="Resource-based policy for table" /> },
        { id: "settings", label: "Additional settings", content: <Settings d={d} /> },
      ]} />
    </ContentLayout>
  );
}

function Overview({ d }) {
  const pk = keyOf(d, "HASH"), sk = keyOf(d, "RANGE");
  return (
    <SpaceBetween size="l">
      <KeyValue title="General information" columns={4} items={[
        ["Partition key", pk && `${pk} (${attrType(d, pk)})`], ["Sort key", sk ? `${sk} (${attrType(d, sk)})` : "-"],
        ["Capacity mode", capacity(d)], ["Table status", statusOf(d.TableStatus)],
        ["Alarms", "No active alarms"], ["Point-in-time recovery (PITR)", "Off"], ["Item count", d.ItemCount ?? 0], ["Table size", `${d.TableSizeBytes ?? 0} bytes`],
        ["Amazon Resource Name (ARN)", d.TableArn], ["Creation date", fmtDate(d.CreationDateTime)], ["Deletion protection", d.DeletionProtectionEnabled ? "On" : "Off"],
        ["Table class", d.TableClassSummary?.TableClass === "STANDARD_INFREQUENT_ACCESS" ? "DynamoDB Standard-IA" : "DynamoDB Standard"],
      ]} />
    </SpaceBetween>
  );
}

function Indexes({ d }) {
  const rows = [...(d.GlobalSecondaryIndexes || []).map((i) => ({ ...i, kind: "Global" })), ...(d.LocalSecondaryIndexes || []).map((i) => ({ ...i, kind: "Local" }))];
  return (
    <Table variant="container" header={<Header variant="h2" counter={`(${rows.length})`}>Global secondary indexes</Header>} items={rows}
      columnDefinitions={[
        { id: "n", header: "Name", cell: (i) => i.IndexName },
        { id: "s", header: "Status", cell: (i) => statusOf(i.IndexStatus || "ACTIVE") },
        { id: "pk", header: "Partition key", cell: (i) => i.KeySchema?.find((k) => k.KeyType === "HASH")?.AttributeName },
        { id: "sk", header: "Sort key", cell: (i) => i.KeySchema?.find((k) => k.KeyType === "RANGE")?.AttributeName || "-" },
        { id: "p", header: "Projected attributes", cell: (i) => i.Projection?.ProjectionType || "-" },
        { id: "k", header: "Type", cell: (i) => i.kind },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No global secondary indexes</b><Box variant="p" color="inherit">You have not created any global secondary indexes for this table.</Box></Box>} />
  );
}

function Backups({ name }) {
  const b = useAsync(() => api.describeBackups(name), [name]);
  if (b.loading) return <Spinner />;
  if (b.data === null) return <NotSimulatedContainer title="Point-in-time recovery (PITR)" />;
  const pitr = b.data?.PointInTimeRecoveryDescription?.PointInTimeRecoveryStatus;
  return <KeyValue title="Point-in-time recovery (PITR)" columns={2} items={[["Status", pitr === "ENABLED" ? "On" : "Off"], ["Earliest restore date", fmtDate(b.data?.PointInTimeRecoveryDescription?.EarliestRestorableDateTime)]]} />;
}

function Settings({ d }) {
  const ttl = useAsync(() => api.describeTtl(d.TableName), [d.TableName]);
  const tags = useAsync(() => api.tags(d.TableArn), [d.TableArn]);
  return (
    <SpaceBetween size="l">
      <KeyValue title="Read/write capacity" columns={2} items={[["Capacity mode", capacity(d)], ["Read capacity", d.ProvisionedThroughput?.ReadCapacityUnits || "On-demand"], ["Write capacity", d.ProvisionedThroughput?.WriteCapacityUnits || "On-demand"]]} />
      {ttl.data === null ? <NotSimulatedContainer title="Time to Live (TTL)" /> :
        <KeyValue title="Time to Live (TTL)" columns={2} items={[["TTL status", ttl.data?.TimeToLiveStatus === "ENABLED" ? "On" : "Off"], ["TTL attribute", ttl.data?.AttributeName]]} />}
      <KeyValue title="Encryption" columns={2} items={[["Key management", d.SSEDescription?.SSEType === "KMS" ? "AWS managed key" : "Owned by Amazon DynamoDB"]]} />
      {tags.data === null ? <NotSimulatedContainer title="Tags" /> : (
        <Table variant="container" header={<Header variant="h2" counter={`(${tags.data?.length || 0})`}>Tags</Header>} items={tags.data || []} loading={tags.loading}
          columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.Key }, { id: "v", header: "Value", cell: (x) => x.Value || "-" }]}
          empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      )}
    </SpaceBetween>
  );
}

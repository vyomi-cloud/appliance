import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { follow } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, KeyValue, fmtBytes, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

function DetailsModal({ arn, onDismiss }) {
  const d = useAsync(() => (arn ? api.describeExport(arn) : Promise.resolve(null)), [arn]);
  return (
    <Modal visible={!!arn} onDismiss={onDismiss} size="large" header="Export details"
      footer={<Box float="right"><Button onClick={onDismiss}>Close</Button></Box>}>
      {d.loading ? "Loading…" : d.error ? <ErrorAlert error={d.error} /> : (
        <KeyValue columns={2} items={[
          ["Status", d.data?.ExportStatus], ["Table ARN", d.data?.TableArn],
          ["Destination S3 bucket", d.data?.S3Bucket], ["S3 prefix", d.data?.S3Prefix || "-"],
          ["Export format", d.data?.ExportFormat], ["Export type", d.data?.ExportType],
          ["Item count", d.data?.ItemCount], ["Size", fmtBytes(d.data?.BilledSizeBytes)],
          ["Start time", fmtDate(d.data?.StartTime)], ["End time", fmtDate(d.data?.EndTime)],
          ["Manifest", d.data?.ExportManifest || "-"],
          ...(d.data?.FailureCode ? [["Failure reason", `${d.data.FailureCode}: ${d.data.FailureMessage}`]] : []),
          ["Export ARN", d.data?.ExportArn],
        ]} />
      )}
    </Modal>
  );
}

export default function Exports() {
  const [sel, setSel] = useState([]);
  const [details, setDetails] = useState(null);
  // ListExports only returns {ExportArn, ExportStatus, ExportType} (the real DynamoDB
  // shape) — DescribeExport per row fills in the table/bucket/time columns.
  const exports = useAsync(async () => {
    const summaries = await api.listExports();
    return Promise.all(summaries.map((s) => api.describeExport(s.ExportArn)));
  }, []);

  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="dynamodb.exports" />}>Exports to S3</Header>}>
      <ResourceTable
        resourceName="Exports"
        items={exports.data || []}
        loading={exports.loading}
        error={exports.error}
        onRefresh={exports.reload}
        trackBy="ExportArn"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        columns={[
          { id: "arn", header: "Export ARN", isRowHeader: true, cell: (e) => e.ExportArn },
          { id: "table", header: "Table name", cell: (e) => (e.TableArn || "").split(":table/", 2)[1]?.split("/")[0] || "" },
          { id: "bucket", header: "Destination S3 bucket", cell: (e) => e.S3Bucket },
          { id: "status", header: "Status", cell: (e) => <StatusIndicator type={e.ExportStatus === "COMPLETED" ? "success" : e.ExportStatus === "FAILED" ? "error" : "in-progress"}>{e.ExportStatus}</StatusIndicator> },
          { id: "start", header: "Export job start time", cell: (e) => fmtDate(e.StartTime) },
          { id: "type", header: "Export type", cell: (e) => e.ExportType },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setDetails(sel[0].ExportArn)}>View details</Button>
            <Button variant="primary" href="#/dynamodb/exports/create" onFollow={follow}>Export to S3</Button>
          </SpaceBetween>
        }
        empty={{ title: "No exports", subtitle: "You have not exported any tables to Amazon S3 yet.",
                action: <Button href="#/dynamodb/exports/create" onFollow={follow}>Export to S3</Button> }}
      />
      <DetailsModal arn={details} onDismiss={() => setDetails(null)} />
    </ContentLayout>
  );
}

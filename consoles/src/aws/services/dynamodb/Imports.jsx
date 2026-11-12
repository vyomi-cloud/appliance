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
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const importId = (arn) => (arn || "").split("/import/", 2)[1] || arn;
const tableNameOf = (arn) => (arn || "").split(":table/", 2)[1]?.split("/")[0] || "";

function DetailsModal({ arn, onDismiss }) {
  const d = useAsync(() => (arn ? api.describeImport(arn) : Promise.resolve(null)), [arn]);
  return (
    <Modal visible={!!arn} onDismiss={onDismiss} size="large" header="Import details"
      footer={<Box float="right"><Button onClick={onDismiss}>Close</Button></Box>}>
      {d.loading ? "Loading…" : d.error ? <ErrorAlert error={d.error} /> : (
        <KeyValue columns={2} items={[
          ["Status", d.data?.ImportStatus], ["Table ARN", d.data?.TableArn],
          ["Source S3 bucket", d.data?.S3BucketSource?.S3Bucket], ["S3 key prefix", d.data?.S3BucketSource?.S3KeyPrefix || "-"],
          ["Input format", d.data?.InputFormat], ["Input compression", d.data?.InputCompressionType],
          ["Processed item count", d.data?.ProcessedItemCount], ["Imported item count", d.data?.ImportedItemCount],
          ["Processed size", `${d.data?.ProcessedSizeBytes ?? 0} bytes`], ["Error count", d.data?.ErrorCount],
          ["Start time", fmtDate(d.data?.StartTime)], ["End time", fmtDate(d.data?.EndTime)],
          ...(d.data?.FailureCode ? [["Failure reason", `${d.data.FailureCode}: ${d.data.FailureMessage}`]] : []),
          ["Import ARN", d.data?.ImportArn],
        ]} />
      )}
    </Modal>
  );
}

export default function Imports() {
  const [sel, setSel] = useState([]);
  const [details, setDetails] = useState(null);
  const imports = useAsync(async () => {
    const summaries = await api.listImports();
    return Promise.all(summaries.map((s) => api.describeImport(s.ImportArn)));
  }, []);

  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="dynamodb.imports" />}>Imports from S3</Header>}>
      <ResourceTable
        resourceName="Imports"
        items={imports.data || []}
        loading={imports.loading}
        error={imports.error}
        onRefresh={imports.reload}
        trackBy="ImportArn"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        columns={[
          { id: "id", header: "Import ID", isRowHeader: true, cell: (e) => importId(e.ImportArn) },
          { id: "table", header: "Table", cell: (e) => tableNameOf(e.TableArn) },
          { id: "format", header: "Format", cell: (e) => e.InputFormat },
          { id: "status", header: "Status", cell: (e) => <StatusIndicator type={e.ImportStatus === "COMPLETED" ? "success" : e.ImportStatus === "FAILED" ? "error" : "in-progress"}>{e.ImportStatus}</StatusIndicator> },
          { id: "start", header: "Import job start time", cell: (e) => fmtDate(e.StartTime) },
          { id: "end", header: "End time", cell: (e) => fmtDate(e.EndTime) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setDetails(sel[0].ImportArn)}>View details</Button>
            <Button variant="primary" href="#/dynamodb/imports/create" onFollow={follow}>Import from S3</Button>
          </SpaceBetween>
        }
        empty={{ title: "No imports", subtitle: "You have not imported any tables from Amazon S3 yet.",
                action: <Button href="#/dynamodb/imports/create" onFollow={follow}>Import from S3</Button> }}
      />
      <DetailsModal arn={details} onDismiss={() => setDetails(null)} />
    </ContentLayout>
  );
}

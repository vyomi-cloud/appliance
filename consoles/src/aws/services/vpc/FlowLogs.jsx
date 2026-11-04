/* Flow logs tab, shared by VPC and subnet detail pages (api.js: CreateFlowLogs /
 * DescribeFlowLogs / DeleteFlowLogs over the native EC2 Query wire). Vyomi manages the
 * flow log resource for real; it never delivers records to CloudWatch Logs or S3 — see
 * aws.vpc.flow-logs in core/capabilities/aws/vpc.json for why. */
import { useState } from "react";
import Table from "@cloudscape-design/components/table";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export function FlowLogsTab({ resourceId, resourceType }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeFlowLogs(), [resourceId]);
  const rows = (t.data || []).filter((f) => f.ResourceId === resourceId);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);

  return (
    <CapabilityContainer id="aws.vpc.flow-logs" title="Flow logs" counter={`(${rows.length})`}
      actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={async () => {
            await api.deleteFlowLogs(sel.map((s) => s.FlowLogId));
            notify.success(`${sel.length} flow log(s) deleted.`); setSel([]); t.reload();
          }}>Delete</Button>
          <Button variant="primary" onClick={() => setCreate(true)}>Create flow log</Button>
        </SpaceBetween>
      }>
      <Table
        variant="embedded"
        items={rows}
        loading={t.loading}
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        trackBy="FlowLogId"
        columnDefinitions={[
          { id: "id", header: "Flow log ID", cell: (f) => f.FlowLogId },
          { id: "filter", header: "Filter", cell: (f) => f.TrafficType },
          { id: "status", header: "Status", cell: (f) => f.FlowLogStatus },
          { id: "destType", header: "Destination type", cell: (f) => (f.LogDestinationType === "s3" ? "S3" : "CloudWatch Logs") },
          { id: "dest", header: "Destination", cell: (f) => f.LogGroupName || f.LogDestination || "-" },
          { id: "interval", header: "Maximum aggregation interval", cell: (f) => `${f.MaxAggregationInterval / 60} minutes` },
          { id: "created", header: "Creation time", cell: (f) => f.CreationTime },
        ]}
        empty={<Box textAlign="center" color="inherit">No flow logs</Box>}
      />
      {create && (
        <CreateFlowLogModal resourceId={resourceId} resourceType={resourceType}
          onDismiss={() => setCreate(false)} onCreated={() => { setCreate(false); t.reload(); }} />
      )}
    </CapabilityContainer>
  );
}

export function CreateFlowLogModal({ resourceId, resourceType, onDismiss, onCreated }) {
  const notify = useNotify();
  const [trafficType, setTrafficType] = useState("ALL");
  const [interval_, setInterval_] = useState("600");
  const [logGroupName, setLogGroupName] = useState("/vpc/flowlogs");
  const [roleArn, setRoleArn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createFlowLog(resourceId, resourceType, {
        trafficType, logDestinationType: "cloud-watch-logs", logGroupName,
        deliverLogsPermissionArn: roleArn, maxAggregationInterval: Number(interval_),
      });
      notify.success("Flow log created.");
      onCreated();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible onDismiss={onDismiss} size="large" header="Create flow log"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button formAction="none" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Create flow log</Button>
      </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="l">
          <Box variant="p" color="text-body-secondary">Resource: {resourceId}</Box>
          <FormField label="Filter">
            <RadioGroup value={trafficType} onChange={({ detail }) => setTrafficType(detail.value)}
              items={[{ value: "ACCEPT", label: "Accept" }, { value: "REJECT", label: "Reject" }, { value: "ALL", label: "All" }]} />
          </FormField>
          <FormField label="Maximum aggregation interval">
            <RadioGroup value={interval_} onChange={({ detail }) => setInterval_(detail.value)}
              items={[{ value: "60", label: "1 minute" }, { value: "600", label: "10 minutes" }]} />
          </FormField>
          <FormField label="Destination log group" description="CloudWatch Logs log group name.">
            <Input value={logGroupName} onChange={({ detail }) => setLogGroupName(detail.value)} />
          </FormField>
          <FormField label="IAM role" description="Grants permission to publish to the log group.">
            <Input value={roleArn} onChange={({ detail }) => setRoleArn(detail.value)} placeholder="arn:aws:iam::123456789012:role/flow-logs-role" />
          </FormField>
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

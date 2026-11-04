/* Flow logs tab, shared by VPC and subnet detail pages (api.js: CreateFlowLogs /
 * DescribeFlowLogs / DeleteFlowLogs over the native EC2 Query wire). Destinations: CloudWatch Logs or S3. Records are produced
 * only when offline netsim enforcement is on (core/netsim/flowdeliver.py); the records viewer reads them back from the
 * CloudWatch Logs group - see aws.vpc.flow-logs in core/capabilities/aws/vpc.json. */
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
import Alert from "@cloudscape-design/components/alert";
import Link from "@cloudscape-design/components/link";
import { awsJson } from "../../../common/wire.js";
import { follow } from "../../../common/router.js";
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
  const [view, setView] = useState(null);

  return (
    <CapabilityContainer id="aws.vpc.flow-logs" title="Flow logs" counter={`(${rows.length})`}
      actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button disabled={sel.length !== 1} onClick={() => setView(sel[0])}>View flow records</Button>
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
      {view && <FlowRecordsModal flowLog={view} onDismiss={() => setView(null)} />}
      {create && (
        <CreateFlowLogModal resourceId={resourceId} resourceType={resourceType}
          onDismiss={() => setCreate(false)} onCreated={() => { setCreate(false); t.reload(); }} />
      )}
    </CapabilityContainer>
  );
}

const DEFAULT_FIELDS = ["version", "account-id", "interface-id", "srcaddr", "dstaddr", "srcport", "dstport", "protocol", "packets", "bytes", "start", "end", "action", "log-status"];

function FlowRecordsModal({ flowLog, onDismiss }) {
  const isS3 = flowLog.LogDestinationType === "s3";
  const group = flowLog.LogGroupName;
  const t = useAsync(async () => {
    if (isS3 || !group) return [];
    const fields = (flowLog.LogFormat || "").match(/\$\{([^}]+)\}/g)?.map((x) => x.slice(2, -1)) || DEFAULT_FIELDS;
    const r = await awsJson("logs", "Logs_20140328.FilterLogEvents", { logGroupName: group, limit: 200 }, { version: "1.1" });
    return (r.events || []).map((e, i) => { const v = e.message.split(" "); return { i, stream: e.logStreamName, ts: e.timestamp, ...Object.fromEntries(fields.map((f, k) => [f, v[k]])) }; });
  }, [flowLog.FlowLogId]);
  const cols = ["interface-id", "srcaddr", "dstaddr", "srcport", "dstport", "protocol", "packets", "bytes", "action"];
  return (
    <Modal visible onDismiss={onDismiss} size="max" header={`Flow records - ${flowLog.FlowLogId}`}>
      <SpaceBetween size="m">
        {isS3
          ? <Alert type="info">This flow log delivers gzip objects under <code>{flowLog.LogDestination}/AWSLogs/&lt;account&gt;/vpcflowlogs/</code>. Browse them in the <Link href="#/s3" onFollow={follow}>S3 console</Link>.</Alert>
          : <Alert type="info">Records are read from log group {group}. They are written only when offline netsim enforcement is on (VYOMI_NETSIM_ENFORCE) with the Docker compute backend and live traffic flowing; Nano has no packets, so no records exist there.</Alert>}
        {!isS3 && <Table variant="embedded" items={t.data || []} loading={t.loading} trackBy="i"
          columnDefinitions={cols.map((c) => ({ id: c, header: c, cell: (r) => r[c] ?? "-" }))}
          empty={<Box textAlign="center" color="inherit">No flow records delivered yet</Box>} />}
        {t.error && <ErrorAlert error={t.error} />}
      </SpaceBetween>
    </Modal>
  );
}

export function CreateFlowLogModal({ resourceId, resourceType, onDismiss, onCreated }) {
  const notify = useNotify();
  const [trafficType, setTrafficType] = useState("ALL");
  const [interval_, setInterval_] = useState("600");
  const [destType, setDestType] = useState("cloud-watch-logs");
  const [logGroupName, setLogGroupName] = useState("/vpc/flowlogs");
  const [bucketArn, setBucketArn] = useState("");
  const [roleArn, setRoleArn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createFlowLog(resourceId, resourceType, {
        trafficType, logDestinationType: destType, ...(destType === "s3" ? { logDestination: bucketArn } : { logGroupName, deliverLogsPermissionArn: roleArn }), maxAggregationInterval: Number(interval_),
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
          <FormField label="Destination">
            <RadioGroup value={destType} onChange={({ detail }) => setDestType(detail.value)}
              items={[{ value: "cloud-watch-logs", label: "Send to CloudWatch Logs" }, { value: "s3", label: "Send to an Amazon S3 bucket" }]} />
          </FormField>
          {destType === "s3" ? (
            <FormField label="S3 bucket ARN" description="arn:aws:s3:::bucket[/prefix]">
              <Input ariaLabel="S3 bucket ARN" value={bucketArn} onChange={({ detail }) => setBucketArn(detail.value)} placeholder="arn:aws:s3:::my-flow-logs" />
            </FormField>
          ) : (<>
            <FormField label="Destination log group" description="CloudWatch Logs log group name.">
              <Input value={logGroupName} onChange={({ detail }) => setLogGroupName(detail.value)} />
            </FormField>
            <FormField label="IAM role" description="Grants permission to publish to the log group.">
              <Input value={roleArn} onChange={({ detail }) => setRoleArn(detail.value)} placeholder="arn:aws:iam::123456789012:role/flow-logs-role" />
            </FormField>
          </>)}
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

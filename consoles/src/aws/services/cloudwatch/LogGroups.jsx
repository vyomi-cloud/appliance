import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

function DataSourcesTab() {
  const notify = useNotify();
  const t = useAsync(() => api.describeFlowLogDataSources(), []);
  const vpcs = useAsync(() => api.describeVpcsForDataSource(), []);
  const [creating, setCreating] = useState(false);
  const [vpcId, setVpcId] = useState(null);
  const [logGroupName, setLogGroupName] = useState("");

  const create = async () => {
    await api.createFlowLogDataSource(vpcId, logGroupName);
    notify.success(`VPC Flow Logs data source created for ${vpcId}, vended to ${logGroupName}.`);
    setCreating(false); setVpcId(null); setLogGroupName(""); t.reload();
  };
  const remove = async (f) => { await api.deleteFlowLogDataSource(f.FlowLogId); notify.success("Data source removed."); t.reload(); };

  return (
    <CapabilityContainer id="aws.cloudwatch.logs.data-sources" title="Data sources"
      actions={<Button onClick={() => setCreating(true)}>Add data source</Button>}>
      <Table
        variant="embedded"
        items={t.data || []}
        loading={t.loading}
        trackBy="FlowLogId"
        columnDefinitions={[
          { id: "type", header: "Source type", cell: () => "VPC Flow Logs" },
          { id: "resource", header: "Resource", cell: (f) => f.ResourceId },
          { id: "dest", header: "Destination log group", cell: (f) => <Link href={href("cloudwatch", "logs", f.LogGroupName)} onFollow={follow}>{f.LogGroupName}</Link> },
          { id: "status", header: "Status", cell: (f) => f.Status },
          { id: "del", header: "", cell: (f) => <Button variant="icon" iconName="remove" ariaLabel={`Remove ${f.FlowLogId}`} onClick={() => remove(f)} /> },
        ]}
        empty={<Box textAlign="center" color="inherit">No data sources. Add a VPC's Flow Logs to vend them into a CloudWatch Logs log group.</Box>}
      />
      <Modal visible={creating} onDismiss={() => setCreating(false)} header="Add data source"
        footer={<Box float="right"><Button variant="primary" disabled={!vpcId || !logGroupName} onClick={create}>Add data source</Button></Box>}>
        <SpaceBetween size="l">
          <FormField label="Source type"><Select selectedOption={{ label: "VPC Flow Logs", value: "vpc-flow-logs" }} disabled options={[{ label: "VPC Flow Logs", value: "vpc-flow-logs" }]} ariaLabel="Source type" /></FormField>
          <FormField label="VPC" description="Vyomi really creates an EC2 Flow Log for this VPC, through the same ec2 API the EC2 console's Flow Logs tab uses.">
            <Select placeholder="Select a VPC" selectedOption={vpcId ? { label: vpcId, value: vpcId } : null}
              onChange={({ detail }) => setVpcId(detail.selectedOption.value)}
              options={(vpcs.data || []).map((v) => ({ label: `${v.VpcId} (${v.CidrBlock})`, value: v.VpcId }))} ariaLabel="VPC" />
          </FormField>
          <FormField label="Destination log group" description="Created if it doesn't already exist.">
            <Input value={logGroupName} onChange={({ detail }) => setLogGroupName(detail.value)} placeholder="/vpc/flowlogs" ariaLabel="Destination log group" />
          </FormField>
        </SpaceBetween>
      </Modal>
    </CapabilityContainer>
  );
}

export default function LogGroups() {
  const notify = useNotify();
  const t = useAsync(async () => {
    const groups = await api.describeLogGroups({});
    const [subs, rules, detectors] = await Promise.all([
      Promise.all(groups.map((g) => api.describeSubscriptionFilters(g.logGroupName).catch(() => []))),
      api.describeInsightRules({}),
      api.listLogAnomalyDetectors(),
    ]);
    const ruleCount = (name) => rules.filter((r) => { try { return JSON.parse(r.Definition).LogGroupNames?.includes(name); } catch { return false; } }).length;
    return groups.map((g, i) => ({
      ...g, subscriptionFilterCount: subs[i].length, insightRuleCount: ruleCount(g.logGroupName),
      anomalyDetector: detectors.find((d) => d.logGroupArnList.includes(g.logGroupArn)) || null,
    }));
  }, []);
  const [selected, setSelected] = useState([]);
  const [deleting, setDeleting] = useState(false);

  return (
    <ContentLayout header={<Header variant="h1">Log management</Header>}>
      <Tabs tabs={[
        {
          id: "groups", label: "Log groups", content: (
            <SpaceBetween size="l">
              <ResourceTable
                resourceName="Log groups"
                items={t.data || []}
                loading={t.loading}
                error={t.error}
                onRefresh={t.reload}
                trackBy="logGroupName"
                selectionType="multi"
                selectedItems={selected}
                onSelectionChange={setSelected}
                filterPlaceholder="Filter log groups or try prefix search"
                actions={
                  <SpaceBetween direction="horizontal" size="xs">
                    <ButtonDropdown
                      disabled={!selected.length}
                      items={[{ id: "delete", text: "Delete" }]}
                      onItemClick={({ detail }) => detail.id === "delete" && setDeleting(true)}
                    >
                      Actions
                    </ButtonDropdown>
                    <Button disabled={selected.length !== 1} onClick={() => navigate("cloudwatch", "logs-insights")}>View in Logs Insights</Button>
                    <Button disabled={selected.length !== 1} onClick={() => navigate("cloudwatch", "live-tail")}>Start tailing</Button>
                    <Button variant="primary" href={href("cloudwatch", "logs", "create")} onFollow={follow}>Create log group</Button>
                  </SpaceBetween>
                }
                columns={[
                  { id: "name", header: "Log group", isRowHeader: true, sortingField: "logGroupName", cell: (g) => <Link href={href("cloudwatch", "logs", g.logGroupName)} onFollow={follow}>{g.logGroupName}</Link> },
                  { id: "class", header: "Log class", cell: (g) => ({ STANDARD: "Standard", INFREQUENT_ACCESS: "Infrequent Access", DELIVERY: "Delivery" }[g.logGroupClass] || g.logGroupClass) },
                  { id: "anomaly", header: "Anomaly detection", cell: (g) => (g.anomalyDetector ? `Enabled (${g.anomalyDetector.anomalyDetectorStatus})` : "-") },
                  { id: "protect", header: "Data protection", cell: (g) => ({ mask: "Activated (masking)", audit: "Activated (audit only)" }[g.dataProtectionMode] || "Deactivated") },
                  { id: "sensitive", header: "Sensitive data count", cell: (g) => g.dataProtectionFindings || 0 },
                  { id: "retention", header: "Retention", cell: (g) => (g.retentionInDays ? `${g.retentionInDays} days` : "Never expire") },
                  { id: "metricFilters", header: "Metric filters", cell: (g) => g.metricFilterCount ?? 0 },
                  { id: "ci", header: "Contributor Insights", cell: (g) => g.insightRuleCount },
                  { id: "subFilters", header: "Subscription filters", cell: (g) => g.subscriptionFilterCount },
                  { id: "kms", header: "KMS key ID", cell: (g) => g.kmsKeyId || "Not associated" },
                ]}
                empty={{ title: "No log groups", subtitle: "Create a log group to start sending log data.", action: <Button href={href("cloudwatch", "logs", "create")} onFollow={follow}>Create log group</Button> }}
              />
              <DeleteModal
                visible={deleting}
                onDismiss={() => setDeleting(false)}
                resourceType="log group"
                names={selected.map((g) => g.logGroupName)}
                onConfirm={async () => { await Promise.all(selected.map((g) => api.deleteLogGroup(g.logGroupName))); notify.success(`${selected.length > 1 ? "Log groups" : "Log group"} deleted.`); setSelected([]); t.reload(); }}
              />
            </SpaceBetween>
          ),
        },
        { id: "sources", label: "Data sources", content: <DataSourcesTab /> },
      ]} />
    </ContentLayout>
  );
}

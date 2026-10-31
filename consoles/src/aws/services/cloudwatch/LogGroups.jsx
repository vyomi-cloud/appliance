import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

export default function LogGroups() {
  const notify = useNotify();
  const t = useAsync(async () => {
    const groups = await api.describeLogGroups({});
    const [subs, rules] = await Promise.all([
      Promise.all(groups.map((g) => api.describeSubscriptionFilters(g.logGroupName).catch(() => []))),
      api.describeInsightRules({}),
    ]);
    const ruleCount = (name) => rules.filter((r) => { try { return JSON.parse(r.Definition).LogGroupNames?.includes(name); } catch { return false; } }).length;
    return groups.map((g, i) => ({ ...g, subscriptionFilterCount: subs[i].length, insightRuleCount: ruleCount(g.logGroupName) }));
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
                  { id: "anomaly", header: "Anomaly detection", cell: () => "-" },
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
        { id: "sources", label: "Data sources", content: <CapabilityContainer id="aws.cloudwatch.logs.data-sources" title="Data sources" /> },
      ]} />
    </ContentLayout>
  );
}

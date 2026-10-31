import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow } from "../../../common/router.js";
import { ErrorAlert, fmtDate, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { DeleteDatabaseModal, ModifyModal, SnapshotModal } from "./DatabaseActions.jsx";
import { statusOf } from "./Databases.jsx";
import * as api from "./api.js";

function InstanceRecommendations({ arn }) {
  const t = useAsync(async () => (await api.describeDBRecommendations()).filter((r) => r.ResourceArn === arn), [arn]);
  return (
    <Table variant="container" items={t.data || []} loading={t.loading} trackBy="RecommendationId"
      header={<Header variant="h2" counter={`(${(t.data || []).length})`}>Recommendations</Header>}
      columnDefinitions={[
        { id: "severity", header: "Severity", cell: (r) => r.Severity },
        { id: "detection", header: "Detection", cell: (r) => r.Detection },
        { id: "reco", header: "Recommendation", cell: (r) => r.Recommendation },
        { id: "impact", header: "Impact", cell: (r) => r.Impact },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No active recommendations</b></Box>} />
  );
}

function InstanceIntegrations({ arn }) {
  const t = useAsync(async () => (await api.describeIntegrations()).filter((r) => r.SourceArn === arn), [arn]);
  return (
    <Table variant="container" items={t.data || []} loading={t.loading} trackBy="IntegrationName"
      header={<Header variant="h2" counter={`(${(t.data || []).length})`}>Zero-ETL integrations</Header>}
      columnDefinitions={[
        { id: "name", header: "Integration name", cell: (r) => r.IntegrationName },
        { id: "status", header: "Status", cell: (r) => r.Status },
        { id: "target", header: "Destination ARN", cell: (r) => r.TargetArn },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No zero-ETL integrations</b></Box>} />
  );
}

function RecentEvents({ id }) {
  const t = useAsync(() => api.describeEvents(id), [id]);
  return (
    <Table variant="container" items={t.data || []} loading={t.loading} trackBy={(e) => e.Date}
      header={<Header variant="h2" counter={`(${(t.data || []).length})`}>Recent events</Header>}
      columnDefinitions={[
        { id: "time", header: "Time", cell: (e) => fmtDate(e.Date) },
        { id: "notes", header: "System notes", cell: (e) => e.Message },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No events</b></Box>} />
  );
}

function Snapshots({ id, onTakeSnapshot }) {
  const t = useAsync(() => api.describeDBSnapshots(id), [id]);
  return (
    <Table variant="container" items={t.data || []} loading={t.loading} trackBy="DBSnapshotIdentifier"
      header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={<Button onClick={onTakeSnapshot}>Take snapshot</Button>}>Snapshots</Header>}
      columnDefinitions={[
        { id: "name", header: "Snapshot name", cell: (s) => s.DBSnapshotIdentifier },
        { id: "created", header: "Snapshot creation time", cell: (s) => fmtDate(s.SnapshotCreateTime) },
        { id: "status", header: "Status", cell: (s) => s.Status },
        { id: "type", header: "Snapshot type", cell: (s) => s.SnapshotType },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No manual snapshots</b></Box>} />
  );
}

function TagsTab({ d, reload }) {
  const notify = useNotify();
  const t = useAsync(() => api.listTagsForResource(d.DBInstanceArn), [d.DBInstanceArn]);
  const [editing, setEditing] = useState(false);
  const [tags, setTags] = useState([]);
  return (
    <>
      <Table variant="container" items={t.data || []} loading={t.loading}
        header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={
          <Button onClick={() => { setTags((t.data || []).map((x) => ({ key: x.Key, value: x.Value }))); setEditing(true); }}>Manage tags</Button>
        }>Tags</Header>}
        columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.Key }, { id: "v", header: "Value", cell: (x) => x.Value || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      <Modal visible={editing} size="large" onDismiss={() => setEditing(false)} header="Manage tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            const before = new Set((t.data || []).map((x) => x.Key));
            const after = new Set(tags.filter((x) => x.key).map((x) => x.key));
            const removed = [...before].filter((k) => !after.has(k));
            if (removed.length) await api.removeTagsFromResource(d.DBInstanceArn, removed);
            const kept = tags.filter((x) => x.key);
            if (kept.length) await api.addTagsToResource(d.DBInstanceArn, kept.map((x) => ({ Key: x.key, Value: x.value || "" })));
            notify.success("Tags saved.");
            setEditing(false); t.reload(); reload();
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} />
      </Modal>
    </>
  );
}

export default function DatabaseDetail({ params, query }) {
  const id = params.id;
  const notify = useNotify();
  const [tab, setTab] = useState(query.tab || "connectivity");
  const [modify, setModify] = useState(false);
  const [snapModal, setSnapModal] = useState(false);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeDBInstance(id), [id]);
  const certs = useAsync(() => api.describeCertificates());

  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const d = t.data;
  if (!d) return <Box textAlign="center" padding="xxl"><b>Database not found</b></Box>;
  const cert = (certs.data || []).find((c) => c.CertificateIdentifier === d.CACertificateIdentifier);

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
          <Button onClick={() => setModify(true)}>Modify</Button>
          <ButtonDropdown items={[
            { id: "reboot", text: "Reboot" },
            { id: "snapshot", text: "Take snapshot" },
            { id: "stop", text: "Stop temporarily", disabled: d.DBInstanceStatus !== "available" },
            { id: "start", text: "Start", disabled: d.DBInstanceStatus !== "stopped" },
            { id: "delete", text: "Delete" },
          ]} onItemClick={async ({ detail }) => {
            try {
              if (detail.id === "reboot") { await api.rebootDBInstance(id); notify.success("Rebooting."); t.reload(); }
              else if (detail.id === "stop") { await api.stopDBInstance(id); notify.success("Stopping."); t.reload(); }
              else if (detail.id === "start") { await api.startDBInstance(id); notify.success("Starting."); t.reload(); }
              else if (detail.id === "snapshot") setSnapModal(true);
              else if (detail.id === "delete") setDel(true);
            } catch (e) { notify.error(e); }
          }}>Actions</ButtonDropdown>
        </SpaceBetween>
      }>{id}</Header>
    }>
      <SpaceBetween size="l">
        <KeyValue title="Summary" columns={4} items={[
          ["DB identifier", d.DBInstanceIdentifier], ["Status", statusOf(d.DBInstanceStatus)],
          ["Role", "Instance"], ["Engine", `${d.Engine} ${d.EngineVersion}`],
          ["Recommendations", "-"], ["CPU", "-"], ["Class", d.DBInstanceClass], ["Current activity", "-"],
          ["Region & AZ", d.AvailabilityZone],
        ]} />

        <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
          {
            id: "connectivity", label: "Connectivity & security", content: (
              <SpaceBetween size="l">
                <KeyValue title="Endpoint & port" columns={2} items={[["Endpoint", d.Endpoint?.Address], ["Port", d.Endpoint?.Port]]} />
                <KeyValue title="Networking" columns={3} items={[
                  ["Availability Zone", d.AvailabilityZone], ["VPC", d.DBSubnetGroup?.VpcId || "vpc-default"],
                  ["Subnet group", d.DBSubnetGroup?.DBSubnetGroupName], ["Subnets", "-"], ["Network type", "IPv4"],
                ]} />
                <KeyValue title="Security" columns={3} items={[
                  ["VPC security groups", [].concat(d.VpcSecurityGroups?.VpcSecurityGroupMembership || []).map((g) => g.VpcSecurityGroupId).join(", ") || "sg-default"],
                  ["Publicly accessible", d.PubliclyAccessible === "true" ? "Yes" : "No"],
                  ["Certificate authority", d.CACertificateIdentifier], ["Certificate authority date", cert?.ValidFrom || "-"],
                  ["DB instance certificate expiration date", cert?.ValidTill || "-"],
                ]} />
                <CapabilityContainer id="rds.replication" title="Connected compute resources" />
                <CapabilityContainer id="rds.replication" title="Security group rules" />
                <CapabilityContainer id="rds.replication" title="Replication" />
              </SpaceBetween>
            ),
          },
          {
            id: "monitoring", label: "Monitoring", content: (
              <CapabilityContainer id="rds.monitoring" title="CloudWatch" />
            ),
          },
          {
            id: "logs", label: "Logs & events", content: (
              <SpaceBetween size="l">
                <NotSimulatedContainer title="CloudWatch alarms" feature="RDS CloudWatch alarms" />
                <RecentEvents id={id} />
                <CapabilityContainer id="rds.logs" title="Logs" />
              </SpaceBetween>
            ),
          },
          {
            id: "configuration", label: "Configuration", content: (
              <SpaceBetween size="l">
                <KeyValue title="Configuration" columns={3} items={[
                  ["DB instance ID", d.DBInstanceIdentifier], ["Engine version", d.EngineVersion],
                  ["RDS Extended Support", "-"], ["DB name", "-"], ["License model", "general-public-license"],
                  ["Option groups", "default"], ["Amazon Resource Name (ARN)", d.DBInstanceArn],
                  ["Resource ID", "-"], ["Created time", fmtDate(d.InstanceCreateTime)],
                  ["DB instance parameter group", d.DBParameterGroups?.DBParameterGroupStatus?.DBParameterGroupName || "default"],
                  ["Deletion protection", d.DeletionProtection === "true" ? "Enabled" : "Disabled"],
                ]} />
                <KeyValue title="Instance class" columns={3} items={[["Instance class", d.DBInstanceClass], ["vCPU", "-"], ["RAM", "-"]]} />
                <KeyValue title="Availability" columns={3} items={[
                  ["Master username", d.MasterUsername], ["Master password", "••••••••"],
                  ["IAM DB authentication", "Disabled"], ["Multi-AZ", d.MultiAZ === "true" ? "Yes" : "No"], ["Secondary Zone", "-"],
                ]} />
                <KeyValue title="Storage" columns={3} items={[
                  ["Encryption", "Not enabled"], ["Storage type", d.StorageType], ["Storage", `${d.AllocatedStorage} GiB`],
                  ["Provisioned IOPS", "-"], ["Storage throughput", "-"], ["Storage autoscaling", "Disabled"], ["Maximum storage threshold", "-"],
                ]} />
                <KeyValue title="Performance Insights" columns={1} items={[["Performance Insights enabled", "Not enabled"]]} />
              </SpaceBetween>
            ),
          },
          { id: "zero-etl", label: "Zero-ETL integrations", content: <InstanceIntegrations arn={d.DBInstanceArn} /> },
          {
            id: "maintenance", label: "Maintenance & backups", content: (
              <SpaceBetween size="l">
                <KeyValue title="Maintenance" columns={2} items={[
                  ["Auto minor version upgrade", "Enabled"], ["Maintenance window", "sun:05:00-sun:05:30"],
                  ["Pending maintenance", "None"], ["Pending modifications", "None"],
                ]} />
                <Table variant="container" items={[]}
                  header={<Header variant="h2" counter="(0)" actions={<SpaceBetween direction="horizontal" size="xs">
                    <Button disabled>Apply now</Button><Button disabled>Apply at next maintenance window</Button>
                  </SpaceBetween>}>Pending maintenance</Header>}
                  columnDefinitions={[{ id: "d", header: "Description", cell: () => "-" }, { id: "s", header: "Status", cell: () => "-" }, { id: "a", header: "Apply date", cell: () => "-" }]}
                  empty={<Box textAlign="center" color="inherit"><b>No pending maintenance actions</b></Box>} />
                <KeyValue title="Backup" columns={3} items={[
                  ["Automated backups", Number(d.BackupRetentionPeriod) > 0 ? "Enabled" : "Disabled"],
                  ["Copy tags to snapshots", "-"], ["Backup window", "-"],
                  ["Backup retention period", `${d.BackupRetentionPeriod} days`],
                  ["Earliest restorable time", fmtDate(d.InstanceCreateTime)], ["Latest restorable time", fmtDate(d.LatestRestorableTime)],
                  ["Replicated automated backups", "-"],
                ]} />
                <Snapshots id={id} onTakeSnapshot={() => setSnapModal(true)} />
              </SpaceBetween>
            ),
          },
          { id: "migrations", label: "Data migrations", content: <NotSimulatedContainer title="Data migrations" feature="AWS DMS data migrations" /> },
          { id: "tags", label: "Tags", content: <TagsTab d={d} reload={t.reload} /> },
          { id: "recommendations", label: "Recommendations", content: <InstanceRecommendations arn={d.DBInstanceArn} /> },
        ]} />
      </SpaceBetween>

      <ModifyModal db={d} visible={modify} onDismiss={() => setModify(false)} onDone={t.reload} notify={notify} />
      <SnapshotModal dbId={id} visible={snapModal} onDismiss={() => setSnapModal(false)} notify={notify} />
      <DeleteDatabaseModal dbIds={[id]} visible={del} onDismiss={() => setDel(false)}
        onDone={() => { setDel(false); location.hash = href("rds", "databases").slice(1); }} notify={notify} />
    </ContentLayout>
  );
}

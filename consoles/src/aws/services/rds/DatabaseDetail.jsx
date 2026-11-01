import { useEffect, useState } from "react";
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
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Select from "@cloudscape-design/components/select";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow } from "../../../common/router.js";
import { ErrorAlert, fmtDate, KeyValue, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { DeleteDatabaseModal, ModifyModal, SnapshotModal } from "./DatabaseActions.jsx";
import { statusOf } from "./Databases.jsx";
import * as api from "./api.js";

const RANGE_OPTIONS = [
  { label: "Last hour", value: "60" }, { label: "Last 3 hours", value: "180" },
  { label: "Last 6 hours", value: "360" }, { label: "Last 12 hours", value: "720" }, { label: "Last day", value: "1440" },
];

const MONITORING_FIELDS = [
  { key: "CPUUtilization" }, { key: "DatabaseConnections", stat: "Maximum" }, { key: "FreeStorageSpace" },
  { key: "FreeableMemory" }, { key: "ReadIOPS", stat: "Sum" }, { key: "WriteIOPS", stat: "Sum" },
];

function MonitoringTab({ d }) {
  const [minutes, setMinutes] = useState(60);
  const real = MONITORING_FIELDS.filter((f) => f.stat);
  const t = useAsync(() => Promise.all(real.map((f) => api.getDBInstanceMetric(d.DBInstanceIdentifier, f.key, minutes))),
    [d.DBInstanceIdentifier, minutes]);
  const valueFor = (f) => {
    if (!f.stat) return "-";
    const pts = t.data?.[real.indexOf(f)] || [];
    return pts.length ? String(pts[pts.length - 1][f.stat]) : "0";
  };
  return (
    <CapabilityContainer id="rds.monitoring" title="CloudWatch" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Select selectedOption={RANGE_OPTIONS.find((o) => o.value === String(minutes))} ariaLabel="Time range"
          onChange={({ detail }) => setMinutes(Number(detail.selectedOption.value))} options={RANGE_OPTIONS} />
        <Button iconName="external" href="#/cloudwatch/metrics" target="_blank">Monitoring</Button>
      </SpaceBetween>
    }>
      <SpaceBetween size="l">
        <ColumnLayout columns={3} variant="text-grid">
          {MONITORING_FIELDS.map((f) => (
            <div key={f.key}>
              <Box variant="awsui-key-label">{f.key}</Box>
              <div>{t.loading && f.stat ? <Spinner size="normal" /> : valueFor(f)}</div>
            </div>
          ))}
        </ColumnLayout>
        <NotSimulated feature="CPUUtilization, FreeStorageSpace, FreeableMemory"
          note="Vyomi has no virtualized compute, disk or memory allocation behind a DB instance to measure, so these are shown as unavailable rather than invented. DatabaseConnections, ReadIOPS and WriteIOPS above are real — pushed to CloudWatch as the activity actually happens." />
      </SpaceBetween>
    </CapabilityContainer>
  );
}

function LogsTab({ id }) {
  const t = useAsync(() => api.describeDBLogFiles(id), [id]);
  const [sel, setSel] = useState([]);
  const [viewing, setViewing] = useState(null);

  useEffect(() => {
    if (!viewing?.watch) return;
    const timer = setInterval(async () => {
      const r = await api.downloadDBLogFilePortion(id, viewing.name);
      setViewing((v) => (v ? { ...v, content: r.data } : v));
    }, 3000);
    return () => clearInterval(timer);
  }, [viewing?.watch, viewing?.name, id]);

  const open = async (name, watch) => {
    const r = await api.downloadDBLogFilePortion(id, name);
    setViewing({ name, content: r.data, watch });
  };
  const download = async (name) => {
    const r = await api.downloadDBLogFilePortion(id, name);
    const url = URL.createObjectURL(new Blob([r.data], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url; a.download = name.replace(/\//g, "-"); a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <CapabilityContainer id="rds.logs" title="Logs">
      <Table variant="embedded" items={t.data || []} loading={t.loading} trackBy="LogFileName"
        selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h3" counter={`(${(t.data || []).length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => open(sel[0].LogFileName, false)}>View</Button>
            <Button disabled={!sel.length} onClick={() => open(sel[0].LogFileName, true)}>Watch</Button>
            <Button disabled={!sel.length} onClick={() => download(sel[0].LogFileName)}>Download</Button>
          </SpaceBetween>
        }>Logs</Header>}
        columnDefinitions={[
          { id: "name", header: "Name", cell: (f) => f.LogFileName },
          { id: "last", header: "Last written", cell: (f) => (Number(f.LastWritten) ? fmtDate(new Date(Number(f.LastWritten)).toISOString()) : "-") },
          { id: "size", header: "Size", cell: (f) => `${f.Size} B` },
        ]}
        empty={<Box textAlign="center" color="inherit">No log files</Box>} />
      <Modal visible={!!viewing} onDismiss={() => setViewing(null)} size="large" header={viewing?.name}>
        <Box as="pre" fontSize="body-s" padding="n" data-vyomi-log-content="">
          {viewing?.content || "(empty — no statements have failed on this instance)"}
        </Box>
      </Modal>
    </CapabilityContainer>
  );
}

function ruleText(p) {
  const proto = p.IpProtocol === "-1" ? "All traffic" : `${(p.IpProtocol || "").toUpperCase()} ${p.FromPort === p.ToPort ? p.FromPort : `${p.FromPort}-${p.ToPort}`}`;
  const src = p.cidrs?.[0] || p.groupIds?.[0] || "0.0.0.0/0";
  return `${proto} from ${src}`;
}

function SecurityGroupRules({ sgIds }) {
  const t = useAsync(() => api.describeSecurityGroupsById(sgIds), [sgIds.join(",")]);
  const rows = (t.data || []).flatMap((sg) => [
    ...sg.Ingress.map((p) => ({ sg, type: "Inbound", p })),
    ...sg.Egress.map((p) => ({ sg, type: "Outbound", p })),
  ]);
  return (
    <CapabilityContainer id="rds.replication" title="Security group rules">
      <Table variant="embedded" items={rows} loading={t.loading}
        header={<Header variant="h3" counter={`(${rows.length})`}>Security group rules</Header>}
        columnDefinitions={[
          { id: "sg", header: "Security group", cell: (r) => r.sg.GroupId },
          { id: "type", header: "Type", cell: (r) => r.type },
          { id: "rule", header: "Rule", cell: (r) => ruleText(r.p) },
        ]}
        empty={<Box textAlign="center" color="inherit">No security group rules</Box>} />
    </CapabilityContainer>
  );
}

function SetUpEc2ConnectionModal({ dbSgIds, port, visible, onDismiss, notify, onDone }) {
  const t = useAsync(() => (visible ? api.describeAllEc2Instances() : Promise.resolve([])), [visible]);
  const [chosen, setChosen] = useState("");
  const [busy, setBusy] = useState(false);
  const instances = t.data || [];
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Set up EC2 connection"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!chosen} loading={busy} onClick={async () => {
          setBusy(true);
          try {
            const inst = instances.find((i) => i.InstanceId === chosen);
            const ec2Sg = inst?.GroupIds?.[0];
            await Promise.all(dbSgIds.map((dbSg) => api.setUpEc2Connection(dbSg, ec2Sg, port || 5432)));
            notify.success(`Connected EC2 instance "${chosen}" to this database.`);
            onDone(); onDismiss();
          } catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Continue</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        <Box variant="p">Vyomi really authorizes the EC2 instance's security group to reach this database's port
          (AuthorizeSecurityGroupIngress), the same change the real console's wizard makes.</Box>
        <FormField label="EC2 instance">
          <Select selectedOption={chosen ? { label: chosen, value: chosen } : null} ariaLabel="EC2 instance"
            placeholder="Choose an EC2 instance" loadingText="Loading instances"
            statusType={t.loading ? "loading" : "finished"}
            onChange={({ detail }) => setChosen(detail.selectedOption.value)}
            options={instances.map((i) => ({ label: `${i.InstanceId} (${i.InstanceType})`, value: i.InstanceId }))} />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function ConnectedComputeResources({ d, notify }) {
  const sgIds = [].concat(d.VpcSecurityGroups?.VpcSecurityGroupMembership || []).map((g) => g.VpcSecurityGroupId);
  const t = useAsync(() => api.describeConnectedComputeResources(sgIds), [sgIds.join(",")]);
  const [setup, setSetup] = useState(false);
  return (
    <CapabilityContainer id="rds.replication" title="Connected compute resources"
      actions={<Button onClick={() => setSetup(true)}>Set up EC2 connection</Button>}>
      <Table variant="embedded" items={t.data || []} loading={t.loading} trackBy="InstanceId"
        columnDefinitions={[
          { id: "id", header: "Resource identifier", cell: (r) => r.InstanceId },
          { id: "type", header: "Resource type", cell: () => "EC2 instance" },
          { id: "csg", header: "Compute resource security group", cell: (r) => r.ComputeSecurityGroupId },
          { id: "dsg", header: "DB security group", cell: (r) => r.ComputeSecurityGroupId },
        ]}
        empty={<Box textAlign="center" color="inherit">No connected compute resources</Box>} />
      <SetUpEc2ConnectionModal dbSgIds={sgIds} port={d.Endpoint?.Port} visible={setup}
        onDismiss={() => setSetup(false)} onDone={t.reload} notify={notify} />
    </CapabilityContainer>
  );
}

function ReplicationTable({ d }) {
  const sourceId = d.ReadReplicaSourceDBInstanceIdentifier;
  const replicaIds = [].concat(d.ReadReplicaDBInstanceIdentifiers?.ReadReplicaDBInstanceIdentifier || []);
  const ids = [...(sourceId ? [sourceId] : []), ...replicaIds];
  const t = useAsync(() => Promise.all(ids.map((id) => api.describeDBInstance(id))), [ids.join(",")]);
  const rows = (t.data || []).filter(Boolean);
  return (
    <CapabilityContainer id="rds.replication" title="Replication">
      <Table variant="embedded" items={rows} loading={t.loading} trackBy="DBInstanceIdentifier"
        columnDefinitions={[
          { id: "id", header: "DB identifier", cell: (r) => r.DBInstanceIdentifier },
          { id: "role", header: "Role", cell: (r) => (r.DBInstanceIdentifier === sourceId ? "Primary" : "Read replica") },
          { id: "az", header: "Region & AZ", cell: (r) => r.AvailabilityZone },
          { id: "src", header: "Replication source", cell: (r) => r.ReadReplicaSourceDBInstanceIdentifier || "-" },
          { id: "state", header: "Replication state", cell: () => "replicating" },
          { id: "lag", header: "Lag", cell: () => "0" },
        ]}
        empty={<Box textAlign="center" color="inherit">No read replicas</Box>} />
    </CapabilityContainer>
  );
}

function CreateReadReplicaModal({ db, visible, onDismiss, notify, onDone }) {
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  if (!db) return null;
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={`Create read replica of ${db.DBInstanceIdentifier}`}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!id} loading={busy} onClick={async () => {
          setBusy(true);
          try {
            await api.createDBInstanceReadReplica(id, db.DBInstanceIdentifier);
            notify.success(`Creating read replica "${id}".`);
            onDone(); onDismiss(); setId("");
          } catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Create read replica</Button>
      </SpaceBetween></Box>}>
      <FormField label="Read replica identifier">
        <Input value={id} onChange={({ detail }) => setId(detail.value)} ariaLabel="Read replica identifier" />
      </FormField>
    </Modal>
  );
}

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
  const [replicaModal, setReplicaModal] = useState(false);
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
            { id: "failover", text: "Failover", disabled: d.MultiAZ !== "true" },
            { id: "snapshot", text: "Take snapshot" },
            { id: "stop", text: "Stop temporarily", disabled: d.DBInstanceStatus !== "available" },
            { id: "start", text: "Start", disabled: d.DBInstanceStatus !== "stopped" },
            { id: "create-replica", text: "Create read replica", disabled: !!d.ReadReplicaSourceDBInstanceIdentifier },
            { id: "promote", text: "Promote", disabled: !d.ReadReplicaSourceDBInstanceIdentifier },
            { id: "delete", text: "Delete" },
          ]} onItemClick={async ({ detail }) => {
            try {
              if (detail.id === "reboot") { await api.rebootDBInstance(id); notify.success("Rebooting."); t.reload(); }
              else if (detail.id === "failover") { await api.failoverDBInstance(id); notify.success("Failing over to the secondary Availability Zone."); t.reload(); }
              else if (detail.id === "stop") { await api.stopDBInstance(id); notify.success("Stopping."); t.reload(); }
              else if (detail.id === "start") { await api.startDBInstance(id); notify.success("Starting."); t.reload(); }
              else if (detail.id === "snapshot") setSnapModal(true);
              else if (detail.id === "create-replica") setReplicaModal(true);
              else if (detail.id === "promote") { await api.promoteReadReplica(id); notify.success("Promoting read replica."); t.reload(); }
              else if (detail.id === "delete") setDel(true);
            } catch (e) { notify.error(e); }
          }}>Actions</ButtonDropdown>
        </SpaceBetween>
      }>{id}</Header>
    }>
      <SpaceBetween size="l">
        <KeyValue title="Summary" columns={4} items={[
          ["DB identifier", d.DBInstanceIdentifier], ["Status", statusOf(d.DBInstanceStatus)],
          ["Role", d.ReadReplicaSourceDBInstanceIdentifier ? "Replica" : "Instance"], ["Engine", `${d.Engine} ${d.EngineVersion}`],
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
                <ConnectedComputeResources d={d} notify={notify} />
                <SecurityGroupRules sgIds={[].concat(d.VpcSecurityGroups?.VpcSecurityGroupMembership || []).map((g) => g.VpcSecurityGroupId)} />
                <ReplicationTable d={d} />
              </SpaceBetween>
            ),
          },
          {
            id: "monitoring", label: "Monitoring", content: <MonitoringTab d={d} />,
          },
          {
            id: "logs", label: "Logs & events", content: (
              <SpaceBetween size="l">
                <NotSimulatedContainer title="CloudWatch alarms" feature="RDS CloudWatch alarms" />
                <RecentEvents id={id} />
                <LogsTab id={id} />
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
                  ["IAM DB authentication", "Disabled"], ["Multi-AZ", d.MultiAZ === "true" ? "Yes" : "No"], ["Secondary Zone", d.SecondaryAvailabilityZone || "-"],
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
      <CreateReadReplicaModal db={d} visible={replicaModal} onDismiss={() => setReplicaModal(false)} onDone={t.reload} notify={notify} />
      <DeleteDatabaseModal dbIds={[id]} visible={del} onDismiss={() => setDel(false)}
        onDone={() => { setDel(false); location.hash = href("rds", "databases").slice(1); }} notify={notify} />
    </ContentLayout>
  );
}

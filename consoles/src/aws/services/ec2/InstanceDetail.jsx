import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { navigate } from "../../../common/router.js";
import { StateBadge, nameOf } from "./Instances.jsx";
import * as api from "./api.js";

export default function InstanceDetail({ params }) {
  const id = params.id;
  const t = useAsync(() => api.describeInstance(id), [id]);
  const [connect, setConnect] = useState(false);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error || !t.data) return <ErrorAlert error={t.error || { message: "Instance not found" }} />;
  const i = t.data;

  const act = async (fn, verb) => {
    try { await fn([id]); t.reload(); } catch (e) { alert(`${verb} failed: ${e.message}`); }
  };

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
          <Button onClick={() => setConnect(true)}>Connect</Button>
          <ButtonDropdown items={[{ id: "start", text: "Start instance" }, { id: "stop", text: "Stop instance" }, { id: "reboot", text: "Reboot instance" }, { id: "terminate", text: "Terminate instance" }]}
            onItemClick={({ detail }) => {
              if (detail.id === "start") act(api.startInstances, "Start");
              else if (detail.id === "stop") act(api.stopInstances, "Stop");
              else if (detail.id === "reboot") act(api.rebootInstances, "Reboot");
              else if (detail.id === "terminate" && confirm("Terminate this instance?")) act(api.terminateInstances, "Terminate").then(() => navigate("ec2", "instances"));
            }}>Instance state</ButtonDropdown>
          <ButtonDropdown items={[{ id: "image", text: "Create image" }]} onItemClick={() => navigate("ec2", "instances", id, "create-image")}>Actions</ButtonDropdown>
        </SpaceBetween>
      }>{`Instance summary for ${nameOf(i) !== "-" ? nameOf(i) : id}`}</Header>
    }>
      <SpaceBetween size="l">
        <KeyValue title="Instance summary" columns={4} items={[
          ["Instance ID", i.instanceId], ["Public IPv4 address", i.ipAddress || "-"], ["Private IPv4 addresses", i.privateIpAddress],
          ["IPv6 address", "-"], ["Instance state", <StateBadge key="s" s={i.instanceState?.name} />], ["Public DNS", i.dnsName || "-"],
          ["Hostname type", i.hostnameType || "ip-name"], ["Private IP DNS name (IPv4 only)", i.privateDnsName],
          ["Instance type", i.instanceType], ["Elastic IP addresses", "-"], ["Auto-assigned IP address", i.ipAddress || "-"],
          ["VPC ID", i.vpcId], ["IAM Role", i.iamInstanceProfile?.arn || "-"], ["Subnet ID", i.subnetId],
          ["Instance ARN", `arn:aws:ec2:us-east-1:123456789012:instance/${i.instanceId}`], ["Managed", "No"],
        ]} />
        <Tabs tabs={[
          { id: "details", label: "Details", content: <DetailsTab i={i} /> },
          { id: "status", label: "Status and alarms", content: <StatusTab i={i} /> },
          { id: "monitoring", label: "Monitoring", content: <MonitoringTab /> },
          { id: "security", label: "Security", content: <SecurityTab i={i} /> },
          { id: "networking", label: "Networking", content: <NetworkingTab i={i} /> },
          { id: "storage", label: "Storage", content: <StorageTab i={i} /> },
          { id: "tags", label: "Tags", content: <TagsTab i={i} reload={t.reload} /> },
        ]} />
      </SpaceBetween>
      <Modal visible={connect} onDismiss={() => setConnect(false)} header="Connect to instance" footer={<Box float="right"><Button onClick={() => setConnect(false)}>Close</Button></Box>}>
        <CapabilityContainer id="ec2.instances.connect" title="Connect" />
      </Modal>
    </ContentLayout>
  );
}

function DetailsTab({ i }) {
  return (
    <SpaceBetween size="l">
      <KeyValue title="Instance details" columns={3} items={[
        ["Platform", i.platform || "-"], ["AMI ID", i.imageId], ["Monitoring", i.monitoring?.state === "enabled" ? "Enabled" : "Disabled"],
        ["Platform details", i.platformDetails], ["AMI name", "-"], ["Termination protection", i.disableApiTermination === "true" ? "Enabled" : "Disabled"],
        ["Stop protection", i.disableApiStop === "true" ? "Enabled" : "Disabled"], ["Launch time", i.launchTime], ["AMI location", "-"],
        ["Lifecycle", "normal"], ["Stop-hibernate behavior", i.hibernationOptions?.configured === "true" ? "Enabled" : "Disabled"],
        ["AMI Launch index", "0"], ["Key pair assigned at launch", i.keyName || "-"], ["State transition reason", "-"],
        ["Credit specification", i.creditSpecification?.cpuCredits || "standard"], ["Kernel ID", "-"],
        ["Usage operation", i.usageOperation || "RunInstances"], ["RAM disk ID", "-"], ["Enclaves Support", "Disabled"],
        ["Boot mode", "-"], ["Allowed image", "-"],
      ]} />
      <KeyValue title="Host and placement group" columns={3} items={[
        ["Host ID", "-"], ["Affinity", "-"], ["Placement group", i.placement?.groupName || "-"], ["Host resource group name", "-"],
        ["Tenancy", i.placement?.tenancy || "default"], ["Partition number", "-"], ["Virtualization type", i.virtualizationType],
        ["Number of vCPUs", "-"],
      ]} />
      <KeyValue title="Capacity reservation" columns={2} items={[["Capacity Reservation ID", "-"], ["Capacity Reservation setting", "open"]]} />
      <KeyValue title="Instance auto-recovery" columns={1} items={[["Auto-recovery behavior", i.autoRecovery || "default"]]} />
    </SpaceBetween>
  );
}

function StatusTab({ i }) {
  const ok = i.instanceState?.name === "running";
  return (
    <SpaceBetween size="l">
      <KeyValue title="Status checks" columns={3} items={[
        ["System status checks", ok ? "2/2 checks passed" : "-"], ["Instance status checks", ok ? "2/2 checks passed" : "-"],
        ["Attached EBS status checks", ok ? "ok" : "-"],
      ]} />
      <CapabilityContainer id="ec2.instances.status-alarms" title="Alarms" />
    </SpaceBetween>
  );
}

function MonitoringTab() {
  return <CapabilityContainer id="ec2.instances.status-alarms" title="Monitoring" />;
}

function SecurityTab({ i }) {
  const sgs = useAsync(() => Promise.all((i.GroupSet || []).map((g) => api.describeSecurityGroup(g.groupId))), [i.instanceId]);
  const all = (sgs.data || []).filter(Boolean);
  return (
    <SpaceBetween size="l">
      <KeyValue title="Security details" columns={2} items={[
        ["IAM Role", i.iamInstanceProfile?.arn || "-"], ["Owner ID", "123456789012"], ["Launch time", i.launchTime],
        ["Security groups", (i.GroupSet || []).map((g) => `${g.groupName} (${g.groupId})`).join(", ") || "-"],
      ]} />
      <Table variant="container" items={all.flatMap((sg) => sg.IpPermissions.map((p) => ({ ...p, sg })))}
        header={<Header variant="h2" counter={`(${all.flatMap((sg) => sg.IpPermissions).length})`}>Inbound rules</Header>}
        columnDefinitions={[
          { id: "n", header: "Name", cell: () => "-" }, { id: "id", header: "Security group rule ID", cell: (p) => p.RuleId },
          { id: "p", header: "Port range", cell: (p) => (p.FromPort !== undefined ? `${p.FromPort} - ${p.ToPort}` : "All") },
          { id: "proto", header: "Protocol", cell: (p) => (p.IpProtocol === "-1" ? "All" : p.IpProtocol) },
          { id: "src", header: "Source", cell: (p) => p.cidrs?.[0] || p.groupIds?.[0] || "-" },
          { id: "sg", header: "Security groups", cell: (p) => p.sg.GroupId }, { id: "desc", header: "Description", cell: (p) => p.Description || "-" },
        ]}
        empty={<Box textAlign="center" color="inherit">No inbound rules</Box>} />
      <Table variant="container" items={all.flatMap((sg) => sg.IpPermissionsEgress.map((p) => ({ ...p, sg })))}
        header={<Header variant="h2" counter={`(${all.flatMap((sg) => sg.IpPermissionsEgress).length})`}>Outbound rules</Header>}
        columnDefinitions={[
          { id: "n", header: "Name", cell: () => "-" }, { id: "id", header: "Security group rule ID", cell: (p) => p.RuleId },
          { id: "p", header: "Port range", cell: (p) => (p.FromPort !== undefined ? `${p.FromPort} - ${p.ToPort}` : "All") },
          { id: "proto", header: "Protocol", cell: (p) => (p.IpProtocol === "-1" ? "All" : p.IpProtocol) },
          { id: "dst", header: "Destination", cell: (p) => p.cidrs?.[0] || p.groupIds?.[0] || "-" },
          { id: "sg", header: "Security groups", cell: (p) => p.sg.GroupId }, { id: "desc", header: "Description", cell: (p) => p.Description || "-" },
        ]}
        empty={<Box textAlign="center" color="inherit">No outbound rules</Box>} />
    </SpaceBetween>
  );
}

function NetworkingTab({ i }) {
  const enis = useAsync(() => api.describeNetworkInterfaces(), []).data || [];
  const eips = useAsync(() => api.describeAddresses(), []).data || [];
  const myEnis = enis.filter((e) => e.attachment?.instanceId === i.instanceId);
  const myEips = eips.filter((a) => a.instanceId === i.instanceId);
  return (
    <SpaceBetween size="l">
      <KeyValue title="Networking details" columns={3} items={[
        ["Public IPv4 address", i.ipAddress || "-"], ["Private IPv4 addresses", i.privateIpAddress], ["VPC ID", i.vpcId],
        ["Public DNS", i.dnsName || "-"], ["Subnet ID", i.subnetId], ["IPv6 addresses", "-"],
        ["Availability Zone", i.placement?.availabilityZone], ["Private IP DNS name (IPv4 only)", i.privateDnsName],
        ["Secondary private IPv4 addresses", "-"], ["Carrier IP addresses (ephemeral)", "-"],
      ]} />
      <Table variant="container" items={myEnis} header={<Header variant="h2" counter={`(${myEnis.length})`}>Network interfaces</Header>}
        columnDefinitions={[{ id: "id", header: "Interface ID", cell: (e) => e.networkInterfaceId }, { id: "desc", header: "Description", cell: (e) => e.description || "-" },
          { id: "pub", header: "Public IPv4 address", cell: (e) => e.association?.publicIp || "-" }, { id: "priv", header: "Private IPv4 address", cell: (e) => e.privateIpAddress },
          { id: "status", header: "Attachment status", cell: (e) => e.status }]}
        empty={<Box textAlign="center" color="inherit">No extra network interfaces</Box>} />
      <Table variant="container" items={myEips} header={<Header variant="h2" counter={`(${myEips.length})`}>Elastic IP addresses</Header>}
        columnDefinitions={[{ id: "ip", header: "Allocated IPv4 address", cell: (a) => a.publicIp }, { id: "type", header: "Type", cell: (a) => a.domain },
          { id: "id", header: "Allocation ID", cell: (a) => a.allocationId }]}
        empty={<Box textAlign="center" color="inherit">No Elastic IP addresses</Box>} />
    </SpaceBetween>
  );
}

function StorageTab({ i }) {
  const vols = useAsync(() => Promise.all((i.BlockDeviceMapping || []).map((bd) => api.describeVolume(bd.ebs?.volumeId))), [i.instanceId]).data || [];
  return (
    <SpaceBetween size="l">
      <KeyValue title="Root device details" columns={3} items={[["Root device name", "/dev/xvda"], ["Root device type", i.rootDeviceType], ["EBS optimization", i.ebsOptimized === "true" ? "Enabled" : "Disabled"]]} />
      <Table variant="container" items={vols.filter(Boolean)} header={<Header variant="h2" counter={`(${vols.filter(Boolean).length})`}>Block devices</Header>}
        columnDefinitions={[
          { id: "id", header: "Volume ID", cell: (v) => v.volumeId }, { id: "dev", header: "Device name", cell: () => "/dev/xvda" },
          { id: "size", header: "Volume size (GiB)", cell: (v) => v.size }, { id: "status", header: "Attachment status", cell: () => "attached" },
          { id: "time", header: "Attachment time", cell: (v) => v.createTime }, { id: "enc", header: "Encrypted", cell: (v) => v.encrypted },
          { id: "kms", header: "KMS key ID", cell: (v) => v.kmsKeyId || "-" }, { id: "dot", header: "Delete on termination", cell: () => "true" },
        ]}
        empty={<Box textAlign="center" color="inherit">No block devices</Box>} />
    </SpaceBetween>
  );
}

function TagsTab({ i, reload }) {
  const notify = useNotify();
  const tags = Object.entries(i.Tags || {}).map(([Key, Value]) => ({ key: Key, value: Value, existing: true }));
  const save = async (editedTags) => {
    const kept = editedTags.filter((t) => !t.markedForRemoval && t.key);
    const removed = editedTags.filter((t) => t.markedForRemoval && t.existing).map((t) => t.key);
    if (kept.length) await api.createTags([i.instanceId], Object.fromEntries(kept.map((t) => [t.key, t.value || ""])));
    if (removed.length) await api.deleteTags([i.instanceId], removed);
    notify.success("Tags updated."); reload();
  };
  return (
    <Table variant="container" items={tags} header={<Header variant="h2" counter={`(${tags.length})`} actions={<ManageTagsButton tags={tags} onSave={save} />}>Tags</Header>}
      columnDefinitions={[{ id: "k", header: "Key", cell: (t) => t.key }, { id: "v", header: "Value", cell: (t) => t.value || "-" }]}
      empty={<Box textAlign="center" color="inherit">No tags</Box>} />
  );
}

function ManageTagsButton({ tags, onSave }) {
  const [open, setOpen] = useState(false);
  const [edited, setEdited] = useState(tags);
  return (
    <>
      <Button onClick={() => { setEdited(tags); setOpen(true); }}>Manage tags</Button>
      <Modal visible={open} onDismiss={() => setOpen(false)} header="Manage tags" size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => { onSave(edited); setOpen(false); }}>Save</Button></SpaceBetween></Box>}>
        <TagEditor tags={edited} onChange={({ detail }) => setEdited(detail.tags)} i18nStrings={TAG_I18N} />
      </Modal>
    </>
  );
}

export const TAG_I18N = {
  keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
  undoPrompt: "This tag will be removed upon saving changes", loading: "Loading tags", keyPlaceholder: "Enter key",
  valuePlaceholder: "Enter value", emptyTags: "No tags associated with the resource.", tooManyKeysSuggestion: "", tooManyValuesSuggestion: "",
  keysSuggestionLoading: "", keysSuggestionError: "", valuesSuggestionLoading: "", valuesSuggestionError: "",
  emptyKeyError: "You must specify a tag key", maxKeyCharLengthError: "Max 128 characters", maxValueCharLengthError: "Max 256 characters",
  duplicateKeyError: "You must specify a unique tag key.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.",
  awsPrefixError: "Cannot start with aws:", tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "Tag limit reached.", tagLimitExceeded: () => "Tag limit exceeded.",
};

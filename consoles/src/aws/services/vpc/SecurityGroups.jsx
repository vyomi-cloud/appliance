/* Same component as the EC2 console's Security Groups (ui-spec notes this explicitly) —
 * one resource, reachable from both the EC2 and VPC nav. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Spinner from "@cloudscape-design/components/spinner";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ResourceSharingTab } from "./ResourceSharing.jsx";
import { TAG_I18N } from "./tagI18n.js";
import * as api from "./api.js";
import { describeInstances as ec2DescribeInstances } from "../ec2/api.js";

const opt = (v) => ({ value: v, label: v });
const TYPES = [
  { label: "All traffic", protocol: "-1" }, { label: "SSH", protocol: "tcp", from: 22, to: 22 }, { label: "HTTP", protocol: "tcp", from: 80, to: 80 },
  { label: "HTTPS", protocol: "tcp", from: 443, to: 443 }, { label: "RDP", protocol: "tcp", from: 3389, to: 3389 },
  { label: "Custom TCP", protocol: "tcp" }, { label: "All ICMP", protocol: "icmp" },
];
const typeLabel = (p) => TYPES.find((t) => t.protocol === p.IpProtocol && (t.from === undefined || t.from === p.FromPort))?.label || "Custom TCP";

export function SecurityGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeSecurityGroups(), []);
  const rows = t.data || [];

  const exportCsv = () => {
    const header = "Name,Security group ID,VPC ID,Description,Inbound rules,Outbound rules\n";
    const csv = header + rows.map((sg) => [sg.Tags?.Name || "", sg.GroupId, sg.VpcId, sg.GroupDescription, sg.IpPermissions.length, sg.IpPermissionsEgress.length].join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "security-groups.csv"; a.click();
  };

  return (
    <ContentLayout header={<Header variant="h1">Security Groups</Header>}>
      <ResourceTable
        resourceName="Security Groups"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="GroupId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find security groups by attribute or tag"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => g.Tags?.Name || "-" },
          { id: "id", header: "Security group ID", cell: (g) => <Link href={href("vpc", "security-groups", g.GroupId)} onFollow={follow}>{g.GroupId}</Link> },
          { id: "gn", header: "Security group name", cell: (g) => g.GroupName },
          { id: "vpc", header: "VPC ID", cell: (g) => g.VpcId },
          { id: "desc", header: "Description", cell: (g) => g.GroupDescription },
          { id: "owner", header: "Owner", cell: () => "123456789012" },
          { id: "in", header: "Inbound rules count", cell: (g) => g.IpPermissions.length },
          { id: "out", header: "Outbound rules count", cell: (g) => g.IpPermissionsEgress.length },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "view", text: "View details", disabled: sel.length !== 1 }, { id: "in", text: "Edit inbound rules", disabled: sel.length !== 1 },
              { id: "out", text: "Edit outbound rules", disabled: sel.length !== 1 }, { id: "delete", text: "Delete security groups" },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "view") navigate("vpc", "security-groups", sel[0].GroupId);
              else if (detail.id === "in") navigate("vpc", "security-groups", sel[0].GroupId, "edit-inbound-rules");
              else if (detail.id === "out") navigate("vpc", "security-groups", sel[0].GroupId, "edit-outbound-rules");
              else setDel(true);
            }}>Actions</ButtonDropdown>
            <Button onClick={exportCsv}>Export security groups to CSV</Button>
            <Button variant="primary" href={href("vpc", "create-security-group")} onFollow={follow}>Create security group</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="security group" names={sel.map((g) => g.GroupId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const g of sel) await api.deleteSecurityGroup(g.GroupId); notify.success(`${sel.length} security group(s) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

export function SecurityGroupDetail({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeSecurityGroup(params.id), [params.id]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Security group not found" }} />;
  const g = t.data;
  const saveTags = async (edited) => {
    const kept = edited.filter((x) => !x.markedForRemoval && x.key);
    const removed = edited.filter((x) => x.markedForRemoval && x.existing).map((x) => x.key);
    if (kept.length) await api.createTags([g.GroupId], Object.fromEntries(kept.map((x) => [x.key, x.value || ""])));
    if (removed.length) await api.deleteTags([g.GroupId], removed);
    notify.success("Tags updated."); t.reload();
  };
  return (
    <ContentLayout header={<Header variant="h1" actions={<ButtonDropdown items={[{ id: "delete", text: "Delete security group" }]} onItemClick={async () => {
      if (confirm(`Delete ${g.GroupId}?`)) { await api.deleteSecurityGroup(g.GroupId); notify.success("Security group deleted."); navigate("vpc", "security-groups"); }
    }}>Actions</ButtonDropdown>}>{`${g.GroupId} - ${g.GroupName}`}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["Security group name", g.GroupName], ["Security group ID", g.GroupId], ["Description", g.GroupDescription], ["VPC ID", g.VpcId],
          ["Owner", "123456789012"], ["Inbound rules count", g.IpPermissions.length], ["Outbound rules count", g.IpPermissionsEgress.length],
        ]} />
        <Tabs tabs={[
          { id: "in", label: "Inbound rules", content: <RulesTable g={g} direction="ingress" reload={t.reload} /> },
          { id: "out", label: "Outbound rules", content: <RulesTable g={g} direction="egress" reload={t.reload} /> },
          { id: "share", label: "Sharing", content: <ResourceSharingTab resourceId={g.GroupId} resourceKind="security-group" capabilityId="aws.vpc.security-group-sharing" title="Sharing" /> },
          { id: "vpc", label: "VPC associations", content: <VpcAssociationsTab g={g} /> },
          { id: "rel", label: "Related resources - new", content: <RelatedResourcesTab g={g} /> },
          { id: "tags", label: "Tags", content: <TagsTable resourceId={g.GroupId} tags={g.Tags} onSave={saveTags} /> },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}

function VpcAssociationsTab({ g }) {
  return (
    <CapabilityContainer id="aws.vpc.security-group-sharing" title="VPC associations">
      <Table items={[{ vpc: g.VpcId }]} columnDefinitions={[{ id: "vpc", header: "VPC", cell: (r) => r.vpc }, { id: "s", header: "Association state", cell: () => "Associated (owning account)" }]}
        empty={<Box textAlign="center" color="inherit">Not associated with any VPC.</Box>} />
    </CapabilityContainer>
  );
}

function RelatedResourcesTab({ g }) {
  const enis = useAsync(() => api.describeNetworkInterfaces(), [g.GroupId]);
  const instances = useAsync(() => ec2DescribeInstances(), [g.GroupId]);
  const eniRows = (enis.data || []).filter((e) => e.GroupIds.includes(g.GroupId));
  const instRows = (instances.data || []).filter((i) => (i.GroupSet || []).some((s) => s.groupId === g.GroupId));
  return (
    <CapabilityContainer id="aws.vpc.security-group-sharing" title="Related resources" counter={`(${eniRows.length + instRows.length})`}>
      <Table items={[
        ...instRows.map((i) => ({ id: i.instanceId, type: "Instance" })),
        ...eniRows.map((e) => ({ id: e.NetworkInterfaceId, type: "Network interface" })),
      ]} columnDefinitions={[{ id: "id", header: "Resource", cell: (r) => r.id }, { id: "type", header: "Type", cell: (r) => r.type }]}
        empty={<Box textAlign="center" color="inherit">No resources use this security group.</Box>} />
    </CapabilityContainer>
  );
}

function TagsTable({ tags, onSave }) {
  const [open, setOpen] = useState(false);
  const rows = Object.entries(tags || {}).map(([k, v]) => ({ key: k, value: v, existing: true }));
  const [edited, setEdited] = useState(rows);
  return (
    <>
      <Table variant="container" items={rows} header={<Header variant="h2" counter={`(${rows.length})`} actions={<Button onClick={() => { setEdited(rows); setOpen(true); }}>Manage tags</Button>}>Tags</Header>}
        columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.key }, { id: "v", header: "Value", cell: (r) => r.value || "-" }]}
        empty={<Box textAlign="center" color="inherit">No tags</Box>} />
      {open && (
        <Modal visible onDismiss={() => setOpen(false)} header="Manage tags" size="large" footer={<Box float="right"><Button variant="primary" onClick={async () => { await onSave(edited); setOpen(false); }}>Save</Button></Box>}>
          <TagEditor tags={edited} onChange={({ detail }) => setEdited(detail.tags)} i18nStrings={TAG_I18N} />
        </Modal>
      )}
    </>
  );
}

function RulesTable({ g, direction, reload }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [editing, setEditing] = useState(false);
  const perms = direction === "ingress" ? g.IpPermissions : g.IpPermissionsEgress;
  const revoke = direction === "ingress" ? api.revokeIngress : api.revokeEgress;
  return editing ? (
    <RuleEditor group={g} direction={direction} onDone={() => { setEditing(false); reload(); }} onCancel={() => setEditing(false)} />
  ) : (
    <Table
      variant="container"
      items={perms}
      trackBy="RuleId"
      selectionType="multi"
      selectedItems={sel}
      onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
      header={<Header variant="h2" counter={`(${perms.length})`} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={async () => { await revoke(g.GroupId, sel.map((p) => p.RuleId)); notify.success("Rule(s) removed."); setSel([]); reload(); }}>Delete</Button>
          <Button variant="primary" onClick={() => setEditing(true)}>{direction === "ingress" ? "Edit inbound rules" : "Edit outbound rules"}</Button>
        </SpaceBetween>
      }>{direction === "ingress" ? "Inbound rules" : "Outbound rules"}</Header>}
      columnDefinitions={[
        { id: "n", header: "Name", cell: () => "-" }, { id: "id", header: "Security group rule ID", cell: (p) => p.RuleId },
        { id: "type", header: "Type", cell: typeLabel }, { id: "proto", header: "Protocol", cell: (p) => (p.IpProtocol === "-1" ? "All" : p.IpProtocol) },
        { id: "port", header: "Port range", cell: (p) => (p.FromPort !== undefined ? `${p.FromPort} - ${p.ToPort}` : "All") },
        { id: "src", header: direction === "ingress" ? "Source" : "Destination", cell: (p) => p.cidrs?.[0] || p.groupIds?.[0] || "-" },
        { id: "desc", header: "Description", cell: (p) => p.Description || "-" },
      ]}
      empty={<Box textAlign="center" color="inherit">No {direction === "ingress" ? "inbound" : "outbound"} rules</Box>}
    />
  );
}

export function RuleEditor({ group, direction, onDone, onCancel }) {
  const notify = useNotify();
  const existing = direction === "ingress" ? group.IpPermissions : group.IpPermissionsEgress;
  const [rows, setRows] = useState(existing.map((p) => ({ type: typeLabel(p), protocol: p.IpProtocol, from: p.FromPort, to: p.ToPort, sourceType: p.groupIds?.length ? "sg" : "custom", source: p.cidrs?.[0] || p.groupIds?.[0] || "0.0.0.0/0", description: p.Description || "", ruleId: p.RuleId })));
  const [busy, setBusy] = useState(false);
  const authorize = direction === "ingress" ? api.authorizeIngress : api.authorizeEgress;
  const revoke = direction === "ingress" ? api.revokeIngress : api.revokeEgress;

  const save = async () => {
    setBusy(true);
    try {
      const keepIds = rows.filter((r) => r.ruleId).map((r) => r.ruleId);
      const removeIds = existing.map((p) => p.RuleId).filter((id) => !keepIds.includes(id));
      if (removeIds.length) await revoke(group.GroupId, removeIds);
      const toAdd = rows.filter((r) => !r.ruleId);
      if (toAdd.length) await authorize(group.GroupId, toAdd.map((r) => ({ IpProtocol: r.protocol, FromPort: r.from, ToPort: r.to, cidr: r.sourceType === "custom" ? r.source : undefined, groupId: r.sourceType === "sg" ? r.source : undefined, description: r.description })));
      notify.success(`${direction === "ingress" ? "Inbound" : "Outbound"} rules saved.`);
      onDone();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  const update = (idx, patch) => setRows((xs) => xs.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const setType = (idx, label) => {
    const preset = TYPES.find((t) => t.label === label);
    update(idx, { type: label, protocol: preset.protocol, from: preset.from, to: preset.to });
  };

  return (
    <SpaceBetween size="l">
      <Table
        variant="embedded"
        items={rows}
        header={<Header variant="h3">{direction === "ingress" ? "Inbound rules" : "Outbound rules"}</Header>}
        columnDefinitions={[
          { id: "type", header: "Type", cell: (r) => <Select selectedOption={opt(r.type)} onChange={({ detail }) => setType(rows.indexOf(r), detail.selectedOption.value)} options={TYPES.map((t) => opt(t.label))} ariaLabel="Type" /> },
          { id: "proto", header: "Protocol", cell: (r) => (r.protocol === "-1" ? "All" : r.protocol) },
          { id: "port", header: "Port range", cell: (r) => (r.type === "Custom TCP" ? <Input type="number" value={r.from || ""} onChange={({ detail }) => update(rows.indexOf(r), { from: Number(detail.value), to: Number(detail.value) })} ariaLabel="Port range" /> : (r.from !== undefined ? `${r.from} - ${r.to}` : "All")) },
          { id: "st", header: direction === "ingress" ? "Source type" : "Destination type", cell: (r) => <Select selectedOption={opt(r.sourceType === "sg" ? "Custom (security group)" : "Custom")} onChange={({ detail }) => update(rows.indexOf(r), { sourceType: detail.selectedOption.value.includes("security") ? "sg" : "custom" })} options={[opt("Custom"), opt("Custom (security group)"), opt("Anywhere-IPv4")]} ariaLabel="Source type" /> },
          { id: "src", header: direction === "ingress" ? "Source" : "Destination", cell: (r) => <Input value={r.source} onChange={({ detail }) => update(rows.indexOf(r), { source: detail.value })} ariaLabel="Source" /> },
          { id: "desc", header: "Description - optional", cell: (r) => <Input value={r.description} onChange={({ detail }) => update(rows.indexOf(r), { description: detail.value })} ariaLabel="Description - optional" /> },
          { id: "del", header: "", cell: (r) => <Button iconName="close" ariaLabel="Delete rule" onClick={() => setRows((xs) => xs.filter((x) => x !== r))} /> },
        ]}
        footer={<Button onClick={() => setRows((xs) => [...xs, { type: "Custom TCP", protocol: "tcp", from: undefined, to: undefined, sourceType: "custom", source: "0.0.0.0/0", description: "" }])}>Add rule</Button>}
        empty={<Box textAlign="center" color="inherit">This security group has no {direction === "ingress" ? "inbound" : "outbound"} rules.</Box>}
      />
      <SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={save}>Save rules</Button>
      </SpaceBetween>
    </SpaceBetween>
  );
}

export function CreateSecurityGroup() {
  const notify = useNotify();
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [vpcId, setVpcId] = useState("");
  const [inbound, setInbound] = useState([]);
  const [outbound, setOutbound] = useState([{ type: "All traffic", protocol: "-1", sourceType: "custom", source: "0.0.0.0/0", description: "" }]);
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const addRow = (setter) => setter((xs) => [...xs, { type: "Custom TCP", protocol: "tcp", from: undefined, to: undefined, sourceType: "custom", source: "0.0.0.0/0", description: "" }]);
  const editRow = (setter, idx, patch) => setter((xs) => xs.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const id = await api.createSecurityGroup(name, desc, vpcId || undefined, Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value])));
      if (inbound.length) await api.authorizeIngress(id, inbound.map((r) => ({ IpProtocol: r.protocol, FromPort: r.from, ToPort: r.to, cidr: r.source, description: r.description })));
      notify.success(`Security group "${name}" (${id}) created.`);
      navigate("vpc", "security-groups");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const ruleTable = (rows, setter, direction) => (
    <Table variant="embedded" items={rows}
      columnDefinitions={[
        { id: "type", header: "Type", cell: (r) => <Select selectedOption={opt(r.type)} onChange={({ detail }) => { const preset = TYPES.find((t) => t.label === detail.selectedOption.value); editRow(setter, rows.indexOf(r), { type: preset.label, protocol: preset.protocol, from: preset.from, to: preset.to }); }} options={TYPES.map((t) => opt(t.label))} ariaLabel="Type" /> },
        { id: "proto", header: "Protocol", cell: (r) => (r.protocol === "-1" ? "All" : r.protocol) },
        { id: "port", header: "Port range", cell: (r) => (r.type === "Custom TCP" ? <Input type="number" value={r.from || ""} onChange={({ detail }) => editRow(setter, rows.indexOf(r), { from: Number(detail.value), to: Number(detail.value) })} ariaLabel="Port range" /> : (r.from !== undefined ? `${r.from} - ${r.to}` : "All")) },
        { id: "st", header: `${direction} type`, cell: () => "Custom" },
        { id: "src", header: direction, cell: (r) => <Input value={r.source} onChange={({ detail }) => editRow(setter, rows.indexOf(r), { source: detail.value })} ariaLabel={direction} /> },
        { id: "desc", header: "Description - optional", cell: (r) => <Input value={r.description} onChange={({ detail }) => editRow(setter, rows.indexOf(r), { description: detail.value })} ariaLabel="Description - optional" /> },
        { id: "del", header: "", cell: (r) => <Button iconName="close" ariaLabel="Delete rule" onClick={() => setter((xs) => xs.filter((x) => x !== r))} /> },
      ]}
      footer={<SpaceBetween direction="horizontal" size="xs"><Button onClick={() => addRow(setter)}>Add rule</Button>{rows.length > 0 && <Button onClick={() => setter([])}>Delete</Button>}</SpaceBetween>}
      empty={<Box textAlign="center" color="inherit">This security group has no {direction === "Source" ? "inbound" : "outbound"} rules.</Box>}
    />
  );

  return (
    <ContentLayout header={<Header variant="h1">Create security group</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "security-groups")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name || !desc} onClick={submit}>Create security group</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Basic details</Header>}>
            <SpaceBetween size="l">
              <FormField label="Security group name" constraintText="Name cannot be edited after creation."><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="MyWebServerGroup" ariaLabel="Security group name" /></FormField>
              <FormField label="Description"><Input value={desc} onChange={({ detail }) => setDesc(detail.value)} placeholder="Allows SSH access to developers" ariaLabel="Description" /></FormField>
              <FormField label="VPC" description="Defaults to the default VPC">
                <Select selectedOption={vpcId ? { value: vpcId, label: vpcId } : { value: "", label: "Default VPC" }}
                  options={[{ value: "", label: "Default VPC" }, ...(vpcs.data || []).map((v) => ({ value: v.VpcId, label: v.VpcId }))]}
                  onChange={({ detail }) => setVpcId(detail.selectedOption.value)} ariaLabel="VPC" />
              </FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Inbound rules</Header>}><FormField label="Inbound rules">{ruleTable(inbound, setInbound, "Source")}</FormField></Container>
          <Container header={<Header variant="h2">Outbound rules</Header>}><FormField label="Outbound rules">{ruleTable(outbound, setOutbound, "Destination")}</FormField></Container>
          <Container header={<Header variant="h2">Tags - optional</Header>}><FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField></Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}

export function EditInboundRules({ params }) {
  const t = useAsync(() => api.describeSecurityGroup(params.id), [params.id]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Security group not found" }} />;
  return (
    <ContentLayout header={<Header variant="h1">Edit inbound rules</Header>}>
      <RuleEditor group={t.data} direction="ingress" onDone={() => navigate("vpc", "security-groups", params.id)} onCancel={() => navigate("vpc", "security-groups", params.id)} />
    </ContentLayout>
  );
}

export function EditOutboundRules({ params }) {
  const t = useAsync(() => api.describeSecurityGroup(params.id), [params.id]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Security group not found" }} />;
  return (
    <ContentLayout header={<Header variant="h1">Edit outbound rules</Header>}>
      <RuleEditor group={t.data} direction="egress" onDone={() => navigate("vpc", "security-groups", params.id)} onCancel={() => navigate("vpc", "security-groups", params.id)} />
    </ContentLayout>
  );
}

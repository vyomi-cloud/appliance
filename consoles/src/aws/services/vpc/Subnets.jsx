import { useEffect, useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import Tabs from "@cloudscape-design/components/tabs";
import Form from "@cloudscape-design/components/form";
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
import Spinner from "@cloudscape-design/components/spinner";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { FlowLogsTab } from "./FlowLogs.jsx";
import { TagsModal } from "./Vpcs.jsx";
import GapButton from "./GapButton.jsx";
import { TAG_I18N } from "./tagI18n.js";
import * as api from "./api.js";

export function Subnets() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [tags, setTags] = useState(null);
  const t = useAsync(() => api.describeSubnets(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Subnets</Header>}>
      <ResourceTable
        resourceName="Subnets"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="SubnetId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={<Box textAlign="center">No subnets found</Box>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (s) => s.Tags?.Name || "-" },
          { id: "id", header: "Subnet ID", cell: (s) => <Link href={href("vpc", "subnets", s.SubnetId)} onFollow={follow}>{s.SubnetId}</Link> },
          { id: "state", header: "State", cell: (s) => s.State },
          { id: "vpc", header: "VPC", cell: (s) => <Link href={href("vpc", "vpcs", s.VpcId)} onFollow={follow}>{s.VpcId}</Link> },
          { id: "bpa", header: "Block Public Access", cell: () => "Off" },
          { id: "cidr4", header: "IPv4 CIDR", cell: (s) => s.CidrBlock },
          { id: "cidr6", header: "IPv6 CIDR", cell: () => "-" },
          { id: "cidr6id", header: "IPv6 CIDR association ID", cell: () => "-" },
          { id: "avail", header: "Available IPv4 addresses", cell: (s) => s.AvailableIpAddressCount },
          { id: "az", header: "Availability Zone", cell: (s) => s.AvailabilityZone },
          { id: "azid", header: "Availability Zone ID", cell: () => "-" },
          { id: "border", header: "Network border group", cell: () => "us-east-1" },
          { id: "rt", header: "Route table", cell: (s) => <Link href={href("vpc", "route-tables", s.RouteTableId)} onFollow={follow}>{s.RouteTableId}</Link> },
          { id: "nacl", header: "Network ACL", cell: (s) => s.NetworkAclId || "-" },
          { id: "default", header: "Default subnet", cell: (s) => (s.DefaultForAz ? "Yes" : "No") },
          { id: "autopub4", header: "Auto-assign public IPv4 address", cell: (s) => (s.MapPublicIpOnLaunch ? "Yes" : "No") },
          { id: "autopub6", header: "Auto-assign IPv6 address", cell: () => "No" },
          { id: "owner", header: "Owner ID", cell: (s) => "123456789012" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "edit", text: "Edit subnet settings", disabled: sel.length !== 1 },
              { id: "tags", text: "Manage tags", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete subnet" },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "tags") setTags(sel[0]); else if (detail.id === "delete") setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("vpc", "create-subnet")} onFollow={follow}>Create subnet</Button>
          </SpaceBetween>
        }
      />
      <Container><Box variant="p" color="text-body-secondary">Select a subnet</Box></Container>
      <DeleteModal visible={del} resourceType="subnet" names={sel.map((s) => s.SubnetId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const s of sel) await api.deleteSubnet(s.SubnetId); notify.success(`${sel.length} subnet(s) deleted.`); setSel([]); t.reload(); }} />
      {tags && <TagsModal resource={tags} onDismiss={() => setTags(null)} onSaved={() => { setTags(null); t.reload(); }} />}
    </ContentLayout>
  );
}

export function SubnetDetail({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeSubnet(params.id), [params.id]);
  const rt = useAsync(() => (t.data?.RouteTableId ? api.describeRouteTable(t.data.RouteTableId) : null), [t.data?.RouteTableId]);
  const nacl = useAsync(() => (t.data?.NetworkAclId ? api.describeNetworkAcl(t.data.NetworkAclId) : null), [t.data?.NetworkAclId]);
  const [tags, setTags] = useState(false);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Subnet not found" }} />;
  const s = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<ButtonDropdown items={[{ id: "delete", text: "Delete subnet" }]} onItemClick={async () => {
      if (confirm(`Delete ${s.SubnetId}?`)) { await api.deleteSubnet(s.SubnetId); notify.success("Subnet deleted."); navigate("vpc", "subnets"); }
    }}>Actions</ButtonDropdown>}>{`${s.SubnetId} / ${s.Tags?.Name || ""}`}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["Subnet ID", s.SubnetId], ["Subnet ARN", `arn:aws:ec2:us-east-1:123456789012:subnet/${s.SubnetId}`], ["State", s.State],
          ["Block Public Access", "Off"], ["IPv4 CIDR", s.CidrBlock], ["Available IPv4 addresses", s.AvailableIpAddressCount],
          ["IPv6 CIDR", "-"], ["Availability Zone", s.AvailabilityZone], ["Availability Zone ID", "-"], ["Network border group", "us-east-1"],
          ["VPC", s.VpcId], ["Route table", s.RouteTableId || "-"], ["Network ACL", s.NetworkAclId || "-"], ["Default subnet", s.DefaultForAz ? "Yes" : "No"],
          ["Auto-assign public IPv4 address", s.MapPublicIpOnLaunch ? "Yes" : "No"], ["Auto-assign IPv6 address", "No"],
          ["Hostname type", "IP name"], ["Owner", "123456789012"],
        ]} />
        <Tabs tabs={[
          { id: "flow", label: "Flow logs", content: <FlowLogsTab resourceId={s.SubnetId} resourceType="Subnet" /> },
          { id: "rt", label: "Route table", content: (
            <Table variant="container" items={rt.data?.Routes || []} header={<Header variant="h2" actions={<Button href={href("vpc", "route-tables")} onFollow={follow}>Edit route table association</Button>}>Route table</Header>}
              columnDefinitions={[{ id: "d", header: "Destination", cell: (r) => r.DestinationCidrBlock }, { id: "t", header: "Target", cell: (r) => r.GatewayId }]} empty={<Box textAlign="center" color="inherit">No explicit route table association</Box>} />
          ) },
          { id: "nacl", label: "Network ACL", content: (
            <Table variant="container" items={nacl.data?.Entries || []} header={<Header variant="h2" actions={<Button href={href("vpc", "network-acls")} onFollow={follow}>Edit network ACL association</Button>}>Network ACL</Header>}
              columnDefinitions={[
                { id: "n", header: "Rule number", cell: (r) => r.RuleNumber }, { id: "t", header: "Type", cell: (r) => (r.Protocol === "-1" ? "All traffic" : r.Protocol) },
                { id: "p", header: "Protocol", cell: (r) => r.Protocol }, { id: "r", header: "Port range", cell: (r) => (r.PortRange ? `${r.PortRange.From} - ${r.PortRange.To}` : "All") },
                { id: "s", header: "Source", cell: (r) => r.CidrBlock }, { id: "a", header: "Allow/Deny", cell: (r) => (r.RuleAction === "allow" ? "Allow" : "Deny") },
              ]}
              empty={<Box textAlign="center" color="inherit">Default network ACL (allow all)</Box>} />
          ) },
          { id: "cidr", label: "CIDR reservations", content: <CapabilityContainer id="aws.vpc.cidr-reservations" title="CIDR reservations" /> },
          { id: "share", label: "Sharing", content: <CapabilityContainer id="aws.vpc.resource-sharing" title="Sharing" /> },
          { id: "tags", label: "Tags", content: (
            <Table variant="container" items={Object.entries(s.Tags || {}).map(([k, v]) => ({ k, v }))}
              header={<Header variant="h2" counter={`(${Object.keys(s.Tags || {}).length})`} actions={<Button onClick={() => setTags(true)}>Manage tags</Button>}>Tags</Header>}
              columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.k }, { id: "v", header: "Value", cell: (r) => r.v || "-" }]}
              empty={<Box textAlign="center" color="inherit">No tags</Box>} />
          ) },
        ]} />
      </SpaceBetween>
      {tags && <TagsModal resource={s} onDismiss={() => setTags(false)} onSaved={() => { setTags(false); t.reload(); }} />}
    </ContentLayout>
  );
}

export function CreateSubnet() {
  const notify = useNotify();
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const [vpcId, setVpcId] = useState("");
  const [name, setName] = useState("");
  const [az, setAz] = useState("");
  const [cidr, setCidr] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // AWS hides "Subnet settings" until a VPC is chosen; default to the first one so the
  // section (and its fields) render without forcing a redundant manual selection step.
  useEffect(() => { if (!vpcId && vpcs.data?.length) setVpcId(vpcs.data[0].VpcId); }, [vpcs.data]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const tagMap = Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value]));
      if (name) tagMap.Name = name;
      const subnet = await api.createSubnet(vpcId, cidr, az || undefined, tagMap);
      notify.success(`Subnet "${subnet.SubnetId}" created.`);
      navigate("vpc", "subnets");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create subnet</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "subnets")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!vpcId || !cidr} onClick={submit}>Create subnet</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">VPC</Header>}>
            <FormField label="VPC ID" description="Create subnets in this VPC.">
              <Select selectedOption={vpcId ? { value: vpcId, label: vpcId } : null} placeholder="Select a VPC"
                options={(vpcs.data || []).map((v) => ({ value: v.VpcId, label: `${v.VpcId}${v.Tags?.Name ? ` (${v.Tags.Name})` : ""}` }))}
                onChange={({ detail }) => setVpcId(detail.selectedOption.value)} />
            </FormField>
          </Container>
          {vpcId && (
            <Container header={<Header variant="h2">Subnet settings</Header>}>
              <SpaceBetween size="l">
                <FormField label="Subnet name"><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-subnet-01" /></FormField>
                <FormField label="Availability Zone">
                  <Select selectedOption={az ? { value: az, label: az } : { value: "", label: "No preference" }}
                    options={["No preference", "us-east-1a", "us-east-1b", "us-east-1c"].map((z) => ({ value: z === "No preference" ? "" : z, label: z }))}
                    onChange={({ detail }) => setAz(detail.selectedOption.value)} />
                </FormField>
                <FormField label="IPv4 VPC CIDR block"><Input value={(vpcs.data || []).find((v) => v.VpcId === vpcId)?.CidrBlock || ""} disabled /></FormField>
                <FormField label="IPv4 subnet CIDR block"><Input value={cidr} onChange={({ detail }) => setCidr(detail.value)} placeholder="10.0.0.0/24" /></FormField>
                <FormField label="Tags - optional"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField>
                <GapButton text="Add new subnet" feature="Creating multiple subnets in one batch" note="Create subnets one at a time; each submit creates a single subnet over the native wire." />
              </SpaceBetween>
            </Container>
          )}
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}

import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import Tabs from "@cloudscape-design/components/tabs";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
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
import { ErrorAlert, KeyValue, NotSimulated } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { CreateFlowLogModal, FlowLogsTab } from "./FlowLogs.jsx";
import GapButton from "./GapButton.jsx";
import { TAG_I18N } from "./tagI18n.js";
import * as api from "./api.js";

export function Vpcs() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [tags, setTags] = useState(null);
  const [gap, setGap] = useState(null);
  const [flowLog, setFlowLog] = useState(null);
  const t = useAsync(() => api.describeVpcs(), []);
  const rows = t.data || [];

  const createDefault = async () => { await api.describeVpcs(); notify.success("Default VPC ready."); t.reload(); };

  return (
    <ContentLayout header={<Header variant="h1">Your VPCs</Header>}>
      <ResourceTable
        resourceName="Your VPCs"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="VpcId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={<Box textAlign="center"><b>No VPCs found</b><Box padding={{ top: "s" }}><Button href={href("vpc", "create-vpc")} onFollow={follow}>Create VPC</Button></Box></Box>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (v) => v.Tags?.Name || "-" },
          { id: "id", header: "VPC ID", cell: (v) => <Link href={href("vpc", "vpcs", v.VpcId)} onFollow={follow}>{v.VpcId}</Link> },
          { id: "state", header: "State", cell: (v) => v.State },
          { id: "bpa", header: "Block Public Access", cell: () => "Off" },
          { id: "cidr4", header: "IPv4 CIDR", cell: (v) => v.CidrBlock },
          { id: "cidr6", header: "IPv6 CIDR", cell: () => "-" },
          { id: "pool6", header: "IPv6 pool", cell: () => "-" },
          { id: "dopt", header: "DHCP option set", cell: (v) => v.DhcpOptionsId },
          { id: "mrt", header: "Main route table", cell: (v) => v.MainRouteTableId },
          { id: "mnacl", header: "Main network ACL", cell: (v) => v.MainNetworkAclId },
          { id: "tenancy", header: "Tenancy", cell: (v) => v.InstanceTenancy },
          { id: "default", header: "Default VPC", cell: (v) => (v.IsDefault ? "Yes" : "No") },
          { id: "owner", header: "Owner ID", cell: (v) => v.OwnerId },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "create-default", text: "Create default VPC", disabled: sel.length > 0 },
              { id: "flow", text: "Create flow log", disabled: sel.length !== 1 },
              { id: "edit", text: "Edit VPC settings", disabled: sel.length !== 1 },
              { id: "cidr", text: "Edit CIDRs", disabled: sel.length !== 1 },
              { id: "middlebox", text: "Manage middlebox routes", disabled: sel.length !== 1 },
              { id: "tags", text: "Manage tags", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete VPC" },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "create-default") createDefault();
              else if (detail.id === "edit") navigate("vpc", "vpcs", sel[0].VpcId, "edit-settings");
              else if (detail.id === "tags") setTags(sel[0]);
              else if (detail.id === "delete") setDel(true);
              else if (detail.id === "flow") setFlowLog(sel[0].VpcId);
              else if (detail.id === "cidr") setGap({ text: "Edit CIDRs", feature: "Secondary/IPAM-allocated CIDR blocks" });
              else if (detail.id === "middlebox") setGap({ text: "Manage middlebox routes", feature: "Gateway Load Balancer middlebox routing" });
            }}>Actions</ButtonDropdown>
            <Button onClick={createDefault}>Create default VPC</Button>
            <Button variant="primary" href={href("vpc", "create-vpc")} onFollow={follow}>Create VPC</Button>
          </SpaceBetween>
        }
      />
      <Container><Box variant="p" color="text-body-secondary">Select a VPC above</Box></Container>
      <DeleteModal visible={del} resourceType="VPC" names={sel.map((v) => v.VpcId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const v of sel) await api.deleteVpc(v.VpcId); notify.success(`${sel.length} VPC(s) deleted.`); setSel([]); t.reload(); }} />
      {tags && <TagsModal resource={tags} onDismiss={() => setTags(null)} onSaved={() => { setTags(null); t.reload(); }} />}
      {flowLog && <CreateFlowLogModal resourceId={flowLog} resourceType="VPC" onDismiss={() => setFlowLog(null)} onCreated={() => setFlowLog(null)} />}
      {gap && (
        <Modal visible onDismiss={() => setGap(null)} header={gap.text} footer={<Box float="right"><Button onClick={() => setGap(null)}>Close</Button></Box>}>
          <NotSimulated feature={gap.feature} />
        </Modal>
      )}
    </ContentLayout>
  );
}

export function TagsModal({ resource, onDismiss, onSaved }) {
  const notify = useNotify();
  const rows = Object.entries(resource.Tags || {}).map(([k, v]) => ({ key: k, value: v, existing: true }));
  const [edited, setEdited] = useState(rows);
  const id = resource.VpcId || resource.SubnetId || resource.RouteTableId || resource.InternetGatewayId || resource.NatGatewayId || resource.NetworkAclId;
  const save = async () => {
    const kept = edited.filter((x) => !x.markedForRemoval && x.key);
    const removed = edited.filter((x) => x.markedForRemoval && x.existing).map((x) => x.key);
    if (kept.length) await api.createTags([id], Object.fromEntries(kept.map((x) => [x.key, x.value || ""])));
    if (removed.length) await api.deleteTags([id], removed);
    notify.success("Tags updated."); onSaved();
  };
  return (
    <Modal visible onDismiss={onDismiss} header="Manage tags" size="large" footer={<Box float="right"><Button variant="primary" onClick={save}>Save</Button></Box>}>
      <TagEditor tags={edited} onChange={({ detail }) => setEdited(detail.tags)} i18nStrings={TAG_I18N} />
    </Modal>
  );
}

export function VpcDetail({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeVpc(params.id), [params.id]);
  const subnets = useAsync(() => api.describeSubnets({ VpcId: [params.id] }), [params.id]);
  const rts = useAsync(() => api.describeRouteTables({ VpcId: [params.id] }), [params.id]);
  const dns = useAsync(async () => ({
    hostnames: await api.describeVpcAttribute(params.id, "enableDnsHostnames"),
    support: await api.describeVpcAttribute(params.id, "enableDnsSupport"),
  }), [params.id]);
  const [tags, setTags] = useState(false);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "VPC not found" }} />;
  const v = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<ButtonDropdown items={[{ id: "delete", text: "Delete VPC" }]} onItemClick={async () => {
      if (confirm(`Delete ${v.VpcId}?`)) { await api.deleteVpc(v.VpcId); notify.success("VPC deleted."); navigate("vpc", "vpcs"); }
    }}>Actions</ButtonDropdown>}>{`${v.VpcId} / ${v.Tags?.Name || ""}`}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["VPC ID", v.VpcId], ["State", v.State], ["Block Public Access", "Off"],
          ["DNS hostnames", dns.data ? (dns.data.hostnames ? "Enabled" : "Disabled") : "-"],
          ["DNS resolution", dns.data ? (dns.data.support ? "Enabled" : "Disabled") : "-"],
          ["Tenancy", v.InstanceTenancy], ["DHCP option set", v.DhcpOptionsId], ["Main route table", v.MainRouteTableId],
          ["Main network ACL", v.MainNetworkAclId], ["Default VPC", v.IsDefault ? "Yes" : "No"], ["IPv4 CIDR", v.CidrBlock],
          ["IPv6 pool", "-"], ["IPv6 CIDR (Network border group)", "-"], ["Network Address Usage metrics", "Disabled"],
          ["Route 53 Resolver DNS Firewall rule groups", "-"], ["Owner ID", v.OwnerId],
        ]} />
        <Tabs tabs={[
          { id: "map", label: "Resource map", content: (
            <KeyValue title="Resource map" columns={4} items={[
              ["VPC", v.VpcId], ["Subnets", subnets.data?.length ?? "-"], ["Route tables", rts.data?.length ?? "-"], ["Network connections", v.MainNetworkAclId ? 1 : 0],
            ]} />
          ) },
          { id: "cidrs", label: "CIDRs", content: (
            <SpaceBetween size="l">
              <Table variant="container" items={[{ cidr: v.CidrBlock, status: "associated", reason: "" }]}
                header={<Header variant="h2" actions={<GapButton text="Edit CIDRs" feature="Secondary/IPAM-allocated CIDR blocks" />}>IPv4 CIDRs</Header>}
                columnDefinitions={[{ id: "c", header: "CIDR", cell: (r) => r.cidr }, { id: "s", header: "Status", cell: (r) => r.status }, { id: "r", header: "Status reason", cell: (r) => r.reason || "-" }]} />
              <Table variant="container" items={[]} header={<Header variant="h2">IPv6 CIDRs</Header>}
                columnDefinitions={[{ id: "c", header: "CIDR" }, { id: "p", header: "Address pool" }, { id: "g", header: "Network border group" }, { id: "s", header: "Status" }]}
                empty={<Box textAlign="center" color="inherit">No IPv6 CIDRs</Box>} />
            </SpaceBetween>
          ) },
          { id: "flow", label: "Flow logs", content: <FlowLogsTab resourceId={v.VpcId} resourceType="VPC" /> },
          { id: "tags", label: "Tags", content: (
            <Table variant="container" items={Object.entries(v.Tags || {}).map(([k, val]) => ({ k, val }))}
              header={<Header variant="h2" counter={`(${Object.keys(v.Tags || {}).length})`} actions={<Button onClick={() => setTags(true)}>Manage tags</Button>}>Tags</Header>}
              columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.k }, { id: "v", header: "Value", cell: (r) => r.val || "-" }]}
              empty={<Box textAlign="center" color="inherit">No tags</Box>} />
          ) },
          { id: "integ", label: "Integrations", content: <CapabilityContainer id="aws.vpc.integrations" title="Integrations" /> },
        ]} />
      </SpaceBetween>
      {tags && <TagsModal resource={v} onDismiss={() => setTags(false)} onSaved={() => { setTags(false); t.reload(); }} />}
    </ContentLayout>
  );
}

export function EditVpcSettings({ params }) {
  const dns = useAsync(async () => ({
    hostnames: await api.describeVpcAttribute(params.id, "enableDnsHostnames"),
    support: await api.describeVpcAttribute(params.id, "enableDnsSupport"),
  }), [params.id]);
  if (dns.loading || !dns.data) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  return <EditVpcSettingsForm vpcId={params.id} initial={dns.data} />;
}

function EditVpcSettingsForm({ vpcId, initial }) {
  const notify = useNotify();
  const [hostnames, setHostnames] = useState(initial.hostnames);
  const [support, setSupport] = useState(initial.support);
  const [busy, setBusy] = useState(false);
  return (
    <ContentLayout header={<Header variant="h1">Edit VPC settings</Header>}>
      <Form actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "vpcs", vpcId)} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true);
            await api.modifyVpcAttribute(vpcId, { "EnableDnsHostnames.Value": hostnames });
            await api.modifyVpcAttribute(vpcId, { "EnableDnsSupport.Value": support });
            notify.success("VPC settings saved."); navigate("vpc", "vpcs", vpcId);
          }}>Save</Button>
        </SpaceBetween>
      }>
        <Container header={<Header variant="h2">DNS settings</Header>}>
          <SpaceBetween size="m">
            <Checkbox checked={support} onChange={({ detail }) => setSupport(detail.checked)}>Enable DNS resolution</Checkbox>
            <Checkbox checked={hostnames} onChange={({ detail }) => setHostnames(detail.checked)}>Enable DNS hostnames</Checkbox>
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
}

const AZ_POOL = ["us-east-1a", "us-east-1b", "us-east-1c"];

/** Carve the Nth /24 off a base CIDR by bumping its 3rd octet — the same scheme the real
 * "VPC and more" wizard uses for a /16 input; good enough for any CIDR a demo wizard sees. */
function carveSubnetCidr(baseCidr, index) {
  const [addr] = baseCidr.split("/");
  const parts = addr.split(".").map(Number);
  parts[2] = (parts[2] + index) % 256;
  return `${parts[0]}.${parts[1]}.${parts[2]}.0/24`;
}

/** Real orchestration over the already-fully-built primitives (CreateVpc/CreateSubnet/
 * CreateRouteTable/CreateInternetGateway/CreateNatGateway/CreateVpcEndpoint) — no new backend
 * state, just the sequence of calls "VPC and more" performs on your behalf. */
async function createVpcAndMore({ cidr, tagMap, tenancy, numAzs, numPublic, numPrivate, natOption, endpointOption, dnsHostnames, dnsSupport }) {
  const vpc = await api.createVpc(cidr, tagMap, tenancy);
  await api.modifyVpcAttribute(vpc.VpcId, { "EnableDnsSupport.Value": dnsSupport });
  await api.modifyVpcAttribute(vpc.VpcId, { "EnableDnsHostnames.Value": dnsHostnames });
  const azs = AZ_POOL.slice(0, numAzs);
  let cidrIndex = 0;
  const publicSubnets = [];
  const privateSubnets = [];
  for (let i = 0; i < numPublic; i++) {
    const az = azs[i % azs.length];
    const sn = await api.createSubnet(vpc.VpcId, carveSubnetCidr(cidr, cidrIndex++), az, { Name: `${tagMap.Name || vpc.VpcId}-public-${az}` });
    publicSubnets.push(sn);
  }
  for (let i = 0; i < numPrivate; i++) {
    const az = azs[i % azs.length];
    const sn = await api.createSubnet(vpc.VpcId, carveSubnetCidr(cidr, cidrIndex++), az, { Name: `${tagMap.Name || vpc.VpcId}-private-${az}` });
    privateSubnets.push(sn);
  }
  let igw = null;
  if (publicSubnets.length) {
    igw = await api.createInternetGateway({ Name: `${tagMap.Name || vpc.VpcId}-igw` });
    await api.attachInternetGateway(igw.InternetGatewayId, vpc.VpcId);
    const mainRt = (await api.describeRouteTables()).find((r) => r.VpcId === vpc.VpcId && r.Associations.some((a) => a.Main));
    await api.createRoute(mainRt.RouteTableId, "0.0.0.0/0", igw.InternetGatewayId);
    for (const sn of publicSubnets) await api.associateRouteTable(mainRt.RouteTableId, sn.SubnetId);
  }
  const natGateways = [];
  if (natOption !== "None" && publicSubnets.length) {
    const natCount = natOption === "1 per AZ" ? publicSubnets.length : 1;
    for (let i = 0; i < natCount; i++) natGateways.push(await api.createNatGateway(publicSubnets[i].SubnetId, "public", { Name: `${tagMap.Name || vpc.VpcId}-nat-${i + 1}` }));
  }
  if (privateSubnets.length) {
    for (let i = 0; i < privateSubnets.length; i++) {
      const rt = await api.createRouteTable(vpc.VpcId, { Name: `${tagMap.Name || vpc.VpcId}-private-rt-${i + 1}` });
      await api.associateRouteTable(rt.RouteTableId, privateSubnets[i].SubnetId);
      if (natGateways.length) await api.createRoute(rt.RouteTableId, "0.0.0.0/0", natGateways[i % natGateways.length].NatGatewayId);
    }
  }
  if (endpointOption === "S3 Gateway") {
    const allRts = (await api.describeRouteTables()).filter((r) => r.VpcId === vpc.VpcId);
    await api.createVpcEndpoint(vpc.VpcId, "com.amazonaws.us-east-1.s3", "Gateway", { routeTableIds: allRts.map((r) => r.RouteTableId) });
  }
  return vpc;
}

export function CreateVpc() {
  const notify = useNotify();
  const [resources, setResources] = useState("VPC only");
  const [name, setName] = useState("");
  const [cidrSource, setCidrSource] = useState("manual");
  const [cidr, setCidr] = useState("10.0.0.0/16");
  const [tenancy, setTenancy] = useState("Default");
  const [tags, setTags] = useState([]);
  const [numAzs, setNumAzs] = useState("2");
  const [numPublic, setNumPublic] = useState("2");
  const [numPrivate, setNumPrivate] = useState("2");
  const [natOption, setNatOption] = useState("None");
  const [endpointOption, setEndpointOption] = useState("None");
  const [dnsHostnames, setDnsHostnames] = useState(true);
  const [dnsSupport, setDnsSupport] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const tagMap = Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value]));
      if (name) tagMap.Name = name;
      if (resources === "VPC and more") {
        const vpc = await createVpcAndMore({
          cidr, tagMap, tenancy, numAzs: Number(numAzs), numPublic: Number(numPublic), numPrivate: Number(numPrivate),
          natOption, endpointOption, dnsHostnames, dnsSupport,
        });
        notify.success(`VPC "${vpc.VpcId}" and its subnets/route tables/gateways created.`);
        navigate("vpc", "vpcs", vpc.VpcId);
        return;
      }
      const vpc = await api.createVpc(cidr, tagMap, tenancy);
      notify.success(`VPC "${vpc.VpcId}" created.`);
      navigate("vpc", "vpcs", vpc.VpcId);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create VPC</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "vpcs")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!cidr} onClick={submit}>Create VPC</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">VPC settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Resources to create" description="Create only the VPC resource or the VPC and other networking resources.">
                <RadioGroup value={resources} onChange={({ detail }) => setResources(detail.value)} items={[{ value: "VPC only", label: "VPC only" }, { value: "VPC and more", label: "VPC and more" }]} />
              </FormField>
              <FormField label="Name tag - optional" description="Auto-generates Name tags for every resource this wizard creates (vpcName-public-az, vpcName-nat-1, …), same as the real console.">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-vpc-01" />
              </FormField>
              {resources === "VPC and more" && (
                <CapabilityContainer id="aws.vpc.create-vpc-and-more" title="VPC and more">
                  <SpaceBetween size="l">
                    <FormField label="Name tag auto-generation" description="Automatically generates Name tags for the resources this wizard creates, derived from the Name tag above.">
                      <Checkbox checked readOnly>Auto-generate</Checkbox>
                    </FormField>
                    <FormField label="Number of Availability Zones (AZs)">
                      <Select selectedOption={{ value: numAzs, label: numAzs }} options={["1", "2", "3"].map((v) => ({ value: v, label: v }))}
                        onChange={({ detail }) => setNumAzs(detail.selectedOption.value)} />
                    </FormField>
                    <FormField label="Number of public subnets">
                      <Select selectedOption={{ value: numPublic, label: numPublic }} options={["0", "1", "2", "3"].map((v) => ({ value: v, label: v }))}
                        onChange={({ detail }) => setNumPublic(detail.selectedOption.value)} />
                    </FormField>
                    <FormField label="Number of private subnets">
                      <Select selectedOption={{ value: numPrivate, label: numPrivate }} options={["0", "1", "2", "3"].map((v) => ({ value: v, label: v }))}
                        onChange={({ detail }) => setNumPrivate(detail.selectedOption.value)} />
                    </FormField>
                    <FormField label="NAT gateways ($)" description="Creates a real NAT gateway (billed-with-$ in real AWS) per selection, and routes every private subnet's table through it.">
                      <Select selectedOption={{ value: natOption, label: natOption }} options={["None", "1 per AZ", "In 1 AZ"].map((v) => ({ value: v, label: v }))}
                        onChange={({ detail }) => setNatOption(detail.selectedOption.value)} />
                    </FormField>
                    <FormField label="VPC endpoints" description="S3 Gateway adds a real route (target = the endpoint) to every route table this wizard creates.">
                      <Select selectedOption={{ value: endpointOption, label: endpointOption }} options={["None", "S3 Gateway"].map((v) => ({ value: v, label: v }))}
                        onChange={({ detail }) => setEndpointOption(detail.selectedOption.value)} />
                    </FormField>
                    <FormField label="DNS options">
                      <SpaceBetween size="xs">
                        <Checkbox checked={dnsHostnames} onChange={({ detail }) => setDnsHostnames(detail.checked)}>Enable DNS hostnames</Checkbox>
                        <Checkbox checked={dnsSupport} onChange={({ detail }) => setDnsSupport(detail.checked)}>Enable DNS resolution</Checkbox>
                      </SpaceBetween>
                    </FormField>
                  </SpaceBetween>
                </CapabilityContainer>
              )}
              <FormField label="IPv4 CIDR block">
                <RadioGroup value={cidrSource} onChange={({ detail }) => setCidrSource(detail.value)}
                  items={[{ value: "manual", label: "IPv4 CIDR manual input" }, { value: "ipam", label: "IPAM-allocated IPv4 CIDR block", disabled: true }]} />
              </FormField>
              <FormField label="IPv4 CIDR" constraintText="CIDR block size must be between /16 and /28.">
                <Input value={cidr} onChange={({ detail }) => setCidr(detail.value)} placeholder="10.0.0.0/24" disabled={cidrSource !== "manual"} />
              </FormField>
              <FormField label="IPv6 CIDR block">
                <Select selectedOption={{ value: "none", label: "No IPv6 CIDR block" }} options={[{ value: "none", label: "No IPv6 CIDR block" }]} disabled />
              </FormField>
              <FormField label="Tenancy">
                <Select selectedOption={{ value: tenancy, label: tenancy }} onChange={({ detail }) => setTenancy(detail.selectedOption.value)} options={[{ value: "Default", label: "Default" }, { value: "Dedicated", label: "Dedicated" }]} />
              </FormField>
              <FormField label="VPC encryption control ($)">
                <Select selectedOption={{ value: "None", label: "None" }} options={[{ value: "None", label: "None" }, { value: "Monitor mode", label: "Monitor mode" }, { value: "Enforce mode", label: "Enforce mode" }]} disabled />
              </FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Tags</Header>}><FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField></Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}

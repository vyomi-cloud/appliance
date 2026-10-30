import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import Table from "@cloudscape-design/components/table";
import Container from "@cloudscape-design/components/container";
import Box from "@cloudscape-design/components/box";
import Spinner from "@cloudscape-design/components/spinner";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { TagsModal } from "./Vpcs.jsx";
import { TAG_I18N } from "./tagI18n.js";
import * as api from "./api.js";

export function NatGateways() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [tags, setTags] = useState(null);
  const t = useAsync(() => api.describeNatGateways(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">NAT gateways</Header>}>
      <ResourceTable
        resourceName="NAT gateways"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="NatGatewayId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={<Box textAlign="center">No NAT gateways found</Box>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => g.Tags?.Name || "-" },
          { id: "id", header: "NAT gateway ID", cell: (g) => <Link href={href("vpc", "nat-gateways", g.NatGatewayId)} onFollow={follow}>{g.NatGatewayId}</Link> },
          { id: "mode", header: "Availability mode", cell: () => "Regional" },
          { id: "conn", header: "Connectivity type", cell: (g) => (g.ConnectivityType === "public" ? "Public" : "Private") },
          { id: "state", header: "State", cell: (g) => g.State },
          { id: "msg", header: "State message", cell: () => "-" },
          { id: "pubip", header: "Primary public IPv4 address", cell: (g) => g.NatGatewayAddresses?.[0]?.PublicIp || "-" },
          { id: "privip", header: "Primary private IPv4 address", cell: (g) => g.NatGatewayAddresses?.[0]?.PrivateIp || "-" },
          { id: "eni", header: "Primary network interface ID", cell: (g) => g.NatGatewayAddresses?.[0]?.NetworkInterfaceId || "-" },
          { id: "vpc", header: "VPC", cell: (g) => <Link href={href("vpc", "vpcs", g.VpcId)} onFollow={follow}>{g.VpcId}</Link> },
          { id: "subnet", header: "Subnet", cell: (g) => <Link href={href("vpc", "subnets", g.SubnetId)} onFollow={follow}>{g.SubnetId}</Link> },
          { id: "created", header: "Created", cell: (g) => g.CreateTime },
          { id: "deleted", header: "Deleted", cell: () => "-" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "eip", text: "Edit secondary IP address associations", disabled: sel.length !== 1 },
              { id: "tags", text: "Manage tags", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete NAT gateway" },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "tags") setTags(sel[0]); else if (detail.id === "delete") setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("vpc", "create-nat-gateway")} onFollow={follow}>Create NAT gateway</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="NAT gateway" names={sel.map((g) => g.NatGatewayId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const g of sel) await api.deleteNatGateway(g.NatGatewayId); notify.success(`${sel.length} NAT gateway(s) deleted.`); setSel([]); t.reload(); }} />
      {tags && <TagsModal resource={tags} onDismiss={() => setTags(null)} onSaved={() => { setTags(null); t.reload(); }} />}
    </ContentLayout>
  );
}

export function NatGatewayDetail({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeNatGateway(params.id), [params.id]);
  const [tags, setTags] = useState(false);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "NAT gateway not found" }} />;
  const g = t.data;
  const addr = g.NatGatewayAddresses?.[0];
  return (
    <ContentLayout header={<Header variant="h1" actions={<ButtonDropdown items={[{ id: "delete", text: "Delete NAT gateway" }]} onItemClick={async () => {
      if (confirm(`Delete ${g.NatGatewayId}?`)) { await api.deleteNatGateway(g.NatGatewayId); notify.success("NAT gateway deleted."); navigate("vpc", "nat-gateways"); }
    }}>Actions</ButtonDropdown>}>{`${g.NatGatewayId} / ${g.Tags?.Name || ""}`}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["NAT gateway ID", g.NatGatewayId], ["Connectivity type", g.ConnectivityType === "public" ? "Public" : "Private"], ["State", g.State],
          ["State message", "-"], ["NAT gateway ARN", `arn:aws:ec2:us-east-1:123456789012:natgateway/${g.NatGatewayId}`],
          ["Primary public IPv4 address", addr?.PublicIp || "-"], ["Primary private IPv4 address", addr?.PrivateIp || "-"],
          ["Primary network interface ID", addr?.NetworkInterfaceId || "-"], ["VPC", g.VpcId], ["Subnet", g.SubnetId],
          ["Created", g.CreateTime], ["Deleted", "-"],
        ]} />
        <Tabs tabs={[
          { id: "sec", label: "Secondary IPv4 addresses", content: (
            <Table variant="container" items={[]} header={<Header variant="h2">Secondary IPv4 addresses</Header>}
              columnDefinitions={[{ id: "p", header: "Private IPv4 address" }, { id: "pub", header: "Public IPv4 address" }, { id: "a", header: "Allocation ID" }, { id: "as", header: "Association ID" }, { id: "s", header: "Status" }]}
              empty={<Box textAlign="center" color="inherit">No secondary IPv4 addresses</Box>} />
          ) },
          { id: "mon", label: "Monitoring", content: <CapabilityContainer id="aws.vpc.nat-gateway-monitoring" title="Monitoring" /> },
          { id: "tags", label: "Tags", content: (
            <Table variant="container" items={Object.entries(g.Tags || {}).map(([k, v]) => ({ k, v }))}
              header={<Header variant="h2" counter={`(${Object.keys(g.Tags || {}).length})`} actions={<Button onClick={() => setTags(true)}>Manage tags</Button>}>Tags</Header>}
              columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.k }, { id: "v", header: "Value", cell: (r) => r.v || "-" }]}
              empty={<Box textAlign="center" color="inherit">No tags</Box>} />
          ) },
        ]} />
      </SpaceBetween>
      {tags && <TagsModal resource={g} onDismiss={() => setTags(false)} onSaved={() => { setTags(false); t.reload(); }} />}
    </ContentLayout>
  );
}

export function CreateNatGateway() {
  const notify = useNotify();
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const subnets = useAsync(() => api.describeSubnets(), []);
  const [name, setName] = useState("");
  const [vpcId, setVpcId] = useState("");
  const [subnetId, setSubnetId] = useState("");
  const [connectivity, setConnectivity] = useState("Public");
  const [eipMethod, setEipMethod] = useState("Automatic");
  const [allocationId, setAllocationId] = useState("");
  const addresses = useAsync(() => api.describeAddresses(), []);
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const vpcSubnets = (subnets.data || []).filter((s) => s.VpcId === vpcId);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const tagMap = Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value]));
      if (name) tagMap.Name = name;
      const gw = await api.createNatGateway(subnetId, connectivity.toLowerCase(), tagMap, eipMethod === "Manual" ? allocationId : undefined);
      notify.success(`NAT gateway "${gw.NatGatewayId}" created.`);
      navigate("vpc", "nat-gateways", gw.NatGatewayId);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create NAT gateway</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "nat-gateways")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!subnetId} onClick={submit}>Create NAT gateway</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">NAT gateway settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name - optional" constraintText="The name can be up to 256 characters long."><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-nat-gateway-01" /></FormField>
              <FormField label="Availability mode"><RadioGroup value="Regional" items={[{ value: "Regional", label: "Regional - new" }, { value: "Zonal", label: "Zonal", disabled: true }]} /></FormField>
              <FormField label="VPC">
                <Select selectedOption={vpcId ? { value: vpcId, label: vpcId } : null} placeholder="Select a VPC"
                  options={(vpcs.data || []).map((v) => ({ value: v.VpcId, label: v.VpcId }))} onChange={({ detail }) => { setVpcId(detail.selectedOption.value); setSubnetId(""); }} />
              </FormField>
              <FormField label="Subnet">
                <Select selectedOption={subnetId ? { value: subnetId, label: subnetId } : null} placeholder="Select a subnet" disabled={!vpcId}
                  options={vpcSubnets.map((s) => ({ value: s.SubnetId, label: s.SubnetId }))} onChange={({ detail }) => setSubnetId(detail.selectedOption.value)} />
              </FormField>
              <FormField label="Connectivity type">
                <RadioGroup value={connectivity} onChange={({ detail }) => setConnectivity(detail.value)} items={[{ value: "Public", label: "Public" }, { value: "Private", label: "Private" }]} />
              </FormField>
              <FormField label="Method of Elastic IP (EIP) allocation">
                <RadioGroup value={eipMethod} onChange={({ detail }) => setEipMethod(detail.value)} items={[{ value: "Automatic", label: "Automatic" }, { value: "Manual", label: "Manual" }]} />
              </FormField>
              {eipMethod === "Manual" && (
                <FormField label="Elastic IP allocation ID">
                  <Select selectedOption={allocationId ? { value: allocationId, label: allocationId } : null} placeholder="Select an allocation ID"
                    options={(addresses.data || []).map((a) => ({ value: a.AllocationId, label: `${a.AllocationId} (${a.PublicIp})` }))}
                    onChange={({ detail }) => setAllocationId(detail.selectedOption.value)} />
                </FormField>
              )}
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Tags</Header>}><FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField></Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}

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
import GapButton from "./GapButton.jsx";
import { TAG_I18N } from "./tagI18n.js";
import * as api from "./api.js";

export function Vpcs() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [tags, setTags] = useState(null);
  const [gap, setGap] = useState(null);
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
              else if (detail.id === "flow") setGap({ text: "Create flow log", feature: "VPC Flow Logs" });
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
          { id: "flow", label: "Flow logs", content: <CapabilityContainer id="aws.vpc.flow-logs" title="Flow logs" actions={<GapButton text="Create flow log" feature="VPC Flow Logs" />} /> },
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

export function CreateVpc() {
  const notify = useNotify();
  const [resources, setResources] = useState("VPC only");
  const [name, setName] = useState("");
  const [cidrSource, setCidrSource] = useState("manual");
  const [cidr, setCidr] = useState("10.0.0.0/16");
  const [tenancy, setTenancy] = useState("Default");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const tagMap = Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value]));
      if (name) tagMap.Name = name;
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
              {resources === "VPC only" && (
                <FormField label="Name tag - optional" description="Creates a tag with a key of 'Name' and a value that you specify.">
                  <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-vpc-01" />
                </FormField>
              )}
              {resources === "VPC and more" && (
                <CapabilityContainer id="aws.vpc.create-vpc-and-more" title="VPC and more" />
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

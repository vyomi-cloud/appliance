/* Small, genuinely self-contained VPC resource types that the real console's capture
 * only recorded as a bare nav entry (no columns/fields crawled) — still real CRUD against
 * vpc_core.py, just without a bespoke layout to match (none was captured). */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

function ResourceList({ title, resourceName, trackBy, list, create, del, columns, createLabel, deleteLabel, CreateForm, extra }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [showDel, setShowDel] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const t = useAsync(list, []);
  const rows = t.data || [];
  return (
    <ContentLayout header={<Header variant="h1">{title}</Header>}>
      {extra}
      <ResourceTable
        resourceName={resourceName}
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy={trackBy}
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        columns={columns}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: deleteLabel }]} onItemClick={() => setShowDel(true)}>Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => setShowCreate(true)}>{createLabel}</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={showDel} resourceType={resourceName.toLowerCase()} names={sel.map((r) => r[trackBy])} confirmText="delete" onDismiss={() => setShowDel(false)}
        onConfirm={async () => { for (const r of sel) await del(r[trackBy]); notify.success(`${sel.length} deleted.`); setSel([]); t.reload(); }} />
      {showCreate && <CreateForm onDismiss={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); t.reload(); }} create={create} notify={notify} />}
    </ContentLayout>
  );
}

function SimpleCreateModal({ header, fields, onDismiss, onCreated, create, notify, successText }) {
  const [values, setValues] = useState(Object.fromEntries(fields.map((f) => [f.key, f.default || ""])));
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try { const r = await create(values); notify.success(successText(r)); onCreated(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  const required = fields.filter((f) => f.required).every((f) => values[f.key]);
  return (
    <Modal visible onDismiss={onDismiss} header={header} footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
      <Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!required} onClick={submit}>Create</Button>
    </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {fields.map((f) => (
          <FormField key={f.key} label={f.label}>
            {f.options ? (
              <Select selectedOption={values[f.key] ? { value: values[f.key], label: values[f.key] } : null} placeholder={f.placeholder}
                options={f.options.map((o) => ({ value: o, label: o }))} onChange={({ detail }) => setValues((v) => ({ ...v, [f.key]: detail.selectedOption.value }))} />
            ) : (
              <Input value={values[f.key]} placeholder={f.placeholder} onChange={({ detail }) => setValues((v) => ({ ...v, [f.key]: detail.value }))} />
            )}
          </FormField>
        ))}
      </SpaceBetween>
    </Modal>
  );
}

export function EgressOnlyInternetGateways() {
  const vpcs = useAsync(() => api.describeVpcs(), []);
  return (
    <ResourceList
      title="Egress-only internet gateways" resourceName="Egress-only internet gateways" trackBy="EgressOnlyInternetGatewayId"
      list={() => api.describeEgressOnlyInternetGateways()} del={api.deleteEgressOnlyInternetGateway}
      createLabel="Create egress-only internet gateway" deleteLabel="Delete egress-only internet gateway"
      columns={[
        { id: "name", header: "Name", isRowHeader: true, cell: (g) => g.Tags?.Name || "-" },
        { id: "id", header: "Egress-only internet gateway ID", cell: (g) => g.EgressOnlyInternetGatewayId },
        { id: "state", header: "State", cell: (g) => g.Attachments?.[0]?.State || "detached" },
        { id: "vpc", header: "VPC", cell: (g) => g.Attachments?.[0]?.VpcId || "-" },
      ]}
      CreateForm={({ onDismiss, onCreated, notify }) => (
        <SimpleCreateModal header="Create egress-only internet gateway" onDismiss={onDismiss} onCreated={onCreated} notify={notify}
          fields={[{ key: "vpcId", label: "VPC", required: true, placeholder: "Select a VPC", options: (vpcs.data || []).map((v) => v.VpcId) }]}
          create={(v) => api.createEgressOnlyInternetGateway(v.vpcId)} successText={(g) => `Egress-only internet gateway "${g.EgressOnlyInternetGatewayId}" created.`} />
      )}
    />
  );
}

function DnsResolutionTester() {
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const [vpcId, setVpcId] = useState("");
  const [result, setResult] = useState(null);
  const [reach, setReach] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setReach(null);
    try {
      const r = await api.describeVpcDnsResolution(vpcId);
      setResult(r);
      if (r.dnsSupportEnabled !== false && r.DnsServers?.length) {
        const rr = await api.analyzeReachability({ ip: (vpcs.data || []).find((v) => v.VpcId === vpcId)?.CidrBlock?.replace(/0\/\d+$/, "10") }, { ip: r.DnsServers[0] }, 53, "udp");
        setReach(rr);
      }
    } finally { setBusy(false); }
  };
  return (
    <Box padding={{ bottom: "l" }}>
      <Header variant="h2" description="The resolver address(es) instances in this VPC actually get, computed live from its DHCP option set + enableDnsSupport attribute — not a stored value.">Test DNS resolution</Header>
      <SpaceBetween direction="horizontal" size="xs" alignItems="center">
        <Select selectedOption={vpcId ? { value: vpcId, label: vpcId } : null} placeholder="Select a VPC"
          options={(vpcs.data || []).map((v) => ({ value: v.VpcId, label: v.VpcId }))} onChange={({ detail }) => { setVpcId(detail.selectedOption.value); setResult(null); }} />
        <Button disabled={!vpcId} loading={busy} onClick={run}>Test</Button>
      </SpaceBetween>
      {result && (
        <Box padding={{ top: "s" }}>
          <div>DNS support enabled: <b>{String(result.DnsSupportEnabled)}</b></div>
          <div>Amazon-provided DNS: <b>{String(result.AmazonProvidedDns)}</b></div>
          <div>Domain name: <b>{result.DomainName || "-"}</b></div>
          <div>Effective DNS server(s): <b>{result.DnsServers.join(", ") || "none (DNS support disabled)"}</b></div>
          {reach && <div>A representative instance in this VPC reaching that resolver on port 53: <b>{reach.reachable ? "Reachable" : `Blocked — ${reach.reason}`}</b></div>}
        </Box>
      )}
    </Box>
  );
}

export function DhcpOptionSets() {
  return (
    <ResourceList
      title="DHCP option sets" resourceName="DHCP option sets" trackBy="DhcpOptionsId"
      list={() => api.describeDhcpOptions()} del={api.deleteDhcpOptions}
      createLabel="Create DHCP option set" deleteLabel="Delete DHCP option set"
      extra={<DnsResolutionTester />}
      columns={[
        { id: "name", header: "Name", isRowHeader: true, cell: (d) => d.Tags?.Name || "-" },
        { id: "id", header: "DHCP options set ID", cell: (d) => d.DhcpOptionsId },
        { id: "domain", header: "Domain name", cell: (d) => d.DhcpConfigurations.find((c) => c.Key === "domain-name")?.Values.join(", ") || "-" },
        { id: "dns", header: "Domain name servers", cell: (d) => d.DhcpConfigurations.find((c) => c.Key === "domain-name-servers")?.Values.join(", ") || "-" },
      ]}
      CreateForm={({ onDismiss, onCreated, notify }) => (
        <SimpleCreateModal header="Create DHCP option set" onDismiss={onDismiss} onCreated={onCreated} notify={notify}
          fields={[{ key: "domain", label: "Domain name", placeholder: "example.internal" }, { key: "servers", label: "Domain name servers", placeholder: "10.0.0.2" }]}
          create={(v) => api.createDhcpOptions([{ Key: "domain-name", Values: [v.domain] }, { Key: "domain-name-servers", Values: [v.servers || "AmazonProvidedDNS"] }])}
          successText={(d) => `DHCP option set "${d.DhcpOptionsId}" created.`} />
      )}
    />
  );
}

export function ManagedPrefixLists() {
  return (
    <ResourceList
      title="Managed prefix lists" resourceName="Managed prefix lists" trackBy="PrefixListId"
      list={() => api.describeManagedPrefixLists()} del={api.deleteManagedPrefixList}
      createLabel="Create prefix list" deleteLabel="Delete prefix list"
      columns={[
        { id: "name", header: "Name", isRowHeader: true, cell: (p) => p.PrefixListName },
        { id: "id", header: "Prefix list ID", cell: (p) => p.PrefixListId },
        { id: "family", header: "Address family", cell: (p) => p.AddressFamily },
        { id: "max", header: "Max entries", cell: (p) => p.MaxEntries },
        { id: "state", header: "State", cell: (p) => p.State },
        { id: "owner", header: "Owner ID", cell: (p) => p.OwnerId },
      ]}
      CreateForm={({ onDismiss, onCreated, notify }) => (
        <SimpleCreateModal header="Create prefix list" onDismiss={onDismiss} onCreated={onCreated} notify={notify}
          fields={[{ key: "name", label: "Prefix list name", required: true, placeholder: "my-prefix-list" }, { key: "maxEntries", label: "Max entries", default: "10", placeholder: "10" }, { key: "cidr", label: "First entry — CIDR", placeholder: "10.0.0.0/16" }]}
          create={(v) => api.createManagedPrefixList(v.name, Number(v.maxEntries) || 10, "IPv4", v.cidr ? [{ Cidr: v.cidr }] : [])}
          successText={(p) => `Prefix list "${p.PrefixListName}" created.`} />
      )}
    />
  );
}

export function PeeringConnections() {
  const vpcs = useAsync(() => api.describeVpcs(), []);
  return (
    <ResourceList
      title="Peering connections" resourceName="Peering connections" trackBy="VpcPeeringConnectionId"
      list={() => api.describeVpcPeeringConnections()} del={api.deleteVpcPeeringConnection}
      createLabel="Create peering connection" deleteLabel="Delete peering connection"
      columns={[
        { id: "id", header: "Peering connection ID", cell: (p) => p.VpcPeeringConnectionId },
        { id: "status", header: "Status", cell: (p) => p.Status },
        { id: "req", header: "Requester VPC", cell: (p) => p.RequesterVpcId },
        { id: "acc", header: "Accepter VPC", cell: (p) => p.AccepterVpcId },
      ]}
      CreateForm={({ onDismiss, onCreated, notify }) => (
        <SimpleCreateModal header="Create peering connection" onDismiss={onDismiss} onCreated={onCreated} notify={notify}
          fields={[
            { key: "vpcId", label: "VPC (Requester)", required: true, placeholder: "Select a VPC", options: (vpcs.data || []).map((v) => v.VpcId) },
            { key: "peerVpcId", label: "VPC (Accepter)", required: true, placeholder: "Select a VPC", options: (vpcs.data || []).map((v) => v.VpcId) },
          ]}
          create={(v) => api.createVpcPeeringConnection(v.vpcId, v.peerVpcId)} successText={(p) => `Peering connection "${p.VpcPeeringConnectionId}" requested.`} />
      )}
    />
  );
}

export function RouteServers() {
  return (
    <ResourceList
      title="Route servers" resourceName="Route servers" trackBy="RouteServerId"
      list={() => api.describeRouteServers()} del={api.deleteRouteServer}
      createLabel="Create route server" deleteLabel="Delete route server"
      columns={[
        { id: "id", header: "Route server ID", cell: (r) => r.RouteServerId },
        { id: "asn", header: "Amazon side ASN", cell: (r) => r.AmazonSideAsn },
        { id: "state", header: "State", cell: (r) => r.State },
      ]}
      CreateForm={({ onDismiss, onCreated, notify }) => (
        <SimpleCreateModal header="Create route server" onDismiss={onDismiss} onCreated={onCreated} notify={notify}
          fields={[{ key: "asn", label: "Amazon side ASN", default: "64512", placeholder: "64512" }]}
          create={(v) => api.createRouteServer(Number(v.asn) || 64512)} successText={(r) => `Route server "${r.RouteServerId}" created.`} />
      )}
    />
  );
}

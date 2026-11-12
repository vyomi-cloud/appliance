/* PrivateLink: VPC endpoints + endpoint services. Gateway endpoints (S3/DynamoDB) get a REAL
 * route (dest = the service's prefix-list CIDRs, target = the vpce- id) added to every chosen
 * route table — core/netsim's GATEWAY_ENDPOINT route kind makes Reachability Analyzer (and the
 * offline packet enforcer) honor it. Interface endpoints get a real ENI + private DNS name but
 * no L7 proxying to a real target service (see aws.vpc.privatelink's limitations). */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Multiselect from "@cloudscape-design/components/multiselect";
import Table from "@cloudscape-design/components/table";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const SERVICES = [
  { value: "com.amazonaws.us-east-1.s3", label: "com.amazonaws.us-east-1.s3", type: "Gateway" },
  { value: "com.amazonaws.us-east-1.dynamodb", label: "com.amazonaws.us-east-1.dynamodb", type: "Gateway" },
  { value: "com.amazonaws.us-east-1.ec2", label: "com.amazonaws.us-east-1.ec2", type: "Interface" },
  { value: "com.amazonaws.us-east-1.secretsmanager", label: "com.amazonaws.us-east-1.secretsmanager", type: "Interface" },
];

function CreateEndpointModal({ onDismiss, onCreated }) {
  const notify = useNotify();
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const subnets = useAsync(() => api.describeSubnets(), []);
  const routeTables = useAsync(() => api.describeRouteTables(), []);
  const [serviceName, setServiceName] = useState(SERVICES[0].value);
  const [vpcId, setVpcId] = useState("");
  const [rtIds, setRtIds] = useState([]);
  const [subnetIds, setSubnetIds] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const svc = SERVICES.find((s) => s.value === serviceName) || SERVICES[0];
  const vpcRouteTables = (routeTables.data || []).filter((r) => r.VpcId === vpcId);
  const vpcSubnets = (subnets.data || []).filter((s) => s.VpcId === vpcId);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const ep = await api.createVpcEndpoint(vpcId, serviceName, svc.type, { routeTableIds: rtIds, subnetIds, privateDnsEnabled: svc.type === "Interface" });
      notify.success(`Endpoint "${ep.VpcEndpointId}" created.`);
      onCreated();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible onDismiss={onDismiss} size="large" header="Create endpoint"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button formAction="none" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!vpcId || (svc.type === "Gateway" ? !rtIds.length : !subnetIds.length)} onClick={submit}>Create endpoint</Button>
      </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="l">
          <FormField label="Service category"><RadioGroup value={svc.type} readOnly items={[{ value: "Gateway", label: "AWS services (Gateway)" }, { value: "Interface", label: "AWS services (Interface)" }]} /></FormField>
          <FormField label="Service name">
            <Select selectedOption={{ value: serviceName, label: serviceName }} options={SERVICES.map((s) => ({ value: s.value, label: s.value }))}
              onChange={({ detail }) => setServiceName(detail.selectedOption.value)} />
          </FormField>
          <FormField label="VPC">
            <Select selectedOption={vpcId ? { value: vpcId, label: vpcId } : null} placeholder="Select a VPC"
              options={(vpcs.data || []).map((v) => ({ value: v.VpcId, label: v.VpcId }))} onChange={({ detail }) => { setVpcId(detail.selectedOption.value); setRtIds([]); setSubnetIds([]); }} />
          </FormField>
          {svc.type === "Gateway" ? (
            <FormField label="Route tables" description="Vyomi adds a real route (dest = the service's address ranges, target = this endpoint) to each chosen table.">
              <Multiselect selectedOptions={rtIds.map((id) => ({ value: id, label: id }))} placeholder="Select route tables" disabled={!vpcId}
                options={vpcRouteTables.map((r) => ({ value: r.RouteTableId, label: r.RouteTableId }))}
                onChange={({ detail }) => setRtIds(detail.selectedOptions.map((o) => o.value))} />
            </FormField>
          ) : (
            <FormField label="Subnets" description="Vyomi creates a real ENI in each chosen subnet.">
              <Multiselect selectedOptions={subnetIds.map((id) => ({ value: id, label: id }))} placeholder="Select subnets" disabled={!vpcId}
                options={vpcSubnets.map((s) => ({ value: s.SubnetId, label: s.SubnetId }))}
                onChange={({ detail }) => setSubnetIds(detail.selectedOptions.map((o) => o.value))} />
            </FormField>
          )}
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

export function Endpoints() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeVpcEndpoints(), []);
  const rows = t.data || [];
  return (
    <ContentLayout header={<Header variant="h1">Endpoints</Header>}>
      <CapabilityContainer id="aws.vpc.privatelink" title="Endpoints" counter={`(${rows.length})`}>
        <ResourceTable
          resourceName="Endpoints" items={rows} loading={t.loading} error={t.error} onRefresh={t.reload}
          trackBy="VpcEndpointId" selectionType="multi" selectedItems={sel} onSelectionChange={setSel}
          empty={<Box textAlign="center">No endpoints found</Box>}
          columns={[
            { id: "id", header: "Endpoint ID", isRowHeader: true, cell: (e) => e.VpcEndpointId },
            { id: "type", header: "Type", cell: (e) => e.VpcEndpointType },
            { id: "service", header: "Service name", cell: (e) => e.ServiceName },
            { id: "state", header: "State", cell: (e) => e.State },
            { id: "vpc", header: "VPC", cell: (e) => <Link href={href("vpc", "vpcs", e.VpcId)} onFollow={follow}>{e.VpcId}</Link> },
            { id: "dns", header: "DNS names", cell: (e) => e.DnsEntries?.join(", ") || "-" },
            { id: "created", header: "Created", cell: (e) => e.CreationTimestamp },
          ]}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: "Delete VPC endpoints" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>
              <Button variant="primary" onClick={() => setCreate(true)}>Create endpoint</Button>
            </SpaceBetween>
          }
        />
      </CapabilityContainer>
      <DeleteModal visible={del} resourceType="endpoint" names={sel.map((e) => e.VpcEndpointId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteVpcEndpoints(sel.map((e) => e.VpcEndpointId)); notify.success(`${sel.length} endpoint(s) deleted.`); setSel([]); t.reload(); }} />
      {create && <CreateEndpointModal onDismiss={() => setCreate(false)} onCreated={() => { setCreate(false); t.reload(); }} />}
    </ContentLayout>
  );
}

function CreateEndpointServiceModal({ onDismiss, onCreated }) {
  const notify = useNotify();
  const [nlbArn, setNlbArn] = useState("");
  const [acceptanceRequired, setAcceptanceRequired] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const svc = await api.createVpcEndpointServiceConfiguration([nlbArn], acceptanceRequired);
      notify.success(`Endpoint service "${svc.ServiceId}" created.`); onCreated();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible onDismiss={onDismiss} header="Create endpoint service"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button formAction="none" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!nlbArn} onClick={submit}>Create endpoint service</Button>
      </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="l">
          <FormField label="Load balancer type"><RadioGroup value="Network" readOnly items={[{ value: "Network", label: "Network" }, { value: "Gateway Load Balancer", label: "Gateway Load Balancer" }]} /></FormField>
          <FormField label="Load balancer ARN"><Input value={nlbArn} placeholder="arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/abc" onChange={({ detail }) => setNlbArn(detail.value)} /></FormField>
          <FormField label="Require acceptance for endpoint"><RadioGroup value={String(acceptanceRequired)} onChange={({ detail }) => setAcceptanceRequired(detail.value === "true")}
            items={[{ value: "true", label: "Require acceptance" }, { value: "false", label: "Acceptance not required" }]} /></FormField>
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

function EndpointServiceDetail({ service, onClose, reload }) {
  const notify = useNotify();
  const conns = useAsync(() => api.describeVpcEndpointConnections(), [service.ServiceId]);
  const rows = (conns.data || []).filter((c) => c.ServiceId === service.ServiceId);
  const [principal, setPrincipal] = useState("");
  return (
    <Box padding="l">
      <SpaceBetween size="l">
        <Header variant="h3" actions={<Button onClick={onClose}>Close</Button>}>{service.ServiceName}</Header>
        <Tabs tabs={[
          { id: "conn", label: "Endpoint connections", content: (
            <Table items={rows} columnDefinitions={[
              { id: "ep", header: "Endpoint ID", cell: (c) => c.VpcEndpointId },
              { id: "state", header: "State", cell: (c) => c.VpcEndpointState },
            ]} empty={<Box textAlign="center" color="inherit">No connections</Box>}
            footer={rows.filter((c) => c.VpcEndpointState === "pendingAcceptance").length > 0 && (
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={async () => { await api.acceptVpcEndpointConnections(service.ServiceId, rows.filter((c) => c.VpcEndpointState === "pendingAcceptance").map((c) => c.VpcEndpointId)); notify.success("Connection(s) accepted."); conns.reload(); reload(); }}>Accept</Button>
                <Button onClick={async () => { await api.rejectVpcEndpointConnections(service.ServiceId, rows.filter((c) => c.VpcEndpointState === "pendingAcceptance").map((c) => c.VpcEndpointId)); notify.success("Connection(s) rejected."); conns.reload(); reload(); }}>Reject</Button>
              </SpaceBetween>
            )} />
          ) },
          { id: "perm", label: "Allowed principals", content: (
            <SpaceBetween size="m">
              <Table items={(service.AllowedPrincipals || []).map((p) => ({ p }))} columnDefinitions={[{ id: "p", header: "Principal", cell: (r) => r.p }]}
                empty={<Box textAlign="center" color="inherit">No allowed principals</Box>} />
              <SpaceBetween direction="horizontal" size="xs">
                <Input value={principal} placeholder="123456789012" onChange={({ detail }) => setPrincipal(detail.value)} />
                <Button disabled={!principal} onClick={async () => { await api.modifyVpcEndpointServicePermissions(service.ServiceId, [principal], []); notify.success("Principal allowed."); setPrincipal(""); reload(); }}>Allow principal</Button>
              </SpaceBetween>
            </SpaceBetween>
          ) },
        ]} />
      </SpaceBetween>
    </Box>
  );
}

export function EndpointServices() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const [detail, setDetail] = useState(null);
  const t = useAsync(() => api.describeVpcEndpointServiceConfigurations(), []);
  const rows = t.data || [];
  return (
    <ContentLayout header={<Header variant="h1">Endpoint services</Header>}>
      <CapabilityContainer id="aws.vpc.privatelink" title="Endpoint services" counter={`(${rows.length})`}>
        <SpaceBetween size="l">
          <ResourceTable
            resourceName="Endpoint services" items={rows} loading={t.loading} error={t.error} onRefresh={t.reload}
            trackBy="ServiceId" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
            empty={<Box textAlign="center">No endpoint services found</Box>}
            columns={[
              { id: "id", header: "Service ID", isRowHeader: true, cell: (s) => <Link onFollow={(e) => { e.preventDefault(); setDetail(s); }} href="#">{s.ServiceId}</Link> },
              { id: "name", header: "Service name", cell: (s) => s.ServiceName },
              { id: "state", header: "State", cell: (s) => s.ServiceState },
              { id: "accept", header: "Acceptance required", cell: (s) => String(s.AcceptanceRequired) },
            ]}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: "Delete" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>
                <Button variant="primary" onClick={() => setCreate(true)}>Create endpoint service</Button>
              </SpaceBetween>
            }
          />
          {detail && <EndpointServiceDetail service={rows.find((s) => s.ServiceId === detail.ServiceId) || detail} onClose={() => setDetail(null)} reload={t.reload} />}
        </SpaceBetween>
      </CapabilityContainer>
      <DeleteModal visible={del} resourceType="endpoint service" names={sel.map((s) => s.ServiceId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteVpcEndpointServiceConfigurations(sel.map((s) => s.ServiceId)); notify.success(`${sel.length} endpoint service(s) deleted.`); setSel([]); t.reload(); }} />
      {create && <CreateEndpointServiceModal onDismiss={() => setCreate(false)} onCreated={() => { setCreate(false); t.reload(); }} />}
    </ContentLayout>
  );
}

export function PrivatelinkGettingStarted() {
  return (
    <ContentLayout header={<Header variant="h1">Getting started</Header>}>
      <Box variant="p">PrivateLink lets resources in your VPC reach AWS services (and services you share with other VPCs) without traversing the internet.</Box>
      <SpaceBetween size="s">
        <Link href={href("vpc", "endpoints")} onFollow={follow}>Create a VPC endpoint</Link>
        <Link href={href("vpc", "endpoint-services")} onFollow={follow}>Create an endpoint service</Link>
      </SpaceBetween>
    </ContentLayout>
  );
}

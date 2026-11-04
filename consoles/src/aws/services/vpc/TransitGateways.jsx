/* Transit gateways, attachments and TGW route tables (static + propagated routes, associations,
 * propagations) over the native EC2 Query wire. Forwarding is evaluated by the Reachability Analyzer. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Multiselect from "@cloudscape-design/components/multiselect";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

function FormModal({ header, submit, children, onDismiss, onDone, valid = true, label = "Create" }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const go = async () => { setBusy(true); setErr(null); try { await submit(); onDone(); onDismiss(); } catch (e) { setErr(e); notify.error?.(e); } finally { setBusy(false); } };
  return (
    <Modal visible onDismiss={onDismiss} header={header}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!valid} onClick={go}>{label}</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">{err && <ErrorAlert error={err} />}{children}</SpaceBetween>
    </Modal>
  );
}

const opt = (v, label) => (v ? { value: v, label: label || v } : null);

export function TransitGateways() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const [desc, setDesc] = useState(""); const [asn, setAsn] = useState("64512");
  const t = useAsync(() => api.describeTransitGateways(), []);
  return (
    <ContentLayout header={<Header variant="h1">Transit gateways</Header>}>
      <ResourceTable resourceName="Transit gateways" description={<CapabilityBadge id="aws.vpc.transit-gateway" />} items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload}
        trackBy="TransitGatewayId" selectionType="multi" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Search"
        empty={<Box textAlign="center">No transit gateways found</Box>}
        columns={[
          { id: "id", header: "Transit gateway ID", isRowHeader: true, cell: (g) => g.TransitGatewayId },
          { id: "state", header: "State", cell: (g) => g.State },
          { id: "desc", header: "Description", cell: (g) => g.Description || "-" },
          { id: "asn", header: "Amazon ASN", cell: (g) => g.AmazonSideAsn },
          { id: "assoc", header: "Association route table ID", cell: (g) => <Link href={href("vpc", "transit-gateway-route-tables", g.AssociationDefaultRouteTableId || "-")} onFollow={follow}>{g.AssociationDefaultRouteTableId || "-"}</Link> },
          { id: "prop", header: "Propagation route table ID", cell: (g) => g.PropagationDefaultRouteTableId || "-" },
          { id: "dns", header: "DNS support", cell: (g) => g.DnsSupport },
          { id: "created", header: "Creation time", cell: (g) => g.CreationTime },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete transit gateway</Button>
          <Button variant="primary" onClick={() => setCreate(true)}>Create transit gateway</Button></SpaceBetween>} />
      <DeleteModal visible={del} resourceType="transit gateway" names={sel.map((g) => g.TransitGatewayId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { try { for (const g of sel) await api.deleteTransitGateway(g.TransitGatewayId); notify.success("Transit gateway deleted."); } catch (e) { notify.error(e); } setSel([]); t.reload(); }} />
      {create && <FormModal header="Create transit gateway" onDismiss={() => setCreate(false)} onDone={t.reload} submit={() => api.createTransitGateway(desc, asn)}>
        <FormField label="Description - optional"><Input value={desc} onChange={({ detail }) => setDesc(detail.value)} ariaLabel="Description" /></FormField>
        <FormField label="Amazon side ASN"><Input value={asn} onChange={({ detail }) => setAsn(detail.value)} ariaLabel="Amazon side ASN" /></FormField>
      </FormModal>}
    </ContentLayout>
  );
}

export function TransitGatewayAttachments() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const [tgw, setTgw] = useState(null); const [vpc, setVpc] = useState(null); const [subs, setSubs] = useState([]);
  const t = useAsync(() => api.describeTransitGatewayAttachments(), []);
  const tgws = useAsync(() => api.describeTransitGateways(), []);
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const subnets = useAsync(() => api.describeSubnets(), []);
  return (
    <ContentLayout header={<Header variant="h1">Transit gateway attachments</Header>}>
      <ResourceTable resourceName="Transit gateway attachments" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload}
        trackBy="AttachmentId" selectionType="multi" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Search"
        empty={<Box textAlign="center">No transit gateway attachments found</Box>}
        columns={[
          { id: "id", header: "Transit gateway attachment ID", isRowHeader: true, cell: (a) => a.AttachmentId },
          { id: "tgw", header: "Transit gateway ID", cell: (a) => a.TransitGatewayId },
          { id: "type", header: "Resource type", cell: (a) => (a.ResourceType === "vpc" ? "VPC" : a.ResourceType) },
          { id: "res", header: "Resource ID", cell: (a) => a.ResourceId },
          { id: "state", header: "State", cell: (a) => a.State },
          { id: "rt", header: "Association route table ID", cell: (a) => a.AssociatedRouteTableId || "-" },
          { id: "created", header: "Creation time", cell: (a) => a.CreationTime },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
          <Button variant="primary" onClick={() => setCreate(true)}>Create transit gateway attachment</Button></SpaceBetween>} />
      <DeleteModal visible={del} resourceType="attachment" names={sel.map((a) => a.AttachmentId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { try { for (const a of sel) await api.deleteTransitGatewayVpcAttachment(a.AttachmentId); notify.success("Attachment deleted."); } catch (e) { notify.error(e); } setSel([]); t.reload(); }} />
      {create && <FormModal header="Create transit gateway attachment" onDismiss={() => setCreate(false)} onDone={t.reload} valid={!!(tgw && vpc && subs.length)}
        submit={() => api.createTransitGatewayVpcAttachment(tgw.value, vpc.value, subs.map((s) => s.value))}>
        <FormField label="Transit gateway ID"><Select selectedOption={tgw} onChange={({ detail }) => setTgw(detail.selectedOption)} placeholder="Select a transit gateway" options={(tgws.data || []).map((g) => opt(g.TransitGatewayId))} ariaLabel="Transit gateway ID" /></FormField>
        <FormField label="Attachment type"><Select selectedOption={opt("vpc", "VPC")} options={[opt("vpc", "VPC")]} ariaLabel="Attachment type" /></FormField>
        <FormField label="VPC ID"><Select selectedOption={vpc} onChange={({ detail }) => { setVpc(detail.selectedOption); setSubs([]); }} placeholder="Select a VPC" options={(vpcs.data || []).map((v) => opt(v.VpcId))} ariaLabel="VPC ID" /></FormField>
        <FormField label="Subnet IDs"><Multiselect selectedOptions={subs} onChange={({ detail }) => setSubs(detail.selectedOptions)} placeholder="Select subnets" disabled={!vpc} options={(subnets.data || []).filter((s) => s.VpcId === vpc?.value).map((s) => opt(s.SubnetId))} ariaLabel="Subnet IDs" /></FormField>
      </FormModal>}
    </ContentLayout>
  );
}

export function TransitGatewayRouteTables() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const [tgw, setTgw] = useState(null);
  const t = useAsync(() => api.describeTransitGatewayRouteTables(), []);
  const tgws = useAsync(() => api.describeTransitGateways(), []);
  return (
    <ContentLayout header={<Header variant="h1">Transit gateway route tables</Header>}>
      <ResourceTable resourceName="Transit gateway route tables" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload}
        trackBy="RouteTableId" selectionType="multi" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Search"
        empty={<Box textAlign="center">No transit gateway route tables found</Box>}
        columns={[
          { id: "id", header: "Transit gateway route table ID", isRowHeader: true, cell: (r) => <Link href={href("vpc", "transit-gateway-route-tables", r.RouteTableId)} onFollow={follow}>{r.RouteTableId}</Link> },
          { id: "tgw", header: "Transit gateway ID", cell: (r) => r.TransitGatewayId },
          { id: "state", header: "State", cell: (r) => r.State },
          { id: "da", header: "Default association route table", cell: (r) => (r.DefaultAssociation ? "Yes" : "No") },
          { id: "dp", header: "Default propagation route table", cell: (r) => (r.DefaultPropagation ? "Yes" : "No") },
          { id: "created", header: "Creation time", cell: (r) => r.CreationTime },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
          <Button variant="primary" onClick={() => setCreate(true)}>Create transit gateway route table</Button></SpaceBetween>} />
      <DeleteModal visible={del} resourceType="route table" names={sel.map((r) => r.RouteTableId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { try { for (const r of sel) await api.deleteTransitGatewayRouteTable(r.RouteTableId); notify.success("Route table deleted."); } catch (e) { notify.error(e); } setSel([]); t.reload(); }} />
      {create && <FormModal header="Create transit gateway route table" onDismiss={() => setCreate(false)} onDone={t.reload} valid={!!tgw} submit={() => api.createTransitGatewayRouteTable(tgw.value)}>
        <FormField label="Transit gateway ID"><Select selectedOption={tgw} onChange={({ detail }) => setTgw(detail.selectedOption)} placeholder="Select a transit gateway" options={(tgws.data || []).map((g) => opt(g.TransitGatewayId))} ariaLabel="Transit gateway ID" /></FormField>
      </FormModal>}
    </ContentLayout>
  );
}

function AttachmentAction({ label, header, rtId, atts, onRun, onDone }) {
  const [open, setOpen] = useState(false); const [att, setAtt] = useState(null);
  return (
    <>
      <Button onClick={() => setOpen(true)}>{label}</Button>
      {open && <FormModal header={header} label={label} valid={!!att} onDismiss={() => setOpen(false)} onDone={onDone} submit={() => onRun(rtId, att.value)}>
        <FormField label="Transit gateway attachment ID"><Select selectedOption={att} onChange={({ detail }) => setAtt(detail.selectedOption)} placeholder="Select an attachment" options={atts.map((a) => opt(a.AttachmentId, `${a.AttachmentId} (${a.ResourceId})`))} ariaLabel="Transit gateway attachment ID" /></FormField>
      </FormModal>}
    </>
  );
}

export function TransitGatewayRouteTableDetail({ params }) {
  const notify = useNotify();
  const id = params.id;
  const rt = useAsync(() => api.describeTransitGatewayRouteTables().then((xs) => xs.find((x) => x.RouteTableId === id)), [id]);
  const routes = useAsync(() => api.searchTransitGatewayRoutes(id), [id]);
  const assocs = useAsync(() => api.getTransitGatewayRouteTableAssociations(id), [id]);
  const props = useAsync(() => api.getTransitGatewayRouteTablePropagations(id), [id]);
  const allAtts = useAsync(() => api.describeTransitGatewayAttachments(), []);
  const [newRoute, setNewRoute] = useState(false); const [cidr, setCidr] = useState(""); const [attSel, setAttSel] = useState(null);
  const [selRoute, setSelRoute] = useState([]); const [selA, setSelA] = useState([]); const [selP, setSelP] = useState([]);
  if (!rt.data && !rt.loading) return <ErrorAlert error={{ message: "Transit gateway route table not found" }} />;
  const atts = (allAtts.data || []).filter((a) => a.TransitGatewayId === rt.data?.TransitGatewayId);
  const all = () => { routes.reload(); assocs.reload(); props.reload(); allAtts.reload(); };
  const run = async (fn, msg) => { try { await fn(); notify.success(msg); } catch (e) { notify.error(e); } all(); };
  return (
    <ContentLayout header={<Header variant="h1">{id}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={3} items={[["Transit gateway route table ID", id], ["Transit gateway ID", rt.data?.TransitGatewayId], ["State", rt.data?.State], ["Default association route table", rt.data?.DefaultAssociation ? "Yes" : "No"], ["Default propagation route table", rt.data?.DefaultPropagation ? "Yes" : "No"], ["Creation time", rt.data?.CreationTime]]} />
        <Tabs tabs={[
          { id: "routes", label: "Routes", content: (
            <Table variant="container" items={routes.data || []} loading={routes.loading} selectionType="single" selectedItems={selRoute} onSelectionChange={({ detail }) => setSelRoute(detail.selectedItems)} trackBy="Cidr"
              header={<Header variant="h2" counter={`(${(routes.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
                <Button disabled={selRoute.length !== 1 || selRoute[0]?.Type !== "static"} onClick={() => run(() => api.deleteTransitGatewayRoute(id, selRoute[0].Cidr).then(() => setSelRoute([])), "Route deleted.")}>Delete static route</Button>
                <Button variant="primary" onClick={() => setNewRoute(true)}>Create static route</Button></SpaceBetween>}>Routes</Header>}
              columnDefinitions={[{ id: "c", header: "CIDR", cell: (r) => r.Cidr }, { id: "a", header: "Attachment ID", cell: (r) => r.AttachmentId || "-" }, { id: "r", header: "Resource ID", cell: (r) => r.ResourceId || "-" },
                { id: "t", header: "Route type", cell: (r) => r.Type }, { id: "s", header: "Route state", cell: (r) => r.State }]}
              empty={<Box textAlign="center" color="inherit">No routes</Box>} />) },
          { id: "assoc", label: "Associations", content: (
            <Table variant="container" items={assocs.data || []} loading={assocs.loading} selectionType="single" selectedItems={selA} onSelectionChange={({ detail }) => setSelA(detail.selectedItems)} trackBy="AttachmentId"
              header={<Header variant="h2" counter={`(${(assocs.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
                <Button disabled={selA.length !== 1} onClick={() => run(() => api.disassociateTransitGatewayRouteTable(id, selA[0].AttachmentId).then(() => setSelA([])), "Association removed.")}>Delete association</Button>
                <AttachmentAction label="Create association" header="Create association" rtId={id} atts={atts.filter((a) => !a.AssociatedRouteTableId)} onRun={api.associateTransitGatewayRouteTable} onDone={all} /></SpaceBetween>}>Associations</Header>}
              columnDefinitions={[{ id: "a", header: "Attachment ID", cell: (r) => r.AttachmentId }, { id: "r", header: "Resource ID", cell: (r) => r.ResourceId }, { id: "s", header: "Association state", cell: (r) => r.State }]}
              empty={<Box textAlign="center" color="inherit">No associations</Box>} />) },
          { id: "prop", label: "Propagations", content: (
            <Table variant="container" items={props.data || []} loading={props.loading} selectionType="single" selectedItems={selP} onSelectionChange={({ detail }) => setSelP(detail.selectedItems)} trackBy="AttachmentId"
              header={<Header variant="h2" counter={`(${(props.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
                <Button disabled={selP.length !== 1} onClick={() => run(() => api.disableTransitGatewayRouteTablePropagation(id, selP[0].AttachmentId).then(() => setSelP([])), "Propagation disabled.")}>Disable propagation</Button>
                <AttachmentAction label="Create propagation" header="Create propagation" rtId={id} atts={atts.filter((a) => !(props.data || []).some((p) => p.AttachmentId === a.AttachmentId))} onRun={api.enableTransitGatewayRouteTablePropagation} onDone={all} /></SpaceBetween>}>Propagations</Header>}
              columnDefinitions={[{ id: "a", header: "Attachment ID", cell: (r) => r.AttachmentId }, { id: "r", header: "Resource ID", cell: (r) => r.ResourceId }, { id: "s", header: "Propagation state", cell: (r) => r.State }]}
              empty={<Box textAlign="center" color="inherit">No propagations</Box>} />) },
        ]} />
      </SpaceBetween>
      {newRoute && <FormModal header="Create static route" valid={!!cidr && !!attSel} onDismiss={() => setNewRoute(false)} onDone={all}
        submit={() => (attSel.value === "blackhole" ? api.createTransitGatewayRoute(id, cidr, "", true) : api.createTransitGatewayRoute(id, cidr, attSel.value, false))}>
        <FormField label="CIDR"><Input value={cidr} onChange={({ detail }) => setCidr(detail.value)} ariaLabel="CIDR" placeholder="10.0.0.0/16" /></FormField>
        <FormField label="Type"><Select selectedOption={attSel} onChange={({ detail }) => setAttSel(detail.selectedOption)} placeholder="Choose attachment or blackhole" ariaLabel="Route target"
          options={[opt("blackhole", "Blackhole"), ...atts.map((a) => opt(a.AttachmentId, `${a.AttachmentId} (${a.ResourceId})`))]} /></FormField>
      </FormModal>}
    </ContentLayout>
  );
}

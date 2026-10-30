import { useState } from "react";
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
import { TagsModal } from "./Vpcs.jsx";
import { TAG_I18N } from "./tagI18n.js";
import * as api from "./api.js";

const subnetAssoc = (rt) => (rt.Associations || []).filter((a) => a.SubnetId);
const mainAssoc = (rt) => (rt.Associations || []).find((a) => a.Main);

export function RouteTables() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [tags, setTags] = useState(null);
  const t = useAsync(() => api.describeRouteTables(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Route tables</Header>}>
      <ResourceTable
        resourceName="Route tables"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="RouteTableId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={<Box textAlign="center">No route tables found</Box>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (r) => r.Tags?.Name || "-" },
          { id: "id", header: "Route table ID", cell: (r) => <Link href={href("vpc", "route-tables", r.RouteTableId)} onFollow={follow}>{r.RouteTableId}</Link> },
          { id: "explicit", header: "Explicit subnet associations", cell: (r) => subnetAssoc(r).length },
          { id: "edge", header: "Edge associations", cell: () => 0 },
          { id: "main", header: "Main", cell: (r) => (mainAssoc(r) ? "Yes" : "No") },
          { id: "vpc", header: "VPC", cell: (r) => <Link href={href("vpc", "vpcs", r.VpcId)} onFollow={follow}>{r.VpcId}</Link> },
          { id: "owner", header: "Owner ID", cell: () => "123456789012" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "main", text: "Set main route table", disabled: sel.length !== 1 || !!mainAssoc(sel[0]) },
              { id: "subnets", text: "Edit subnet associations", disabled: sel.length !== 1 },
              { id: "edge", text: "Edit edge associations", disabled: sel.length !== 1 },
              { id: "prop", text: "Edit route propagation", disabled: sel.length !== 1 },
              { id: "routes", text: "Edit routes", disabled: sel.length !== 1 },
              { id: "tags", text: "Manage tags", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete route table" },
            ]} onItemClick={async ({ detail }) => {
              if (detail.id === "routes") navigate("vpc", "route-tables", sel[0].RouteTableId, "edit-routes");
              else if (detail.id === "tags") setTags(sel[0]);
              else if (detail.id === "delete") setDel(true);
              else if (detail.id === "main") { await api.replaceRouteTableAssociation(`rtbassoc-main-${sel[0].VpcId}`, sel[0].RouteTableId); notify.success("Main route table updated."); t.reload(); }
              else if (detail.id === "subnets" || detail.id === "edge" || detail.id === "prop") navigate("vpc", "route-tables", sel[0].RouteTableId);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("vpc", "create-route-table")} onFollow={follow}>Create route table</Button>
          </SpaceBetween>
        }
      />
      <Container><Box variant="p" color="text-body-secondary">Select a route table</Box></Container>
      <DeleteModal visible={del} resourceType="route table" names={sel.map((r) => r.RouteTableId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const r of sel) await api.deleteRouteTable(r.RouteTableId); notify.success(`${sel.length} route table(s) deleted.`); setSel([]); t.reload(); }} />
      {tags && <TagsModal resource={tags} onDismiss={() => setTags(null)} onSaved={() => { setTags(null); t.reload(); }} />}
    </ContentLayout>
  );
}

export function RouteTableDetail({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeRouteTable(params.id), [params.id]);
  const subnets = useAsync(() => api.describeSubnets(), []);
  const [tags, setTags] = useState(false);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Route table not found" }} />;
  const r = t.data;
  const assocSubnetIds = new Set(subnetAssoc(r).map((a) => a.SubnetId));
  const assocRows = (subnets.data || []).filter((s) => assocSubnetIds.has(s.SubnetId));
  const unassocRows = (subnets.data || []).filter((s) => s.VpcId === r.VpcId && !assocSubnetIds.has(s.SubnetId));
  return (
    <ContentLayout header={<Header variant="h1" actions={<ButtonDropdown items={[{ id: "delete", text: "Delete route table" }]} onItemClick={async () => {
      if (confirm(`Delete ${r.RouteTableId}?`)) { await api.deleteRouteTable(r.RouteTableId); notify.success("Route table deleted."); navigate("vpc", "route-tables"); }
    }}>Actions</ButtonDropdown>}>{`${r.RouteTableId} / ${r.Tags?.Name || ""}`}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["Route table ID", r.RouteTableId], ["Main", mainAssoc(r) ? "Yes" : "No"], ["Explicit subnet associations", subnetAssoc(r).length],
          ["Edge associations", 0], ["VPC", r.VpcId], ["Owner ID", "123456789012"],
        ]} />
        <Tabs tabs={[
          { id: "routes", label: "Routes", content: (
            <Table variant="container" items={r.Routes} header={<Header variant="h2" counter={`(${r.Routes.length})`} actions={<Button href={href("vpc", "route-tables", r.RouteTableId, "edit-routes")} onFollow={follow}>Edit routes</Button>}>Routes</Header>}
              columnDefinitions={[
                { id: "d", header: "Destination", cell: (x) => x.DestinationCidrBlock }, { id: "t", header: "Target", cell: (x) => x.GatewayId },
                { id: "s", header: "Status", cell: (x) => x.State }, { id: "p", header: "Propagated", cell: () => "No" }, { id: "o", header: "Route Origin", cell: (x) => (x.GatewayId === "local" ? "CreateVpc" : "CreateRoute") },
              ]} />
          ) },
          { id: "subnets", label: "Subnet associations", content: (
            <SpaceBetween size="l">
              <Table variant="container" items={assocRows} header={<Header variant="h2" actions={<Button onClick={async () => { const id = prompt("Subnet ID to associate:"); if (id) { await api.associateRouteTable(r.RouteTableId, id); notify.success("Subnet associated."); t.reload(); } }}>Edit subnet associations</Button>}>Explicit subnet associations</Header>}
                columnDefinitions={[{ id: "n", header: "Name", cell: (s) => s.Tags?.Name || "-" }, { id: "id", header: "Subnet ID", cell: (s) => s.SubnetId }, { id: "c4", header: "IPv4 CIDR", cell: (s) => s.CidrBlock }, { id: "c6", header: "IPv6 CIDR", cell: () => "-" }]}
                empty={<Box textAlign="center" color="inherit">No explicit subnet associations</Box>} />
              <Table variant="container" items={unassocRows} header={<Header variant="h2">Subnets without explicit associations</Header>}
                columnDefinitions={[{ id: "n", header: "Name", cell: (s) => s.Tags?.Name || "-" }, { id: "id", header: "Subnet ID", cell: (s) => s.SubnetId }, { id: "c4", header: "IPv4 CIDR", cell: (s) => s.CidrBlock }, { id: "c6", header: "IPv6 CIDR", cell: () => "-" }]}
                empty={<Box textAlign="center" color="inherit">None</Box>} />
            </SpaceBetween>
          ) },
          { id: "edge", label: "Edge associations", content: <CapabilityContainer id="aws.vpc.edge-associations" title="Edge associations" /> },
          { id: "prop", label: "Route propagation", content: <CapabilityContainer id="aws.vpc.route-propagation" title="Route propagation" /> },
          { id: "tags", label: "Tags", content: (
            <Table variant="container" items={Object.entries(r.Tags || {}).map(([k, v]) => ({ k, v }))}
              header={<Header variant="h2" counter={`(${Object.keys(r.Tags || {}).length})`} actions={<Button onClick={() => setTags(true)}>Manage tags</Button>}>Tags</Header>}
              columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.k }, { id: "v", header: "Value", cell: (x) => x.v || "-" }]}
              empty={<Box textAlign="center" color="inherit">No tags</Box>} />
          ) },
        ]} />
      </SpaceBetween>
      {tags && <TagsModal resource={r} onDismiss={() => setTags(false)} onSaved={() => { setTags(false); t.reload(); }} />}
    </ContentLayout>
  );
}

export function EditRoutes({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeRouteTable(params.id), [params.id]);
  if (t.loading || !t.data) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  return <EditRoutesForm rt={t.data} />;
}

function EditRoutesForm({ rt }) {
  const notify = useNotify();
  const [rows, setRows] = useState(rt.Routes.filter((r) => r.GatewayId !== "local").map((r) => ({ dest: r.DestinationCidrBlock, target: r.GatewayId, orig: r.DestinationCidrBlock })));
  const [busy, setBusy] = useState(false);
  const update = (i, patch) => setRows((xs) => xs.map((x, idx) => (idx === i ? { ...x, ...patch } : x)));
  const save = async () => {
    setBusy(true);
    try {
      for (const r of rt.Routes) if (r.GatewayId !== "local" && !rows.some((x) => x.orig === r.DestinationCidrBlock)) await api.deleteRoute(rt.RouteTableId, r.DestinationCidrBlock);
      for (const row of rows) { if (row.orig && row.orig !== row.dest) await api.deleteRoute(rt.RouteTableId, row.orig); await api.createRoute(rt.RouteTableId, row.dest, row.target); }
      notify.success("Routes saved."); navigate("vpc", "route-tables", rt.RouteTableId);
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <ContentLayout header={<Header variant="h1">Edit routes</Header>}>
      <Form actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "route-tables", rt.RouteTableId)} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={save}>Save changes</Button>
        </SpaceBetween>
      }>
        <Container header={<Header variant="h2">Edit routes</Header>}>
          <FormField label="Routes" description="Target types: Internet Gateway, NAT Gateway, Instance, Network Interface, local...">
            <Table
              variant="embedded"
              items={rows}
              columnDefinitions={[
                { id: "d", header: "Destination", cell: (row, i) => <Input value={row.dest} onChange={({ detail }) => update(rows.indexOf(row), { dest: detail.value })} ariaLabel="Destination" /> },
                { id: "t", header: "Target", cell: (row) => <Input value={row.target} onChange={({ detail }) => update(rows.indexOf(row), { target: detail.value })} ariaLabel="Target" /> },
                { id: "s", header: "Status", cell: () => "active" }, { id: "p", header: "Propagated", cell: () => "No" }, { id: "o", header: "Route Origin", cell: () => "CreateRoute" },
                { id: "x", header: "", cell: (row) => <Button iconName="close" ariaLabel="Remove" onClick={() => setRows((xs) => xs.filter((x) => x !== row))} /> },
              ]}
              footer={<Button onClick={() => setRows((xs) => [...xs, { dest: "", target: "", orig: "" }])}>Add route</Button>}
            />
          </FormField>
        </Container>
      </Form>
    </ContentLayout>
  );
}

export function CreateRouteTable() {
  const notify = useNotify();
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const [vpcId, setVpcId] = useState("");
  const [name, setName] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const tagMap = Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value]));
      if (name) tagMap.Name = name;
      const rt = await api.createRouteTable(vpcId, tagMap);
      notify.success(`Route table "${rt.RouteTableId}" created.`);
      navigate("vpc", "route-tables", rt.RouteTableId);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create route table</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "route-tables")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!vpcId} onClick={submit}>Create route table</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Route table settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name - optional"><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-route-table-01" /></FormField>
              <FormField label="VPC">
                <Select selectedOption={vpcId ? { value: vpcId, label: vpcId } : null} placeholder="Select a VPC"
                  options={(vpcs.data || []).map((v) => ({ value: v.VpcId, label: v.VpcId }))} onChange={({ detail }) => setVpcId(detail.selectedOption.value)} />
              </FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Tags</Header>}><FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField></Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}

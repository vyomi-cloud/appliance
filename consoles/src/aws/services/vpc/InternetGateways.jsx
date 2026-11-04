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
import { TagsModal } from "./Vpcs.jsx";
import { TAG_I18N } from "./tagI18n.js";
import * as api from "./api.js";

const attachedVpc = (g) => g.Attachments?.[0]?.VpcId || "";

export function InternetGateways() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [tags, setTags] = useState(null);
  const t = useAsync(() => api.describeInternetGateways(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Internet gateways</Header>}>
      <ResourceTable
        resourceName="Internet gateways"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="InternetGatewayId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={<Box textAlign="center">No internet gateways found</Box>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => g.Tags?.Name || "-" },
          { id: "id", header: "Internet gateway ID", cell: (g) => <Link href={href("vpc", "internet-gateways", g.InternetGatewayId)} onFollow={follow}>{g.InternetGatewayId}</Link> },
          { id: "state", header: "State", cell: (g) => (attachedVpc(g) ? "Attached" : "Detached") },
          { id: "vpc", header: "VPC ID", cell: (g) => attachedVpc(g) || "-" },
          { id: "owner", header: "Owner", cell: () => "123456789012" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "view", text: "View details", disabled: sel.length !== 1 },
              { id: "attach", text: "Attach to VPC", disabled: sel.length !== 1 || !!attachedVpc(sel[0] || {}) },
              { id: "detach", text: "Detach from VPC", disabled: sel.length !== 1 || !attachedVpc(sel[0] || {}) },
              { id: "tags", text: "Manage tags", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete internet gateway" },
            ]} onItemClick={async ({ detail }) => {
              if (detail.id === "view") navigate("vpc", "internet-gateways", sel[0].InternetGatewayId);
              else if (detail.id === "attach") navigate("vpc", "internet-gateways", sel[0].InternetGatewayId, "attach");
              else if (detail.id === "detach") { await api.detachInternetGateway(sel[0].InternetGatewayId, attachedVpc(sel[0])); notify.success("Internet gateway detached."); setSel([]); t.reload(); }
              else if (detail.id === "tags") setTags(sel[0]);
              else if (detail.id === "delete") setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("vpc", "create-internet-gateway")} onFollow={follow}>Create internet gateway</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="internet gateway" names={sel.map((g) => g.InternetGatewayId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const g of sel) await api.deleteInternetGateway(g.InternetGatewayId); notify.success(`${sel.length} internet gateway(s) deleted.`); setSel([]); t.reload(); }} />
      {tags && <TagsModal resource={tags} onDismiss={() => setTags(null)} onSaved={() => { setTags(null); t.reload(); }} />}
    </ContentLayout>
  );
}

export function InternetGatewayDetail({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeInternetGateway(params.id), [params.id]);
  const [tags, setTags] = useState(false);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Internet gateway not found" }} />;
  const g = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<ButtonDropdown items={[{ id: "delete", text: "Delete internet gateway" }]} onItemClick={async () => {
      if (confirm(`Delete ${g.InternetGatewayId}?`)) { await api.deleteInternetGateway(g.InternetGatewayId); notify.success("Internet gateway deleted."); navigate("vpc", "internet-gateways"); }
    }}>Actions</ButtonDropdown>}>{`${g.InternetGatewayId} / ${g.Tags?.Name || ""}`}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["Internet gateway ID", g.InternetGatewayId], ["State", attachedVpc(g) ? "Attached" : "Detached"],
          ["VPC ID", attachedVpc(g) || "-"], ["Owner", "123456789012"],
        ]} />
        <Tabs tabs={[
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

export function CreateInternetGateway() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const tagMap = Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value]));
      if (name) tagMap.Name = name;
      const igw = await api.createInternetGateway(tagMap);
      notify.success(`Internet gateway "${igw.InternetGatewayId}" created.`);
      navigate("vpc", "internet-gateways", igw.InternetGatewayId, "attach");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create internet gateway</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "internet-gateways")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={submit}>Create internet gateway</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Internet gateway settings</Header>}>
            <FormField label="Name tag"><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-internet-gateway" /></FormField>
          </Container>
          <Container header={<Header variant="h2">Tags - optional</Header>}><FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField></Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}

export function AttachInternetGateway({ params }) {
  const notify = useNotify();
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const [vpcId, setVpcId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.attachInternetGateway(params.id, vpcId);
      notify.success(`Internet gateway attached to ${vpcId}.`);
      navigate("vpc", "internet-gateways", params.id);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Attach to VPC</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "internet-gateways")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!vpcId} onClick={submit}>Attach internet gateway</Button>
        </SpaceBetween>
      }>
        <Container header={<Header variant="h2">VPC</Header>}>
          <FormField label="Available VPCs">
            <Select selectedOption={vpcId ? { value: vpcId, label: vpcId } : null} placeholder="Select a VPC"
              options={(vpcs.data || []).map((v) => ({ value: v.VpcId, label: v.VpcId }))}
              onChange={({ detail }) => setVpcId(detail.selectedOption.value)} />
          </FormField>
        </Container>
      </Form>
    </ContentLayout>
  );
}

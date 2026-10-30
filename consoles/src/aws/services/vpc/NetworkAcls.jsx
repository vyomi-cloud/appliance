import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { TagsModal } from "./Vpcs.jsx";
import * as api from "./api.js";

export function NetworkAcls() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [tags, setTags] = useState(null);
  const [create, setCreate] = useState(false);
  const [rules, setRules] = useState(null);
  const [assoc, setAssoc] = useState(false);
  const t = useAsync(() => api.describeNetworkAcls(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Network ACLs</Header>}>
      <ResourceTable
        resourceName="Network ACLs"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="NetworkAclId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (n) => n.Tags?.Name || "-" },
          { id: "id", header: "Network ACL ID", cell: (n) => n.NetworkAclId },
          { id: "assoc", header: "Associated with", cell: (n) => `${n.Associations.length} subnet${n.Associations.length === 1 ? "" : "s"}` },
          { id: "default", header: "Default", cell: (n) => (n.IsDefault ? "Yes" : "No") },
          { id: "vpc", header: "VPC ID", cell: (n) => n.VpcId },
          { id: "in", header: "Inbound rules count", cell: (n) => n.Entries.filter((e) => !e.Egress).length },
          { id: "out", header: "Outbound rules count", cell: (n) => n.Entries.filter((e) => e.Egress).length },
          { id: "owner", header: "Owner", cell: () => "123456789012" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "in", text: "Edit inbound rules", disabled: sel.length !== 1 },
              { id: "out", text: "Edit outbound rules", disabled: sel.length !== 1 },
              { id: "subnets", text: "Edit subnet associations", disabled: sel.length !== 1 },
              { id: "tags", text: "Manage tags", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete network ACLs" },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "in") setRules({ nacl: sel[0], direction: false });
              else if (detail.id === "out") setRules({ nacl: sel[0], direction: true });
              else if (detail.id === "subnets") setAssoc(sel[0]);
              else if (detail.id === "tags") setTags(sel[0]);
              else if (detail.id === "delete") setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => setCreate(true)}>Create network ACL</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="network ACL" names={sel.map((n) => n.NetworkAclId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const n of sel) await api.deleteNetworkAcl(n.NetworkAclId); notify.success(`${sel.length} network ACL(s) deleted.`); setSel([]); t.reload(); }} />
      {tags && <TagsModal resource={tags} onDismiss={() => setTags(null)} onSaved={() => { setTags(null); t.reload(); }} />}
      {create && <CreateNaclModal onDismiss={() => setCreate(false)} onCreated={() => { setCreate(false); t.reload(); }} />}
      {rules && <RulesModal nacl={rules.nacl} egress={rules.direction} onDismiss={() => setRules(null)} onSaved={() => { setRules(null); setSel([]); t.reload(); }} />}
      {assoc && <AssocModal nacl={assoc} onDismiss={() => setAssoc(false)} onSaved={() => { setAssoc(false); setSel([]); t.reload(); }} />}
    </ContentLayout>
  );
}

function CreateNaclModal({ onDismiss, onCreated }) {
  const notify = useNotify();
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const [vpcId, setVpcId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const nacl = await api.createNetworkAcl(vpcId, name ? { Name: name } : {});
      notify.success(`Network ACL "${nacl.NetworkAclId}" created.`); onCreated();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible onDismiss={onDismiss} header="Create network ACL" footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
      <Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!vpcId} onClick={submit}>Create network ACL</Button>
    </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="l">
          <FormField label="Name - optional"><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-network-acl" /></FormField>
          <FormField label="VPC">
            <Select selectedOption={vpcId ? { value: vpcId, label: vpcId } : null} placeholder="Select a VPC"
              options={(vpcs.data || []).map((v) => ({ value: v.VpcId, label: v.VpcId }))} onChange={({ detail }) => setVpcId(detail.selectedOption.value)} />
          </FormField>
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

function RulesModal({ nacl, egress, onDismiss, onSaved }) {
  const notify = useNotify();
  const existing = nacl.Entries.filter((e) => e.Egress === egress);
  const [rows, setRows] = useState(existing.map((e) => ({ ...e, orig: e.RuleNumber })));
  const [busy, setBusy] = useState(false);
  const update = (i, patch) => setRows((xs) => xs.map((x, idx) => (idx === i ? { ...x, ...patch } : x)));
  const save = async () => {
    setBusy(true);
    try {
      for (const e of existing) if (!rows.some((r) => r.orig === e.RuleNumber)) await api.deleteNetworkAclEntry(nacl.NetworkAclId, e.RuleNumber, egress);
      for (const row of rows) {
        if (row.orig !== undefined) await api.deleteNetworkAclEntry(nacl.NetworkAclId, row.orig, egress);
        await api.createNetworkAclEntry(nacl.NetworkAclId, { RuleNumber: Number(row.RuleNumber), Protocol: row.Protocol || "-1", RuleAction: row.RuleAction || "allow", Egress: egress, CidrBlock: row.CidrBlock || "0.0.0.0/0" });
      }
      notify.success(`${egress ? "Outbound" : "Inbound"} rules saved.`); onSaved();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible onDismiss={onDismiss} size="large" header={egress ? "Edit outbound rules" : "Edit inbound rules"}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>Save</Button></SpaceBetween></Box>}>
      <Table
        variant="embedded"
        items={rows}
        columnDefinitions={[
          { id: "n", header: "Rule number", cell: (r) => <Input type="number" value={String(r.RuleNumber)} onChange={({ detail }) => update(rows.indexOf(r), { RuleNumber: detail.value })} ariaLabel="Rule number" /> },
          { id: "p", header: "Protocol", cell: (r) => <Input value={r.Protocol || "-1"} onChange={({ detail }) => update(rows.indexOf(r), { Protocol: detail.value })} ariaLabel="Protocol" /> },
          { id: "c", header: "Source", cell: (r) => <Input value={r.CidrBlock || "0.0.0.0/0"} onChange={({ detail }) => update(rows.indexOf(r), { CidrBlock: detail.value })} ariaLabel="Source" /> },
          { id: "a", header: "Allow/Deny", cell: (r) => <Select selectedOption={{ value: r.RuleAction || "allow", label: (r.RuleAction || "allow") === "allow" ? "Allow" : "Deny" }} options={[{ value: "allow", label: "Allow" }, { value: "deny", label: "Deny" }]} onChange={({ detail }) => update(rows.indexOf(r), { RuleAction: detail.selectedOption.value })} /> },
          { id: "x", header: "", cell: (r) => <Button iconName="close" ariaLabel="Remove rule" onClick={() => setRows((xs) => xs.filter((x) => x !== r))} /> },
        ]}
        footer={<Button onClick={() => setRows((xs) => [...xs, { RuleNumber: 100 * (xs.length + 1), Protocol: "-1", RuleAction: "allow", CidrBlock: "0.0.0.0/0" }])}>Add rule</Button>}
        empty={<Box textAlign="center" color="inherit">This network ACL has no {egress ? "outbound" : "inbound"} rules.</Box>}
      />
    </Modal>
  );
}

function AssocModal({ nacl, onDismiss, onSaved }) {
  const notify = useNotify();
  const subnets = useAsync(() => api.describeSubnets({ VpcId: [nacl.VpcId] }), [nacl.VpcId]);
  const [subnetId, setSubnetId] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api.associateNetworkAcl(nacl.NetworkAclId, subnetId); notify.success("Subnet association updated."); onSaved(); }
    finally { setBusy(false); }
  };
  return (
    <Modal visible onDismiss={onDismiss} header="Edit subnet associations" footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
      <Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!subnetId} onClick={save}>Save</Button>
    </SpaceBetween></Box>}>
      <FormField label="Subnet to associate with this network ACL">
        <Select selectedOption={subnetId ? { value: subnetId, label: subnetId } : null} placeholder="Select a subnet"
          options={(subnets.data || []).map((s) => ({ value: s.SubnetId, label: s.SubnetId }))} onChange={({ detail }) => setSubnetId(detail.selectedOption.value)} />
      </FormField>
    </Modal>
  );
}

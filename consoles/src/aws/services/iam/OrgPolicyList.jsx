/* Organization policy list (SCP / RCP) on the real Organizations backend: create, delete, enable the
 * policy type on the root, with the live attached-target count. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { OrgGate, useOrgModel } from "./OrgKit.jsx";
import * as api from "./api.js";

const DEFAULT_DOC = JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: ["s3:DeleteBucket"], Resource: "*" }] }, null, 2);

function CreateModal({ type, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [doc, setDoc] = useState(DEFAULT_DOC);
  const [busy, setBusy] = useState(false);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create policy" size="large"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={async () => {
          setBusy(true);
          try { await api.orgCreatePolicy(name, desc, type, doc); notify.success(`Policy "${name}" created.`); setName(""); setDesc(""); onDone(); onDismiss(); }
          catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Create policy</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="m">
        <FormField label="Policy name"><Input ariaLabel="Policy name" value={name} onChange={({ detail }) => setName(detail.value)} /></FormField>
        <FormField label="Description"><Input ariaLabel="Description" value={desc} onChange={({ detail }) => setDesc(detail.value)} /></FormField>
        <FormField label="Policy (JSON)"><Textarea rows={10} value={doc} onChange={({ detail }) => setDoc(detail.value)} spellcheck={false} /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function OrgPolicyList({ type, resourceName, base }) {
  const notify = useNotify();
  const model = useOrgModel();
  const list = useAsync(async () => {
    const policies = await api.orgListPolicies(type);
    return Promise.all(policies.map(async (p) => ({ ...p, attached: (await api.listTargetsForPolicy(p.Id)).length })));
  }, [model.data?.org?.Id]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const enabled = (model.data?.root?.PolicyTypes || []).some((t) => t.Type === type && t.Status === "ENABLED");
  const reload = () => { model.reload(); list.reload(); };
  return (
    <OrgGate model={model} title={resourceName}>{(m) => !enabled ? (
      <CapabilityContainer id="iam.organizations.policies" title={resourceName}>
        <Box textAlign="center" padding="l"><SpaceBetween size="s">
          <b>{resourceName} are not enabled</b>
          <Button variant="primary" onClick={async () => { try { await api.enablePolicyType(m.root.Id, type); notify.success(`${resourceName} enabled.`); reload(); } catch (e) { notify.error(e); } }}>Enable {resourceName}</Button>
        </SpaceBetween></Box>
      </CapabilityContainer>
    ) : (
      <>
        <ResourceTable
          resourceName={resourceName} items={list.data || []} loading={list.loading} error={list.error} onRefresh={list.reload}
          trackBy="Id" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
          empty={{ title: "No resources to display" }}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length || sel[0].AwsManaged} onClick={async () => { try { await api.orgDeletePolicy(sel[0].Id); notify.success(`Policy "${sel[0].Name}" deleted.`); setSel([]); list.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create policy</Button>
          </SpaceBetween>}
          columns={[
            { id: "name", header: "Policy name", isRowHeader: true, cell: (x) => <Link href={`#/iam/${base}/${encodeURIComponent(x.Name)}`} onFollow={follow}>{x.Name}</Link> },
            { id: "desc", header: "Description", cell: (x) => x.Description || "-" },
            { id: "managed", header: "Managed by", cell: (x) => (x.AwsManaged ? "AWS" : "Customer") },
            { id: "attached", header: "Attached to entities", cell: (x) => String(x.attached) },
          ]} />
        <CreateModal type={type} visible={create} onDismiss={() => setCreate(false)} onDone={list.reload} />
      </>
    )}</OrgGate>
  );
}

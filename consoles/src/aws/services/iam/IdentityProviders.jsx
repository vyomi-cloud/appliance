/* Identity providers list — real SAML/OIDC create+delete, listed together. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function IdentityProviders() {
  const notify = useNotify();
  const d = useAsync(() => Promise.all([api.listSamlProviders(), api.listOidcProviders()]), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [addModal, setAddModal] = useState(false);
  const [type, setType] = useState("SAML");
  const [name, setName] = useState("");
  const [metadata, setMetadata] = useState("");
  const [url, setUrl] = useState("");
  const [clientId, setClientId] = useState("");

  const items = d.data ? [
    ...d.data[0].map((p) => ({ arn: p.Arn, name: p.Arn.split("/").pop(), type: "SAML", created: p.CreateDate })),
    ...d.data[1].map((a) => ({ arn: a.Arn, name: a.Arn.split("/").pop(), type: "OpenID Connect", created: null })),
  ] : [];

  const create = async () => {
    try {
      if (type === "SAML") await api.createSamlProvider(name, metadata);
      else await api.createOidcProvider(url, clientId ? [clientId] : []);
      notify.success(`Identity provider "${type === "SAML" ? name : url}" added.`);
      setAddModal(false); setName(""); setMetadata(""); setUrl(""); setClientId(""); d.reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <ResourceTable
        resourceName="Identity providers"
        items={items}
        loading={d.loading}
        error={d.error}
        onRefresh={d.reload}
        trackBy="arn"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={{ title: "No resources to display" }}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => setAddModal(true)}>Add provider</Button>
          </SpaceBetween>
        }
        columns={[
          { id: "name", header: "Provider name", isRowHeader: true, cell: (x) => x.name },
          { id: "type", header: "Type", cell: (x) => x.type },
          { id: "created", header: "Creation time", cell: (x) => fmtDate(x.created) },
        ]}
      />
      <Modal visible={addModal} onDismiss={() => setAddModal(false)} size="large" header="Add an identity provider"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAddModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={type === "SAML" ? (!name || !metadata) : !url} onClick={create}>Add provider</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          <FormField label="Provider type">
            <RadioGroup value={type} onChange={({ detail }) => setType(detail.value)} items={[{ value: "SAML", label: "SAML" }, { value: "OpenID Connect", label: "OpenID Connect" }]} />
          </FormField>
          {type === "SAML" ? (
            <>
              <FormField label="Provider name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Provider name" /></FormField>
              <FormField label="Metadata document"><Textarea rows={10} value={metadata} onChange={({ detail }) => setMetadata(detail.value)} spellcheck={false} /></FormField>
            </>
          ) : (
            <>
              <FormField label="Provider URL"><Input value={url} onChange={({ detail }) => setUrl(detail.value)} placeholder="https://example.com" ariaLabel="Provider URL" /></FormField>
              <FormField label="Audience (client ID)"><Input value={clientId} onChange={({ detail }) => setClientId(detail.value)} ariaLabel="Audience (client ID)" /></FormField>
            </>
          )}
        </SpaceBetween>
      </Modal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="identity provider"
        names={sel.map((x) => x.name)}
        onConfirm={async () => {
          for (const x of sel) { if (x.type === "SAML") await api.deleteSamlProvider(x.arn); else await api.deleteOidcProvider(x.arn); }
          notify.success("Identity provider(s) deleted."); setSel([]); d.reload();
        }} />
    </>
  );
}

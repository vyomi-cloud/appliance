import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function DomainNameAccessAssociations() {
  const notify = useNotify();
  const t = useAsync(() => api.listDomainAccessAssociationsV2(), []);
  const domains = useAsync(() => api.listDomainNamesV2(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [domain, setDomain] = useState(null);
  const [vpce, setVpce] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  return (
    <>
      <ResourceTable
        resourceName="Domain name access associations"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="domainNameAccessAssociationArn"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No domain association", action: <Button onClick={() => setCreate(true)}>Create domain association</Button> }}
        columns={[
          { id: "vpce", header: "VPC endpoint ID", isRowHeader: true, cell: (a) => a.accessAssociationSource },
          { id: "domain", header: "Domain name", cell: (a) => a.domainNameArn.split("/").pop() },
          { id: "arn", header: "Domain name ARN", cell: (a) => a.domainNameArn },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { for (const a of sel) await api.deleteDomainAccessAssociationV2(a.domainNameAccessAssociationArn); notify.success("Association(s) deleted."); setSel([]); t.reload(); }}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create domain association</Button>
          </SpaceBetween>
        }
      />
      <Modal visible={create} onDismiss={() => setCreate(false)} header="Create domain association"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!domain || !vpce} onClick={async () => {
            setBusy(true); setError(null);
            try {
              await api.createDomainAccessAssociationV2({ domainNameArn: domain.value, accessAssociationSourceType: "VPCE", accessAssociationSource: vpce });
              notify.success("Domain association created."); setCreate(false); setVpce(""); t.reload();
            } catch (e) { setError(e); } finally { setBusy(false); }
          }}>Create</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="l">
          {error && <ErrorAlert error={error} />}
          <FormField label="Domain name"><Select selectedOption={domain} onChange={({ detail }) => setDomain(detail.selectedOption)}
            options={(domains.data || []).map((d) => ({ value: d.domainNameArn, label: d.domainName }))} /></FormField>
          <FormField label="VPC endpoint ID"><Input value={vpce} onChange={({ detail }) => setVpce(detail.value)} placeholder="vpce-0123456789abcdef0" ariaLabel="VPC endpoint ID" /></FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
}

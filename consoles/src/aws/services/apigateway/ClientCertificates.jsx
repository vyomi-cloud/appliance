import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { fmtDate, ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function ClientCertificates() {
  const notify = useNotify();
  const t = useAsync(() => api.listClientCertificates(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Client certificates"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="clientCertificateId"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No client certificates found" }}
        columns={[
          { id: "id", header: "ID", isRowHeader: true, cell: (c) => c.clientCertificateId },
          { id: "description", header: "Description", cell: (c) => c.description || "-" },
          { id: "created", header: "Creation date", cell: (c) => fmtDate(c.createdDate) },
          { id: "expires", header: "Expiration date", cell: (c) => fmtDate(c.expirationDate) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown items={[{ id: "delete", text: "Delete", disabled: !sel.length }]}
              onItemClick={async ({ detail }) => { if (detail.id === "delete") { for (const c of sel) await api.deleteClientCertificate(c.clientCertificateId); notify.success("Certificate(s) deleted."); setSel([]); t.reload(); } }}
            >Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => setCreate(true)}>Generate certificate</Button>
          </SpaceBetween>
        }
      />
      <Modal visible={create} onDismiss={() => setCreate(false)} header="Generate client certificate"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true);
            try { await api.generateClientCertificate({ description }); notify.success("Client certificate generated."); setCreate(false); setDescription(""); t.reload(); }
            finally { setBusy(false); }
          }}>Generate certificate</Button>
        </SpaceBetween></Box>}>
        <FormField label="Description"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
      </Modal>
    </>
  );
}

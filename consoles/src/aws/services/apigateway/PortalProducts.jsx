/* Developer portal products — native apigatewayv2 control plane (CreatePortalProduct,
 * UpdatePortalProduct, DeletePortalProduct). A product is what a Portal bundles and
 * publishes to API consumers (Portals.jsx references products by ARN). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

function EditModal({ product, onDismiss, onSaved }) {
  const notify = useNotify();
  const [name, setName] = useState(product?.displayName || "");
  const [description, setDescription] = useState(product?.description || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const creating = !product?.portalProductId;
  return (
    <Modal visible onDismiss={onDismiss} header={creating ? "Create product" : "Edit product"}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={async () => {
          setBusy(true); setError(null);
          try {
            if (creating) {
              await api.createPortalProduct({ displayName: name, description });
              notify.success(`Portal product "${name}" created.`);
            } else {
              await api.updatePortalProduct(product.portalProductId, { displayName: name, description });
              notify.success("Portal product updated.");
            }
            onSaved();
          } catch (e) { setError(e); } finally { setBusy(false); }
        }}>{creating ? "Create product" : "Save changes"}</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Display name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Display name" /></FormField>
        <FormField label="Description" optional>
          <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function PortalProducts() {
  const t = useAsync(() => api.listPortalProducts(), []);
  const [sel, setSel] = useState([]);
  const [modal, setModal] = useState(null); // null | "create" | product object (edit)
  const [error, setError] = useState(null);
  const chosen = sel[0];

  return (
    <>
      {error && <Box padding={{ horizontal: "l", top: "s" }}><ErrorAlert error={error} /></Box>}
      <ResourceTable
        resourceName="Portal products"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="portalProductId"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No products", action: <Button onClick={() => setModal("create")}>Create products</Button> }}
        columns={[
          { id: "name", header: "Display name", isRowHeader: true, cell: (p) => p.displayName },
          { id: "description", header: "Description", cell: (p) => p.description || "-" },
          { id: "created", header: "Date created", cell: (p) => fmtDate(p.lastModified) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!chosen} onClick={() => setModal(chosen)}>Edit</Button>
            <Button variant="primary" onClick={() => setModal("create")}>Create product</Button>
          </SpaceBetween>
        }
      />
      <Box padding={{ horizontal: "l", bottom: "l" }}>
        <Container header={<Header variant="h2">How products work</Header>}>
          <Box color="text-body-secondary">
            A portal product is a collection of APIs that you bundle together and publish to a
            developer portal. Vyomi backs products with the real API Gateway V2 developer-portal
            control plane (CreatePortalProduct/UpdatePortalProduct/DeletePortalProduct); a
            portal references products by their ARN and the reference is validated.
          </Box>
        </Container>
      </Box>
      {modal && <EditModal product={modal === "create" ? {} : modal} onDismiss={() => setModal(null)} onSaved={() => { setModal(null); setSel([]); t.reload(); }} />}
    </>
  );
}

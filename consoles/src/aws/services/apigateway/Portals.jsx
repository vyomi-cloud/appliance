/* Developer portal (Portals) — native apigatewayv2 control plane (CreatePortal,
 * UpdatePortal, DeletePortal, PublishPortal/DisablePortal). Create/Edit keep the
 * form to what the capture shows (name + description); publishing is real:
 * PublishPortal flips publishStatus to PUBLISHED and stamps lastPublished. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const DEFAULT_COLORS = { accentColor: "#0972d3", backgroundColor: "#ffffff", errorValidationColor: "#d13212",
  headerColor: "#0f1b2a", navigationColor: "#0f1b2a", textColor: "#16191f" };

const STATUS = {
  PUBLISHED: { type: "success", text: "Published" },
  PUBLISH_IN_PROGRESS: { type: "in-progress", text: "Publishing" },
  PUBLISH_FAILED: { type: "error", text: "Publish failed" },
  DISABLE_IN_PROGRESS: { type: "in-progress", text: "Unpublishing" },
  DISABLE_FAILED: { type: "error", text: "Unpublish failed" },
  DISABLED: { type: "stopped", text: "Not published" },
};

function EditModal({ portal, onDismiss, onSaved }) {
  const notify = useNotify();
  const [name, setName] = useState(portal?.portalContent?.displayName || "");
  const [description, setDescription] = useState(portal?.portalContent?.description || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const creating = !portal?.portalId;
  return (
    <Modal visible onDismiss={onDismiss} header={creating ? "Create portal" : "Edit portal"}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={async () => {
          setBusy(true); setError(null);
          try {
            if (creating) {
              await api.createPortal({
                authorization: { none: {} }, endpointConfiguration: { none: {} },
                portalContent: { displayName: name, description, theme: { customColors: DEFAULT_COLORS } },
              });
              notify.success(`Portal "${name}" created.`);
            } else {
              await api.updatePortal(portal.portalId, { portalContent: { ...portal.portalContent, displayName: name, description } });
              notify.success("Portal updated.");
            }
            onSaved();
          } catch (e) { setError(e); } finally { setBusy(false); }
        }}>{creating ? "Create portal" : "Save changes"}</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
        <FormField label="Description" optional>
          <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function Portals() {
  const notify = useNotify();
  const t = useAsync(() => api.listPortals(), []);
  const [sel, setSel] = useState([]);
  const [modal, setModal] = useState(null); // null | "create" | portal object (edit)
  const [error, setError] = useState(null);
  const chosen = sel[0];

  return (
    <>
      {error && <Box padding={{ horizontal: "l", top: "s" }}><ErrorAlert error={error} /></Box>}
      <ResourceTable
        resourceName="Portals"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="portalId"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No portals", action: <Button onClick={() => setModal("create")}>Create developer portal</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (p) => p.portalContent?.displayName },
          { id: "status", header: "Status", cell: (p) => { const s = STATUS[p.publishStatus] || STATUS.DISABLED; return <StatusIndicator type={s.type}>{s.text}</StatusIndicator>; } },
          { id: "modified", header: "Date modified", cell: (p) => fmtDate(p.lastModified) },
          { id: "published", header: "Last published", cell: (p) => (p.lastPublished ? fmtDate(p.lastPublished) : "-") },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!chosen} onClick={() => setModal(chosen)}>Edit</Button>
            <Button disabled={!chosen || chosen.publishStatus === "PUBLISHED"}
              onClick={async () => { try { await api.publishPortal(chosen.portalId, `Published from Vyomi console`); notify.success("Portal published."); t.reload(); } catch (e) { setError(e); } }}>
              Publish
            </Button>
            <Button disabled={!chosen || chosen.publishStatus !== "PUBLISHED"}
              onClick={async () => { try { await api.disablePortal(chosen.portalId); notify.success("Portal unpublished."); t.reload(); } catch (e) { setError(e); } }}>
              Unpublish
            </Button>
            <Button variant="primary" onClick={() => setModal("create")}>Create portal</Button>
          </SpaceBetween>
        }
      />
      <Box padding={{ horizontal: "l", bottom: "l" }}>
        <Container header={<Header variant="h2">How portals work</Header>}>
          <Box color="text-body-secondary">
            A developer portal is a self-service website where API consumers browse published
            portal products, subscribe and get API keys. Vyomi backs portals with the real
            API Gateway V2 developer-portal control plane (CreatePortal/UpdatePortal/DeletePortal,
            PublishPortal/DisablePortal) — publishing actually flips the portal's status and
            records when it was last published.
          </Box>
        </Container>
      </Box>
      {modal && <EditModal portal={modal === "create" ? {} : modal} onDismiss={() => setModal(null)} onSaved={() => { setModal(null); setSel([]); t.reload(); }} />}
    </>
  );
}

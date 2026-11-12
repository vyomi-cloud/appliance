/* MicroVMs — a running instance of a MicroVM image; the resource is real, stored
 * state, but there is no Firecracker runtime underneath (see MicrovmImages.jsx). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function Microvms() {
  const notify = useNotify();
  const t = useAsync(() => api.listMicrovms(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <ContentLayout>
      <SpaceBetween size="l">
        <ResourceTable
          resourceName="MicroVMs"
          items={t.data || []}
          loading={t.loading}
          error={t.error}
          onRefresh={t.reload}
          trackBy="Id"
          selectionType="single"
          selectedItems={sel}
          onSelectionChange={setSel}
          empty={{ title: "No data to display.", action: <Button variant="primary" href={href("lambda", "create", "microvm")} onFollow={follow}>Run MicroVM</Button> }}
          columns={[
            { id: "id", header: "ID", isRowHeader: true, cell: (m) => m.Id },
            { id: "status", header: "Status", cell: (m) => <StatusIndicator type={m.Status === "RUNNING" ? "success" : "info"}>{m.Status}</StatusIndicator> },
            { id: "image", header: "MicroVM Image", cell: (m) => m.MicrovmImage },
            { id: "version", header: "Version", cell: (m) => m.Version },
            { id: "created", header: "Creation time", cell: (m) => fmtDate(m.CreationTime) },
          ]}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <ButtonDropdown items={[{ id: "terminate", text: "Terminate", disabled: !sel.length }]}
                onItemClick={({ detail }) => { if (detail.id === "terminate") setDel(true); }}>Actions</ButtonDropdown>
              <Button variant="primary" href={href("lambda", "create", "microvm")} onFollow={follow}>Run MicroVM</Button>
            </SpaceBetween>
          }
        />
        <Container header={<Header variant="h2">How it works</Header>}>
          <SpaceBetween direction="horizontal" size="xs">
            <Button href={href("lambda", "create", "microvm-image")} onFollow={follow}>Create new MicroVM image</Button>
            <Button href={href("lambda", "create", "microvm")} onFollow={follow}>Run MicroVM</Button>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
      <DeleteModal visible={del} resourceType="MicroVM" names={sel.map((m) => m.Id)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const m of sel) await api.deleteMicrovm(m.Id); notify.success(`${sel.length} MicroVM(s) terminated.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

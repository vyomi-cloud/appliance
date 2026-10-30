/* MicroVM Images — the resource (name/state/version) is real, stored state; there is
 * no Firecracker runtime underneath, so an image never actually boots. See
 * core/capabilities/aws/lambda.json (lambda.microvms). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function MicrovmImages() {
  const notify = useNotify();
  const t = useAsync(() => api.listMicrovmImages(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <ContentLayout>
      <SpaceBetween size="l">
        <ResourceTable
          resourceName="MicroVM Images"
          items={t.data || []}
          loading={t.loading}
          error={t.error}
          onRefresh={t.reload}
          trackBy="Name"
          selectionType="single"
          selectedItems={sel}
          onSelectionChange={setSel}
          empty={{ title: "No data to display.", action: <Button variant="primary" href={href("lambda", "create", "microvm-image")} onFollow={follow}>Create</Button> }}
          columns={[
            { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (i) => i.Name },
            { id: "state", header: "State", cell: (i) => <StatusIndicator type={i.State === "ACTIVE" ? "success" : "info"}>{i.State}</StatusIndicator> },
            { id: "active", header: "Active version", cell: (i) => i.ActiveVersion },
            { id: "failed", header: "Failed version", cell: (i) => i.FailedVersion ?? "-" },
            { id: "created", header: "Created", cell: (i) => fmtDate(i.Created) },
            { id: "arn", header: "Image ARN", cell: (i) => i.ImageArn },
          ]}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <ButtonDropdown items={[{ id: "delete", text: "Delete", disabled: !sel.length }]}
                onItemClick={({ detail }) => { if (detail.id === "delete") setDel(true); }}>Actions</ButtonDropdown>
              <Button variant="primary" href={href("lambda", "create", "microvm-image")} onFollow={follow}>Create</Button>
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
      <DeleteModal visible={del} resourceType="MicroVM image" names={sel.map((i) => i.Name)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const i of sel) await api.deleteMicrovmImage(i.Name); notify.success(`${sel.length} MicroVM image(s) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

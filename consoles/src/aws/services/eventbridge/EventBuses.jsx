import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function EventBuses() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const { data = [], loading, error, reload } = useAsync(async () => (await api.listEventBuses()).filter((b) => b.Name !== "default"));

  const onAction = async (id) => {
    if (id === "delete" && sel[0]) {
      try { await api.deleteEventBus(sel[0].Name); notify.success(`Deleted event bus ${sel[0].Name}.`); setSel([]); reload(); }
      catch (e) { notify.error(e); }
    }
  };

  return (
    <SpaceBetween size="l">
      <Alert header="Introducing the new custom event bus">Custom event buses now support schema discovery, archives, and resource-based policies from a single detail page.</Alert>
      <ResourceTable
        resourceName="Event buses"
        items={data}
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        trackBy="Name"
        filterPlaceholder="Find event buses"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (b) => <Link href={href("eventbridge", "event-buses", b.Name)} onFollow={follow}>{b.Name}</Link> },
          { id: "type", header: "Type", cell: () => "Custom" },
          { id: "status", header: "Status", cell: () => "Active" },
          { id: "arn", header: "Amazon Resource Name (ARN)", cell: (b) => b.Arn },
          { id: "schema", header: "Schema discovery", cell: () => "Off" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown items={[{ id: "delete", text: "Delete", disabled: sel.length !== 1 }]} disabled={sel.length !== 1} onItemClick={({ detail }) => onAction(detail.id)}>Actions</ButtonDropdown>
            <Button disabled={sel.length !== 1} href={sel.length === 1 ? href("eventbridge", "event-buses", sel[0].Name, "send") : undefined} onFollow={follow}>Send events</Button>
            <Button variant="primary" href={href("eventbridge", "create-event-bus")} onFollow={follow}>Create</Button>
          </SpaceBetween>
        }
        empty={{ title: "No event buses", subtitle: "You don't have any custom event buses.", action: <Button href={href("eventbridge", "create-event-bus")} onFollow={follow}>Create</Button> }}
      />
    </SpaceBetween>
  );
}

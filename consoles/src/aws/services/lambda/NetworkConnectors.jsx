/* Network connectors — the resource (VPC, protocol, compute type) is real, stored
 * state; it never actually bridges traffic since Vyomi has no MicroVM runtime on the
 * other end. See core/capabilities/aws/lambda.json (lambda.network-connectors). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function NetworkConnectors() {
  const t = useAsync(() => api.listNetworkConnectors(), []);
  const [sel, setSel] = useState([]);

  return (
      <ResourceTable
        resourceName="Network connectors"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="Name"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search by attributes or search by keyword"
        empty={{ title: "No network connectors.", action: <Button variant="primary" href={href("lambda", "create", "network-connector")} onFollow={follow}>Create network connector</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (n) => n.Name },
          { id: "id", header: "ID", cell: (n) => n.Id },
          { id: "arn", header: "ARN", cell: (n) => n.Arn },
          { id: "type", header: "Type", cell: (n) => n.Type },
          { id: "state", header: "State", cell: (n) => <StatusIndicator type={n.State === "AVAILABLE" ? "success" : "info"}>{n.State}</StatusIndicator> },
          { id: "modified", header: "Last modified", cell: (n) => fmtDate(n.LastModified) },
        ]}
        actions={<Button variant="primary" href={href("lambda", "create", "network-connector")} onFollow={follow}>Create network connector</Button>}
      />
  );
}

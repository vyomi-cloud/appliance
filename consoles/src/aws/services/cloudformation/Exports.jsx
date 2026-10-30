import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

export default function Exports() {
  const { data = [], loading, error, reload } = useAsync(() => api.listExports(), []);
  return (
    <ResourceTable
      resourceName="Exports"
      items={data}
      trackBy="Name"
      loading={loading}
      error={error}
      onRefresh={reload}
      filterPlaceholder="Filter by export name"
      columns={[
        { id: "n", header: "Export name", isRowHeader: true, cell: (e) => e.Name },
        { id: "v", header: "Export value", cell: (e) => e.Value },
        { id: "s", header: "Stack name", cell: (e) => e.ExportingStackId?.split("/")[1] || "-" },
        { id: "id", header: "Stack ID", cell: (e) => e.ExportingStackId },
      ]}
      empty={{ title: "No exported values" }}
    />
  );
}

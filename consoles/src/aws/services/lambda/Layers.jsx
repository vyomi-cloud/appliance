import Button from "@cloudscape-design/components/button";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function Layers() {
  const t = useAsync(() => api.listLayers(), []);
  return (
    <ResourceTable
      resourceName="Layers"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="LayerName"
      filterPlaceholder="Search by attributes or search by keyword"
      empty={{ title: "There is no data to display.", action: <Button variant="primary" href={href("lambda", "create", "layer")} onFollow={follow}>Create layer</Button> }}
      columns={[
        { id: "name", header: "Name", isRowHeader: true, cell: (l) => l.LayerName },
        { id: "version", header: "Version", cell: (l) => l.LatestMatchingVersion?.Version },
        { id: "desc", header: "Description", cell: (l) => l.LatestMatchingVersion?.Description || "-" },
        { id: "runtimes", header: "Compatible runtimes", cell: (l) => (l.LatestMatchingVersion?.CompatibleRuntimes || []).join(", ") || "-" },
        { id: "arch", header: "Compatible architectures", cell: (l) => (l.LatestMatchingVersion?.CompatibleArchitectures || []).join(", ") || "-" },
        { id: "created", header: "Created", cell: (l) => fmtDate(l.LatestMatchingVersion?.CreatedDate) },
      ]}
      actions={<Button variant="primary" href={href("lambda", "create", "layer")} onFollow={follow}>Create layer</Button>}
    />
  );
}

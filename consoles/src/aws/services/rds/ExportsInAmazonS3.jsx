import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

export default function ExportsInAmazonS3() {
  const [sel, setSel] = useState([]);
  const notify = useNotify();
  const t = useAsync(() => api.describeExportTasks());
  const cancel = async () => {
    try { await api.cancelExportTask(sel[0].ExportTaskIdentifier); notify.success(`Cancelling "${sel[0].ExportTaskIdentifier}".`); setSel([]); t.reload(); }
    catch (e) { notify.error(e); }
  };
  return (
    <ResourceTable
      resourceName="Exports In Amazon S3"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="ExportTaskIdentifier"
      selectionType="single"
      selectedItems={sel}
      onSelectionChange={setSel}
      empty={{ title: "No exports created, create an export from a specific snapshot" }}
      actions={<Button disabled={sel.length !== 1} onClick={cancel}>Cancel</Button>}
      columns={[
        { id: "name", header: "Name", isRowHeader: true, cell: (x) => x.ExportTaskIdentifier },
        { id: "source", header: "Source type", cell: (x) => x.SourceType || "-" },
        { id: "status", header: "Status", cell: (x) => x.Status || "-" },
        { id: "bucket", header: "S3 bucket", cell: (x) => x.S3Bucket || "-" },
        { id: "src", header: "Source", cell: (x) => x.SourceArn || "-" },
        { id: "srcTime", header: "Source creation time", cell: () => "-" },
        { id: "start", header: "Export task start time", cell: () => "-" },
        { id: "end", header: "Export task end time", cell: () => "-" },
      ]}
    />
  );
}

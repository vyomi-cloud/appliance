/* Event source mappings — the account-wide trigger list (see core/lambda_core.py
 * module docstring + core/capabilities/aws/lambda.json "lambda.triggers" for scope). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function EventSourceMappings() {
  const notify = useNotify();
  const t = useAsync(() => api.listEventSourceMappings(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Event source mappings"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="UUID"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search by attributes or search by keyword"
        empty={{ title: "There is no data to display." }}
        columns={[
          { id: "uuid", header: "UUID", isRowHeader: true, cell: (e) => e.UUID },
          { id: "arn", header: "Event source ARN", cell: (e) => e.EventSourceArn || "-" },
          { id: "type", header: "Event source type", cell: (e) => e.EventSourceType },
          { id: "fn", header: "Function", cell: (e) => <Link href={href("lambda", "functions", e.FunctionName)} onFollow={follow}>{e.FunctionName}</Link> },
          { id: "state", header: "State", cell: (e) => <StatusIndicator type={e.State === "Enabled" ? "success" : "stopped"}>{e.State}</StatusIndicator> },
          { id: "result", header: "Last processing result", cell: (e) => e.LastProcessingResult },
          { id: "modified", header: "Last modified", cell: (e) => fmtDate(e.LastModified) },
        ]}
        actions={<Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>}
      />
      <DeleteModal visible={del} resourceType="trigger" names={sel.map((e) => e.UUID)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const e of sel) await api.deleteEventSourceMapping(e.UUID); notify.success(`${sel.length} trigger(s) deleted.`); setSel([]); t.reload(); }} />
    </>
  );
}

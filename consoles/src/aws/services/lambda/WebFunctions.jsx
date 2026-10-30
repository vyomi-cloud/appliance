/* Web Functions — Lambda functions with a Function URL configured. */
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

export default function WebFunctions() {
  const notify = useNotify();
  const t = useAsync(() => api.listFunctionsSplit().then((r) => r.webFunctions), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Web Functions"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="FunctionName"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search by attributes or search by keyword"
        empty={{ title: "No Web Functions", action: <Button variant="primary" href={href("lambda", "create", "web-function")} onFollow={follow}>Create Web Function</Button> }}
        columns={[
          { id: "name", header: "Function name", isRowHeader: true, sortingField: "FunctionName", cell: (f) => <Link href={href("lambda", "functions", f.FunctionName)} onFollow={follow}>{f.FunctionName}</Link> },
          { id: "state", header: "State", cell: () => <StatusIndicator type="success">Active</StatusIndicator> },
          { id: "reason", header: "State reason", cell: () => "-" },
          { id: "created", header: "Created", cell: (f) => fmtDate(f.LastModified) },
        ]}
        actions={
          <>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            {" "}
            <Button variant="primary" href={href("lambda", "create", "web-function")} onFollow={follow}>Create Web Function</Button>
          </>
        }
      />
      <DeleteModal visible={del} resourceType="function" names={sel.map((f) => f.FunctionName)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const f of sel) await api.deleteFunction(f.FunctionName); notify.success(`${sel.length} function(s) deleted.`); setSel([]); t.reload(); }} />
    </>
  );
}

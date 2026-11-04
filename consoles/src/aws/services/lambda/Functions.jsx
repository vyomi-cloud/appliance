/* Event Functions — standard Lambda functions (no Function URL). The console's own
 * Event/Web split over one function store; see api.js listFunctionsSplit(). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function Functions() {
  const notify = useNotify();
  const t = useAsync(() => api.listFunctionsSplit().then((r) => r.eventFunctions), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Event Functions"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="FunctionName"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search by attributes or search by keyword"
        empty={{ title: "There is no data to display.", action: <Button variant="primary" href={href("lambda", "create", "function")} onFollow={follow}>Create Event Function</Button> }}
        columns={[
          { id: "name", header: "Function name", isRowHeader: true, sortingField: "FunctionName", cell: (f) => <Link href={href("lambda", "functions", f.FunctionName)} onFollow={follow}>{f.FunctionName}</Link> },
          { id: "desc", header: "Description", cell: (f) => f.Description || "-" },
          { id: "pkg", header: "Package type", cell: (f) => f.PackageType },
          { id: "runtime", header: "Runtime", cell: (f) => f.Runtime },
          { id: "type", header: "Type", cell: () => "Event Function" },
          { id: "modified", header: "Last modified", cell: (f) => fmtDate(f.LastModified) },
        ]}
        actions={
          <>
            <ButtonDropdown
              items={[{ id: "delete", text: "Delete", disabled: !sel.length }]}
              onItemClick={({ detail }) => { if (detail.id === "delete") setDel(true); }}
            >Actions</ButtonDropdown>
            {" "}
            <Button variant="primary" href={href("lambda", "create", "function")} onFollow={follow}>Create Event Function</Button>
          </>
        }
      />
      <DeleteModal visible={del} resourceType="function" names={sel.map((f) => f.FunctionName)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const f of sel) await api.deleteFunction(f.FunctionName); notify.success(`${sel.length} function(s) deleted.`); setSel([]); t.reload(); }} />
    </>
  );
}

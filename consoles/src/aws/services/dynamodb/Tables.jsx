import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";

export const keyOf = (t, type) => t.KeySchema?.find((k) => k.KeyType === type)?.AttributeName;
export const attrType = (t, name) => ({ S: "String", N: "Number", B: "Binary" }[t.AttributeDefinitions?.find((a) => a.AttributeName === name)?.AttributeType] || "");
export const statusOf = (s) => <StatusIndicator type={s === "ACTIVE" ? "success" : s === "DELETING" ? "loading" : "in-progress"}>{s ? s[0] + s.slice(1).toLowerCase() : "-"}</StatusIndicator>;
export const capacity = (t) => t.BillingModeSummary?.BillingMode === "PAY_PER_REQUEST" ? "On-demand" : "Provisioned";

export default function Tables() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(async () => Promise.all((await api.listTables()).map(api.describeTable)));

  return (
    <>
      <ResourceTable
        resourceName="Tables"
        items={data}
        trackBy="TableName"
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find tables by table name"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "TableName", cell: (t) => <Link href={href("dynamodb", "tables", t.TableName)} onFollow={follow}>{t.TableName}</Link> },
          { id: "status", header: "Status", cell: (t) => statusOf(t.TableStatus) },
          { id: "pk", header: "Partition key", cell: (t) => { const k = keyOf(t, "HASH"); return k ? `${k} (${attrType(t, k)})` : "-"; } },
          { id: "sk", header: "Sort key", cell: (t) => { const k = keyOf(t, "RANGE"); return k ? `${k} (${attrType(t, k)})` : "-"; } },
          { id: "indexes", header: "Indexes", cell: (t) => (t.GlobalSecondaryIndexes?.length || 0) + (t.LocalSecondaryIndexes?.length || 0) },
          { id: "replication", header: "Replication Regions", cell: (t) => t.Replicas?.length || 0 },
          { id: "protection", header: "Deletion protection", cell: (t) => t.DeletionProtectionEnabled ? "On" : "Off" },
          { id: "favorite", header: "Favorite", cell: () => "☆" },
          { id: "readcap", header: "Read capacity mode", cell: (t) => capacity(t) },
          { id: "writecap", header: "Write capacity mode", cell: (t) => capacity(t) },
          { id: "size", header: "Total size", cell: (t) => `${t.TableSizeBytes ?? 0} bytes` },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={sel.length !== 1} items={[{ id: "explore", text: "Explore items" }, { id: "details", text: "View details" }]}
              onItemClick={({ detail }) => navigate("dynamodb", "tables", sel[0].TableName, ...(detail.id === "explore" ? ["items"] : []))}>Actions</ButtonDropdown>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" href={href("dynamodb", "create-table")} onFollow={follow}>Create table</Button>
          </SpaceBetween>
        }
        empty={{ title: "No tables", subtitle: "You have not created any tables yet.", action: <Button href={href("dynamodb", "create-table")} onFollow={follow}>Create table</Button> }}
      />
      <DeleteModal
        visible={del}
        resourceType="table"
        names={sel.map((t) => t.TableName)}
        confirmText="confirm"
        onDismiss={() => setDel(false)}
        onConfirm={async () => {
          for (const t of sel) await api.deleteTable(t.TableName);
          notify.success(`The request to delete the ${sel.length === 1 ? `"${sel[0].TableName}" table` : `${sel.length} tables`} has been submitted successfully.`);
          setSel([]); reload();
        }}
      />
    </>
  );
}

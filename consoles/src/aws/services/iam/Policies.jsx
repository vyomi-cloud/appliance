/* Policies list — real ListPolicies/DeletePolicy. Rows expand to show the policy JSON. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate, follow } from "../../../common/router.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

export default function Policies() {
  const notify = useNotify();
  const p = useAsync(() => api.listPolicies(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const selected = sel[0];

  return (
    <>
      <ResourceTable
        resourceName="Policies"
        items={p.data || []}
        loading={p.loading}
        error={p.error}
        onRefresh={p.reload}
        trackBy="Arn"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!selected} items={[
              { id: "attach", text: "Attach" }, { id: "detach", text: "Detach" }, { id: "boundary", text: "Set as permissions boundary" },
            ]} onItemClick={({ detail }) => navigate("iam", "policies", selected?.PolicyName)}>Actions</ButtonDropdown>
            <Button disabled={!selected} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("iam", "create-policy")}>Create policy</Button>
          </SpaceBetween>
        }
        columns={[
          { id: "name", header: "Policy name", isRowHeader: true, cell: (x) => <Link href={`#/iam/policies/${x.PolicyName}`} onFollow={follow}>{x.PolicyName}</Link> },
          { id: "type", header: "Type", cell: () => "Customer managed" },
          { id: "used", header: "Used as", cell: (x) => (x.AttachmentCount ? "Permissions policy" : "None") },
          { id: "desc", header: "Description", cell: (x) => x.Description || "-" },
        ]}
      />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="policy"
        names={sel.map((x) => x.PolicyName)}
        onConfirm={async () => { for (const x of sel) await api.deletePolicy(x.Arn); notify.success("Policy deleted."); setSel([]); p.reload(); }} />
    </>
  );
}

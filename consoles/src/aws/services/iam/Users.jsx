/* IAM users list — real ListUsers/DeleteUser. The "Go to Identity Center" banner is a
 * dismissible marketing banner in the native console; we skip rendering it (no spec
 * element requires it beyond the page note) and focus on the real table. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate, follow } from "../../../common/router.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import Link from "@cloudscape-design/components/link";
import * as api from "./api.js";

export default function Users() {
  const notify = useNotify();
  const u = useAsync(() => api.listUsers(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const items = u.data || [];

  return (
    <>
      <ResourceTable
        resourceName="IAM users"
        items={items}
        loading={u.loading}
        error={u.error}
        onRefresh={u.reload}
        trackBy="UserName"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={{ title: "No resources to display" }}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete user</Button>
            <Button variant="primary" onClick={() => navigate("iam", "create-user")}>Create user</Button>
          </SpaceBetween>
        }
        columns={[
          { id: "name", header: "User name", isRowHeader: true, cell: (x) => <Link href={`#/iam/users/${x.UserName}`} onFollow={follow}>{x.UserName}</Link> },
          { id: "path", header: "Path", cell: (x) => x.Path || "/" },
          { id: "groups", header: "Groups", cell: (x) => x._groups ?? "-" },
          { id: "last", header: "Last activity", cell: () => "-" },
          { id: "mfa", header: "MFA", cell: () => "Not enabled" },
          { id: "pwage", header: "Password age", cell: () => "-" },
          { id: "lastsignin", header: "Console last sign-in", cell: () => "-" },
          { id: "akid", header: "Access key ID", cell: () => "-" },
          { id: "akage", header: "Active key age", cell: () => "-" },
          { id: "aklast", header: "Access key last used", cell: () => "-" },
          { id: "arn", header: "ARN", cell: (x) => x.Arn },
          { id: "created", header: "Creation time", cell: (x) => fmtDate(x.CreateDate) },
          { id: "console", header: "Console access", cell: () => "-" },
          { id: "certs", header: "Signing certs", cell: () => "-" },
        ]}
      />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="user"
        names={sel.map((x) => x.UserName)}
        onConfirm={async () => { for (const x of sel) await api.deleteUser(x.UserName); notify.success("User(s) deleted."); setSel([]); u.reload(); }} />
    </>
  );
}

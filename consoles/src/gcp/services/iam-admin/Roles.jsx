/* Roles: Predefined (static reference catalog, native GET /v1/roles) and Custom
 * (native projects.roles CRUD) tabs. */
import { useState } from "react";
import { Button, Stack, Tab, Tabs } from "@mui/material";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import * as api from "./api.js";

export default function Roles() {
  const [tab, setTab] = useState("predefined");
  const predefined = useAsync(() => api.listPredefinedRoles(), []);
  const custom = useAsync(() => api.listCustomRoles(), []);
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <PageHeader title="Roles" actions={<Button href="https://cloud.google.com/iam/docs/roles-overview" target="_blank" rel="noreferrer">Learn</Button>} />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Roles tabs">
        <Tab value="predefined" label="Predefined" />
        <Tab value="custom" label="Custom" />
      </Tabs>
      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
        <Button href="#/iam-admin/roles/create">Create custom role</Button>
        {tab === "custom" && <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>}
      </Stack>
      {tab === "predefined" ? (
        <>
          <ErrorAlert error={predefined.error} title="Failed to load roles" />
          <ResourceTable resourceName="predefined roles" items={predefined.data || []} rowKey={(r) => r.name} loading={predefined.loading} onRetry={predefined.reload}
            selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Filter"
            columns={[
              { id: "title", header: "Title", sortField: "title", cell: (r) => <Link href={hashHref("iam-admin", "roles", "details", api.roleSlug(r.name))}>{r.title}</Link> },
              { id: "service", header: "Product or service", sortField: "service", cell: (r) => r.service },
              { id: "name", header: "Name", cell: (r) => r.name },
              { id: "actions", header: "Actions", cell: () => "—" },
            ]} />
        </>
      ) : (
        <>
          <ErrorAlert error={custom.error} title="Failed to load custom roles" />
          <ResourceTable resourceName="custom roles" items={custom.data || []} rowKey={(r) => r.name} loading={custom.loading} onRetry={custom.reload}
            selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Filter" empty="No rows to display"
            columns={[
              { id: "title", header: "Title", sortField: "title", cell: (r) => <Link href={hashHref("iam-admin", "roles", "details", api.roleSlug(r.name))}>{r.title}</Link> },
              { id: "name", header: "Name", cell: (r) => r.name.split("/").pop() },
              { id: "status", header: "Status", cell: (r) => r.stage },
              { id: "actions", header: "Actions", cell: (r) => <Button size="small" color="error" onClick={() => setDel(r.name)}>Delete</Button> },
            ]} />
        </>
      )}
      <DeleteDialog open={!!del} onClose={() => setDel(false)} title="Delete custom role(s)?" confirmText="DELETE"
        onConfirm={async () => {
          const names = del === true ? sel : [del];
          for (const name of names) await api.deleteRole(name);
          notify.success(`Deleted ${names.length} role${names.length === 1 ? "" : "s"}`);
          setSel([]); custom.reload();
        }}>
        {(del === true ? sel : [del]).join(", ")}
      </DeleteDialog>
    </>
  );
}

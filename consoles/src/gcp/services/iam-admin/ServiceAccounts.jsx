/* Service accounts list — native Cloud IAM v1 serviceAccounts.{create,list,delete}. */
import { useState } from "react";
import { Button, Stack } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import * as api from "./api.js";

export default function ServiceAccounts() {
  const notify = useNotify();
  const list = useAsync(() => api.listServiceAccounts(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <PageHeader title="Service accounts" actions={
        <Stack direction="row" spacing={1}>
          <Button variant="contained" startIcon={<AddIcon />} href="#/iam-admin/serviceaccounts/create">Create service account</Button>
          <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
          <Button disabled={sel.length !== 1}>Manage access</Button>
          <Button startIcon={<RefreshIcon />} onClick={list.reload}>Refresh</Button>
          <Button href="https://cloud.google.com/iam/docs/service-accounts-create" target="_blank" rel="noreferrer">Learn</Button>
        </Stack>} />
      <ErrorAlert error={list.error} title="Failed to load service accounts" />
      <ResourceTable
        resourceName="service accounts"
        items={list.data || []}
        rowKey={(a) => a.email}
        loading={list.loading}
        onRetry={list.reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Enter property name or value"
        columns={[
          { id: "email", header: "Email", sortField: "email", cell: (a) => <Link href={hashHref("iam-admin", "serviceaccounts", "details", a.email)}>{a.email}</Link> },
          { id: "status", header: "Status", cell: (a) => a.disabled ? "Disabled" : "Enabled" },
          { id: "name", header: "Name", sortField: "displayName", cell: (a) => a.displayName || "—" },
          { id: "description", header: "Description", cell: (a) => a.description || "—" },
          { id: "keyId", header: "Key ID", cell: () => "—" },
          { id: "keyCreated", header: "Key creation date", cell: () => "—" },
          { id: "oauth", header: "OAuth 2 Client ID", cell: (a) => a.oauth2ClientId },
          { id: "actions", header: "Actions", cell: (a) => <Button size="small" href={hashHref("iam-admin", "serviceaccounts", "details", a.email)}>Manage details</Button> },
        ]}
        empty="No rows to display"
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={`Delete ${sel.length} service account${sel.length === 1 ? "" : "s"}?`}
        confirmText="DELETE"
        onConfirm={async () => {
          for (const email of sel) await api.deleteServiceAccount(email);
          notify.success(`Deleted ${sel.length} service account${sel.length === 1 ? "" : "s"}`);
          setSel([]); list.reload();
        }}
      >
        {sel.join(", ")}
      </DeleteDialog>
    </>
  );
}

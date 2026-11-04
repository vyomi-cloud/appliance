/* Asset Inventory — live searchAllResources over what Vyomi's IAM & Resource Manager
 * cores actually model for this project (not the full Cloud Asset Inventory index). */
import { useState } from "react";
import { Button, Stack, TextField } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function AssetInventory() {
  const [query, setQuery] = useState("");
  const list = useAsync(() => api.searchAssets(query), [query]);

  return (
    <>
      <PageHeader title="Asset Inventory" />
      <CapabilityContainer id="gcp.iam-admin.asset-inventory" title="Resources">
        <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
          <TextField size="small" label="Query" value={query} onChange={(e) => setQuery(e.target.value)}
            helperText="Filters by resource name or type" sx={{ minWidth: 320 }} />
          <Button onClick={list.reload}>Search</Button>
        </Stack>
        <ErrorAlert error={list.error} title="Failed to search assets" />
        <ResourceTable resourceName="assets" items={list.data || []} rowKey={(a) => a.name} loading={list.loading} onRetry={list.reload}
          empty="No resources found"
          columns={[
            { id: "type", header: "Asset type", sortField: "assetType", cell: (a) => a.assetType },
            { id: "name", header: "Display name", sortField: "displayName", cell: (a) => a.displayName },
            { id: "project", header: "Project", cell: (a) => a.project },
            { id: "state", header: "State", cell: (a) => a.state },
            { id: "fullName", header: "Resource name", cell: (a) => a.name },
          ]} />
      </CapabilityContainer>
    </>
  );
}

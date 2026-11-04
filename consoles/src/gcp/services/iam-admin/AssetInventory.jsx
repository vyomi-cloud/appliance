/* Asset Inventory — live searchAllResources over what Vyomi's IAM & Resource Manager
 * cores actually model for this project (not the full Cloud Asset Inventory index), with the
 * real search query language (field:value, AND/OR/NOT, wildcards, labels.k, assetTypes, orderBy). */
import { useState } from "react";
import { Button, MenuItem, Select, Stack, TextField } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const ASSET_TYPES = [
  "iam.googleapis.com/ServiceAccount", "iam.googleapis.com/Role", "iam.googleapis.com/WorkloadIdentityPool",
  "cloudresourcemanager.googleapis.com/Project", "cloudresourcemanager.googleapis.com/Folder", "cloudresourcemanager.googleapis.com/TagKey",
];

export default function AssetInventory() {
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState({ q: "", type: "", order: "" });
  const [type, setType] = useState("");
  const [order, setOrder] = useState("");
  const list = useAsync(() => api.searchAssets(applied.q, { assetTypes: applied.type, orderBy: applied.order }), [applied]);
  const search = () => setApplied({ q: query, type, order });

  return (
    <>
      <PageHeader title="Asset Inventory" />
      <CapabilityContainer id="gcp.iam-admin.asset-inventory" title="Resources">
        <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
          <TextField size="small" label="Query" value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") search(); }}
            helperText='e.g. displayName:web* AND state=ACTIVE, -labels.env=dev, assetType:Folder' sx={{ minWidth: 420 }} />
          <Select size="small" displayEmpty value={type} onChange={(e) => setType(e.target.value)} inputProps={{ "aria-label": "Asset type" }} renderValue={(v) => v || "All asset types"}>
            <MenuItem value="">All asset types</MenuItem>
            {ASSET_TYPES.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
          </Select>
          <Select size="small" displayEmpty value={order} onChange={(e) => setOrder(e.target.value)} inputProps={{ "aria-label": "Order by" }} renderValue={(v) => v ? `Order: ${v}` : "Default order"}>
            <MenuItem value="">Default order</MenuItem>
            <MenuItem value="displayName">displayName</MenuItem>
            <MenuItem value="displayName desc">displayName desc</MenuItem>
            <MenuItem value="assetType">assetType</MenuItem>
          </Select>
          <Button onClick={search}>Search</Button>
        </Stack>
        <ErrorAlert error={list.error} title="Failed to search assets" />
        <ResourceTable resourceName="assets" items={list.data || []} rowKey={(a) => a.name} loading={list.loading} onRetry={list.reload}
          empty="No resources found"
          columns={[
            { id: "type", header: "Asset type", sortField: "assetType", cell: (a) => a.assetType },
            { id: "name", header: "Display name", sortField: "displayName", cell: (a) => a.displayName },
            { id: "project", header: "Project", cell: (a) => a.project },
            { id: "state", header: "State", cell: (a) => a.state },
            { id: "labels", header: "Labels", cell: (a) => Object.entries(a.labels || {}).map(([k, v]) => `${k}:${v}`).join(", ") },
            { id: "fullName", header: "Resource name", cell: (a) => a.name },
          ]} />
      </CapabilityContainer>
    </>
  );
}

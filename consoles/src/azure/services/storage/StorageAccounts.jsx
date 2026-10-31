/* Storage accounts browse blade (ARM list at subscription scope). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Link, ToolbarButton } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph, NotSimulated } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export default function StorageAccounts() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listStorageAccounts(), [sub.id]);
  const subName = sub.displayName || sub.id;
  const [gap, setGap] = useState(null); // "Restore" | "Open query" | "Assign tags"
  return (
    <>
      <TitleRow title="Storage accounts" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="storage" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="storage account"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("storage", "create")}
          extraCommands={<>
            <ToolbarButton onClick={() => setGap("Restore")}>Restore</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Open query")}>Open query</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Assign tags")}>Assign tags</ToolbarButton>
          </>}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteStorageAccount(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} storage account${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="storage-accounts.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "kind", label: "Kind", value: (r) => r.kind },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/storage/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "type", label: "Type", value: () => "Storage account" },
            { key: "kind", label: "Kind" },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "sku", label: "Replication", value: (r) => api.skuLabel(r.sku?.name), hidden: true },
            { key: "tier", label: "Access tier", value: (r) => r.properties?.accessTier, hidden: true },
            { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState, hidden: true },
          ]}
          emptyAction={<Link href="#/storage/create">Create storage account</Link>}
        />
      </div>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Restore" ? "Restoring a deleted storage account" : gap === "Open query" ? "Resource Graph queries" : "Bulk tag assignment"} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

/* Azure Cosmos DB browse blade (ARM list at subscription scope). */
import { useState } from "react";
import { Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Button, Link, ToolbarButton } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph, NotSimulated } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export default function CosmosAccounts() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listAccounts(), [sub.id]);
  const subName = sub.displayName || sub.id;
  const [gap, setGap] = useState(null); // "Restore" | "Open query" | "Assign tags"

  return (
    <>
      <TitleRow title="Azure Cosmos DB" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="cosmos" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="Azure Cosmos DB account"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("cosmos", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteAccount(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} Azure Cosmos DB account${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          extraCommands={<>
            <ToolbarButton onClick={() => setGap("Restore")}>Restore</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Open query")}>Open query</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Assign tags")}>Assign tags</ToolbarButton>
          </>}
          subscriptionLabel={subName}
          csvName="cosmos-db-accounts.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/cosmos/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "type", label: "Type", value: () => "Azure Cosmos DB account" },
            { key: "status", label: "Status", value: (r) => r.properties?.provisioningState || "Succeeded" },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "kind", label: "API", value: (r) => r.kind, hidden: true },
          ]}
          emptyAction={<Link href="#/cosmos/create">Create Azure Cosmos DB account</Link>}
        />
      </div>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Open query" ? "Querying across accounts with Azure Resource Graph" : gap === "Restore" ? "Restoring a deleted/backed-up account" : "Bulk tag assignment from the browse grid"} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

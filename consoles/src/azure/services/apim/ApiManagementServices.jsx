/* API Management services browse blade (ARM list at subscription scope). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Link, ToolbarButton } from "@fluentui/react-components";
import { Tag20Regular, DocumentSearch20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph, NotSimulated } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export default function ApiManagementServices() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listServices(), [sub.id]);
  const subName = sub.displayName || sub.id;
  const [gap, setGap] = useState(null);
  return (
    <>
      <TitleRow title="API Management services" glyph={<Glyph id="apim" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="API Management service"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("apim", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteService(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} API Management service${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="api-management-services.csv"
          extraCommands={<>
            <ToolbarButton icon={<DocumentSearch20Regular />} onClick={() => setGap("Open query")}>Open query</ToolbarButton>
            <ToolbarButton icon={<Tag20Regular />} onClick={() => setGap("Assign tags")}>Assign tags</ToolbarButton>
          </>}
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/apim/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "status", label: "Status", value: (r) => r.properties?.provisioningState || "Online" },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "tier", label: "Tier", value: (r) => r.sku?.name || "--" },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/apim/create">Create API Management service</Link>}
        />
      </div>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Open query" ? "Azure Resource Graph queries" : "Bulk-assigning tags from the browse grid"} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

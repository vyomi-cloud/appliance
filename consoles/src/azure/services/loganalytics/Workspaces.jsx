/* Log Analytics browse blade (ARM list at subscription scope). */
import { Link } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export default function Workspaces() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listWorkspaces(), [sub.id]);
  const subName = sub.displayName || sub.id;
  return (
    <>
      <TitleRow title="Log Analytics workspaces" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="loganalytics" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="workspace"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("loganalytics", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteWorkspace(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} workspace${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="loganalytics-workspaces.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/loganalytics/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "pricingTier", label: "Pricing tier", value: (r) => api.skuLabel(r.properties?.sku) },
            { key: "retention", label: "Retention (days)", value: (r) => r.properties?.retentionInDays },
            { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState || "Succeeded" },
          ]}
          emptyAction={<Link href="#/loganalytics/create">Create Log Analytics workspace</Link>}
        />
        <NotSimulatedContainer feature="Assign tags from the command bar" />
      </div>
    </>
  );
}

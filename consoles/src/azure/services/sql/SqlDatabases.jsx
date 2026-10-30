/* SQL databases browse blade — cross-server, subscription-wide (ARM has no single native
 * "list all databases" call, so the real portal uses Resource Graph; Vyomi aggregates the
 * native per-server Databases_List call across every server instead — see api.listAllDatabases). */
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

export default function SqlDatabases() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listAllDatabases(), [sub.id]);
  const subName = sub.displayName || sub.id;
  return (
    <>
      <TitleRow title="SQL databases" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="sql" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="sql database"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("sql", "create")}
          onDelete={async (rows) => {
            for (const r of rows) { await api.deleteDatabase(r.resourceGroup, r.server, r.name); await api.dropDataPlane(r.server, r.name); }
            notify.success(`Deleted ${rows.length} database${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="sql-databases.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/sql/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.server)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "status", label: "Status", value: (r) => r.properties?.status || "Online" },
            { key: "replicationRole", label: "Replication role", value: () => "Primary" },
            { key: "server", label: "Server", value: (r) => r.server },
            { key: "pricingTier", label: "Pricing tier", value: (r) => r.sku?.tier || "--" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/sql/create">Create SQL database</Link>}
        />
        <NotSimulatedContainer feature="Reservations, Open query (Azure Resource Graph) and Assign tags from the command bar" />
      </div>
    </>
  );
}

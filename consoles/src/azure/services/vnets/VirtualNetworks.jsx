/* Virtual networks browse blade (ARM list at subscription scope). */
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

export default function VirtualNetworks() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listVnets(), [sub.id]);
  const subName = sub.displayName || sub.id;
  return (
    <>
      <TitleRow title="Virtual networks" glyph={<Glyph id="vnets" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="virtual network"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("vnets", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteVnet(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} virtual network${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="virtual-networks.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/vnets/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/vnets/create">Create virtual network</Link>}
        />
        <NotSimulatedContainer feature="Open query (Azure Resource Graph) and Assign tags from the command bar" />
      </div>
    </>
  );
}

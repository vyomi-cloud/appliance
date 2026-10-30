/* Network security groups browse blade (ARM list at subscription scope). */
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

export default function NetworkSecurityGroups() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listNsgs(), [sub.id]);
  const subName = sub.displayName || sub.id;
  return (
    <>
      <TitleRow title="Network security groups" glyph={<Glyph id="nsgs" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="network security group"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("nsgs", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteNsg(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} network security group${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="network-security-groups.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/nsgs/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/nsgs/create">Create network security group</Link>}
        />
        <NotSimulatedContainer feature="Open query (Azure Resource Graph) and Assign tags from the command bar" />
      </div>
    </>
  );
}

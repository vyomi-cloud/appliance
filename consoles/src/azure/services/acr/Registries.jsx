/* Container registries browse blade (ARM list at subscription scope). */
import { Link } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export default function Registries() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listRegistries(), [sub.id]);
  const subName = sub.displayName || sub.id;
  return (
    <>
      <TitleRow title="Container registries" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="acr" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="container registry"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("acr", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteRegistry(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} container registr${rows.length === 1 ? "y" : "ies"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="container-registries.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/acr/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "type", label: "Type", value: () => "Container Registry" },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/acr/create">Create container registry</Link>}
        />
        <CapabilityContainer id="azure.acr.registry.listactions" title="Manage view, Open query and Assign tags" />
      </div>
    </>
  );
}

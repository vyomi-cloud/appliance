/* Container Apps Environments browse blade (ARM list at subscription scope). */
import { Link } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export default function ContainerAppsEnvironments() {
  const notify = useNotify();
  const sub = useSubscription();
  const envs = useAsync(() => api.listEnvironments(), [sub.id]);
  const subName = sub.displayName || sub.id;

  return (
    <>
      <TitleRow title="Container Apps Environments" glyph={<Glyph id="containerapps" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="container apps environment"
          items={envs.data || []}
          loading={envs.loading}
          error={envs.error}
          onRefresh={envs.reload}
          onCreate={() => navigate("containerapps", "environments", "create")}
          onDelete={async (xs) => {
            for (const r of xs) await api.deleteEnvironment(r.resourceGroup, r.name);
            notify.success(`Deleted ${xs.length} environment${xs.length === 1 ? "" : "s"}.`, "Delete succeeded");
            envs.reload();
          }}
          subscriptionLabel={subName}
          csvName="container-apps-environments.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/containerapps/environments/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/containerapps/environments/create">Create container apps environment</Link>}
        />
      </div>
    </>
  );
}

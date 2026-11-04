/* Container Apps Jobs browse blade (ARM list at subscription scope). */
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

export default function ContainerAppsJobs() {
  const notify = useNotify();
  const sub = useSubscription();
  const jobs = useAsync(() => api.listJobs(), [sub.id]);
  const subName = sub.displayName || sub.id;

  return (
    <>
      <TitleRow title="Container Apps Jobs" glyph={<Glyph id="containerapps" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="container apps job"
          items={jobs.data || []}
          loading={jobs.loading}
          error={jobs.error}
          onRefresh={jobs.reload}
          onCreate={() => navigate("containerapps", "jobs", "create")}
          onDelete={async (xs) => {
            for (const r of xs) await api.deleteJob(r.resourceGroup, r.name);
            notify.success(`Deleted ${xs.length} job${xs.length === 1 ? "" : "s"}.`, "Delete succeeded");
            jobs.reload();
          }}
          subscriptionLabel={subName}
          csvName="container-apps-jobs.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/containerapps/jobs/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "trigger", label: "Trigger type", value: (r) => r.properties?.configuration?.triggerType },
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "environment", label: "Environment", value: (r) => api.envName(r.properties?.environmentId) },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/containerapps/jobs/create">Create container apps job</Link>}
        />
      </div>
    </>
  );
}

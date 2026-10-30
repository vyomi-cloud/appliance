/* Resource groups browse blade (ARM list at subscription scope). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Link, ToolbarButton } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export default function ResourceGroups() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listGroups(), [sub.id]);
  const subName = sub.displayName || sub.id;
  const [query, setQuery] = useState(false);
  return (
    <>
      <TitleRow title="Resource groups" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="resourcegroups" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="resource group"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("resourcegroups", "create")}
          extraCommands={<ToolbarButton onClick={() => setQuery(true)}>Open query</ToolbarButton>}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteGroup(r.name);
            notify.success(`Deleted ${rows.length} resource group${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="resource-groups.csv"
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/resourcegroups/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          emptyAction={<Link href="#/resourcegroups/create">Create resource group</Link>}
        />
        <NotSimulatedContainer feature="Assign tags across a multi-selection and Open query (Azure Resource Graph) from the command bar" />
      </div>
      <Dialog open={query} onOpenChange={(_, d) => setQuery(d.open)}>
        <DialogSurface aria-label="Open query">
          <DialogBody>
            <DialogTitle>Open query</DialogTitle>
            <DialogContent><NotSimulated feature="Azure Resource Graph Explorer" /></DialogContent>
            <DialogActions><Button onClick={() => setQuery(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

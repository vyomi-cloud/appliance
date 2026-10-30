/* Event Grid Topics browse blade (ARM list at subscription scope). */
import { useState } from "react";
import { Dialog, DialogBody, DialogSurface, Link, ToolbarButton } from "@fluentui/react-components";
import { DocumentSearch20Regular, Tag20Regular } from "@fluentui/react-icons";
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

export default function Topics() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listTopics(), [sub.id]);
  const subName = sub.displayName || sub.id;
  const [dlg, setDlg] = useState(null);
  return (
    <>
      <TitleRow title="Event Grid Topics" glyph={<Glyph id="eventgrid" />} closeHref="#/eventgrid" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="topic"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("eventgrid", "topics", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteTopic(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} topic${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="event-grid-topics.csv"
          extraCommands={<>
            <ToolbarButton icon={<DocumentSearch20Regular />} onClick={() => setDlg("Open query")}>Open query</ToolbarButton>
            <ToolbarButton icon={<Tag20Regular />} onClick={() => setDlg("Assign tags")}>Assign tags</ToolbarButton>
          </>}
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/eventgrid/topics/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState, hidden: true },
          ]}
          emptyAction={<Link href="#/eventgrid/topics/create">Create topic</Link>}
        />
      </div>
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label={dlg || ""}>
          <DialogBody>
            <CapabilityContainer id="azure.eventgrid.topics.listactions" title={dlg || ""} />
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

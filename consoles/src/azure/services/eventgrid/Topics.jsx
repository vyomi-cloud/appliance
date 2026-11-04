/* Event Grid Topics browse blade (ARM list at subscription scope). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Link, ToolbarButton } from "@fluentui/react-components";
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
import { TagRows } from "./TagRows.jsx";
import * as api from "./api.js";

/** Bulk "Assign tags" dialog — real ARM PATCHes that merge a tag onto every selected topic
 *  (azure.eventgrid.topics.listactions: the bulk-tag half is built; "Open query" — Azure
 *  Resource Graph, a separate query service spanning every resource type — stays honest). */
function AssignTagsDialog({ open, onClose, rows, onDone }) {
  const notify = useNotify();
  const [tags, setTags] = useState([{ name: "", value: "" }]);
  const [busy, setBusy] = useState(false);
  const pairs = tags.filter((t) => t.name.trim());
  const apply = async () => {
    setBusy(true);
    try {
      const body = { tags: Object.fromEntries(pairs.map((t) => [t.name.trim(), t.value])) };
      for (const r of rows) await api.updateTopic(r.resourceGroup, r.name, body);
      notify.success(`Tags were assigned to ${rows.length} topic${rows.length === 1 ? "" : "s"}.`, "Assign tags succeeded");
      setTags([{ name: "", value: "" }]);
      onDone();
    } catch (e) { notify.error(e, "Assign tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Assign tags">
        <DialogBody>
          <DialogTitle>Assign tags</DialogTitle>
          <DialogContent>
            <p style={{ fontSize: 13 }}>Apply tags to the {rows.length} selected resource{rows.length === 1 ? "" : "s"}: {rows.map((r) => r.name).join(", ")}.</p>
            <TagRows tags={tags} onChange={setTags} resource={`${rows.length} resource${rows.length === 1 ? "" : "s"}`} />
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!pairs.length || busy} onClick={apply}>Save</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

export default function Topics() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listTopics(), [sub.id]);
  const subName = sub.displayName || sub.id;
  const [dlg, setDlg] = useState(null);
  const [assigning, setAssigning] = useState(null);
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
          extraCommands={(selected) => <>
            <ToolbarButton icon={<DocumentSearch20Regular />} onClick={() => setDlg("Open query")}>Open query</ToolbarButton>
            <ToolbarButton icon={<Tag20Regular />} disabled={!selected.length} onClick={() => setAssigning(selected)}>Assign tags</ToolbarButton>
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
      <AssignTagsDialog open={!!assigning} rows={assigning || []} onClose={() => setAssigning(null)} onDone={() => { setAssigning(null); reload(); }} />
    </>
  );
}

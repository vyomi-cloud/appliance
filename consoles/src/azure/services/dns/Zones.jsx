/* DNS zones browse blade (ARM list at subscription scope — public AND private zones). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Link, ToolbarButton } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph, NotSimulated } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const rg = (id = "") => (id.split("/resourceGroups/")[1] || "").split("/")[0];

export default function Zones() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listZones(), [sub.id]);
  const subName = sub.displayName || sub.id;
  const [gap, setGap] = useState(null); // "Open query" | "Assign tags"
  return (
    <>
      <TitleRow title="DNS zones" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="dns" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="DNS zone"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("dns", "create")}
          extraCommands={<>
            <ToolbarButton onClick={() => setGap("Open query")}>Open query</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Assign tags")}>Assign tags</ToolbarButton>
          </>}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteZone(rg(r.id), r.name);
            notify.success(`Deleted ${rows.length} DNS zone${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="dns-zones.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => rg(r.id) },
            { key: "type", label: "Zone type", value: (r) => r.properties?.zoneType || "Public" },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/dns/${encodeURIComponent(rg(r.id))}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "resourceGroup", label: "Resource group", value: (r) => rg(r.id) },
            { key: "location", label: "Location", value: () => "global" },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "type", label: "Zone type", value: (r) => r.properties?.zoneType || "Public" },
            { key: "recordsets", label: "Record sets", value: (r) => r.properties?.numberOfRecordSets ?? 0, hidden: true },
          ]}
          emptyAction={<Link href="#/dns/create">Create DNS zone</Link>}
        />
      </div>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Open query" ? "Resource Graph queries" : "Bulk tag assignment"} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

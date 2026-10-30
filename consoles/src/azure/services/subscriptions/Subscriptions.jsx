/* Subscriptions browse blade (ARM list — Vyomi simulates exactly one subscription). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Link, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import { getSubscription } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph, NotSimulated } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import * as api from "./api.js";

const DOLLAR = (n) => `$${Number(n || 0).toFixed(2)}`;
const GAPS = {
  "Manage Policies": "Azure Policy compliance management for the subscription",
  "View Requests": "Subscription ownership-transfer requests",
  "View eligible subscriptions": "Microsoft Entra Privileged Identity Management (PIM) eligible-subscription assignments",
  Analyze: "Azure Resource Graph Explorer",
};

export default function Subscriptions() {
  const sub = useAsync(() => api.getSubscriptionInfo(), []);
  const cost = useAsync(() => api.costQuery(getSubscription(), { type: "ActualCost", timeframe: "MonthToDate", dataset: { aggregation: { totalCost: { name: "Cost", function: "Sum" } } } }).catch(() => null), []);
  const [gap, setGap] = useState(null);
  const row = sub.data ? [{ ...sub.data, _cost: cost.data?.properties?.rows?.[0]?.[0] }] : [];
  return (
    <>
      <TitleRow title="Subscriptions" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="subscriptions" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="subscription"
          items={row}
          loading={sub.loading}
          error={sub.error}
          onRefresh={() => { sub.reload(); cost.reload(); }}
          filterPlaceholder="Search for any field..."
          extraCommands={<>
            <ToolbarButton icon={<Add20Regular />} as="a" href="#/subscriptions/create">Add</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Manage Policies")}>Manage Policies</ToolbarButton>
            <ToolbarButton onClick={() => setGap("View Requests")}>View Requests</ToolbarButton>
            <ToolbarButton onClick={() => setGap("View eligible subscriptions")}>View eligible subscriptions</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Analyze")}>Analyze</ToolbarButton>
          </>}
          csvName="subscriptions.csv"
          columns={[
            { key: "name", label: "Subscription name", render: (r) => <Link href={`#/subscriptions/${r.subscriptionId}`}>{r.displayName || r.subscriptionId}</Link>, value: (r) => r.displayName || r.subscriptionId },
            { key: "id", label: "Subscription ID", value: (r) => r.subscriptionId },
            { key: "role", label: "My role", value: () => "Owner" },
            { key: "cost", label: "Current cost", value: (r) => (r._cost == null ? "--" : DOLLAR(r._cost)) },
            { key: "score", label: "Secure Score", value: () => "--" },
            { key: "mg", label: "Parent management group", value: () => "--" },
            { key: "status", label: "Status", value: (r) => r.state || "Enabled" },
          ]}
        />
      </div>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={GAPS[gap] || gap} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

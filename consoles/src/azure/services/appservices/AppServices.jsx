/* App Services browse blade (ARM list at subscription scope), joined with the App Service
 * plan each site runs on for the Pricing Tier / App Service Plan columns. */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select, ToolbarButton,
} from "@fluentui/react-components";
import { Play20Regular, ArrowClockwise20Regular, Stop20Regular, TagMultiple20Regular, Search20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

/** A dialog that lets the user pick one of the loaded apps and runs `verb` on it — the
 * list toolbar's Start/Restart/Stop act on an app chosen here (BrowseGrid owns its own
 * selection state internally, so these commands pick their target independently). */
function ActionDialog({ open, onClose, title, icon, apps, run, label }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await run(apps.find((a) => a.name === name)); notify.success(`${label} '${name}' succeeded.`, `${label} succeeded`); onClose(); }
    catch (e) { notify.error(e, `${label} failed`); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={title}>
        <DialogBody>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent>
            <Field label="App Service" required>
              <Select value={name} onChange={(_, d) => setName(d.value)} aria-label="App Service">
                <option value="">Select an app...</option>
                {apps.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
              </Select>
            </Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" icon={icon} disabled={!name || busy} onClick={go}>{busy ? `${label}...` : label}</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function AssignTagsDialog({ open, onClose, apps, reload }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [tagName, setTagName] = useState("");
  const [tagValue, setTagValue] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const site = apps.find((a) => a.name === name);
      await api.updateSiteTags(site.resourceGroup, site.name, { ...site.tags, [tagName]: tagValue }, site);
      notify.success(`Tag '${tagName}' assigned to '${name}'.`, "Assign tags succeeded");
      reload(); onClose();
    } catch (e) { notify.error(e, "Assign tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Assign tags">
        <DialogBody>
          <DialogTitle>Assign tags</DialogTitle>
          <DialogContent>
            <Field label="App Service" required>
              <Select value={name} onChange={(_, d) => setName(d.value)} aria-label="App Service">
                <option value="">Select an app...</option>
                {apps.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
              </Select>
            </Field>
            <Field label="Tag name" required><Input value={tagName} onChange={(_, d) => setTagName(d.value)} /></Field>
            <Field label="Tag value"><Input value={tagValue} onChange={(_, d) => setTagValue(d.value)} /></Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!name || !tagName || busy} onClick={go}>{busy ? "Assigning..." : "Assign"}</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

export default function AppServices() {
  const notify = useNotify();
  const sub = useSubscription();
  const sites = useAsync(() => api.listSites(), [sub.id]);
  const plans = useAsync(() => api.listPlans(), [sub.id]);
  const [action, setAction] = useState(null);  // "start" | "restart" | "stop" | "tags" | "query" | null
  const subName = sub.displayName || sub.id;
  const byId = Object.fromEntries((plans.data || []).map((p) => [p.id.toLowerCase(), p]));
  const rows = (sites.data || []).map((s) => ({ ...s, plan: byId[(s.properties?.serverFarmId || "").toLowerCase()] }));

  return (
    <>
      <TitleRow title="App Services" glyph={<Glyph id="appservices" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="app service"
          items={rows}
          loading={sites.loading || plans.loading}
          error={sites.error}
          onRefresh={() => { sites.reload(); plans.reload(); }}
          onCreate={() => navigate("appservices", "create")}
          onDelete={async (xs) => {
            for (const r of xs) await api.deleteSite(r.resourceGroup, r.name);
            notify.success(`Deleted ${xs.length} app service${xs.length === 1 ? "" : "s"}.`, "Delete succeeded");
            sites.reload();
          }}
          subscriptionLabel={subName}
          csvName="app-services.csv"
          extraCommands={(
            <>
              <ToolbarButton icon={<Search20Regular />} onClick={() => setAction("query")}>Open query</ToolbarButton>
              <ToolbarButton icon={<TagMultiple20Regular />} disabled={!rows.length} onClick={() => setAction("tags")}>Assign tags</ToolbarButton>
              <ToolbarButton icon={<Play20Regular />} disabled={!rows.length} onClick={() => setAction("start")}>Start</ToolbarButton>
              <ToolbarButton icon={<ArrowClockwise20Regular />} disabled={!rows.length} onClick={() => setAction("restart")}>Restart</ToolbarButton>
              <ToolbarButton icon={<Stop20Regular />} disabled={!rows.length} onClick={() => setAction("stop")}>Stop</ToolbarButton>
            </>
          )}
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/appservices/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "status", label: "Status", value: (r) => r.properties?.state },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "tier", label: "Pricing Tier", value: (r) => (r.plan ? api.pricingTier(r.plan.sku?.name) : "--") },
            { key: "plan", label: "App Service Plan", value: (r) => r.plan?.name || api.planName(r.properties?.serverFarmId) },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "apptype", label: "App Type", value: (r) => api.appType(r.kind) },
          ]}
          emptyAction={<Link href="#/appservices/create">Create app service</Link>}
        />
      </div>

      <ActionDialog open={action === "start"} onClose={() => setAction(null)} title="Start App Service" icon={<Play20Regular />} label="Start"
        apps={rows} run={(r) => api.startSite(r.resourceGroup, r.name).then(sites.reload)} />
      <ActionDialog open={action === "restart"} onClose={() => setAction(null)} title="Restart App Service" icon={<ArrowClockwise20Regular />} label="Restart"
        apps={rows} run={(r) => api.restartSite(r.resourceGroup, r.name).then(sites.reload)} />
      <ActionDialog open={action === "stop"} onClose={() => setAction(null)} title="Stop App Service" icon={<Stop20Regular />} label="Stop"
        apps={rows} run={(r) => api.stopSite(r.resourceGroup, r.name).then(sites.reload)} />
      <AssignTagsDialog open={action === "tags"} onClose={() => setAction(null)} apps={rows} reload={sites.reload} />
      <Dialog open={action === "query"} onOpenChange={(_, d) => !d.open && setAction(null)}>
        <DialogSurface aria-label="Open query">
          <DialogBody>
            <DialogTitle>Open query</DialogTitle>
            <DialogContent><NotSimulatedContainer feature="Azure Resource Graph query editor" /></DialogContent>
            <DialogActions><Button onClick={() => setAction(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

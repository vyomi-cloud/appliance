/* Container Apps browse blade (ARM list at subscription scope). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Link, Select, ToolbarButton } from "@fluentui/react-components";
import { Play20Regular, ArrowClockwise20Regular, Stop20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

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
            <Field label="Container App" required>
              <Select value={name} onChange={(_, d) => setName(d.value)} aria-label="Container App">
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

export default function ContainerApps() {
  const notify = useNotify();
  const sub = useSubscription();
  const apps = useAsync(() => api.listApps(), [sub.id]);
  const [action, setAction] = useState(null);
  const subName = sub.displayName || sub.id;
  const rows = apps.data || [];

  return (
    <>
      <TitleRow title="Container Apps" glyph={<Glyph id="containerapps" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="container app"
          items={rows}
          loading={apps.loading}
          error={apps.error}
          onRefresh={apps.reload}
          onCreate={() => navigate("containerapps", "create")}
          onDelete={async (xs) => {
            for (const r of xs) await api.deleteApp(r.resourceGroup, r.name);
            notify.success(`Deleted ${xs.length} container app${xs.length === 1 ? "" : "s"}.`, "Delete succeeded");
            apps.reload();
          }}
          subscriptionLabel={subName}
          csvName="container-apps.csv"
          extraCommands={(
            <>
              <ToolbarButton icon={<Play20Regular />} disabled={!rows.length} onClick={() => setAction("start")}>Start</ToolbarButton>
              <ToolbarButton icon={<Stop20Regular />} disabled={!rows.length} onClick={() => setAction("stop")}>Stop</ToolbarButton>
            </>
          )}
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/containerapps/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "status", label: "Status", value: (r) => r.properties?.runningStatus },
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "environment", label: "Environment", value: (r) => api.envName(r.properties?.managedEnvironmentId) },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/containerapps/create">Create container app</Link>}
        />
      </div>

      <ActionDialog open={action === "start"} onClose={() => setAction(null)} title="Start Container App" icon={<Play20Regular />} label="Start"
        apps={rows} run={(r) => api.startApp(r.resourceGroup, r.name).then(apps.reload)} />
      <ActionDialog open={action === "stop"} onClose={() => setAction(null)} title="Stop Container App" icon={<Stop20Regular />} label="Stop"
        apps={rows} run={(r) => api.stopApp(r.resourceGroup, r.name).then(apps.reload)} />
    </>
  );
}

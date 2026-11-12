/* Function apps browse blade (ARM list at subscription scope). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select, ToolbarButton } from "@fluentui/react-components";
import { DatabaseArrowUp20Regular, Pause20Regular, PlayCircle20Regular, Search20Regular, TagMultiple20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export default function FunctionApps() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listFunctionApps(), [sub.id]);
  const subName = sub.displayName || sub.id;
  const [tags, setTags] = useState(false);

  const bulk = async (label, verb, fn) => {
    const rows = data || [];
    if (!rows.length) { notify.info("No function apps to " + label.toLowerCase() + "."); return; }
    for (const r of rows) await fn(r.resourceGroup, r.name);
    notify.success(`${label} requested for ${rows.length} function app${rows.length === 1 ? "" : "s"}.`, verb);
    reload();
  };

  return (
    <>
      <TitleRow title="Function App" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="functionapp" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="function app"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("functionapp", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteFunctionApp(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} function app${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="function-apps.csv"
          extraCommands={<>
            <ToolbarButton icon={<Search20Regular />} onClick={() => notify.info("Resource Graph Explorer isn't simulated in Vyomi.")}>Open query</ToolbarButton>
            <ToolbarButton icon={<TagMultiple20Regular />} onClick={() => setTags(true)} disabled={!(data || []).length}>Assign tags</ToolbarButton>
            <ToolbarButton icon={<PlayCircle20Regular />} onClick={() => bulk("Start", "Start", api.startFunctionApp)}>Start</ToolbarButton>
            <ToolbarButton icon={<DatabaseArrowUp20Regular />} onClick={() => bulk("Restart", "Restart", api.restartFunctionApp)}>Restart</ToolbarButton>
            <ToolbarButton icon={<Pause20Regular />} onClick={() => bulk("Stop", "Stop", api.stopFunctionApp)}>Stop</ToolbarButton>
          </>}
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/functionapp/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "status", label: "Status", value: (r) => r.properties?.state },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "tier", label: "Pricing Tier", value: (r) => r.properties?.sku || "Dynamic" },
            { key: "plan", label: "App Service Plan", value: (r) => r.properties?.serverFarmId?.split("/").pop() },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "apptype", label: "App Type", value: () => "Function App" },
          ]}
          emptyAction={<Link href="#/functionapp/create">Create function app</Link>}
        />
      </div>
      <AssignTags open={tags} onClose={() => setTags(false)} rows={data || []} onDone={reload} />
    </>
  );
}

function AssignTags({ open, onClose, rows, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [tagName, setTagName] = useState("");
  const [tagValue, setTagValue] = useState("");
  const [busy, setBusy] = useState(false);
  const row = rows.find((r) => r.name === name) || rows[0];
  const go = async () => {
    if (!row || !tagName) return;
    setBusy(true);
    try {
      await api.updateFunctionApp(row.resourceGroup, row.name, { tags: { ...row.tags, [tagName]: tagValue } });
      notify.success(`Tag '${tagName}' assigned to '${row.name}'.`, "Tags assigned");
      setTagName(""); setTagValue(""); onClose(); onDone();
    } catch (e) { notify.error(e, "Assign tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Assign tags">
        <DialogBody>
          <DialogTitle>Assign tags</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Function app"><Select value={row?.name || ""} onChange={(_, d) => setName(d.value)} aria-label="Function app">
                {rows.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
              </Select></Field>
              <Field label="Tag name"><Input value={tagName} onChange={(_, d) => setTagName(d.value)} aria-label="Tag name" /></Field>
              <Field label="Tag value"><Input value={tagValue} onChange={(_, d) => setTagValue(d.value)} aria-label="Tag value" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!row || !tagName || busy} onClick={go}>Assign</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

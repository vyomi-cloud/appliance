/* Stream Analytics jobs browse blade + create dialog (one native ARM PUT). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { DEFAULT_RG, LOCATIONS, listResourceGroups } from "../../kit/arm.js";
import { ErrorBar, Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const rgOf = (id = "") => (id.split("/resourceGroups/")[1] || "").split("/")[0];

export default function Jobs() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listJobs(), [sub.id]);
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", rg: DEFAULT_RG, location: "eastus", compat: "1.2" });
  const [err, setErr] = useState(null);
  const create = async () => {
    setErr(null);
    try {
      await api.createJob(f.rg, f.name, { location: f.location, sku: { name: "Standard" }, properties: { compatibilityLevel: f.compat } });
      notify.success(`Created Stream Analytics job ${f.name}.`, "Deployment succeeded");
      setOpen(false); reload();
    } catch (e) { setErr(e); }
  };
  return (
    <>
      <TitleRow title="Stream Analytics jobs" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="eventgrid" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          tools resourceName="Stream Analytics job" items={data || []} loading={loading} error={error} onRefresh={reload}
          onCreate={() => setOpen(true)}
          onDelete={async (rows) => { for (const r of rows) await api.deleteJob(rgOf(r.id), r.name); reload(); }}
          subscriptionLabel={sub.displayName || sub.id} csvName="stream-analytics-jobs.csv"
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/streamanalytics/${encodeURIComponent(rgOf(r.id))}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "status", label: "Status", value: (r) => r.properties?.jobState },
            { key: "resourceGroup", label: "Resource group", value: (r) => rgOf(r.id) },
            { key: "location", label: "Location", value: (r) => r.location },
            { key: "su", label: "Streaming units", value: (r) => r.properties?.transformation?.properties?.streamingUnits ?? "--" },
          ]}
          emptyAction={<Link as="button" onClick={() => setOpen(true)}>Create Stream Analytics job</Link>}
        />
      </div>
      <Dialog open={open} onOpenChange={(_, d) => !d.open && setOpen(false)}>
        <DialogSurface aria-label="New Stream Analytics job">
          <DialogBody>
            <DialogTitle>New Stream Analytics job</DialogTitle>
            <DialogContent>
              <ErrorBar error={err} title="Creation failed" />
              <Field label="Job name" required><Input aria-label="Job name" value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} /></Field>
              <Field label="Resource group">
                <Select aria-label="Resource group" value={f.rg} onChange={(_, d) => setF({ ...f, rg: d.value })}>
                  {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
                </Select>
              </Field>
              <Field label="Region">
                <Select aria-label="Region" value={f.location} onChange={(_, d) => setF({ ...f, location: d.value })}>
                  {LOCATIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                </Select>
              </Field>
              <Field label="Compatibility level">
                <Select aria-label="Compatibility level" value={f.compat} onChange={(_, d) => setF({ ...f, compat: d.value })}>{["1.0", "1.1", "1.2"].map((v) => <option key={v}>{v}</option>)}</Select>
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={create}>Create</Button>
              <Button onClick={() => setOpen(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

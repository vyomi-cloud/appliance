/* Recovery Services vaults / Backup center browse blade + create dialog. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { ErrorBar, Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const NAME_RE = /^[A-Za-z][A-Za-z0-9-]{1,49}$/;

export default function Vaults() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listVaults(), [sub.id]);
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ rg: DEFAULT_RG, name: "", location: "eastus" });
  const [err, setErr] = useState(null);
  const create = async () => {
    setErr(null);
    if (!NAME_RE.test(f.name)) { setErr({ message: "The vault name must be 2-50 characters, start with a letter and contain only letters, numbers and hyphens." }); return; }
    try {
      await api.createVault(f.rg, f.name, { location: f.location, sku: { name: "RS0", tier: "Standard" }, properties: {} });
      notify.success(`Recovery Services vault '${f.name}' was created.`, "Deployment succeeded");
      setOpen(false); setF({ ...f, name: "" }); reload();
    } catch (e) { setErr(e); }
  };
  return (
    <>
      <TitleRow title="Backup center | Recovery Services vaults" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="recoveryservices" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid tools resourceName="Recovery Services vault" items={data || []} loading={loading} error={error} onRefresh={reload} onCreate={() => { setErr(null); setOpen(true); }}
          onDelete={async (rows) => { for (const r of rows) await api.deleteVault(r.resourceGroup, r.name); notify.success(`Deleted ${rows.length} vault(s).`, "Delete succeeded"); reload(); }}
          subscriptionLabel={sub.displayName || sub.id} csvName="recovery-services-vaults.csv"
          pills={[{ key: "rg", label: "Resource group", value: (r) => r.resourceGroup }, { key: "loc", label: "Location", value: (r) => locationLabel(r.location) }]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/recoveryservices/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "type", label: "Type", value: () => "Recovery Services vault" },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => sub.displayName || sub.id },
          ]}
          emptyAction={<Link as="button" onClick={() => setOpen(true)}>Create</Link>} />
      </div>
      <Dialog open={open} onOpenChange={(_, d) => !d.open && setOpen(false)}>
        <DialogSurface aria-label="Create Recovery Services vault"><DialogBody>
          <DialogTitle>Create Recovery Services vault</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <ErrorBar error={err} title="Could not create the vault" />
            <Field label="Resource group" required><Select value={f.rg} onChange={(_, d) => setF({ ...f, rg: d.value })} aria-label="Resource group">
              {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}</Select></Field>
            <Field label="Vault name" required><Input value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} aria-label="Vault name" /></Field>
            <Field label="Region" required><Select value={f.location} onChange={(_, d) => setF({ ...f, location: d.value })} aria-label="Region">
              {LOCATIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</Select></Field>
          </div></DialogContent>
          <DialogActions><Button appearance="primary" onClick={create}>Create</Button><Button onClick={() => setOpen(false)}>Cancel</Button></DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </>
  );
}

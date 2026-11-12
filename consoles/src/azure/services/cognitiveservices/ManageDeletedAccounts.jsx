/* "Manage deleted accounts" — soft-deleted Microsoft.CognitiveServices/accounts, restorable
 * (PUT ... properties.restore=true, re-specifying kind/sku like `az cognitiveservices account
 * create` does for a real soft-deleted resource) or purgeable (DELETE deletedAccounts/{name}). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Select, ToolbarButton } from "@fluentui/react-components";
import { Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { Glyph, fmtDate } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import * as api from "./api.js";

export default function ManageDeletedAccounts() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDeletedAccounts(), []);
  const [restoring, setRestoring] = useState(null); // row
  const [purging, setPurging] = useState(null); // selected rows
  const rows = data || [];
  return (
    <>
      <TitleRow title="Manage deleted accounts" subtitle="Azure AI services" glyph={<Glyph id="cognitiveservices" />} closeHref="#/cognitiveservices" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="deleted account"
          items={rows}
          loading={loading}
          error={error}
          onRefresh={reload}
          csvName="deleted-accounts.csv"
          extraCommands={(selected) => (
            <>
              <ToolbarButton disabled={selected.length !== 1} onClick={() => setRestoring(selected[0])}>Restore</ToolbarButton>
              <ToolbarButton icon={<Delete20Regular />} disabled={!selected.length} onClick={() => setPurging(selected)}>Purge</ToolbarButton>
            </>
          )}
          columns={[
            { key: "name", label: "Name" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "deletionDate", label: "Deletion date", value: (r) => fmtDate(r.properties?.deletionDate) },
            { key: "purgeDate", label: "Scheduled purge date", value: (r) => fmtDate(r.properties?.scheduledPurgeDate) },
            { key: "resourceGroup", label: "Resource group", value: (r) => api.parseDeletedId(r.id).resourceGroup },
          ]}
        />
      </div>
      <RestoreDialog row={restoring} onClose={() => setRestoring(null)} onRestored={reload} />
      {purging && (
        <DeleteDialog open={!!purging} onClose={() => setPurging(null)} resourceType="deleted account" names={purging.map((r) => r.name)}
          confirmText={purging.length > 1 ? "delete" : undefined}
          onConfirm={async () => {
            for (const r of purging) {
              const { location, resourceGroup } = api.parseDeletedId(r.id);
              await api.purgeDeletedAccount(location, resourceGroup, r.name);
            }
            notify.success(`Purged ${purging.length} account${purging.length === 1 ? "" : "s"}.`, "Purge succeeded");
            reload();
          }} />
      )}
    </>
  );
}

function RestoreDialog({ row, onClose, onRestored }) {
  const notify = useNotify();
  const [kind, setKind] = useState("OpenAI");
  const [sku, setSku] = useState("S0");
  const [busy, setBusy] = useState(false);
  if (!row) return null;
  const { location, resourceGroup } = api.parseDeletedId(row.id);
  const go = async () => {
    setBusy(true);
    try {
      await api.restoreAccount(resourceGroup, row.name, location, kind, sku);
      notify.success(`Account '${row.name}' was restored.`, "Restore succeeded");
      onClose();
      onRestored();
    } catch (e) { notify.error(e, "Restore failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={!!row} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Restore account">
        <DialogBody>
          <DialogTitle>Restore '{row.name}'</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <p style={{ fontSize: 13 }}>Re-enter the kind and pricing tier the account had when it was deleted — the same information <code>az cognitiveservices account create</code> needs to restore a soft-deleted resource.</p>
              <Field label="Kind" required>
                <Select value={kind} onChange={(_, d) => setKind(d.value)} aria-label="Kind">
                  {Object.keys(api.KINDS).map((k) => <option key={k} value={k}>{api.KIND_LABEL[k] || k}</option>)}
                </Select>
              </Field>
              <Field label="Pricing tier" required>
                <Select value={sku} onChange={(_, d) => setSku(d.value)} aria-label="Pricing tier">
                  {(api.KINDS[kind] || ["S0"]).map((s) => <option key={s} value={s}>{s}</option>)}
                </Select>
              </Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy} onClick={go}>{busy ? "Restoring..." : "Restore"}</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

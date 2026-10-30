/* Named values panel: real ARM sub-resource of the service. "Key vault" named values store
 * the reference exactly as configured (config_only) — Vyomi never resolves the live secret,
 * matching the real portal's own grid, which also never shows the resolved value. */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Radio, RadioGroup,
  ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;

export default function NamedValues({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.NamedValues.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <>
      <div className="vy-panel-title">{svc} | Named values</div>
      <BrowseGrid
        resourceName="named value" rowKey={(r) => r.name} filterPlaceholder="Search named values"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.NamedValues.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} named value${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="named-values.csv"
        columns={[
          { key: "name", label: "Name", value: (r) => r.properties?.displayName || r.name },
          { key: "type", label: "Type", value: (r) => (r.properties?.keyVault ? "Key Vault" : r.properties?.secret ? "Secret" : "Plain") },
          { key: "value", label: "Value", value: (r) => r.properties?.keyVault ? "(from Key Vault)" : r.properties?.secret ? "••••••••" : r.properties?.value },
          { key: "tags", label: "Tags", value: (r) => (r.properties?.tags || []).join(", ") || "--" },
        ]}
      />
      <AddNamedValueDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.NamedValues.put(rg, svc, id, body); reload(); }} />
    </>
  );
}

function AddNamedValueDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ name: "", type: "Plain", value: "", secretIdentifier: "", tags: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.name) && !existing.some((v) => v.name.toLowerCase() === f.name.toLowerCase())
    && (f.type === "Key Vault" ? f.secretIdentifier.trim() : f.value.trim());
  const go = async () => {
    setBusy(true);
    try {
      const tags = f.tags.split(",").map((t) => t.trim()).filter(Boolean);
      const properties = f.type === "Key Vault"
        ? { displayName: f.name, secret: true, keyVault: { secretIdentifier: f.secretIdentifier }, tags }
        : { displayName: f.name, secret: f.type === "Secret", value: f.value, tags };
      await onCreate(f.name, { properties });
      notify.success(`Named value '${f.name}' was created.`, "Create succeeded");
      setF({ name: "", type: "Plain", value: "", secretIdentifier: "", tags: "" });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add named value">
        <DialogBody>
          <DialogTitle>Add named value</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Name" /></Field>
              <Field label="Type">
                <RadioGroup value={f.type} onChange={(_, d) => setF((x) => ({ ...x, type: d.value }))} aria-label="Type">
                  <Radio value="Plain" label="Plain" /><Radio value="Secret" label="Secret" /><Radio value="Key Vault" label="Key Vault" />
                </RadioGroup>
              </Field>
              {f.type === "Key Vault"
                ? <Field label="Key Vault secret identifier" required><Input value={f.secretIdentifier} onChange={(_, d) => setF((x) => ({ ...x, secretIdentifier: d.value }))} placeholder="https://{vault}.vault.azure.net/secrets/{name}" aria-label="Key Vault secret identifier" /></Field>
                : <Field label="Value" required><Input type={f.type === "Secret" ? "password" : "text"} value={f.value} onChange={(_, d) => setF((x) => ({ ...x, value: d.value }))} aria-label="Value" /></Field>}
              <Field label="Tags (comma-separated)"><Input value={f.tags} onChange={(_, d) => setF((x) => ({ ...x, tags: d.value }))} aria-label="Tags" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Save</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

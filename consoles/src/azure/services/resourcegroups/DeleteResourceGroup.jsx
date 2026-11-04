/* Delete a resource group: the dedicated confirmation page (not a small dialog — the real
 * portal shows the dependent-resources table and the force-delete checkbox as a full blade). */
import { useState } from "react";
import { Button, Checkbox, Field, Input, MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { Glyph, ErrorBar, Loading, NotSimulated } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { forget } from "../../kit/recent.js";
import * as api from "./api.js";

export default function DeleteResourceGroup({ params }) {
  const { name } = params;
  const notify = useNotify();
  const resources = useAsync(() => api.listResources(name), [name]);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const self = `#/resourcegroups/${encodeURIComponent(name)}`;

  const go = async () => {
    setBusy(true); setError(null);
    try {
      await api.deleteGroup(name);
      forget(self);
      notify.success(`Resource group '${name}' was deleted.`, "Delete succeeded");
      navigate("resourcegroups");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <>
      <TitleRow title="Delete a resource group" subtitle={name} glyph={<Glyph id="resourcegroups" />} closeHref={self} />
      <div className="vy-page" style={{ maxWidth: 760 }}>
        <MessageBar intent="warning" style={{ margin: "8px 0" }}>
          <MessageBarBody>
            <MessageBarTitle>Deleting resource group "{name}" permanently deletes it and ALL of its resources.</MessageBarTitle>
            This action can't be undone.
          </MessageBarBody>
        </MessageBar>

        <section className="vy-form-section"><h3>Dependent resources to be deleted</h3>
          {resources.loading ? <Loading /> : (
            <table className="vy-grid">
              <thead><tr><th>Name</th><th>Resource type</th></tr></thead>
              <tbody>
                {(resources.data || []).length ? resources.data.map((r) => <tr key={r.id}><td>{r.name}</td><td>{r.type}</td></tr>)
                  : <tr><td colSpan={2} className="vy-muted">This resource group has no resources.</td></tr>}
              </tbody>
            </table>
          )}
        </section>

        <section className="vy-form-section">
          <Checkbox disabled label="Apply force delete for selected Virtual machines and Virtual machine scale sets" />
          <NotSimulated feature="Force delete" note="Every delete in Vyomi already removes the whole group unconditionally and synchronously, so there is no graceful VM/VMSS deprovisioning sequence to skip." />
        </section>

        {error && <ErrorBar error={error} title="Delete failed" />}
        <Field label={<span>Enter resource group name to confirm deletion</span>} required>
          <Input value={typed} placeholder={name} onChange={(_, d) => setTyped(d.value)} aria-label="Enter resource group name to confirm deletion" />
        </Field>

        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <Button appearance="primary" style={typed === name ? { background: "var(--colorPaletteRedBackground3)" } : undefined} disabled={typed !== name || busy} onClick={go}>
            {busy ? "Deleting..." : "Delete"}
          </Button>
          <Button as="a" href={self} onClick={() => setTyped("")}>Cancel</Button>
        </div>
      </div>
    </>
  );
}

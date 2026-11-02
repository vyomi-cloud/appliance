/* Identity blade body for a generic ARM resource: system assigned managed identity is real
 * (core/azure_arm_core.py _apply_identity mints a stable principalId/tenantId usable as an IAM
 * subject); user assigned lists identities by resource id attached to the resource. `patch(body)`
 * is the service's ARM PATCH. */
import { useState } from "react";
import { Field, Radio, RadioGroup } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { CapabilityContainer } from "./Capability.jsx";
import { KV } from "./common.jsx";

export default function ResourceIdentity({ a, name, patch, reload, capId }) {
  const notify = useNotify();
  const ident = a.identity || { type: "None" };
  const on = /systemassigned/i.test(ident.type || "");
  const [busy, setBusy] = useState(false);
  const toggle = async (enable) => {
    setBusy(true);
    try {
      await patch({ identity: { type: enable ? "SystemAssigned" : "None" } });
      notify.success(`System assigned managed identity was turned ${enable ? "on" : "off"} for '${name}'.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Identity</div>
      <CapabilityContainer id={capId} title="System assigned">
        <p style={{ fontSize: 13, maxWidth: 640 }}>A system assigned managed identity is restricted to one per resource. It is deleted when the resource itself is deleted.</p>
        <Field label="Status"><RadioGroup value={on ? "On" : "Off"} onChange={(_, d) => toggle(d.value === "On")} aria-label="Status">
          <Radio value="On" label="On" disabled={busy} /><Radio value="Off" label="Off" disabled={busy} />
        </RadioGroup></Field>
        {on && (
          <div className="vy-props" style={{ marginTop: 8 }}>
            <KV label="Object (principal) ID" value={ident.principalId} />
            <KV label="Tenant ID" value={ident.tenantId} />
          </div>
        )}
      </CapabilityContainer>
    </>
  );
}

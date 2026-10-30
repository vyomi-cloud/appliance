/* Default Directory | Properties — Name is real (it's the tenant's displayName, shown on
 * Overview too); the contact fields are config_only. Access management for Azure
 * resources / security defaults are a genuinely separate subsystem Vyomi doesn't model. */
import { useState } from "react";
import { Button, Input } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { saveNotice } from "../../kit/Capability.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";

export default function Properties() {
  const notify = useNotify();
  const org = useAsync(() => api.getOrganization(), []);
  const [draft, setDraft] = useState(null);
  const o = draft || org.data;
  if (org.loading && !o) return <EntraShell active="properties" title="Default Directory | Properties"><div className="vy-page">Loading...</div></EntraShell>;
  if (!o) return <EntraShell active="properties" title="Default Directory | Properties"><div className="vy-page">Failed to load tenant properties.</div></EntraShell>;

  const set = (patch) => setDraft({ ...o, ...patch });
  const save = async () => {
    await api.updateOrganization(o.id, {
      displayName: o.displayName,
      technicalNotificationMails: o.technicalNotificationMails,
      privacyProfile: o.privacyProfile,
    });
    notify.success(`Saved.${saveNotice("azure.entra.organization_properties")}`, "Properties");
    setDraft(null); org.reload();
  };

  return (
    <EntraShell active="properties" title="Default Directory | Properties">
      <div className="vy-page">
        <div className="vy-cmdbar" role="toolbar" aria-label="Properties commands">
          <Button appearance="primary" onClick={save}>Save</Button>
          <Button onClick={() => setDraft(null)}>Discard</Button>
        </div>
        <section className="vy-form-section">
          <h3>Properties</h3>
          <div className="vy-form-row"><label className="req">Name</label><Input value={o.displayName} onChange={(_, d) => set({ displayName: d.value })} style={{ width: 300 }} /></div>
          <div className="vy-kv"><span>Tenant Country/Region</span><span>United States</span></div>
          <div className="vy-kv"><span>Data location (Primary Copy)</span><span>United States</span></div>
          <div className="vy-kv"><span>Notification language</span><span>English</span></div>
          <div className="vy-kv"><span>Tenant ID</span><span>{o.id}</span></div>
          <div className="vy-form-row"><label>Technical contact</label><Input value={o.technicalNotificationMails?.[0] || ""} onChange={(_, d) => set({ technicalNotificationMails: [d.value] })} style={{ width: 300 }} /></div>
          <div className="vy-form-row"><label>Global privacy contact</label><Input value={o.privacyProfile?.contactEmail || ""} onChange={(_, d) => set({ privacyProfile: { ...o.privacyProfile, contactEmail: d.value } })} style={{ width: 300 }} /></div>
          <div className="vy-form-row"><label>Privacy statement URL</label><Input value={o.privacyProfile?.statementUrl || ""} onChange={(_, d) => set({ privacyProfile: { ...o.privacyProfile, statementUrl: d.value } })} style={{ width: 300 }} /></div>
        </section>
        <NotSimulatedContainer title="Access management for Azure resources" feature="Access management for Azure resources"
          note="Whether Global Administrators can manage Azure subscriptions and management groups. Not simulated in Vyomi." />
        <NotSimulatedContainer title="Security defaults" feature="Manage security defaults"
          note="Manage security defaults. Baseline conditional-access-style policy is not simulated in Vyomi." />
      </div>
    </EntraShell>
  );
}

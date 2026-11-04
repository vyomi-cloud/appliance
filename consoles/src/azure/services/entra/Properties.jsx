/* Default Directory | Properties — Name is real (it's the tenant's displayName, shown on
 * Overview too); the contact fields are config_only. "Access management for Azure
 * resources" really grants/revokes a tenant-root "User Access Administrator" role
 * assignment over the same Azure RBAC checkAccess engine every subscription's Access
 * control (IAM) page uses. "Security defaults" is a real Graph policy document, stored
 * and returned exactly as set (azure.entra.security_defaults — see its limitations for
 * what each still doesn't enforce). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Input, Radio, RadioGroup } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";

const YN = ({ value, onChange, label }) => (
  <RadioGroup value={value ? "Yes" : "No"} layout="horizontal" aria-label={label} onChange={(_, d) => onChange(d.value === "Yes")}>
    <Radio value="Yes" label="Yes" /><Radio value="No" label="No" />
  </RadioGroup>
);

export default function Properties() {
  const notify = useNotify();
  const org = useAsync(() => api.getOrganization(), []);
  const assignments = useAsync(() => api.listRoleAssignments(), []);
  const secDefaults = useAsync(() => api.getSecurityDefaults(), []);
  const [draft, setDraft] = useState(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [sdDraft, setSdDraft] = useState(null);
  const [elevatedOverride, setElevatedOverride] = useState(null);
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

  const elevation = (assignments.data || []).find((a) => a.properties.principalId === api.ELEVATED_ADMIN_PRINCIPAL
    && a.properties.roleDefinitionId === api.ELEVATE_ROLE_NAME && a.properties.scope === "/");
  const elevated = elevatedOverride ?? !!elevation;
  const setElevated = async (yes) => {
    setElevatedOverride(yes);
    if (yes && !elevation) await api.assignRole(api.ELEVATE_ROLE_NAME, api.ELEVATED_ADMIN_PRINCIPAL, "/");
    if (!yes && elevation) await api.deleteRoleAssignment(elevation.name);
    notify.success(`Access management for Azure resources set to ${yes ? "Yes" : "No"}.${saveNotice("azure.entra.security_defaults")}`, "Properties");
    await assignments.reload();
    setElevatedOverride(null);
  };

  const openManage = () => { setSdDraft(secDefaults.data?.isEnabled ?? true); setManageOpen(true); };
  const saveSecurityDefaults = async () => {
    await api.updateSecurityDefaults({ isEnabled: sdDraft });
    notify.success(`Security defaults ${sdDraft ? "enabled" : "disabled"}.${saveNotice("azure.entra.security_defaults")}`, "Security defaults");
    setManageOpen(false); secDefaults.reload();
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
        <CapabilityContainer id="azure.entra.security_defaults" title="Access management for Azure resources">
          <div className="vy-form-row">
            <label>Access management for Azure resources</label>
            {assignments.loading ? "Loading..." : <YN value={elevated} onChange={setElevated} label="Access management for Azure resources" />}
          </div>
        </CapabilityContainer>
        <CapabilityContainer id="azure.entra.security_defaults" title="Security defaults">
          <div className="vy-form-row">
            <label>{secDefaults.data ? `Security defaults: ${secDefaults.data.isEnabled ? "Enabled" : "Disabled"}` : "Security defaults"}</label>
            <Button onClick={openManage} disabled={secDefaults.loading}>Manage security defaults</Button>
          </div>
        </CapabilityContainer>
      </div>
      <Dialog open={manageOpen} onOpenChange={(_, d) => setManageOpen(d.open)}>
        <DialogSurface aria-label="Enable security defaults">
          <DialogBody>
            <DialogTitle>Enable security defaults</DialogTitle>
            <DialogContent>
              <p>Security defaults is a set of basic identity security mechanisms recommended by Microsoft.</p>
              <YN value={!!sdDraft} onChange={setSdDraft} label="Enable security defaults" />
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={saveSecurityDefaults}>Save</Button>
              <Button onClick={() => setManageOpen(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </EntraShell>
  );
}

/* Default Directory | User settings — limited (azure.entra.directory_settings):
 * "Users can create security groups" and "Users can register applications" are really
 * enforced on group/application creation (tenant-wide, since Vyomi has no signed-in
 * identity to exempt admins). The rest are stored and returned exactly as set. */
import { useState } from "react";
import { Radio, RadioGroup, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { saveNotice } from "../../kit/Capability.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";

const YN = ({ value, onChange }) => (
  <RadioGroup value={value ? "Yes" : "No"} layout="horizontal" onChange={(_, d) => onChange(d.value === "Yes")}>
    <Radio value="Yes" label="Yes" /><Radio value="No" label="No" />
  </RadioGroup>
);

export default function UserSettings() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getDirectorySettings(), []);
  const [s, setS] = useState(null);
  const settings = s || data;
  const save = async (patch) => {
    const next = { ...settings, ...patch };
    setS(next);
    await api.updateDirectorySettings(patch);
    notify.success(`Setting saved.${saveNotice("azure.entra.directory_settings")}`, "User settings");
  };
  if (loading && !settings) return <EntraShell active="usersettings" title="Default Directory | User settings"><div className="vy-page">Loading...</div></EntraShell>;
  if (error) return <EntraShell active="usersettings" title="Default Directory | User settings"><div className="vy-page">Failed to load settings.</div></EntraShell>;

  return (
    <EntraShell active="usersettings" title="Default Directory | User settings">
      <div className="vy-page">
        <div className="vy-cmdbar" role="toolbar" aria-label="User settings commands">
          <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        </div>
        <section className="vy-form-section">
          <h3>Default user role permissions</h3>
          <div className="vy-form-row"><label>Users can register applications</label><YN value={settings.usersCanRegisterApplications} onChange={(v) => save({ usersCanRegisterApplications: v })} /></div>
          <div className="vy-form-row"><label>Users can register agent identity blueprints</label><YN value={settings.usersCanRegisterAgentIdentityBlueprints} onChange={(v) => save({ usersCanRegisterAgentIdentityBlueprints: v })} /></div>
          <div className="vy-form-row"><label>Restrict non-admin users from creating tenants</label><YN value={settings.restrictNonAdminUsersFromCreatingTenants} onChange={(v) => save({ restrictNonAdminUsersFromCreatingTenants: v })} /></div>
          <div className="vy-form-row"><label>Users can create security groups</label><YN value={settings.usersCanCreateSecurityGroups} onChange={(v) => save({ usersCanCreateSecurityGroups: v })} /></div>
        </section>
        <section className="vy-form-section">
          <h3>Guest user access</h3>
          <div className="vy-form-row">
            <label>Guest user access restrictions</label>
            <RadioGroup value={settings.guestUserAccess} onChange={(_, d) => save({ guestUserAccess: d.value })}>
              <Radio value="Guest users have the same access as members (most inclusive)" label="Guest users have the same access as members (most inclusive)" />
              <Radio value="Guest users have limited access to properties and memberships of directory objects" label="Guest users have limited access to properties and memberships of directory objects" />
              <Radio value="Guest user access is restricted to properties and memberships of their own directory objects (most restrictive)" label="Guest user access is restricted to properties and memberships of their own directory objects (most restrictive)" />
            </RadioGroup>
          </div>
        </section>
        <section className="vy-form-section">
          <h3>Administration center</h3>
          <div className="vy-form-row"><label>Restrict access to Microsoft Entra admin center</label><YN value={settings.restrictAccessToAdminCenter} onChange={(v) => save({ restrictAccessToAdminCenter: v })} /></div>
        </section>
        <section className="vy-form-section">
          <h3>LinkedIn account connections</h3>
          <div className="vy-form-row">
            <label>Allow users to connect their work or school account with LinkedIn</label>
            <RadioGroup value={settings.linkedInConnections} onChange={(_, d) => save({ linkedInConnections: d.value })}>
              <Radio value="Yes" label="Yes" /><Radio value="Selected group" label="Selected group" /><Radio value="No" label="No" />
            </RadioGroup>
          </div>
        </section>
        <section className="vy-form-section">
          <h3>Show keep user signed in</h3>
          <div className="vy-form-row"><label>Show keep user signed in</label><YN value={settings.showKeepUserSignedIn} onChange={(v) => save({ showKeepUserSignedIn: v })} /></div>
        </section>
      </div>
    </EntraShell>
  );
}

/* The Default Directory's small dashboard blades: Overview, Groups | Overview,
 * External Identities | Overview, Devices | Overview. Real counts over the live
 * directory; the quick-action buttons navigate to the real create flows. Device
 * management (MDM/BitLocker) genuinely isn't modelled — its Quick actions are an
 * honest declared gap, not a disabled stub. */
import { useState } from "react";
import { Button, Tab, TabList } from "@fluentui/react-components";
import EntraShell from "./EntraShell.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

const KV = ({ label, value }) => <div className="vy-kv"><span>{label}</span><span>{value ?? "--"}</span></div>;

export function Overview() {
  const [tab, setTab] = useState("overview");
  const org = useAsync(() => api.getOrganization(), []);
  const users = useAsync(() => api.listUsers(), []);
  const groups = useAsync(() => api.listGroups(), []);
  const apps = useAsync(() => api.listApplications(), []);
  const o = org.data;
  return (
    <EntraShell active="overview" title="Default Directory | Overview">
      <div className="vy-page">
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Default Directory">
          <Tab value="overview">Overview</Tab>
          <Tab value="monitoring">Monitoring</Tab>
          <Tab value="properties">Properties</Tab>
          <Tab value="recommendations">Recommendations</Tab>
          <Tab value="setupguides">Setup guides</Tab>
        </TabList>
        {tab === "overview" && (
          <>
            <section className="vy-form-section">
              <h3>Basic information</h3>
              <div className="vy-essentials-grid">
                <div>
                  <KV label="Name" value={o?.displayName} />
                  <KV label="Tenant ID" value={o?.id} />
                  <KV label="Primary domain" value={o?.verifiedDomains?.[0]?.name} />
                  <KV label="License" value="Microsoft Entra ID Free" />
                </div>
                <div>
                  <KV label="Users" value={users.data?.length} />
                  <KV label="Groups" value={groups.data?.length} />
                  <KV label="Applications" value={apps.data?.length} />
                  <KV label="Devices" value={0} />
                </div>
              </div>
            </section>
            <section className="vy-form-section"><h3>Alerts</h3><p>No alerts right now.</p></section>
            <section className="vy-form-section"><h3>My feed</h3><p>Recent directory activity is on <a href="#/entra/auditlogs">Audit logs</a>.</p></section>
            <section className="vy-form-section"><h3>Feature highlights</h3><p>Manage users, groups and app registrations against Vyomi's real simulated directory.</p></section>
            <section className="vy-form-section">
              <h3>Quick actions</h3>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <Button appearance="primary" as="a" href="#/entra/users/create">Add user</Button>
                <Button as="a" href="#/entra/groups/new">Add group</Button>
                <Button as="a" href="#/entra/enterpriseapps">Add enterprise application</Button>
                <Button as="a" href="#/entra/appregistrations/register">Add application registration</Button>
              </div>
            </section>
          </>
        )}
        {tab !== "overview" && <div style={{ padding: "12px 0" }}>Nothing new to report.</div>}
      </div>
    </EntraShell>
  );
}

export function GroupsOverview() {
  const [tab, setTab] = useState("overview");
  const groups = useAsync(() => api.listGroups(), []);
  const gs = groups.data || [];
  const count = (pred) => gs.filter(pred).length;
  return (
    <EntraShell active="groups" title="Groups | Overview">
      <div className="vy-page">
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Groups">
          <Tab value="overview">Overview</Tab>
          <Tab value="tutorials">Tutorials</Tab>
        </TabList>
        {tab === "overview" && (
          <>
            <section className="vy-form-section">
              <h3>Basic information</h3>
              <div className="vy-essentials-grid">
                <div>
                  <KV label="Total groups" value={<a href="#/entra/groups/all">{gs.length}</a>} />
                  <KV label="M365 groups" value={count((g) => g.groupTypes?.includes("Unified"))} />
                  <KV label="Security groups" value={count((g) => g.securityEnabled)} />
                </div>
                <div>
                  <KV label="Dynamic groups" value={count((g) => g.membershipType === "Dynamic")} />
                  <KV label="Cloud groups" value={count((g) => !g.onPremisesSyncEnabled)} />
                  <KV label="On-premises groups" value={count((g) => g.onPremisesSyncEnabled)} />
                </div>
              </div>
            </section>
            <section className="vy-form-section">
              <h3>Quick actions</h3>
              <div style={{ display: "flex", gap: 8 }}>
                <Button appearance="primary" as="a" href="#/entra/groups/new">Add group</Button>
                <Button onClick={() => downloadGroupsCsv(gs)}>Download groups</Button>
              </div>
            </section>
          </>
        )}
        {tab === "tutorials" && <div style={{ padding: "12px 0" }}>See <a href="#/entra/groups/new">New Group</a> to get started.</div>}
      </div>
    </EntraShell>
  );
}

function downloadGroupsCsv(groups) {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const text = ["Name,Object Id,Group type,Membership type,Email,Source", ...groups.map((g) =>
    [g.displayName, g.id, g.groupTypes?.includes("Unified") ? "Microsoft 365" : "Security", g.membershipType, g.mail, g.onPremisesSyncEnabled ? "Windows Server AD" : "Cloud"].map(esc).join(","))].join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = "groups.csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function ExternalIdentities() {
  return (
    <EntraShell active="externalidentities" title="External Identities | Overview">
      <div className="vy-page">
        <section className="vy-form-section">
          <h3>Get started with External Identities</h3>
          <p>Collaborate with guest users from other organizations, or configure external authentication for your own apps. Invite a guest from <a href="#/entra/users">Users</a> with User type set to Guest.</p>
        </section>
      </div>
    </EntraShell>
  );
}

export function DevicesOverview() {
  const [tab, setTab] = useState("overview");
  return (
    <EntraShell active="devices" title="Devices | Overview">
      <div className="vy-page">
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Devices">
          <Tab value="overview">Overview</Tab>
          <Tab value="monitoring">Monitoring</Tab>
          <Tab value="tutorials">Tutorials</Tab>
        </TabList>
        {tab === "overview" && (
          <>
            <section className="vy-form-section">
              <h3>Alerts</h3>
              <div className="vy-essentials-grid">
                <div>
                  <KV label="Stale devices" value={0} />
                  <KV label="Noncompliant devices" value={0} />
                </div>
                <div>
                  <KV label="Unmanaged devices" value={0} />
                </div>
              </div>
            </section>
            <NotSimulatedContainer title="Quick actions" feature="Device management"
              note="Download devices. BitLocker keys. Device registration (MDM/Intune) is a separate subsystem Vyomi does not model." />
          </>
        )}
        {tab !== "overview" && <div style={{ padding: "12px 0" }}>No device data to show.</div>}
      </div>
    </EntraShell>
  );
}

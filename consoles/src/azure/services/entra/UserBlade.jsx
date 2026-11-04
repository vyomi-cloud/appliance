/* A user's own resource blade — the Entra ID peer of StorageAccountBlade.jsx. Overview,
 * Groups, Assigned roles and Devices read the real directory; the remaining menu items
 * are reference-only in the spec (title captured, no further structure), so they render
 * honestly as just their title — there is nothing further to fake. Devices registers a
 * real Microsoft Graph device object (core/azure_graph_core.py) — Vyomi has no OS-level
 * join client, so registration is a direct admin action here rather than a device
 * signing itself in, but the result is a real, listable, deletable directory object. */
import { useState } from "react";
import {
  Button, Field, Input, Link, Select, Tab, TabList, ToolbarButton,
  Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete16Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { ErrorBar, Glyph, KV, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "auditlogs", label: "Audit logs" },
  { id: "signinlogs", label: "Sign-in logs" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "customsecurityattributes", label: "Custom security attributes" },
  { id: "assignedroles", label: "Assigned roles" },
  { id: "administrativeunits", label: "Administrative units" },
  { id: "groups", label: "Groups" },
  { id: "applications", label: "Applications" },
  { id: "licenses", label: "Licenses" },
  { id: "devices", label: "Devices" },
  { id: "azureroleassignments", label: "Azure role assignments" },
  { id: "authenticationmethods", label: "Authentication methods" },
];
const LABEL = Object.fromEntries(MENU.map((m) => [m.id, m.label]));

export default function UserBlade({ params }) {
  const { id, panel = "overview" } = params;
  const u = useAsync(() => api.getUser(id), [id]);
  const self = `#/entra/users/${encodeURIComponent(id)}`;

  let body;
  if (u.loading && !u.data) body = <Loading />;
  else if (u.error) body = <><ErrorBar error={u.error} title="Failed to load the user" /><Link href="#/entra/users">Back to Users</Link></>;
  else {
    const user = u.data, reload = u.reload;
    const P = {
      overview: () => <Overview user={user} reload={reload} self={self} />,
      groups: () => <Groups user={user} />,
      assignedroles: () => <AssignedRoles user={user} />,
      devices: () => <Devices user={user} />,
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{`${user.displayName} | ${LABEL[panel] || panel}`}</div>
        <p>Nothing further to show here for this user.</p>
      </>
    );
  }

  return (
    <ResourceBlade title={u.data?.displayName || id} subtitle="User" glyph={<Glyph id="entra" />} closeHref="#/entra/users"
      menu={MENU} active={panel} hrefFor={(pid) => (pid === "overview" ? self : `${self}/${pid}`)}>
      {body}
    </ResourceBlade>
  );
}

function Overview({ user, reload, self }) {
  const notify = useNotify();
  const [tab, setTab] = useState("overview");
  const [del, setDel] = useState(false);
  const groups = useAsync(() => api.userMemberOf(user.id), [user.id]);
  const roles = useAsync(() => api.listRoleAssignments(), [user.id]);
  const myRoles = (roles.data || []).filter((a) => a.properties.principalId === user.id);
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="User commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="User">
        <Tab value="overview">Overview</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="properties">Properties</Tab>
      </TabList>
      {tab === "overview" && (
        <section className="vy-form-section">
          <h3>Basic info</h3>
          <div className="vy-essentials-grid">
            <div>
              <KV label="User principal name" value={user.userPrincipalName} />
              <KV label="Object ID" value={user.id} />
              <KV label="Created date time" value={user.createdDateTime} />
              <KV label="User type" value={user.userType} />
            </div>
            <div>
              <KV label="Identities" value={user.userPrincipalName} />
              <KV label="Group memberships" value={groups.data ? `${groups.data.length} group(s)` : "Loading..."} />
              <KV label="Applications" value="0 applications" />
              <KV label="Assigned roles" value={`${myRoles.length} role(s)`} />
              <KV label="Assigned licenses" value="0 licenses" />
            </div>
          </div>
        </section>
      )}
      {tab !== "overview" && <div style={{ padding: "12px 0" }}>Nothing new to report.</div>}
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="user" names={[user.displayName]}
        onConfirm={async () => { await api.deleteUser(user.id); notify.success(`Deleted ${user.displayName}.`, "Delete succeeded"); navigate("entra", "users"); }} />
    </>
  );
}

function Groups({ user }) {
  const { data, loading, error } = useAsync(() => api.userMemberOf(user.id), [user.id]);
  return (
    <>
      <div className="vy-panel-title">{`${user.displayName} | Groups`}</div>
      {loading && <Loading />}
      {error && <ErrorBar error={error} />}
      {!loading && !error && (data.length
        ? <ul>{data.map((g) => <li key={g.id}><Link href="#/entra/groups">{g.displayName}</Link></li>)}</ul>
        : <p>{user.displayName} is not a member of any groups.</p>)}
    </>
  );
}

function AssignedRoles({ user }) {
  const { data, loading, error } = useAsync(() => api.listRoleAssignments(), [user.id]);
  const mine = (data || []).filter((a) => a.properties.principalId === user.id);
  return (
    <>
      <div className="vy-panel-title">{`${user.displayName} | Assigned roles`}</div>
      {loading && <Loading />}
      {error && <ErrorBar error={error} />}
      {!loading && !error && (mine.length
        ? <ul>{mine.map((a) => <li key={a.name}>{a.properties.roleDefinitionId}</li>)}</ul>
        : <p>{user.displayName} has no directory roles assigned. <Link href="#/entra/roles">Assign a role</Link></p>)}
    </>
  );
}

const OS_OPTIONS = ["Windows", "macOS", "Linux", "iOS", "Android"];

function Devices({ user }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listRegisteredDevices(user.id), [user.id]);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [os, setOs] = useState("Windows");
  const register = async () => {
    await api.registerDevice(user.id, { displayName: name, operatingSystem: os });
    setAdding(false); setName("");
    notify.success(`Registered ${name}.`, "Devices");
    reload();
  };
  const remove = async (id, deviceName) => {
    await api.deleteDevice(id);
    notify.success(`Removed ${deviceName}.`, "Devices");
    reload();
  };
  const devices = data || [];
  return (
    <>
      <div className="vy-panel-title">{`${user.displayName} | Devices`}</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Devices commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdding(true)}>Register device</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      {loading && <Loading />}
      {error && <ErrorBar error={error} />}
      {!loading && !error && (devices.length ? (
        <Table size="small">
          <TableHeader><TableRow>
            <TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>OS</TableHeaderCell>
            <TableHeaderCell>Join type</TableHeaderCell><TableHeaderCell>Compliant</TableHeaderCell>
            <TableHeaderCell>Managed</TableHeaderCell><TableHeaderCell>Registered</TableHeaderCell><TableHeaderCell />
          </TableRow></TableHeader>
          <TableBody>
            {devices.map((d) => (
              <TableRow key={d.id}>
                <TableCell>{d.displayName}</TableCell>
                <TableCell>{d.operatingSystem}{d.operatingSystemVersion ? ` ${d.operatingSystemVersion}` : ""}</TableCell>
                <TableCell>{d.trustType}</TableCell>
                <TableCell>{d.isCompliant ? "Yes" : "No"}</TableCell>
                <TableCell>{d.isManaged ? "Yes" : "No"}</TableCell>
                <TableCell>{new Date(d.registrationDateTime).toLocaleDateString()}</TableCell>
                <TableCell><Button appearance="subtle" icon={<Delete16Regular />} onClick={() => remove(d.id, d.displayName)} aria-label="Delete device" /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : <p>{user.displayName} has no registered devices.</p>)}
      {adding && (
        <section className="vy-form-section">
          <h3>Register a device</h3>
          <Field label="Name"><Input value={name} onChange={(_, d) => setName(d.value)} /></Field>
          <Field label="Operating system">
            <Select value={os} onChange={(_, d) => setOs(d.value)}>
              {OS_OPTIONS.map((o) => <option key={o}>{o}</option>)}
            </Select>
          </Field>
          <div style={{ marginTop: 8 }}>
            <Button appearance="primary" onClick={register} disabled={!name}>Register</Button>{" "}
            <Button onClick={() => setAdding(false)}>Cancel</Button>
          </div>
        </section>
      )}
    </>
  );
}

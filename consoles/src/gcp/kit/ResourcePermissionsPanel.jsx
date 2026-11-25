/* Shared GCP 'Permissions' panel for one resource: Add principal (the same GrantAccessPanel the project IAM page uses: principal
 * picker, role picker, IAM conditions), View by principals / roles, Remove access. Reads the resource's REAL policy with its native
 * getIamPolicy and writes with setIamPolicy. Usage: <ResourcePermissionsPanel kind="pubsub-topic" args={{ name }} />. */
import { useState } from "react";
import { Box, Button, Stack, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../common/useAsync.js";
import { useNotify } from "../../common/notify.jsx";
import ResourceTable from "./ResourceTable.jsx";
import { ErrorAlert } from "./common.jsx";
import { GrantAccessPanel } from "../services/iam-admin/Iam.jsx";
import * as iamApi from "../services/iam-admin/api.js";
import { RESOURCE_KINDS } from "./resourceIam.js";

const condKey = (b) => b.condition?.expression || "";

export default function ResourcePermissionsPanel({ kind, args, onChanged }) {
  const notify = useNotify();
  const def = RESOURCE_KINDS[kind];
  const wire = def.wire(args);
  const dep = JSON.stringify([kind, args]);
  const pol = useAsync(() => wire.get(), [dep]);
  const [viewBy, setViewBy] = useState("principals");
  const [sel, setSel] = useState([]);
  const [grant, setGrant] = useState(false);
  const bindings = pol.data?.bindings || [];
  const principalRows = bindings.flatMap((b) => b.members.map((m) => ({ key: `${b.role}|${condKey(b)}|${m}`, role: b.role, cond: b.condition, member: m, type: iamApi.parseMember(m).type })));
  const roleRows = bindings.map((b) => ({ key: `${b.role}|${condKey(b)}`, role: b.role, cond: b.condition, members: b.members }));
  const write = async (next, msg) => {
    const conditional = next.some((b) => b.condition);
    await wire.set({ ...pol.data, ...(conditional ? { version: 3 } : {}), bindings: next });
    notify.success(msg); setSel([]); pol.reload(); onChanged && onChanged();
  };
  const remove = async () => {
    try {
      const drop = new Set(sel);
      const next = bindings
        .map((b) => (viewBy === "roles" ? (drop.has(`${b.role}|${condKey(b)}`) ? null : b) : { ...b, members: b.members.filter((m) => !drop.has(`${b.role}|${condKey(b)}|${m}`)) }))
        .filter((b) => b && b.members.length);
      await write(next, `Removed ${sel.length} role binding${sel.length === 1 ? "" : "s"}`);
    } catch (err) { notify.error(err); }
  };
  const roleLabel = (r) => iamApi.roleTitle(r.role) + (r.cond ? ` (condition: ${r.cond.title})` : "");
  return (
    <Box data-testid="resource-permissions">
      <Typography variant="h3" component="h2" sx={{ mb: 1 }}>Permissions for {def.label}</Typography>
      <ErrorAlert error={pol.error} title="Failed to load IAM policy" />
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 1.5 }}>
        <ToggleButtonGroup exclusive size="small" value={viewBy} onChange={(_, v) => { if (v) { setViewBy(v); setSel([]); } }} aria-label="View by">
          <ToggleButton value="principals">View by principals</ToggleButton>
          <ToggleButton value="roles">View by roles</ToggleButton>
        </ToggleButtonGroup>
        <Box sx={{ flex: 1 }} />
        <Button startIcon={<AddIcon />} onClick={() => setGrant(true)}>Grant access</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={remove}>Remove access</Button>
      </Stack>
      {viewBy === "principals" ? (
        <ResourceTable resourceName="principals" items={principalRows} rowKey={(r) => r.key} loading={pol.loading} onRetry={pol.reload}
          selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Enter property name or value" dense
          columns={[
            { id: "type", header: "Type", sortField: "type", cell: (r) => r.type },
            { id: "principal", header: "Principal", sortField: "member", cell: (r) => r.member },
            { id: "role", header: "Role", sortValue: roleLabel, cell: roleLabel },
            { id: "inheritance", header: "Inheritance", cell: () => "Direct" },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No principals have been granted access to this resource.</Typography>} />
      ) : (
        <ResourceTable resourceName="roles" items={roleRows} rowKey={(r) => r.key} loading={pol.loading} onRetry={pol.reload}
          selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Enter property name or value" dense
          columns={[
            { id: "role", header: "Role", sortValue: roleLabel, cell: roleLabel },
            { id: "members", header: "Principal", wrap: true, cell: (r) => r.members.map((m) => iamApi.parseMember(m).display).join(", ") },
            { id: "inheritance", header: "Inheritance", cell: () => "Direct" },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No roles have been granted on this resource.</Typography>} />
      )}
      {grant && <GrantAccessPanel resourceLabel={args.name} usedRoles={[...new Set(bindings.map((b) => b.role))]} onClose={() => setGrant(false)}
        onSave={async (members, rows) => {
          const bs = bindings.map((b) => ({ ...b, members: [...b.members] }));
          const same = (a, c) => (a?.expression || "") === (c?.expression || "");
          for (const { role, condition } of rows) {
            let hit = bs.find((b) => b.role === role && same(b.condition, condition));
            if (!hit) { hit = { role, members: [], ...(condition ? { condition } : {}) }; bs.push(hit); }
            for (const m of members) if (!hit.members.includes(m)) hit.members.push(m);
          }
          await write(bs, `Granted ${rows.length} role${rows.length === 1 ? "" : "s"} to ${members.length} principal${members.length === 1 ? "" : "s"}`);
        }} />}
    </Box>
  );
}

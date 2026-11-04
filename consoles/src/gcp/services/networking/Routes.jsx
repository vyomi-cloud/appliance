/* Routes — Effective routes / Route management tabs, as in the console's Routes page. */
import { useEffect, useState } from "react";
import { Box, Button, Checkbox, FormControl, FormControlLabel, InputLabel, MenuItem, Select, Tab, Tabs, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MenuBookIcon from "@mui/icons-material/esm/MenuBookOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Routes() {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState("effective");
  const [network, setNetwork] = useState("");
  const [region, setRegion] = useState(api.REGIONS[0]);
  const [viewed, setViewed] = useState(true);
  const [suppressed, setSuppressed] = useState(false);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data, loading, error, reload } = useAsync(async () => {
    const [networks, routes] = await Promise.all([api.listNetworks(), api.listRoutes()]);
    return { networks, routes };
  }, [project]);
  const networks = data?.networks || [];
  const routes = data?.routes || [];
  useEffect(() => { if (!network && networks.length) setNetwork(networks[0].name); }, [networks, network]);
  const effective = routes.filter((r) => !network || r.network.endsWith(`/networks/${network}`));

  return (
    <>
      <PageHeader title="Routes" actions={<Button startIcon={<MenuBookIcon />} href="https://cloud.google.com/vpc/docs/routes" target="_blank" rel="noreferrer">Learn</Button>} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="effective" label="Effective routes" />
        <Tab value="management" label="Route management" />
      </Tabs>

      {tab === "effective" && (
        <>
          <Section title="Select the VPC network and region for which you want to view routes">
            <Box sx={{ display: "flex", gap: 2, alignItems: "flex-end", flexWrap: "wrap" }}>
              <FormControl required sx={{ minWidth: 240 }}>
                <InputLabel id="net-label">Network</InputLabel>
                <Select labelId="net-label" label="Network" value={network} onChange={(e) => setNetwork(e.target.value)}>
                  {networks.map((n) => <MenuItem key={n.name} value={n.name}>{n.name}</MenuItem>)}
                </Select>
              </FormControl>
              <FormControl required sx={{ minWidth: 200 }}>
                <InputLabel id="region-label">Region</InputLabel>
                <Select labelId="region-label" label="Region" value={region} onChange={(e) => setRegion(e.target.value)}>
                  {api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                </Select>
              </FormControl>
              <Button variant="contained" disabled={!network} onClick={() => setViewed(true)}>View</Button>
            </Box>
          </Section>
          {viewed && (
            <Box sx={{ mt: 2 }}>
              <ResourceTable
                resourceName="routes"
                items={effective}
                loading={loading}
                error={error}
                onRetry={reload}
                filterPlaceholder="Filter"
                toolbar={<FormControlLabel control={<Checkbox size="small" checked={suppressed} onChange={(e) => setSuppressed(e.target.checked)} />} label="Show suppressed routes" />}
                columns={[
                  { id: "status", header: "Status", cell: () => "Active" },
                  { id: "name", header: "Name", cell: (r) => r.name },
                  { id: "type", header: "Type", cell: () => "Static" },
                  { id: "ipversion", header: "IP version", cell: () => "IPv4" },
                  { id: "dest", header: "Destination IP range", cell: (r) => r.destRange },
                  { id: "priority", header: "Priority", cell: (r) => r.priority },
                  { id: "scope", header: "Scope limits", cell: () => "None" },
                  { id: "nexthop", header: "Next hop", cell: api.routeNextHop },
                ]}
              />
            </Box>
          )}
        </>
      )}

      {tab === "management" && (
        <Section title="Routes" actions={<>
          <Button startIcon={<AddIcon />} href="#/networking/routes/add">Create route</Button>
          <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
          <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        </>}>
          <ResourceTable
            resourceName="routes"
            items={routes}
            loading={loading}
            error={error}
            onRetry={reload}
            selectable
            selected={sel}
            onSelectedChange={setSel}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", sortField: "name", cell: (r) => r.name },
              { id: "network", header: "Network", cell: (r) => api.nameOf(r.network) },
              { id: "dest", header: "Destination IP range", cell: (r) => r.destRange },
              { id: "priority", header: "Priority", cell: (r) => r.priority },
              { id: "tags", header: "Instance tags", cell: (r) => (r.tags?.length ? r.tags.join(", ") : "—") },
              { id: "nexthop", header: "Next hop", cell: api.routeNextHop },
            ]}
          />
        </Section>
      )}

      <DeleteDialog open={del} onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete route?" : `Delete ${sel.length} routes?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        onConfirm={async () => {
          for (const n of sel) await api.deleteRoute(n);
          notify.success(sel.length === 1 ? `Deleted "${sel[0]}"` : `Deleted ${sel.length} routes`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Route <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.join(", ")} will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}

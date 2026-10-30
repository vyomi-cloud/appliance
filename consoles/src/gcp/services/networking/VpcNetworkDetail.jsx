/* VPC network details — Subnets / Static internal IP addresses / Firewalls / Routes /
 * VPC network peering / Private service connection tabs, as in the console. */
import { useState } from "react";
import {
  Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, FormControlLabel,
  IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const TABS = [
  ["subnets", "Subnets"], ["internal-ips", "Static internal IP addresses"], ["firewalls", "Firewalls"],
  ["routes", "Routes"], ["peering", "VPC network peering"], ["psc", "Private service connection"],
];
const STACK_LABEL = { v4: "IPv4 (single-stack)", dual: "IPv4 and IPv6 (dual-stack)", v6: "IPv6 (single-stack)" };
const STACK_VALUE = { v4: "IPV4_ONLY", dual: "IPV4_IPV6", v6: "IPV6_ONLY" };

export default function VpcNetworkDetail({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [tab, setTab] = useState("subnets");
  const [del, setDel] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [edit, setEdit] = useState({ description: "", mtu: "1460", routingMode: "REGIONAL" });
  const [subSel, setSubSel] = useState([]);
  const [draft, setDraft] = useState({ name: "", description: "", region: api.REGIONS[0], stack: "v4", range: "", pga: "Off", flowLogs: "Off" });
  const { data, loading, error, reload } = useAsync(async () => {
    const [network, allSubnets, firewalls, routes, addresses] = await Promise.all([
      api.getNetwork(name), api.listAllSubnets(), api.listFirewalls(), api.listRoutes(), api.listAllAddresses(),
    ]);
    return { network, subnets: api.subnetsOf(allSubnets, name), firewalls: firewalls.filter((f) => f.network.endsWith(`/networks/${name}`)),
      routes: routes.filter((r) => r.network.endsWith(`/networks/${name}`)), addresses: addresses.filter((a) => a.addressType === "INTERNAL") };
  }, [name]);
  const net = data?.network;

  const addSubnet = async () => {
    const err = api.validName(draft.name, "Subnet name") || (!draft.range && "IPv4 range is required.");
    if (err) { notify.error({ message: err }); return; }
    try {
      await api.insertSubnet(draft.region, {
        name: draft.name, description: draft.description, network: name, ipCidrRange: draft.range,
        stackType: STACK_VALUE[draft.stack], privateIpGoogleAccess: draft.pga === "On", logConfig: { enable: draft.flowLogs === "On" },
      });
      notify.success(`Created subnet "${draft.name}"`);
      setAddOpen(false);
      setDraft({ name: "", description: "", region: api.REGIONS[0], stack: "v4", range: "", pga: "Off", flowLogs: "Off" });
      reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <PageHeader title={name} back={<IconButton aria-label="Back" href="#/networking/networks/list"><ArrowBackIcon /></IconButton>} actions={<>
        <Button onClick={reload}>Refresh</Button>
        <Button onClick={() => { setEdit({ description: net?.description || "", mtu: String(net?.mtu || "1460"), routingMode: net?.routingConfig?.routingMode || "REGIONAL" }); setEditOpen(true); }}>Edit</Button>
        <Button color="error" onClick={() => setDel(true)}>Delete VPC network</Button>
      </>} />
      <ErrorAlert error={error} />
      {net && (
        <Section title="Network details" noPad={false} description={null}>
          <KeyValue items={[
            ["Description", net.description || "—"],
            ["MTU", net.mtu],
            ["Mode", net.autoCreateSubnetworks ? "Auto" : "Custom"],
            ["Dynamic routing mode", net.routingConfig?.routingMode === "GLOBAL" ? "Global" : "Regional"],
            ["IPv6 ULA range", net.internalIpv6Range || "—"],
          ]} />
        </Section>
      )}
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mt: 2, mb: 2 }}>
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>

      {tab === "subnets" && (
        <CapabilityContainer id="gcp.networking.subnet.crud" title="Subnets"
          actions={<>
            <Button startIcon={<AddIcon />} onClick={() => setAddOpen(true)}>Add subnet</Button>
            <Button startIcon={<DeleteIcon />} disabled={!subSel.length} onClick={async () => {
              for (const key of subSel) { const [region, n] = key.split("|"); await api.deleteSubnet(region, n); }
              notify.success(`Deleted ${subSel.length} subnet(s)`); setSubSel([]); reload();
            }}>Delete</Button>
          </>}
        >
          <ResourceTable
            resourceName="subnets"
            items={data?.subnets || []}
            rowKey={(s) => `${api.nameOf(s.region)}|${s.name}`}
            loading={loading}
            selectable
            selected={subSel}
            onSelectedChange={setSubSel}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", sortField: "name", cell: (s) => s.name },
              { id: "region", header: "Region", cell: (s) => api.nameOf(s.region) },
              { id: "stack", header: "Stack type", cell: (s) => s.stackType },
              { id: "range", header: "Primary IPv4 range", cell: (s) => s.ipCidrRange },
              { id: "gateway", header: "Gateway", cell: (s) => s.gatewayAddress },
              { id: "pga", header: "Private Google Access", cell: (s) => (s.privateIpGoogleAccess ? "On" : "Off") },
              { id: "flowlogs", header: "Flow logs", cell: (s) => (s.logConfig?.enable ? "On" : "Off") },
            ]}
          />
        </CapabilityContainer>
      )}

      {tab === "internal-ips" && (
        <CapabilityContainer id="gcp.networking.address.crud" title="Static internal IP addresses" description="Internal reserved addresses across this project.">
          <ResourceTable
            resourceName="addresses"
            items={data?.addresses || []}
            loading={loading}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", cell: (a) => a.name },
              { id: "address", header: "IP address", cell: (a) => a.address },
              { id: "region", header: "Region", cell: (a) => (a.region ? api.nameOf(a.region) : "—") },
              { id: "status", header: "Status", cell: (a) => a.status },
            ]}
          />
        </CapabilityContainer>
      )}

      {tab === "firewalls" && (
        <CapabilityContainer id="gcp.networking.firewall.crud" title="Firewalls" actions={<Button startIcon={<AddIcon />} href="#/networking/firewall/add">Create firewall rule</Button>}>
          <ResourceTable
            resourceName="firewall rules"
            items={data?.firewalls || []}
            loading={loading}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", cell: (f) => f.name },
              { id: "direction", header: "Type", cell: (f) => f.direction },
              { id: "targets", header: "Targets", cell: api.firewallTargets },
              { id: "filters", header: "Filters", cell: api.firewallFilters },
              { id: "ports", header: "Protocols / ports", cell: api.firewallProtoPorts },
              { id: "action", header: "Action", cell: api.firewallAction },
              { id: "priority", header: "Priority", cell: (f) => f.priority },
            ]}
          />
        </CapabilityContainer>
      )}

      {tab === "routes" && (
        <CapabilityContainer id="gcp.networking.route.crud" title="Routes" actions={<Button startIcon={<AddIcon />} href="#/networking/routes/add">Create route</Button>}>
          <ResourceTable
            resourceName="routes"
            items={data?.routes || []}
            loading={loading}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", cell: (r) => r.name },
              { id: "dest", header: "Destination IP range", cell: (r) => r.destRange },
              { id: "priority", header: "Priority", cell: (r) => r.priority },
              { id: "nexthop", header: "Next hop", cell: api.routeNextHop },
            ]}
          />
        </CapabilityContainer>
      )}

      {tab === "peering" && <CapabilityContainer id="gcp.networking.peering" title="VPC network peering" />}
      {tab === "psc" && <CapabilityContainer id="gcp.networking.private-service-connection" title="Private service connection" />}

      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete VPC network?" confirmText={name}
        warning="Deleting a network fails while it still has subnets, firewall rules or routes attached — remove those first."
        onConfirm={async () => {
          await api.deleteNetwork(name);
          notify.success(`Deleted network "${name}"`);
          window.location.hash = "#/networking/networks/list";
        }}
      >
        <Typography variant="body2">Network <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit network</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <TextField label="Description" value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} />
            <FormControl>
              <InputLabel id="e-mtu">Maximum transmission unit (MTU)</InputLabel>
              <Select labelId="e-mtu" label="Maximum transmission unit (MTU)" value={edit.mtu} onChange={(e) => setEdit({ ...edit, mtu: e.target.value })}>
                <MenuItem value="1460">1460 (default)</MenuItem>
                <MenuItem value="1500">1500</MenuItem>
              </Select>
            </FormControl>
            <RadioGroup row value={edit.routingMode} onChange={(e) => setEdit({ ...edit, routingMode: e.target.value })} aria-label="Dynamic routing mode">
              <FormControlLabel value="REGIONAL" control={<Radio size="small" />} label="Regional" />
              <FormControlLabel value="GLOBAL" control={<Radio size="small" />} label="Global" />
            </RadioGroup>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={async () => {
            await api.patchNetwork(name, { description: edit.description, mtu: Number(edit.mtu), routingConfig: { routingMode: edit.routingMode } });
            notify.success("Network updated");
            setEditOpen(false);
            reload();
          }}>Save</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={addOpen} onClose={() => setAddOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add subnet</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <TextField label="Name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value.trim() })} />
            <TextField label="Description" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            <FormControl required>
              <InputLabel id="d-region">Region</InputLabel>
              <Select labelId="d-region" label="Region" value={draft.region} onChange={(e) => setDraft({ ...draft, region: e.target.value })}>
                {api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
              </Select>
            </FormControl>
            <RadioGroup row value={draft.stack} onChange={(e) => setDraft({ ...draft, stack: e.target.value })} aria-label="IP stack type">
              {Object.entries(STACK_LABEL).map(([v, l]) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={l} />)}
            </RadioGroup>
            <TextField label="IPv4 range" required placeholder="10.0.0.0/24" value={draft.range} onChange={(e) => setDraft({ ...draft, range: e.target.value })} />
            <FormControlLabel control={<Checkbox checked={draft.pga === "On"} onChange={(e) => setDraft({ ...draft, pga: e.target.checked ? "On" : "Off" })} />} label="Private Google Access" />
            <FormControlLabel control={<Checkbox checked={draft.flowLogs === "On"} onChange={(e) => setDraft({ ...draft, flowLogs: e.target.checked ? "On" : "Off" })} />} label="Flow logs" />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={addSubnet}>Done</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

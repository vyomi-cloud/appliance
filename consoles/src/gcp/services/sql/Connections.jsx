/* Connections — Summary / Networking / Security tabs. IP configuration and authorized
 * networks round-trip through instances.patch (stored, not enforced — see
 * core/capabilities/gcp/sql.json: gcp.sql.connections is "config_only"). */
import { useState } from "react";
import { Box, Button, Checkbox, FormControlLabel, IconButton, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

const TABS = [["summary", "Summary"], ["networking", "Networking"], ["security", "Security"]];

export default function Connections({ params, query }) {
  const name = params.name;
  const notify = useNotify();
  const [tab, setTab] = useState(TABS.some(([t]) => t === query?.tab) ? query.tab : "summary");
  const inst = useAsync(() => api.getInstance(name), [name]);
  const i = inst.data;

  return (
    <>
      <InstanceNav name={name} active="connections" />
      <Typography variant="h2" component="h2" sx={{ fontSize: 20, mb: 1.5 }}>Connections</Typography>
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Connections tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      <ErrorAlert error={inst.error} title="Failed to load instance" />
      {i && tab === "summary" && (
        <Section title="Connection summary">
          <KeyValue items={[
            ["Public IP address", api.publicIp(i)], ["Private IP address", api.privateIp(i)],
            ["Instance connection name", i.connectionName],
            ["Public IP enabled", i.settings?.ipConfiguration?.ipv4Enabled ? "Yes" : "No"],
          ]} />
        </Section>
      )}
      {i && tab === "networking" && <Networking instance={i} reload={inst.reload} />}
      {i && tab === "security" && <CapabilityContainer id="gcp.sql.connections-security" title="Security" />}
    </>
  );
}

function Networking({ instance, reload }) {
  const notify = useNotify();
  const ip = instance.settings?.ipConfiguration || {};
  const [networks, setNetworks] = useState((ip.authorizedNetworks || []).map((n) => ({ Name: n.name || "", Network: n.value || "" })));
  const [busy, setBusy] = useState(false);

  const patch = async (settings, msg) => {
    setBusy(true);
    try { await api.patchInstance(instance.name, { settings }); notify.success(msg); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <CapabilityContainer id="gcp.sql.connections" title="Instance IP assignment">
      <Stack spacing={2}>
        <FormControlLabel control={<Checkbox size="small" disabled={busy} checked={!!ip.privateNetwork}
          onChange={(e) => patch({ ipConfiguration: { ...ip, privateNetwork: e.target.checked ? "projects/-/global/networks/default" : null } }, e.target.checked ? "Private IP enabled" : "Private IP disabled")} />} label="Private IP" />
        <FormControlLabel control={<Checkbox size="small" disabled={busy} checked={!!ip.ipv4Enabled}
          onChange={(e) => patch({ ipConfiguration: { ...ip, ipv4Enabled: e.target.checked } }, e.target.checked ? "Public IP enabled" : "Public IP disabled")} />} label="Public IP" />
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Authorized networks</Typography>
          <Stack spacing={1}>
            {networks.map((n, idx) => (
              <Stack key={idx} direction="row" spacing={1} alignItems="center">
                <TextField size="small" label="Name" value={n.Name} onChange={(e) => setNetworks(networks.map((x, j) => j === idx ? { ...x, Name: e.target.value } : x))} />
                <TextField size="small" label="Network" value={n.Network} onChange={(e) => setNetworks(networks.map((x, j) => j === idx ? { ...x, Network: e.target.value } : x))} />
                <IconButton aria-label={`Delete network ${idx + 1}`} onClick={() => setNetworks(networks.filter((_, j) => j !== idx))}><DeleteIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
            <Stack direction="row" spacing={1}>
              <Button size="small" startIcon={<AddIcon />} onClick={() => setNetworks([...networks, { Name: "", Network: "" }])}>Add a network</Button>
              <Button size="small" variant="outlined" disabled={busy} onClick={() => patch({ ipConfiguration: { ...ip, authorizedNetworks: networks.filter((n) => n.Network).map((n) => ({ name: n.Name, value: n.Network })) } }, "Saved authorized networks")}>Save networks</Button>
            </Stack>
          </Stack>
        </Box>
      </Stack>
    </CapabilityContainer>
  );
}

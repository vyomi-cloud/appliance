/* Connections — Summary / Networking / Security tabs. ipv4Enabled / privateNetwork round-trip
 * through instances.patch and are ENFORCED on ipAddresses (Public IP off removes the PRIMARY
 * address entirely); authorizedNetworks is stored but not enforced — see
 * core/capabilities/gcp/sql.json: gcp.sql.connections is "limited". Security's sslMode +
 * client certs are real sslCerts resources, enforced on Cloud SQL Studio's query RPC — see
 * gcp.sql.connections-security (also "limited": the enforcement boundary is documented there). */
import { useState } from "react";
import {
  Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel,
  IconButton, MenuItem, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, fmtDate, KeyValue, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
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
      {i && tab === "security" && <Security instance={i} reload={inst.reload} />}
    </>
  );
}

function Security({ instance, reload }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const certs = useAsync(() => api.listSslCerts(instance.name), [instance.name]);
  const [addOpen, setAddOpen] = useState(false);
  const [newCertName, setNewCertName] = useState("");
  const [issued, setIssued] = useState(null);   // { commonName, certPrivateKey } — shown once
  const [delCert, setDelCert] = useState(null);
  const sslMode = instance.settings?.ipConfiguration?.sslMode || "ALLOW_UNENCRYPTED_AND_ENCRYPTED";

  const changeMode = async (mode) => {
    setBusy(true);
    try { await api.setSslMode(instance.name, mode); notify.success(`Require SSL/TLS set to "${api.sslModeLabel(mode)}"`); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  const createCert = async () => {
    try {
      const r = await api.insertSslCert(instance.name, newCertName);
      setIssued({ commonName: newCertName, certPrivateKey: r.clientCert.certPrivateKey });
      setAddOpen(false); setNewCertName(""); certs.reload();
      notify.success(`Created client certificate "${newCertName}"`);
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <CapabilityContainer id="gcp.sql.connections-security" title="Security">
        <Stack spacing={3}>
          <TextField select size="small" label="Require SSL/TLS" value={sslMode} disabled={busy}
            onChange={(e) => changeMode(e.target.value)} sx={{ maxWidth: 440 }}>
            {api.SSL_MODES.map(([v, label]) => <MenuItem key={v} value={v}>{label}</MenuItem>)}
          </TextField>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Server CA certificate</Typography>
            <KeyValue items={[
              ["Common name", instance.serverCaCert?.commonName],
              ["SHA-1 fingerprint", instance.serverCaCert?.sha1Fingerprint],
              ["Expiration", fmtDate(instance.serverCaCert?.expirationTime)],
            ]} />
          </Box>
          <Box>
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>Client certificates</Typography>
              <Button size="small" startIcon={<AddIcon />} onClick={() => setAddOpen(true)}>Create client certificate</Button>
            </Stack>
            <ResourceTable resourceName="client certificates" items={certs.data || []} rowKey={(c) => c.sha1Fingerprint} loading={certs.loading}
              filterPlaceholder="Filter client certificates"
              columns={[
                { id: "cn", header: "Common name", cell: (c) => c.commonName },
                { id: "fp", header: "SHA-1 fingerprint", cell: (c) => c.sha1Fingerprint },
                { id: "exp", header: "Expiration", cell: (c) => fmtDate(c.expirationTime) },
                { id: "actions", header: "Actions", cell: (c) => <Button size="small" startIcon={<DeleteIcon />} onClick={() => setDelCert(c)}>Delete</Button> },
              ]}
              empty={<Typography variant="body2" color="text.secondary">No client certificates. Required to connect when SSL/TLS requires a trusted client certificate.</Typography>} />
          </Box>
        </Stack>
      </CapabilityContainer>
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create a client certificate</DialogTitle>
        <DialogContent>
          <TextField autoFocus fullWidth size="small" label="Certificate name" sx={{ mt: 1 }}
            value={newCertName} onChange={(e) => setNewCertName(e.target.value)} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!newCertName} onClick={createCert}>Create</Button>
        </DialogActions>
      </Dialog>
      <Dialog open={!!issued} onClose={() => setIssued(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Client certificate created</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            Copy the private key for <b>{issued?.commonName}</b> now — Vyomi won't show it again.
          </Typography>
          <TextField multiline fullWidth minRows={5} value={issued?.certPrivateKey || ""}
            InputProps={{ readOnly: true, sx: { fontFamily: "monospace", fontSize: 12 } }} />
        </DialogContent>
        <DialogActions><Button onClick={() => setIssued(null)}>Done</Button></DialogActions>
      </Dialog>
      <DeleteDialog open={!!delCert} onClose={() => setDelCert(null)} title="Delete client certificate?"
        confirmText={delCert?.commonName}
        warning="Connections presenting this certificate will be rejected."
        onConfirm={async () => { await api.deleteSslCert(instance.name, delCert.sha1Fingerprint); notify.success("Deleted client certificate"); certs.reload(); }}>
        <Typography variant="body2">Certificate <b>{delCert?.commonName}</b> ({delCert?.sha1Fingerprint}) will be permanently deleted.</Typography>
      </DeleteDialog>
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

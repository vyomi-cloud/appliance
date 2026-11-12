/* Gateway details: hostname, the API config it serves (switchable) and the routes that config defines. */
import { useState } from "react";
import { Box, Button, CircularProgress, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function GatewayDetail({ params }) {
  const { region, name } = params;
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const [pick, setPick] = useState("");
  const g = useAsync(() => api.getGateway(region, name), [region, name]);
  const cfg = useAsync(async () => (g.data ? api.getConfig(api.apiOfConfig(g.data.apiConfig), api.last(g.data.apiConfig)).catch(() => null) : null), [g.data?.apiConfig]);
  const all = useAsync(() => api.listAllConfigs(), []);

  if (g.loading) return <Box sx={{ textAlign: "center", py: 8 }}><CircularProgress /></Box>;
  if (g.error) return <ErrorAlert error={g.error} title="Failed to load gateway" />;
  const gw = g.data, routes = cfg.data?.routes || [];
  return (
    <>
      <PageHeader title={name} back={<IconButton aria-label="Back to gateways" href="#/apigateway"><ArrowBackIcon /></IconButton>}
        actions={<><Button startIcon={<RefreshIcon />} onClick={g.reload}>Refresh</Button><Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button></>} />
      <Section title="Gateway details">
        <KeyValue items={[["Gateway ID", name], ["Location", region], ["State", gw.state === "ACTIVE" ? "Active" : gw.state], ["Default hostname", gw.defaultHostname],
          ["API", api.apiOfConfig(gw.apiConfig)], ["API config", api.last(gw.apiConfig)], ["Created", fmtDate(gw.createTime)], ["Updated", fmtDate(gw.updateTime)]]} />
      </Section>
      <Section title="Change API config">
        <Stack direction="row" spacing={1} alignItems="center">
          <FormControl size="small" sx={{ minWidth: 320 }}><InputLabel id="gwd-cfg-l">API config</InputLabel>
            <Select labelId="gwd-cfg-l" label="API config" value={pick || gw.apiConfig} onChange={(e) => setPick(e.target.value)}>
              {(all.data || []).map((c) => <MenuItem key={c.name} value={c.name}>{api.apiOfConfig(c.name)} / {api.last(c.name)}</MenuItem>)}</Select></FormControl>
          <Button variant="outlined" disabled={!pick || pick === gw.apiConfig}
            onClick={async () => { try { await api.patchGateway(region, name, { apiConfig: pick }, "apiConfig"); notify.success("Gateway updated"); setPick(""); g.reload(); } catch (e) { notify.error(e); } }}>Update</Button>
        </Stack>
      </Section>
      <Section title="Routes">
        <ResourceTable resourceName="routes" items={routes} rowKey={(r) => r.operationId}
          columns={[{ id: "m", header: "Method", cell: (r) => r.method }, { id: "p", header: "Path", cell: (r) => r.path }, { id: "u", header: "URL", cell: (r) => `https://${gw.defaultHostname}${r.path}` }, { id: "b", header: "Backend", cell: (r) => r.backend }]}
          empty={<Typography variant="body2" color="text.secondary">This config defines no routes.</Typography>} />
      </Section>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete gateway?" confirmText={name} warning="This can't be undone."
        onConfirm={async () => { await api.deleteGateway(region, name); notify.success(`Deleted gateway "${name}"`); location.hash = "/apigateway"; }}>
        <Typography variant="body2">Gateway <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

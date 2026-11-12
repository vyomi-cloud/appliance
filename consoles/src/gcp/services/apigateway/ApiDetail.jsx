/* API details: the API, its API configs (create from an OpenAPI 2.0 document, delete) and the routes each config defines. */
import { useState } from "react";
import { Box, Button, CircularProgress, IconButton, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function ApiDetail({ params }) {
  const { api: aid } = params;
  const notify = useNotify();
  const [adding, setAdding] = useState(false);
  const [delCfg, setDelCfg] = useState(null);
  const [view, setView] = useState(null);   // a config whose routes are shown
  const a = useAsync(() => api.getApi(aid), [aid]);
  const cfgs = useAsync(() => api.listConfigs(aid), [aid]);
  const routes = useAsync(async () => (view ? (await api.getConfig(aid, api.last(view.name))).routes || [] : []), [view?.name]);

  if (a.loading) return <Box sx={{ textAlign: "center", py: 8 }}><CircularProgress /></Box>;
  if (a.error) return <ErrorAlert error={a.error} title="Failed to load API" />;
  const reload = () => { a.reload(); cfgs.reload(); };
  return (
    <>
      <PageHeader title={aid} back={<IconButton aria-label="Back to APIs" href="#/apigateway/apis"><ArrowBackIcon /></IconButton>}
        actions={<><Button startIcon={<AddIcon />} onClick={() => setAdding(true)}>Create API config</Button><Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button></>} />
      <Section title="API details">
        <KeyValue items={[["API ID", aid], ["Display name", a.data.displayName], ["Managed service", a.data.managedService], ["State", a.data.state === "ACTIVE" ? "Active" : a.data.state], ["Created", fmtDate(a.data.createTime)]]} />
      </Section>
      <Section title="API configs">
        <ResourceTable resourceName="API configs" items={cfgs.data || []} rowKey={(c) => c.name} loading={cfgs.loading} error={cfgs.error} onRetry={cfgs.reload}
          columns={[
            { id: "id", header: "Config ID", sortValue: (c) => api.last(c.name), cell: (c) => api.last(c.name) },
            { id: "sc", header: "Service config", cell: (c) => c.serviceConfigId },
            { id: "sa", header: "Gateway service account", cell: (c) => c.gatewayServiceAccount || "—" },
            { id: "created", header: "Created", cell: (c) => fmtDate(c.createTime) },
            { id: "act", header: "Actions", cell: (c) => <><Button size="small" aria-label={`View routes of ${api.last(c.name)}`} onClick={() => setView(c)}>Routes</Button>
              <Button size="small" color="error" startIcon={<DeleteIcon />} aria-label={`Delete config ${api.last(c.name)}`} onClick={() => setDelCfg(c)}>Delete</Button></> },
          ]}
          empty={<Typography variant="body2" color="text.secondary">This API has no configs. Create one from an OpenAPI 2.0 document.</Typography>} />
      </Section>
      {view && <Section title={`Routes of ${api.last(view.name)}`}>
        <ResourceTable resourceName="routes" items={routes.data || []} rowKey={(r) => r.operationId} loading={routes.loading}
          columns={[{ id: "m", header: "Method", cell: (r) => r.method }, { id: "p", header: "Path", cell: (r) => r.path }, { id: "o", header: "Operation", cell: (r) => r.operationId }, { id: "b", header: "Backend", cell: (r) => r.backend }]} />
      </Section>}
      {adding && <FormDialog open title="Create API config" submitLabel="Create" onClose={(ok) => { setAdding(false); if (ok) cfgs.reload(); }}
        fields={[{ key: "id", label: "Config ID", helper: "Lowercase letters, numbers and hyphens" },
          { key: "sa", label: "Gateway service account (optional)", default: "" },
          { key: "spec", label: "OpenAPI 2.0 document", multiline: true, default: api.SAMPLE_SPEC, helper: "YAML or JSON; every operation needs an operationId and an https x-google-backend address" }]}
        onSubmit={async (v) => {
          if (!api.ID.test(v.id)) throw new Error("Config ID must be 1-63 characters: lowercase letters, numbers and hyphens, starting with a letter.");
          await api.createConfig(aid, v.id, { openapiDocuments: [{ document: { path: "openapi.yaml", contents: api.b64(v.spec) } }], ...(v.sa.trim() ? { gatewayServiceAccount: v.sa.trim() } : {}) });
          notify.success(`Created API config "${v.id}"`);
        }} />}
      <DeleteDialog open={!!delCfg} onClose={() => setDelCfg(null)} title="Delete API config?" confirmText={delCfg ? api.last(delCfg.name) : ""} warning="A config served by a gateway can't be deleted."
        onConfirm={async () => { await api.deleteConfig(aid, api.last(delCfg.name)); notify.success(`Deleted API config "${api.last(delCfg.name)}"`); if (view?.name === delCfg.name) setView(null); cfgs.reload(); }}>
        <Typography variant="body2">Config <b>{delCfg ? api.last(delCfg.name) : ""}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

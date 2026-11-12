/* GCP Marketplace (Vyomi SaaS-simulator catalog), Cloud Hub (real resource aggregate) and Privacy & Security
 * (Access Transparency-style log derived from Admin Activity audit logs). Wire: /vyomi/gcp/{project}/... */
import { useState } from "react";
import { Box, Button, Card, CardContent, Checkbox, FormControlLabel, Grid, Stack, Typography } from "@mui/material";
import StoreIcon from "@mui/icons-material/esm/StorefrontOutlined.js";
import DashIcon from "@mui/icons-material/esm/DashboardOutlined.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { restJson } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { getProject, useProject } from "../../project.js";

const base = (fam, res, id) => `/vyomi/gcp/${getProject()}/${fam}/${res}${id ? "/" + id : ""}`;
export const api = {
  products: (q) => restJson("GET", base("marketplace", "products"), { query: q ? { q } : {} }),
  subs: () => restJson("GET", base("marketplace", "subscriptions")).then((r) => r.subscriptions || []),
  subscribe: (productId) => restJson("POST", base("marketplace", "subscriptions"), { body: { productId, acceptEula: true } }),
  cancel: (id) => restJson("DELETE", base("marketplace", "subscriptions", id)),
  hub: () => restJson("GET", base("hub", "overview")),
  privacy: () => restJson("GET", base("privacy", "overview")),
  accessLog: () => restJson("GET", base("privacy", "access-log")),
};

function Marketplace() {
  const project = useProject();
  const notify = useNotify();
  const [q, setQ] = useState("");
  const prods = useAsync(() => api.products(q), [project, q]);
  const subs = useAsync(() => api.subs(), [project]);
  const active = Object.fromEntries((subs.data || []).filter((s) => s.state === "ACTIVE").map((s) => [s.productId, s]));
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); subs.reload(); } catch (e) { notify.error(e); } };
  return (
    <>
      <PageHeader title="Marketplace" actions={<Button startIcon={<RefreshIcon />} onClick={() => { prods.reload(); subs.reload(); }}>Refresh</Button>} />
      <Typography variant="body2" sx={{ mb: 2 }}>Vyomi SaaS spaces: subscribing provisions a live simulated service in this project. No billing is metered.</Typography>
      <ErrorAlert error={prods.error} title="Failed to load the catalog" />
      <Grid container spacing={2} data-testid="mp-catalog">
        {(prods.data?.products || []).map((p) => (
          <Grid item xs={12} md={6} key={p.id}>
            <Card variant="outlined"><CardContent>
              <Typography variant="h3" component="h2">{p.name}</Typography>
              <Typography variant="caption" color="text.secondary">{p.category} · {p.pricing}</Typography>
              <Typography variant="body2" sx={{ my: 1 }}>{p.description}</Typography>
              {active[p.id] ? (
                <Stack spacing={0.5}>
                  <Typography variant="body2">Endpoint: <code>{active[p.id].space.endpoint}</code></Typography>
                  <Typography variant="body2">API key: <code>{active[p.id].space.apiKey}</code></Typography>
                  <Box><Button color="error" onClick={() => act(() => api.cancel(active[p.id].id), `Cancelled ${p.name}`)}>Cancel subscription</Button></Box>
                </Stack>
              ) : (
                <Stack spacing={0.5}>
                  <EulaSubscribe name={p.name} onSubscribe={() => act(() => api.subscribe(p.id), `Subscribed to ${p.name}`)} />
                </Stack>
              )}
            </CardContent></Card>
          </Grid>
        ))}
      </Grid>
    </>
  );
}

function EulaSubscribe({ name, onSubscribe }) {
  const [ok, setOk] = useState(false);
  return (
    <>
      <FormControlLabel control={<Checkbox checked={ok} onChange={(e) => setOk(e.target.checked)} />} label="I accept the end-user license agreement" />
      <Box><Button variant="contained" disabled={!ok} onClick={onSubscribe} aria-label={`Subscribe to ${name}`}>Subscribe</Button></Box>
    </>
  );
}

function CloudHub() {
  const project = useProject();
  const hub = useAsync(() => api.hub(), [project]);
  const h = hub.data;
  return (
    <>
      <PageHeader title="Cloud Hub" actions={<Button startIcon={<RefreshIcon />} onClick={hub.reload}>Refresh</Button>} />
      <ErrorAlert error={hub.error} title="Failed to load Cloud Hub" />
      {h && (
        <Stack spacing={3}>
          <Typography variant="body1" data-testid="hub-total">{h.totalResources} resources across {h.resources.length} products · {h.openIncidents.length} open incidents · {h.marketplaceSubscriptions} Marketplace subscriptions</Typography>
          <ResourceTable resourceName="products" items={h.resources} rowKey={(r) => r.product} filterPlaceholder="Filter products"
            columns={[{ id: "product", header: "Product", cell: (r) => r.product, sortValue: (r) => r.product }, { id: "count", header: "Resources", cell: (r) => r.count, sortValue: (r) => r.count }]}
            empty={<Typography>No resources in this project yet.</Typography>} />
          <Typography variant="h3" component="h2">Recent activity</Typography>
          <AuditTable rows={h.recentActivity} />
        </Stack>
      )}
    </>
  );
}

function AuditTable({ rows }) {
  return (
    <ResourceTable resourceName="entries" items={rows} rowKey={(e, ) => `${e.time}${e.method}${e.resource}`} filterPlaceholder="Filter"
      columns={[{ id: "time", header: "Time", cell: (e) => e.time, sortValue: (e) => e.time },
        { id: "principal", header: "Principal", cell: (e) => e.principal },
        { id: "method", header: "Method", cell: (e) => e.method },
        { id: "resource", header: "Resource", cell: (e) => e.resource }]}
      empty={<Typography>No audit entries yet.</Typography>} />
  );
}

export function PrivacySecurity() {
  const project = useProject();
  const ov = useAsync(() => api.privacy(), [project]);
  const log = useAsync(() => api.accessLog(), [project]);
  const o = ov.data;
  return (
    <>
      <PageHeader title="Privacy & Security" actions={<Button startIcon={<RefreshIcon />} onClick={() => { ov.reload(); log.reload(); }}>Refresh</Button>} />
      <ErrorAlert error={ov.error} title="Failed to load" />
      {o && (
        <Stack spacing={2} sx={{ mb: 3 }} data-testid="privacy-overview">
          <Typography variant="body1">Data residency: {o.dataResidency.state}{o.dataResidency.allowedValues?.length ? ` (${o.dataResidency.allowedValues.join(", ")})` : ""}</Typography>
          <Typography variant="body1">Customer-managed encryption keys: {o.customerManagedKeys}</Typography>
          <Typography variant="body1">Access Transparency: {o.access.accessTransparency.state}. {o.access.accessTransparency.note}</Typography>
          <Typography variant="body1">Access Approval: {o.access.accessApproval.state}. {o.access.accessApproval.note}</Typography>
        </Stack>
      )}
      <Typography variant="h3" component="h2" sx={{ mb: 1 }}>Access Transparency log</Typography>
      <AuditTable rows={log.data?.entries || []} />
    </>
  );
}

export default {
  nav: [{ text: "Marketplace", href: "#/marketplace", icon: StoreIcon }, { text: "Cloud Hub", href: "#/cloud-hub", icon: DashIcon }],
  routes: [{ pattern: "/marketplace", component: Marketplace }, { pattern: "/cloud-hub", component: CloudHub }],
};

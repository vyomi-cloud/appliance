/* Key ring detail: Keys + Import jobs (real: RSA wrapping key pair, 3-day expiry, public key PEM). Key rings and keys can't be deleted in Cloud KMS
 * itself, so there's no delete action here, matching the real console. */
import { useState } from "react";
import { Box, Breadcrumbs, Button, Chip, IconButton, MenuItem, Select, Stack, Tab, Tabs, TextField, Tooltip, Typography } from "@mui/material";
import { useNotify } from "../../../../common/notify.jsx";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../../common/useAsync.js";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import { ErrorAlert, fmtDate, PageHeader } from "../../../kit/common.jsx";
import { Link, hashHref } from "../../../link.jsx";
import * as api from "./api.js";

export default function KeyRingDetail({ params, query }) {
  const { location: loc, name: keyRing } = params;
  const tab = query.tab === "import" ? "import" : "keys";
  const ring = useAsync(() => api.getKeyRing(loc, keyRing), [loc, keyRing]);
  const keys = useAsync(() => api.listKeysInRing(loc, keyRing).then((ks) => ks.map((k) => ({ ...k, ...api.parseKeyName(k.name) }))), [loc, keyRing]);

  const jobs = useAsync(() => api.listImportJobs(loc, keyRing), [loc, keyRing]);
  const notify = useNotify();
  const [jobDlg, setJobDlg] = useState(false);
  const [jobId, setJobId] = useState("");
  const [jobMethod, setJobMethod] = useState(api.IMPORT_METHODS[0]);
  const [pem, setPem] = useState(null);
  const createJob = async () => {
    try {
      const j = await api.createImportJob(loc, keyRing, jobId, jobMethod);
      notify.success(`Created import job "${jobId}"`);
      setJobDlg(false); setJobId(""); setPem(j); jobs.reload();
    } catch (e) { notify.error(e); }
  };
  const setTab = (t) => { location.hash = hashHref("security", "kms", "keyring", "manage", loc, keyRing) + (t === "import" ? "?tab=import" : ""); };

  const labels = (k) => {
    const ls = Object.entries(k.labels || {});
    if (!ls.length) return "—";
    return <Stack direction="row" spacing={0.5}>{ls.slice(0, 2).map(([key, v]) => <Chip key={key} size="small" label={`${key}: ${v}`} />)}{ls.length > 2 && <Tooltip title={ls.slice(2).map(([key, v]) => `${key}: ${v}`).join(", ")}><Chip size="small" label={`+${ls.length - 2}`} /></Tooltip>}</Stack>;
  };

  return (
    <>
      <PageHeader title={keyRing} back={<IconButton aria-label="Back" href="#/security/kms/keyrings"><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<AddIcon />} href={`#/security/kms/key/create?location=${loc}&keyring=${encodeURIComponent(keyRing)}`}>Create key</Button>
          <Button startIcon={<RefreshIcon />} onClick={() => { ring.reload(); keys.reload(); }}>Refresh</Button>
        </>} />
      <Breadcrumbs sx={{ mb: 1.5 }}>
        <Link href="#/security/kms/keyrings">Key management</Link>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>{keyRing}</Typography>
      </Breadcrumbs>
      {ring.error && <ErrorAlert error={ring.error} title="Failed to load key ring" />}
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Key ring tabs">
        <Tab value="keys" label="Keys" />
        <Tab value="import" label="Import jobs" />
      </Tabs>
      {tab === "keys" && (
        <ResourceTable
          resourceName={`keys for "${keyRing}" key ring`}
          items={keys.data || []}
          rowKey={(k) => k.name}
          loading={keys.loading}
          error={keys.error}
          onRetry={keys.reload}
          selectable
          selected={[]}
          onSelectedChange={() => {}}
          filterPlaceholder="Filter"
          columns={[
            { id: "name", header: "Name", sortField: "key", cell: (k) => <Link href={hashHref("security", "kms", "key", "manage", loc, keyRing, k.key)}>{k.key}</Link> },
            { id: "status", header: "Status", cell: (k) => api.primaryState(k) },
            { id: "protection", header: "Protection level", cell: (k) => k.primary?.protectionLevel === "SOFTWARE" ? "Software" : k.primary?.protectionLevel },
            { id: "purpose", header: "Purpose", cell: (k) => api.purposeLabel(k.purpose) },
            { id: "labels", header: "Labels", cell: labels },
            { id: "primaryVersion", header: "Primary version", cell: (k) => api.parseVersionId(k.primary?.name) },
            { id: "primaryState", header: "Primary state", cell: (k) => api.primaryState(k) },
            { id: "created", header: "Creation date", sortField: "createTime", cell: (k) => fmtDate(k.createTime) },
            { id: "rotation", header: "Next rotation", cell: (k) => fmtDate(k.nextRotationTime) },
          ]}
          empty={
            <Stack spacing={1.5} alignItems="center">
              <Typography variant="body2" color="text.secondary">There are no keys in this key ring.</Typography>
              <Button variant="contained" startIcon={<AddIcon />} href={`#/security/kms/key/create?location=${loc}&keyring=${encodeURIComponent(keyRing)}`}>Create key</Button>
            </Stack>
          }
        />
      )}
      {tab === "import" && (
        <>
          <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
            <Button startIcon={<AddIcon />} onClick={() => setJobDlg(true)}>Create import job</Button>
            <Button startIcon={<RefreshIcon />} onClick={jobs.reload}>Refresh</Button>
          </Stack>
          <ResourceTable
            resourceName="import jobs"
            items={jobs.data || []}
            rowKey={(j) => j.name}
            loading={jobs.loading}
            error={jobs.error}
            onRetry={jobs.reload}
            selectable selected={[]} onSelectedChange={() => {}}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", cell: (j) => <Button size="small" onClick={() => setPem(j)}>{j.name.split("/").pop()}</Button> },
              { id: "state", header: "State", cell: (j) => j.state },
              { id: "method", header: "Import method", cell: (j) => j.importMethod },
              { id: "created", header: "Creation date", cell: (j) => fmtDate(j.createTime) },
              { id: "expires", header: "Expiration", cell: (j) => fmtDate(j.expireTime) },
            ]}
            empty={<Typography variant="body2" color="text.secondary">There are no import jobs in this key ring.</Typography>}
          />
          {jobDlg && (
            <Box role="dialog" aria-label="Create import job" sx={{ position: "fixed", inset: 0, bgcolor: "rgba(0,0,0,.4)", display: "grid", placeItems: "center", zIndex: 1300 }} onClick={() => setJobDlg(false)}>
              <Box sx={{ bgcolor: "background.paper", borderRadius: 2, p: 3, minWidth: 420 }} onClick={(e) => e.stopPropagation()}>
                <Typography variant="h3" component="h2" sx={{ mb: 2 }}>Create import job</Typography>
                <Stack spacing={2}>
                  <TextField label="Import job name" value={jobId} onChange={(e) => setJobId(e.target.value.trim())} />
                  <Select value={jobMethod} onChange={(e) => setJobMethod(e.target.value)} inputProps={{ "aria-label": "Import method" }}>
                    {api.IMPORT_METHODS.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
                  </Select>
                  <Typography variant="caption" color="text.secondary">Protection level: Software. The job expires 3 days after creation.</Typography>
                </Stack>
                <Stack direction="row" spacing={1} sx={{ mt: 3, justifyContent: "flex-end" }}>
                  <Button onClick={() => setJobDlg(false)}>Cancel</Button>
                  <Button variant="contained" disabled={!jobId} onClick={createJob}>Create</Button>
                </Stack>
              </Box>
            </Box>
          )}
          {pem && (
            <Box role="dialog" aria-label="Import job public key" sx={{ position: "fixed", inset: 0, bgcolor: "rgba(0,0,0,.4)", display: "grid", placeItems: "center", zIndex: 1300 }} onClick={() => setPem(null)}>
              <Box sx={{ bgcolor: "background.paper", borderRadius: 2, p: 3, maxWidth: 640 }} onClick={(e) => e.stopPropagation()}>
                <Typography variant="h3" component="h2" sx={{ mb: 1 }}>{pem.name.split("/").pop()} ({pem.state})</Typography>
                <Typography variant="body2" sx={{ mb: 1 }}>Wrap your key material with this public key ({pem.importMethod}), then import it from the key's Versions tab.</Typography>
                {pem.publicKey ? <Box component="pre" data-testid="import-pem" sx={{ fontSize: 11, overflow: "auto", maxHeight: 260, p: 1, bgcolor: "action.hover" }}>{pem.publicKey.pem}</Box>
                  : <Typography variant="body2">This job has expired; create a new one.</Typography>}
                <Stack direction="row" spacing={1} sx={{ mt: 2, justifyContent: "flex-end" }}>
                  {pem.publicKey && <Button onClick={() => navigator.clipboard?.writeText(pem.publicKey.pem)}>Copy public key</Button>}
                  <Button variant="contained" onClick={() => setPem(null)}>Close</Button>
                </Stack>
              </Box>
            </Box>
          )}
        </>
      )}
    </>
  );
}

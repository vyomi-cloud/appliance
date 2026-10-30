/* Key ring detail: Keys (real) + Import jobs (declared gap — external key import with
 * wrapped key material isn't modeled). Key rings and keys can't be deleted in Cloud KMS
 * itself, so there's no delete action here, matching the real console. */
import { useState } from "react";
import { Box, Breadcrumbs, Button, Chip, IconButton, Stack, Tab, Tabs, Tooltip, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../../common/useAsync.js";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import { ErrorAlert, fmtDate, NotSimulatedContainer, PageHeader } from "../../../kit/common.jsx";
import { Link, hashHref } from "../../../link.jsx";
import * as api from "./api.js";

export default function KeyRingDetail({ params, query }) {
  const { location: loc, name: keyRing } = params;
  const tab = query.tab === "import" ? "import" : "keys";
  const ring = useAsync(() => api.getKeyRing(loc, keyRing), [loc, keyRing]);
  const keys = useAsync(() => api.listKeysInRing(loc, keyRing).then((ks) => ks.map((k) => ({ ...k, ...api.parseKeyName(k.name) }))), [loc, keyRing]);

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
        <NotSimulatedContainer title="Import jobs" feature="Key import jobs"
          note="Importing external key material requires wrapping it against an RSA/AES import job key Vyomi would mint and prove possession of — a real HSM-backed exchange this simulator doesn't model." />
      )}
    </>
  );
}

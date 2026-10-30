/* Key management: the console's three top tabs (Key rings / Key inventory / Autokey) all
 * live on one page, same route family. */
import { useState } from "react";
import { Box, Button, Stack, Tab, Tabs, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../../common/useAsync.js";
import { useProject } from "../../../project.js";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../../kit/Capability.jsx";
import { fmtDate, PageHeader } from "../../../kit/common.jsx";
import { Link, hashHref } from "../../../link.jsx";
import * as api from "./api.js";

const TABS = [["rings", "Key rings", "#/security/kms/keyrings"], ["inventory", "Key inventory", "#/security/kms/key-inventory"], ["autokey", "Autokey", "#/security/kms/autokey"]];

export default function KeyManagement({ tab }) {
  return (
    <>
      <PageHeader title="Key management" />
      <Tabs value={tab} onChange={(_, t) => { location.hash = TABS.find((x) => x[0] === t)[2].slice(1); }}
        sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Key management tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "rings" && <KeyRings />}
      {tab === "inventory" && <KeyInventory />}
      {tab === "autokey" && <Autokey />}
    </>
  );
}

function KeyRings() {
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(async () => {
    const [rings, keys] = await Promise.all([api.listKeyRings(), api.listAllKeys()]);
    const counts = {};
    for (const k of keys) counts[api.parseKeyName(k.name).keyRing] = (counts[api.parseKeyName(k.name).keyRing] || 0) + 1;
    return rings.map((r) => ({ ...r, ...api.parseRingName(r.name), keyCount: counts[api.parseRingName(r.name).keyRing] || 0 }));
  }, [project]);

  return (
    <>
      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
        <Button startIcon={<AddIcon />} href="#/security/kms/keyring/create">Create key ring</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      <ResourceTable
        resourceName="key rings"
        items={data}
        rowKey={(r) => r.name}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "keyRing", cell: (r) => <Link href={hashHref("security", "kms", "keyring", "manage", r.location, r.keyRing)}>{r.keyRing}</Link> },
          { id: "location", header: "Location", sortField: "location", cell: (r) => r.location },
          { id: "keys", header: "Keys", sortField: "keyCount", cell: (r) => r.keyCount },
        ]}
        empty={<Typography variant="body2" color="text.secondary">There are no key rings in this project.</Typography>}
      />
    </>
  );
}

function KeyInventory() {
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(() => api.listAllKeys().then((ks) => ks.map((k) => ({ ...k, ...api.parseKeyName(k.name) }))), [project]);
  return (
    <CapabilityContainer id="gcp.kms.inventory" title="Key inventory"
      description="Keys across every key ring and location in this project."
      actions={<Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>}>
      <ResourceTable
        resourceName="keys"
        items={data}
        rowKey={(k) => k.name}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "key", cell: (k) => <Link href={hashHref("security", "kms", "key", "manage", k.location, k.keyRing, k.key)}>{k.key}</Link> },
          { id: "keyRing", header: "Key ring", sortField: "keyRing", cell: (k) => k.keyRing },
          { id: "location", header: "Location", sortField: "location", cell: (k) => k.location },
          { id: "purpose", header: "Purpose", cell: (k) => api.purposeLabel(k.purpose) },
          { id: "state", header: "Primary state", cell: (k) => api.primaryState(k) },
          { id: "created", header: "Creation date", sortField: "createTime", cell: (k) => fmtDate(k.createTime) },
          { id: "rotation", header: "Next rotation", cell: (k) => fmtDate(k.nextRotationTime) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">There are no keys in this project.</Typography>}
      />
    </CapabilityContainer>
  );
}

function Autokey() {
  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Autokey automatically provisions a key ring and key the first time a resource that supports CMEK is created in a project, folder or organization.
      </Typography>
      <CapabilityContainer id="gcp.kms.autokey" title="Autokey" />
    </Box>
  );
}

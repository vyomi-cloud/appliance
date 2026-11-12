/* Shared VPC — host/service project attachment (compute.googleapis.com projects.*
 * enableXpnHost/enableXpnResource). This project can be the host (sharing its
 * networks/subnets with attached service projects) or stay standalone. */
import { useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { useProject } from "../../project.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function SharedVpc() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [svcId, setSvcId] = useState("");
  const { data, loading, error, reload } = useAsync(async () => {
    const resources = await api.getXpnResources().catch(() => []);
    const usable = await api.listUsableSubnetworks().catch(() => []);
    return { resources, usable };
  }, [project]);

  const attach = async () => {
    if (!svcId.trim()) { notify.error({ message: "Service project ID is required." }); return; }
    try {
      await api.enableXpnResource(svcId.trim());
      notify.success(`Attached service project "${svcId.trim()}"`);
      setOpen(false); setSvcId(""); reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <PageHeader title="Shared VPC" actions={<>
        <Button onClick={async () => { try { await api.enableXpnHost(); notify.success("This project is now a Shared VPC host."); reload(); } catch (e) { notify.error(e); } }}>
          Set up this project as a host
        </Button>
        <Button color="error" onClick={async () => { try { await api.disableXpnHost(); notify.success("Shared VPC host disabled."); reload(); } catch (e) { notify.error(e); } }}>
          Disable host
        </Button>
      </>} />

      <CapabilityContainer id="gcp.networking.shared-vpc" title="Attached service projects"
        description="Service projects that use this project's VPC networks and subnets."
        actions={<>
          <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Attach service project</Button>
          <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={async () => {
            for (const id of sel) await api.disableXpnResource(id);
            notify.success(`Detached ${sel.length} service project(s)`); setSel([]); reload();
          }}>Detach</Button>
        </>}
      >
        <ResourceTable
          resourceName="service projects"
          items={data?.resources || []}
          rowKey={(r) => r.id}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Filter"
          columns={[{ id: "id", header: "Project ID", cell: (r) => r.id }, { id: "type", header: "Type", cell: (r) => r.type }]}
        />
      </CapabilityContainer>

      <Box sx={{ mt: 2 }}>
        <Section title="Usable subnetworks" description="Subnetworks this project can use — its own, plus its Shared VPC host's if attached to one.">
          <ResourceTable
            resourceName="usable subnetworks"
            items={data?.usable || []}
            rowKey={(s) => s.subnetwork}
            loading={loading}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Subnetwork", cell: (s) => api.nameOf(s.subnetwork) },
              { id: "network", header: "Network", cell: (s) => api.nameOf(s.network) },
              { id: "range", header: "IP range", cell: (s) => s.ipCidrRange },
            ]}
          />
        </Section>
      </Box>

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Attach service project</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              This project must be set up as a Shared VPC host first.
            </Typography>
            <TextField label="Service project ID" required value={svcId} onChange={(e) => setSvcId(e.target.value.trim())} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={attach}>Attach</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

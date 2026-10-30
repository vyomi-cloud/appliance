/* The console's "Deploy" action opens a dialog to pick a cluster and deploy a workload to
 * it. Vyomi has no live Kubernetes API server behind a cluster's endpoint (control plane
 * only), so deploying is an honest gap — this dialog says so instead of pretending to work. */
import { Button, Dialog, DialogActions, DialogContent, DialogTitle } from "@mui/material";
import { CapabilityContainer } from "../../kit/Capability.jsx";

export default function DeployDialog({ open, onClose }) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="deploy-title">
      <DialogTitle id="deploy-title">Deploy to Kubernetes clusters</DialogTitle>
      <DialogContent>
        <CapabilityContainer id="gcp.kubernetes.workloads" title="Deploy" />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}

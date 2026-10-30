/* "Connect" shows the real gcloud command to fetch cluster credentials, as the native
 * console does. The command is accurate (real cluster name/location/project); whether
 * kubectl then works depends on a live Kubernetes API server behind the endpoint, which
 * this capability declares limited — see core/capabilities/gcp/kubernetes.json. */
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { getProject } from "../../project.js";

function Cmd({ cmd }) {
  return (
    <Stack direction="row" spacing={1} alignItems="center" sx={{ bgcolor: "action.hover", borderRadius: 1, px: 1.5, py: 1 }}>
      <Typography component="code" variant="body2" sx={{ flex: 1, fontFamily: "monospace", overflowWrap: "anywhere" }}>{cmd}</Typography>
      <Tooltip title="Copy"><IconButton size="small" aria-label={`Copy: ${cmd}`} onClick={() => navigator.clipboard?.writeText(cmd).catch(() => {})}><ContentCopyIcon fontSize="inherit" /></IconButton></Tooltip>
    </Stack>
  );
}

export default function ConnectDialog({ open, onClose, cluster }) {
  if (!cluster) return null;
  const project = getProject();
  const gcloud = `gcloud container clusters get-credentials ${cluster.name} --region ${cluster.location_name || cluster.location} --project ${project}`;
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="connect-title">
      <DialogTitle id="connect-title">Connect to the cluster <CapabilityBadge id="gcp.kubernetes.cluster.connect" /></DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Command-line access</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Configure kubectl to connect to the cluster:</Typography>
            <Cmd cmd={gcloud} />
          </Box>
          <Typography variant="caption" color="text.secondary">
            This command points kubectl at the cluster's real endpoint and credentials, but no Kubernetes API server runs behind it in Vyomi — kubectl commands against the cluster will fail.
          </Typography>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}

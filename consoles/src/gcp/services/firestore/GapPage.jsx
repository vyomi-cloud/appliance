/* A whole-page honest gap, backed by a real capability-registry entry (title renders for
 * real; the body is the registry's declared "not simulated" panel) — gcp/firestore isn't on
 * the base branch's honest-allowlist, so these pages are real routes, never `honest_page`. */
import { Box, Typography } from "@mui/material";
import { CapabilityContainer } from "../../kit/Capability.jsx";

export default function GapPage({ title, id }) {
  return (
    <Box sx={{ pt: 2 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{title}</Typography>
      <CapabilityContainer id={id} title={title} />
    </Box>
  );
}

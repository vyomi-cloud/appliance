/* Org-scoped IAM & Admin pages still out of scope. The title is always real; the body
 * is an honest capability disclaimer (never a disabled skeleton of the real UI).
 * Not in the wave-5b depth-sweep goal list: Vyomi's GCP lens has no Access Transparency /
 * data-residency telemetry to back this page even with an organization modeled. */
import { Box, Typography } from "@mui/material";
import { CapabilityContainer } from "../../kit/Capability.jsx";

function orgOnly(title, id) {
  return function OrgOnlyPage() {
    return (
      <Box sx={{ pt: 1 }}>
        <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{title}</Typography>
        <CapabilityContainer id={id} title={title} />
      </Box>
    );
  };
}

export const PrivacySecurity = orgOnly("Privacy & Security", "gcp.iam-admin.privacy-security");

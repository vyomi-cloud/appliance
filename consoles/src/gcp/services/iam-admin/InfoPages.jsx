/* Org-scoped / not-yet-modeled IAM & Admin pages. The title is always real; the body
 * is an honest capability disclaimer (never a disabled skeleton of the real UI). */
import { Box, Typography } from "@mui/material";
import { CapabilityContainer } from "../../kit/Capability.jsx";

function orgOnly(title, id) {
  return function OrgOnlyPage() {
    return (
      <Box sx={{ pt: 1 }}>
        <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{title}</Typography>
        <Typography variant="body2" sx={{ mb: 2 }}>Page not viewable for projects. This feature requires an organization.</Typography>
        <CapabilityContainer id={id} title={title} />
      </Box>
    );
  };
}

function gap(title, id) {
  return function GapPage() {
    return (
      <Box sx={{ pt: 1 }}>
        <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{title}</Typography>
        <CapabilityContainer id={id} title={title} />
      </Box>
    );
  };
}

export const Groups = orgOnly("Groups", "gcp.iam-admin.groups");
export const WorkforceIdentityFederation = orgOnly("Workforce Identity Federation", "gcp.iam-admin.workforce-identity-federation");
export const IdentityOrganization = orgOnly("Identity & Organization", "gcp.iam-admin.identity-organization");
export const PrivacySecurity = orgOnly("Privacy & Security", "gcp.iam-admin.privacy-security");

export const PrincipalAccessBoundary = gap("Principal Access Boundary", "gcp.iam-admin.principal-access-boundary");
export const ManagedWorkloadIdentities = gap("Managed Workload Identities", "gcp.iam-admin.managed-workload-identities");
export const AssetInventory = gap("Asset Inventory", "gcp.iam-admin.asset-inventory");
export const SecurityInsights = gap("Security Insights", "gcp.iam-admin.security-insights");
export const IdentityAwareProxy = gap("Identity-Aware Proxy", "gcp.iam-admin.identity-aware-proxy");

/* Vulnerability findings of one Docker repository's images (Artifact Analysis). */
import { Chip, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const SEV = { CRITICAL: "error", HIGH: "error", MEDIUM: "warning", LOW: "default" };

export default function Vulnerabilities({ location, name, repo }) {
  const project = useProject();
  const v = useAsync(() => api.listVulnerabilities(location, name), [project, location, name]);
  const disabled = repo.vulnerabilityScanningConfig?.enablementConfig === "DISABLED";
  return (
    <CapabilityContainer id="gcp.artifacts.vulnerability-scanning" title="Vulnerabilities">
      {disabled ? <Typography variant="body2" color="text.secondary">Vulnerability scanning is disabled for this repository.</Typography> : (
        <ResourceTable resourceName="vulnerabilities" items={v.data || []} loading={v.loading} error={v.error} onRetry={v.reload} rowKey={(o) => o.name}
          filterPlaceholder="Filter vulnerabilities"
          columns={[
            { id: "cve", header: "Vulnerability", sortValue: (o) => o.vulnerability.shortDescription, cell: (o) => o.vulnerability.shortDescription },
            { id: "sev", header: "Severity", sortValue: (o) => o.vulnerability.cvssScore, cell: (o) => <Chip size="small" color={SEV[o.vulnerability.severity] || "default"} label={`${o.vulnerability.severity} (${o.vulnerability.cvssScore})`} /> },
            { id: "img", header: "Image", cell: (o) => o.resourceUri.replace(/^https:\/\/[^/]+\/[^/]+\/[^/]+\//, "") },
            { id: "pkg", header: "Package", cell: (o) => `${o.vulnerability.packageIssue[0].affectedPackage} ${o.vulnerability.packageIssue[0].affectedVersion.name}` },
            { id: "fix", header: "Fixed in", cell: (o) => o.vulnerability.packageIssue[0].fixedVersion.name || "no fix" },
            { id: "desc", header: "Description", cell: (o) => o.vulnerability.longDescription },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No known vulnerabilities in the images of this repository.</Typography>} />
      )}
    </CapabilityContainer>
  );
}

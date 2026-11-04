/* Identity & Organization — the project's real backing organization, via Resource
 * Manager's project.parent -> organization lookup. Claiming domain ownership /
 * Workspace signup (the real console's flow when a project has none yet) isn't
 * modeled — every Vyomi project already has one. */
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, KeyValue, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function IdentityOrganization() {
  const org = useAsync(() => api.getOrganization(), []);

  return (
    <>
      <PageHeader title="Identity & Organization" />
      <CapabilityContainer id="gcp.iam-admin.identity-organization" title="Organization">
        <ErrorAlert error={org.error} title="Failed to load organization" />
        {org.data && (
          <KeyValue items={[
            ["Organization name", org.data.displayName],
            ["Organization ID", org.data.name.split("/").pop()],
            ["Directory customer ID", org.data.directoryCustomerId],
            ["State", org.data.state],
          ]} />
        )}
      </CapabilityContainer>
    </>
  );
}

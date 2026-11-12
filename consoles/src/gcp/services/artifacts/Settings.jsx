/* Settings: gcr.io → Artifact Registry redirection, the native projectSettings resource. */
import { useState } from "react";
import { Button, CircularProgress, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const ENABLED = "REDIRECTION_FROM_GCR_IO_ENABLED";
const DISABLED = "REDIRECTION_FROM_GCR_IO_DISABLED";

export default function Settings() {
  const notify = useNotify();
  const project = useProject();
  const [busy, setBusy] = useState(false);
  const { data, loading, error, reload } = useAsync(() => api.getProjectSettings(), [project]);
  const state = data?.legacyRedirectionState;
  const enabled = state === ENABLED;

  const flip = async () => {
    setBusy(true);
    try {
      await api.updateProjectSettings(enabled ? DISABLED : ENABLED);
      notify.success(enabled ? "Disabled redirection from gcr.io" : "Enabled redirection from gcr.io");
      reload();
    } catch (e) { notify.error(e); }
    finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Settings" />
      <ErrorAlert error={error} title="Failed to load settings" />
      {loading && <CircularProgress size={24} />}
      {data && (
        <CapabilityContainer id="gcp.artifacts.project-settings" title="Redirection from gcr.io"
          description="Route docker.io/gcr.io image pulls through their equivalent Artifact Registry repositories."
          actions={<Button variant="outlined" disabled={busy} onClick={flip}>{enabled ? "Disable redirection" : "Enable redirection"}</Button>}>
          <Stack spacing={0.5}>
            <Typography variant="body2">Redirection is <b>{enabled ? "enabled" : "disabled"}</b> for this project.</Typography>
            <Typography variant="body2" color="text.secondary">
              {state === "REDIRECTION_FROM_GCR_IO_UNSPECIFIED" ? "This project has not configured redirection." : `Current state: ${state}`}
            </Typography>
          </Stack>
        </CapabilityContainer>
      )}
    </>
  );
}

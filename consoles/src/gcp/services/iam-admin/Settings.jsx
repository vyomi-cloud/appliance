/* Project settings — native Resource Manager v3 GetProject/PatchProject. */
import { useState } from "react";
import { Button, Stack, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, NotSimulated, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Settings() {
  const project = useAsync(() => api.getProjectMeta(), []);
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const [showShutdown, setShowShutdown] = useState(false);
  const data = project.data;

  return (
    <>
      <PageHeader title="Settings" actions={
        <Stack direction="row" spacing={1}>
          <Button onClick={() => setShowMove((v) => !v)}>Move</Button>
          <Button color="error" onClick={() => setShowShutdown((v) => !v)}>Shut down</Button>
        </Stack>} />
      <ErrorAlert error={project.error} title="Failed to load project" />
      {showMove && <NotSimulated feature="Moving a project to a different resource hierarchy" />}
      {showShutdown && <NotSimulated feature="Shutting down (deleting) a project" />}
      {data && (
        <Stack spacing={2}>
          <Section title="Project" actions={<Button variant="contained" size="small" disabled={busy} onClick={async () => {
            setBusy(true);
            try { await api.patchProjectMeta({ displayName: name || data.displayName }); notify.success("Project saved"); project.reload(); }
            catch (e) { notify.error(e); } finally { setBusy(false); }
          }}>Save</Button>}>
            <Stack spacing={2} sx={{ maxWidth: 480 }}>
              <TextField label="Project name" value={name || data.displayName} onChange={(e) => setName(e.target.value)} />
              <KeyValue items={[["Project ID", data.projectId], ["Project number", data.name.split("/").pop()]]} />
            </Stack>
          </Section>
          <Section title="Tags" actions={<Button size="small" href="#/iam-admin/tags">Manage tags</Button>}>
            <KeyValue items={[["Environment tag", Object.entries(data.labels || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "None"]]} />
          </Section>
          <Section title="Location">
            <KeyValue items={[["Location", "No organization"]]} />
          </Section>
          <Section title="Billing Account" actions={<Button size="small" onClick={() => notify.info("Billing isn't simulated in Vyomi.", "Manage billing")}>Manage billing</Button>}>
            <KeyValue items={[["Billing Account", "Not linked"]]} />
          </Section>
          <Section title="Access Transparency">
            <Typography variant="body2" color="text.secondary">Access Transparency is not enabled for this organization.</Typography>
          </Section>
        </Stack>
      )}
    </>
  );
}

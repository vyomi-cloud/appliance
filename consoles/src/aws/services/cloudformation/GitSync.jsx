/* CloudFormation Git sync: a CFN_STACK_SYNC configuration (CodeConnections-lite, core/aws_codeconn_core.py) links a
 * repository branch to this stack; every push to the branch reads the deployment file and creates/updates the stack
 * through the real CloudFormation core. Repositories owned by "vyomi" live inside Vyomi (push with VyomiPush). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Alert from "@cloudscape-design/components/alert";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import { awsJson } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const T = "com.amazonaws.codeconnections.CodeConnections_20231201.";
const cc = (op, body = {}) => awsJson("codeconnections", T + op, body);

export default function GitSync({ name }) {
  const notify = useNotify();
  const cur = useAsync(async () => {
    try {
      const cfg = (await cc("GetSyncConfiguration", { ResourceName: name, SyncType: "CFN_STACK_SYNC" })).SyncConfiguration;
      const status = await cc("GetResourceSyncStatus", { ResourceName: name, SyncType: "CFN_STACK_SYNC" });
      return { cfg, status };
    } catch (e) { if (e.code === "ResourceNotFoundException") return null; throw e; }
  }, [name]);
  const [f, setF] = useState({ owner: "vyomi", repo: "", branch: "main", file: "deployment.json", role: "arn:aws:iam::000000000000:role/GitSyncRole", trigger: "ANY_CHANGE" });
  const set = (k) => ({ detail }) => setF((x) => ({ ...x, [k]: detail.value ?? detail.selectedOption?.value }));
  const act = async (fn, ok) => { try { await fn(); notify.success(ok); await cur.reload(); } catch (e) { notify.error(e, "Git sync failed"); } };
  const link = () => act(async () => {
    let conn = (await cc("ListConnections")).Connections.find((c) => c.ProviderType === "GitHub");
    const arn = conn ? conn.ConnectionArn : (await cc("CreateConnection", { ConnectionName: "vyomi-github", ProviderType: "GitHub" })).ConnectionArn;
    const links = (await cc("ListRepositoryLinks")).RepositoryLinks;
    let l = links.find((x) => x.OwnerId === f.owner && x.RepositoryName === f.repo);
    if (!l) l = (await cc("CreateRepositoryLink", { ConnectionArn: arn, OwnerId: f.owner, RepositoryName: f.repo })).RepositoryLinkInfo;
    await cc("CreateSyncConfiguration", { Branch: f.branch, ConfigFile: f.file, RepositoryLinkId: l.RepositoryLinkId, ResourceName: name, RoleArn: f.role, SyncType: "CFN_STACK_SYNC", TriggerResourceUpdateOn: f.trigger });
  }, `Stack "${name}" is now synced from ${f.owner}/${f.repo}@${f.branch}.`);
  const d = cur.data;
  const last = d?.status?.LatestSync;
  return (
    <CapabilityContainer id="aws.cloudformation.git-sync" title="Git sync">
      {cur.loading && !d ? <Box>Loading...</Box> : d ? (
        <SpaceBetween size="m">
          <ColumnLayout columns={4} variant="text-grid">
            <div><Box variant="awsui-key-label">Repository</Box>{d.cfg.OwnerId}/{d.cfg.RepositoryName}</div>
            <div><Box variant="awsui-key-label">Branch</Box>{d.cfg.Branch}</div>
            <div><Box variant="awsui-key-label">Deployment file</Box>{d.cfg.ConfigFile}</div>
            <div><Box variant="awsui-key-label">Sync status</Box><StatusIndicator type={last?.Status === "SUCCEEDED" ? "success" : last?.Status === "FAILED" ? "error" : "in-progress"}>{last?.Status || "INITIATED"}</StatusIndicator></div>
            <div><Box variant="awsui-key-label">Trigger</Box>{d.cfg.TriggerResourceUpdateOn}</div>
            <div><Box variant="awsui-key-label">Last synced commit</Box>{(d.status.DesiredState?.Sha || "-").slice(0, 10)}</div>
          </ColumnLayout>
          {last?.Error && <Alert type="error" header="Last sync failed">{last.Error}</Alert>}
          <Table variant="embedded" header={<Box variant="h3">Sync events</Box>} items={d.status.Events || []} empty={<Box>No sync events yet.</Box>}
            columnDefinitions={[{ id: "t", header: "Time", cell: (e) => e.Time }, { id: "e", header: "Event", cell: (e) => e.Event }, { id: "x", header: "Trigger", cell: (e) => e.ExternalId.slice(0, 18) }]} />
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => act(() => awsJson("codeconnections", T + "VyomiSync", { ResourceName: name }), "Sync finished.")}>Sync now</Button>
            <Button onClick={() => act(() => cc("DeleteSyncConfiguration", { ResourceName: name, SyncType: "CFN_STACK_SYNC" }), "Git sync was removed; the stack is unchanged.")}>Remove Git sync</Button>
          </SpaceBetween>
        </SpaceBetween>
      ) : (
        <SpaceBetween size="m">
          <Alert type="info">Link a repository branch to this stack. The deployment file (JSON/YAML) names the template: {"{ \"template-file-path\": \"template.yaml\", \"parameters\": {}, \"tags\": {} }"}. Use owner <b>vyomi</b> for a repository inside Vyomi; other GitHub owners need a personal access token.</Alert>
          <ColumnLayout columns={3}>
            <FormField label="Repository owner"><Input value={f.owner} onChange={set("owner")} ariaLabel="Repository owner" /></FormField>
            <FormField label="Repository name"><Input value={f.repo} onChange={set("repo")} ariaLabel="Repository name" /></FormField>
            <FormField label="Branch"><Input value={f.branch} onChange={set("branch")} ariaLabel="Branch" /></FormField>
            <FormField label="Deployment file path"><Input value={f.file} onChange={set("file")} ariaLabel="Deployment file path" /></FormField>
            <FormField label="IAM role ARN"><Input value={f.role} onChange={set("role")} ariaLabel="IAM role ARN" /></FormField>
            <FormField label="Trigger resource update on"><Select selectedOption={{ value: f.trigger, label: f.trigger }} onChange={set("trigger")} ariaLabel="Trigger" options={[{ value: "ANY_CHANGE", label: "ANY_CHANGE" }, { value: "FILE_CHANGE", label: "FILE_CHANGE" }]} /></FormField>
          </ColumnLayout>
          <Button variant="primary" disabled={!f.repo} onClick={link}>Link repository</Button>
        </SpaceBetween>
      )}
    </CapabilityContainer>
  );
}

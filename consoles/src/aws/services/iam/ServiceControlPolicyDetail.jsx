/* Organization policy detail (SCP / RCP) — real DescribePolicy, attach/detach to the root, OUs and
 * accounts (AttachPolicy / DetachPolicy / ListTargetsForPolicy) and editable policy JSON
 * (UpdatePolicy). The service access report is derived from recorded activity (limited). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import CopyToClipboard from "@cloudscape-design/components/copy-to-clipboard";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { parentLabel, useOrgModel } from "./OrgKit.jsx";
import ServiceAccessReport from "./ServiceAccessReport.jsx";
import * as api from "./api.js";

export default function ServiceControlPolicyDetail({ params, type = "SERVICE_CONTROL_POLICY" }) {
  const notify = useNotify();
  const name = decodeURIComponent(params.name);
  const model = useOrgModel();
  const p = useAsync(async () => {
    const found = (await api.orgListPolicies(type)).find((x) => x.Name === name);
    if (!found) return null;
    const [full, targets] = await Promise.all([api.orgDescribePolicy(found.Id), api.listTargetsForPolicy(found.Id)]);
    return { ...full, targets };
  }, [name]);
  const [draft, setDraft] = useState(null);
  const [pick, setPick] = useState(null);
  if (p.loading || model.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (p.error) return <ErrorAlert error={p.error} />;
  const policy = p.data;
  if (!policy) return <ErrorAlert error={{ code: "NotFound", message: `Policy ${name} not found.` }} />;
  const s = policy.PolicySummary;
  const m = model.data;
  let pretty = policy.Content;
  try { pretty = JSON.stringify(JSON.parse(policy.Content), null, 2); } catch { /* leave as-is */ }
  const attachedIds = new Set(policy.targets.map((t) => t.TargetId));
  const choices = [
    ...(m?.root ? [{ value: m.root.Id, label: `Root (${m.root.Id})` }] : []),
    ...(m?.ous || []).map((u) => ({ value: u.Id, label: `OU: ${parentLabel(m, u.Id)}` })),
    ...(m?.accounts || []).map((a) => ({ value: a.Id, label: `Account: ${a.Name} (${a.Id})` })),
  ].filter((c) => !attachedIds.has(c.value));
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); p.reload(); } catch (e) { notify.error(e); } };

  return (
    <ContentLayout header={<Header variant="h1">{s.Name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={2} items={[
          ["ARN", s.Arn], [type === "SERVICE_CONTROL_POLICY" ? "SCP ID" : "RCP ID", s.Id],
          ["Description", s.Description || "-"], ["Attached to number of entities", String(policy.targets.length)],
        ]} />
        <CapabilityContainer id="iam.organizations.policies" title="Targets" counter={`(${policy.targets.length})`}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Select selectedOption={pick} onChange={({ detail }) => setPick(detail.selectedOption)} options={choices} placeholder="Choose a target" ariaLabel="Attach target" />
            <Button disabled={!pick} onClick={() => act(async () => { await api.orgAttachPolicy(s.Id, pick.value); setPick(null); }, "Policy attached.")}>Attach</Button>
          </SpaceBetween>}>
          <Table variant="embedded" items={policy.targets} trackBy="TargetId"
            columnDefinitions={[
              { id: "name", header: "Name", isRowHeader: true, cell: (t) => t.Name },
              { id: "type", header: "Type", cell: (t) => t.Type },
              { id: "id", header: "Target ID", cell: (t) => t.TargetId },
              { id: "act", header: "Actions", cell: (t) => <Button variant="inline-link" onClick={() => act(() => api.orgDetachPolicy(s.Id, t.TargetId), "Policy detached.")}>Detach</Button> },
            ]}
            empty={<Box textAlign="center"><b>Not attached to any root, OU or account</b></Box>} />
        </CapabilityContainer>
        {type === "SERVICE_CONTROL_POLICY" && <ServiceAccessReport policy={policy} model={m} />}
        <CapabilityContainer id="iam.organizations.policies" title="Policy JSON"
          actions={<SpaceBetween direction="horizontal" size="xs">
            {!s.AwsManaged && (draft === null
              ? <Button onClick={() => setDraft(pretty)}>Edit</Button>
              : <Button variant="primary" onClick={() => act(async () => { await api.orgUpdatePolicy(s.Id, { Content: draft }); setDraft(null); }, "Policy updated.")}>Save changes</Button>)}
            <CopyToClipboard variant="icon" textToCopy={pretty} copyButtonAriaLabel="Copy" copySuccessText="Copied" copyErrorText="Couldn't copy" />
          </SpaceBetween>}>
          {draft === null
            ? <Box variant="code" fontSize="body-s"><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{pretty}</pre></Box>
            : <Textarea rows={12} value={draft} onChange={({ detail }) => setDraft(detail.value)} spellcheck={false} />}
        </CapabilityContainer>
      </SpaceBetween>
    </ContentLayout>
  );
}

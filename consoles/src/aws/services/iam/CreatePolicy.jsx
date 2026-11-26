/* Create policy — defaults to the real JSON editor path (validated client-side);
 * "Visual" editor isn't modeled (no per-service action/resource picker is computed). */
import { useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import Alert from "@cloudscape-design/components/alert";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import { ErrorAlert } from "../../kit/common.jsx";
import { useCatalogs, loadCatalog } from "../../kit/PermissionPicker.jsx";
import { statementsToPolicy, policyToStatements, newStatement, validatePolicy } from "../../kit/iamPolicy.js";
import { useIamApi } from "../../../common/iamEnforceHooks.js";
import { VisualEditor, JsonEditor } from "./PolicyEditor.jsx";
import * as api from "./api.js";

const EMPTY_DOC = JSON.stringify({ Version: "2012-10-17", Statement: [{ Sid: "Statement1", Effect: "Allow", Action: [], Resource: [] }] }, null, 2);

function PermissionsStep({ s, set, jsonErr, cats, api2 }) {
  const switchTo = async (editor) => {
    if (editor === s.editor) return;
    if (editor === "JSON") {
      const doc = s.stmts.some((x) => x.service) ? JSON.stringify(statementsToPolicy(s.stmts, cats), null, 2) : s.doc;
      return set({ editor, doc, convErr: null });
    }
    try {
      const d = JSON.parse(s.doc);
      const stmts = await policyToStatements(d, (svc) => loadCatalog(api2, svc));
      set({ editor, stmts: stmts.length ? stmts : [newStatement()], convErr: null });
    } catch (e) { set({ convErr: `Can't show this policy in the visual editor: ${e.message}` }); }
  };
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" actions={
        <SegmentedControl selectedId={s.editor} onChange={({ detail }) => switchTo(detail.selectedId)} label="Policy editor mode" options={[{ id: "Visual", text: "Visual" }, { id: "JSON", text: "JSON" }]} />}>Policy editor</Header>}>
        <SpaceBetween size="m">
          {s.convErr && <Alert type="warning" statusIconAriaLabel="Warning">{s.convErr}</Alert>}
          {s.editor === "Visual"
            ? <VisualEditor stmts={s.stmts} setStmts={(stmts) => set({ stmts })} />
            : <><JsonEditor doc={s.doc} setDoc={(doc) => set({ doc })} />{jsonErr && <Box color="text-status-error">{jsonErr}</Box>}</>}
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );
}

function ReviewStep({ s, set }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Policy details</Header>}>
        <SpaceBetween size="m">
          <FormField label="Policy name" constraintText="Maximum 128 characters. Use alphanumeric and '+=,.@-_' characters.">
            <Input value={s.name} onChange={({ detail }) => set({ name: detail.value })} ariaLabel="Policy name" />
          </FormField>
          <FormField label="Description - optional" constraintText="Maximum 1,000 characters.">
            <Textarea value={s.description} onChange={({ detail }) => set({ description: detail.value })} ariaLabel="Description - optional" />
          </FormField>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2">Permissions defined in this policy</Header>}>
        <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{s.doc}</pre></Box>
      </Container>
      <Container header={<Header variant="h2">Add tags - optional</Header>}>
        <FormField label="Tags"><TagEditor tags={s.tags} onChange={({ detail }) => set({ tags: detail.tags })} /></FormField>
      </Container>
    </SpaceBetween>
  );
}

export default function CreatePolicy() {
  const notify = useNotify();
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [jsonErr, setJsonErr] = useState(null);
  const [s, setS] = useState({ editor: "Visual", stmts: [newStatement()], doc: EMPTY_DOC, name: "", description: "", tags: [], convErr: null });
  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));
  const api2 = useIamApi("aws");
  const cats = useCatalogs(s.stmts.map((x) => x.service).filter(Boolean));
  const doc = s.editor === "Visual" ? JSON.stringify(statementsToPolicy(s.stmts, cats), null, 2) : s.doc;

  const finish = async () => {
    try { JSON.parse(doc); } catch (e) { setJsonErr(`Policy document is not valid JSON: ${e.message}`); setIdx(0); return; }
    if (validatePolicy(doc, cats).errors.length) { setJsonErr("Fix the errors in the policy before creating it."); setIdx(0); return; }
    setJsonErr(null); setBusy(true); setError(null);
    try {
      const tags = s.tags.filter((t) => !t.markedForRemoval && t.key);
      await api.createPolicy({ PolicyName: s.name, PolicyDocument: doc, Description: s.description, ...api.tagsParams(tags) });
      notify.success(`Policy "${s.name}" created.`);
      navigate("iam", "policies", s.name);
    } catch (e) { setError(e); setIdx(1); } finally { setBusy(false); }
  };

  const steps = [
    { title: "Specify permissions", content: <PermissionsStep s={s} set={set} jsonErr={jsonErr} cats={cats} api2={api2} /> },
    { title: "Review and create", content: <>
      {error && <Box padding={{ bottom: "s" }}><ErrorAlert error={error} header="Couldn't create policy" /></Box>}
      <ReviewStep s={{ ...s, doc }} set={set} />
    </> },
  ];

  return (
    <Box padding={{ top: "l" }}>
      <Wizard
        activeStepIndex={idx}
        onNavigate={({ detail }) => {
          if (detail.requestedStepIndex > idx) {
            const bad = validatePolicy(doc, cats).errors;
            if (bad.length || !JSON.parse(doc).Statement?.length) { setJsonErr(bad[0]?.message || "Add at least one permission statement."); return; }
          }
          setJsonErr(null); setIdx(detail.requestedStepIndex);
        }}
        onCancel={() => navigate("iam", "policies")}
        onSubmit={finish}
        isLoadingNextStep={busy}
        submitButtonText="Create policy"
        i18nStrings={{ stepNumberLabel: (n) => `Step ${n}`, collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`, cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", optional: "optional" }}
        steps={steps}
      />
    </Box>
  );
}

/* Create function: Select a template, Template details → one native ARM PUT on
 * .../sites/{name}/functions/{fn}. */
import { useState } from "react";
import { Input, Radio, RadioGroup, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import * as api from "./api.js";

const FN_NAME_RE = /^[A-Za-z][-A-Za-z0-9_]{0,127}$/;

export default function CreateFunction({ params }) {
  const { rg, name } = params;
  const notify = useNotify();
  const [template, setTemplate] = useState(api.TEMPLATES[0][0]);
  const [fnName, setFnName] = useState("http_trigger");
  const [authLevel, setAuthLevel] = useState("FUNCTION");

  const template_ = (
    <FormSection title="Select a template">
      <Table size="small" aria-label="Template">
        <TableHeader><TableRow><TableHeaderCell>Template</TableHeaderCell><TableHeaderCell>Description</TableHeaderCell></TableRow></TableHeader>
        <TableBody>
          {api.TEMPLATES.map(([key, label]) => (
            <TableRow key={key} aria-selected={template === key} onClick={() => setTemplate(key)} style={{ cursor: "pointer", background: template === key ? "var(--colorNeutralBackground1Selected)" : undefined }}>
              <TableCell><Radio checked={template === key} onChange={() => setTemplate(key)} label={label} /></TableCell>
              <TableCell>A {label.toLowerCase()} starter function.</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </FormSection>
  );

  const details = (
    <FormSection title="Template details">
      <FormRow label="Function name" required htmlFor="fn-name">
        <Input id="fn-name" value={fnName} onChange={(_, d) => setFnName(d.value)} aria-label="Function name" />
      </FormRow>
      <FormRow label="Authorization level" htmlFor="fn-auth">
        <Select id="fn-auth" value={authLevel} onChange={(_, d) => setAuthLevel(d.value)} aria-label="Authorization level">
          <option value="FUNCTION">FUNCTION</option><option value="ANONYMOUS">ANONYMOUS</option><option value="ADMIN">ADMIN</option>
        </Select>
      </FormRow>
    </FormSection>
  );

  const validate = () => (FN_NAME_RE.test(fnName) ? [] : ["Function name must start with a letter and contain only letters, digits, '-' or '_'."]);
  const onCreate = async () => {
    try {
      await api.createFunction(rg, name, fnName, api.functionBody(template, authLevel.toLowerCase()));
      notify.success(`Function '${fnName}' was created.`, "Function created");
      navigate("functionapp", rg, name, "functions", fnName);
    } catch (e) { notify.error(e, "Create function failed"); }
  };

  return (
    <CreateWizard
      title="Create function" closeHref={`#/functionapp/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`} glyph={<Glyph id="functionapp" />}
      tabs={[
        { id: "template", label: "Select a template", content: template_ },
        { id: "details", label: "Template details", content: details, validate },
      ]}
      review={() => <dl><dt>Function name</dt><dd>{fnName}</dd><dt>Template</dt><dd>{api.TEMPLATES.find((t) => t[0] === template)?.[1]}</dd><dt>Authorization level</dt><dd>{authLevel}</dd></dl>}
      onCreate={onCreate}
    />
  );
}

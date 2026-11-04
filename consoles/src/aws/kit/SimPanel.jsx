/* A "simulator verb" panel: a small form -> one data-plane evaluation -> the verdict + step trace. Used by VPC Lattice "Test invoke",
 * Network Firewall "Simulate traffic" and DNS Firewall "Resolve query". Every result is the backend's real evaluation, never canned. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import { ErrorAlert } from "./common.jsx";

/** fields: [{key,label,default,options?:[{value,label}],description}], run(values) -> result object, verdict(result) -> [type, text],
 *  steps(result) -> [{step,detail}] | undefined */
export default function SimPanel({ title, description, fields, run, verdict, steps, testId = "sim" }) {
  const [v, setV] = useState(() => Object.fromEntries(fields.map((f) => [f.key, f.default ?? ""])));
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await run(v)); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const [vt, vx] = res ? verdict(res) : [];
  const st = res && steps ? steps(res) : null;
  return (
    <Container header={<Header variant="h2" description={description} actions={<Button variant="primary" loading={busy} onClick={go}>{title}</Button>}>{title}</Header>}>
      <SpaceBetween size="l">
        <ColumnLayout columns={3}>
          {fields.map((f) => (
            <FormField key={f.key} label={f.label} description={f.description}>
              {f.options
                ? <Select ariaLabel={f.label} selectedOption={f.options.find((o) => o.value === v[f.key]) || null} options={f.options} onChange={({ detail }) => setV({ ...v, [f.key]: detail.selectedOption.value })} />
                : <Input ariaLabel={f.label} value={v[f.key]} onChange={({ detail }) => setV({ ...v, [f.key]: detail.value })} />}
            </FormField>))}
        </ColumnLayout>
        <ErrorAlert error={err} />
        {res && <Alert type={vt} header="Result" data-testid={`${testId}-result`}>{vx}</Alert>}
        {st && st.length > 0 && <Table variant="embedded" header={<Box variant="h3">Evaluation steps</Box>} items={st} trackBy={(i) => JSON.stringify(i)}
          columnDefinitions={[{ id: "s", header: "Step", cell: (r) => r.step }, { id: "d", header: "Detail", cell: (r) => r.detail ?? "-" }]} />}
      </SpaceBetween>
    </Container>
  );
}

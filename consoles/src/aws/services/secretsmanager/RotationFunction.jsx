/* "Rotation function" picker — a Lambda function Secrets Manager invokes through createSecret/setSecret/testSecret/finishSecret. */
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

const NONE = { value: "", label: "No rotation function (carry the current value into a new version)" };

export default function RotationFunction({ value, onChange }) {
  const fns = useAsync(() => api.listLambdaFunctions(), []);
  const opts = [NONE, ...(fns.data || []).map((f) => ({ value: f.FunctionArn, label: f.FunctionName, description: f.Runtime }))];
  return (
    <FormField label="Lambda rotation function" description="Invoked with the four rotation steps; the console grants secretsmanager.amazonaws.com permission to invoke it.">
      <Select ariaLabel="Lambda rotation function" selectedOption={opts.find((o) => o.value === (value || "")) || { value, label: value }} options={opts}
        statusType={fns.loading ? "loading" : "finished"} onChange={({ detail }) => onChange(detail.selectedOption.value)} />
    </FormField>
  );
}

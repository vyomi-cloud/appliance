/* Training-data picker for a real (head) training job: bucket + object from the simulated S3, then a client-side check
 * against the shared caps (rows / size / labels) so the user sees the reason before the cloud's own validation error. */
import { useEffect, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { s3 as s3call } from "../../../../common/wire.js";
import { CAPS, validateJsonl } from "../../../../common/training.js";
import * as s3api from "../../s3/api.js";

const enc = (k) => k.split("/").map(encodeURIComponent).join("/");

/** props: taskType, uri/onUri (s3://bucket/key), onCheck(result|null) so the parent can disable Create. */
export default function TrainingData({ taskType, uri, onUri, onCheck }) {
  const [buckets, setBuckets] = useState([]), [keys, setKeys] = useState([]), [bucket, setBucket] = useState(null), [res, setRes] = useState(null), [loading, setLoading] = useState(false);
  useEffect(() => { s3api.listBuckets().then((b) => setBuckets(b.map((x) => x.name))).catch(() => setBuckets([])); }, []);
  useEffect(() => {
    if (!bucket) return;
    s3api.listObjects(bucket, "").then((r) => setKeys(r.objects.filter((o) => /\.jsonl?$/i.test(o.key)))).catch(() => setKeys([]));
  }, [bucket]);
  const m = String(uri || "").match(/^s3:\/\/([^/]+)\/(.+)$/);
  useEffect(() => {
    let dead = false;
    setRes(null); onCheck?.(null);
    if (!m) return undefined;
    setLoading(true);
    (async () => {
      let size; try { const l = await s3api.listObjects(m[1], m[2]); size = l.objects.find((o) => o.key === m[2])?.size; } catch { /* checked below */ }
      if (size != null && size > CAPS.bytes) return validateJsonl(null, taskType, size);
      const r = await s3call("GET", `/${m[1]}/${enc(m[2])}`, { raw: true });
      return validateJsonl(r.text, taskType, size);
    })().then((v) => { if (!dead) { setRes(v); onCheck?.(v); } })
      .catch((e) => { if (!dead) { const v = { ok: false, rows: 0, bytes: 0, labels: [], errors: [`Could not read ${uri}: ${e.message || e}`], preview: [] }; setRes(v); onCheck?.(v); } })
      .finally(() => !dead && setLoading(false));
    return () => { dead = true; };
  }, [uri, taskType]);   // eslint-disable-line react-hooks/exhaustive-deps
  const bo = buckets.map((b) => ({ label: b, value: b })), ko = keys.map((k) => ({ label: k.key, value: k.key, description: `${(k.size / 1024).toFixed(1)} KB` }));
  return (
    <SpaceBetween size="s">
      <FormField label="Training data (S3 object)" description={`JSONL in the simulated S3. Limits: ${CAPS.rows} rows, ${CAPS.bytes / 1048576} MB, ${CAPS.labels} labels.`}>
        <SpaceBetween direction="horizontal" size="xs">
          <Select selectedOption={bo.find((o) => o.value === (bucket || m?.[1])) || null} options={bo} placeholder="Choose bucket" ariaLabel="Training data bucket" onChange={({ detail }) => { setBucket(detail.selectedOption.value); onUri(`s3://${detail.selectedOption.value}/`); }} />
          <Select selectedOption={ko.find((o) => o.value === m?.[2]) || null} options={ko} placeholder="Choose .jsonl object" ariaLabel="Training data object" empty="No .jsonl objects in this bucket" disabled={!bucket && !m}
            onChange={({ detail }) => onUri(`s3://${bucket || m[1]}/${detail.selectedOption.value}`)} />
        </SpaceBetween>
      </FormField>
      {loading && <Box color="text-status-inactive">Checking the file against the limits...</Box>}
      {res && !res.ok && <Alert type="error" header="Training data cannot be used" data-testid="data-errors"><ul style={{ margin: 0, paddingLeft: 18 }}>{res.errors.map((e) => <li key={e}>{e}</li>)}</ul></Alert>}
      {res?.ok && <Alert type="success" data-testid="data-ok">{res.rows} rows, {(res.bytes / 1024).toFixed(1)} KB{res.labels.length ? `, ${res.labels.length} labels (${res.labels.slice(0, 6).join(", ")}${res.labels.length > 6 ? ", ..." : ""})` : ""}. Within the limits.</Alert>}
    </SpaceBetween>
  );
}

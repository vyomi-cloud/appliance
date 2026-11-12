/* Binary Authorization: the project policy (rule, allowlist, required attestors), attestors with their PKIX keys,
 * attestations (Container Analysis occurrences) and the admission decision log. Enforced at Cloud Run deploy. */
import { useState } from "react";
import { Alert, Button, Chip, Stack, Tab, Tabs, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import FormDialog from "../../../kit/FormDialog.jsx";
import { PageHeader, KeyValue, fmtDate } from "../../../kit/common.jsx";
import { CapabilityContainer } from "../../../kit/Capability.jsx";
import { useProject } from "../../../project.js";
import * as api from "./api.js";

const MODES = ["ALWAYS_ALLOW", "ALWAYS_DENY", "REQUIRE_ATTESTATION"];
const ENF = ["ENFORCED_BLOCK_AND_AUDIT_LOG", "DRYRUN_AUDIT_LOG_ONLY"];

export default function BinAuthz({ query }) {
  const tab = ["attestors", "attestations", "decisions"].includes(query.tab) ? query.tab : "policy";
  const project = useProject();
  const notify = useNotify();
  const policy = useAsync(api.getPolicy, [project]);
  const attestors = useAsync(api.listAttestors, [project]);
  const occs = useAsync(api.listOccurrences, [project]);
  const dec = useAsync(api.decisions, [project]);
  const [dlg, setDlg] = useState(null);
  const [probe, setProbe] = useState(null);
  const reload = () => { policy.reload(); attestors.reload(); occs.reload(); dec.reload(); };
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); } catch (e) { notify.error(e.message); } reload(); };
  const r = policy.data?.defaultAdmissionRule;

  return (
    <>
      <PageHeader title="Binary Authorization" actions={<>
        <Button onClick={() => setDlg("check")}>Check an image</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = "#/security/binauthz" + (t === "policy" ? "" : "?tab=" + t); }} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }}>
        <Tab value="policy" label="Policy" /><Tab value="attestors" label="Attestors" /><Tab value="attestations" label="Attestations" /><Tab value="decisions" label="Decisions" />
      </Tabs>
      {probe && <Alert sx={{ mb: 2 }} severity={probe.allowed ? "success" : "error"} onClose={() => setProbe(null)}>{probe.image}: {probe.allowed ? "allowed" : "denied"} - {probe.reason}</Alert>}
      {tab === "policy" && (
        <CapabilityContainer id="gcp.run.binary-authorization" title="Project policy">
          {r && <KeyValue items={[
            ["Policy", policy.data.name],
            ["Default rule", <Chip size="small" color={r.evaluationMode === "ALWAYS_DENY" ? "error" : r.evaluationMode === "ALWAYS_ALLOW" ? "default" : "primary"} label={r.evaluationMode} />],
            ["Enforcement", r.enforcementMode],
            ["Required attestors", (r.requireAttestationsBy || []).join(", ") || "-"],
            ["Global Google-image allowlist", policy.data.globalPolicyEvaluationMode],
            ["Allowlist patterns", (policy.data.admissionWhitelistPatterns || []).map((x) => x.namePattern).join(", ") || "-"],
          ]} />}
          <Stack direction="row" spacing={1} sx={{ mt: 2 }}><Button variant="contained" onClick={() => setDlg("policy")}>Edit policy</Button></Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>Cloud Run services created or updated with Binary Authorization enabled are checked against this policy at deploy time; a denied image blocks the deploy.</Typography>
        </CapabilityContainer>
      )}
      {tab === "attestors" && (
        <CapabilityContainer id="gcp.run.binary-authorization" title="Attestors">
          <Button sx={{ mb: 1 }} onClick={() => setDlg("attestor")}>Create attestor</Button>
          <ResourceTable resourceName="attestors" items={attestors.data || []} loading={attestors.loading} error={attestors.error} onRetry={attestors.reload} rowKey={(a) => a.name}
            columns={[
              { id: "n", header: "Name", cell: (a) => a.name.split("/").pop() },
              { id: "note", header: "Note", cell: (a) => a.userOwnedGrafeasNote.noteReference },
              { id: "keys", header: "Keys", cell: (a) => a.userOwnedGrafeasNote.publicKeys.length },
              { id: "act", header: "", cell: (a) => <Button size="small" color="error" onClick={() => act(() => api.deleteAttestor(a.name), "Attestor deleted")}>Delete</Button> },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No attestors. Create one with an ECDSA P-256 public key.</Typography>} />
        </CapabilityContainer>
      )}
      {tab === "attestations" && (
        <CapabilityContainer id="gcp.run.binary-authorization" title="Attestations">
          <Button sx={{ mb: 1 }} onClick={() => setDlg("occ")}>Add attestation</Button>
          <ResourceTable resourceName="attestations" items={occs.data || []} loading={occs.loading} error={occs.error} onRetry={occs.reload} rowKey={(o) => o.name}
            columns={[
              { id: "img", header: "Image", cell: (o) => o.resourceUri },
              { id: "note", header: "Note", cell: (o) => o.noteName },
              { id: "sigs", header: "Signatures", cell: (o) => (o.attestation.signatures || []).length },
              { id: "t", header: "Created", cell: (o) => fmtDate(o.createTime) },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No attestations.</Typography>} />
        </CapabilityContainer>
      )}
      {tab === "decisions" && (
        <CapabilityContainer id="gcp.run.binary-authorization" title="Admission decisions">
          <ResourceTable resourceName="decisions" items={[...(dec.data || [])].reverse()} loading={dec.loading} error={dec.error} onRetry={dec.reload} rowKey={(d, i) => d.time + i}
            columns={[
              { id: "t", header: "Time", cell: (d) => fmtDate(d.time) },
              { id: "img", header: "Image", cell: (d) => d.image },
              { id: "res", header: "Result", cell: (d) => <Chip size="small" color={d.allowed ? "success" : d.enforced ? "error" : "warning"} label={d.allowed ? "Allowed" : d.enforced ? "Blocked" : "Dry-run deny"} /> },
              { id: "why", header: "Reason", cell: (d) => d.reason },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No deploys have been evaluated yet.</Typography>} />
        </CapabilityContainer>
      )}
      <FormDialog open={dlg === "policy"} title="Edit policy" submitLabel="Save" onClose={(ok) => { setDlg(null); if (ok) reload(); }}
        onSubmit={async (v) => {
          const rule = { evaluationMode: v.mode, enforcementMode: v.enf, ...(v.mode === "REQUIRE_ATTESTATION" ? { requireAttestationsBy: v.attestors.split(",").map((s) => s.trim()).filter(Boolean) } : {}) };
          await api.putPolicy({ globalPolicyEvaluationMode: "ENABLE", defaultAdmissionRule: rule, admissionWhitelistPatterns: v.allow.split(/[\n,]/).map((s) => s.trim()).filter(Boolean).map((namePattern) => ({ namePattern })) });
          notify.success("Policy saved");
        }}
        fields={[{ key: "mode", label: "Default rule", options: MODES, default: r?.evaluationMode || "ALWAYS_ALLOW" }, { key: "enf", label: "Enforcement mode", options: ENF, default: r?.enforcementMode || ENF[0] },
          { key: "attestors", label: "Required attestors (full names, comma separated)", default: (r?.requireAttestationsBy || []).join(", ") },
          { key: "allow", label: "Allowlist image patterns", multiline: true, default: (policy.data?.admissionWhitelistPatterns || []).map((x) => x.namePattern).join("\n") }]} />
      <FormDialog open={dlg === "attestor"} title="Create attestor" onClose={(ok) => { setDlg(null); if (ok) reload(); }}
        onSubmit={async (v) => { await api.createAttestor(v.id, { userOwnedGrafeasNote: { noteReference: v.note, publicKeys: [{ pkixPublicKey: { publicKeyPem: v.pem, signatureAlgorithm: "ECDSA_P256_SHA256" } }] } }); notify.success("Attestor created"); }}
        fields={[{ key: "id", label: "Attestor name" }, { key: "note", label: "Container Analysis note", default: `projects/${project}/notes/` }, { key: "pem", label: "Public key (PKIX PEM, ECDSA P-256)", multiline: true }]} />
      <FormDialog open={dlg === "occ"} title="Add attestation" submitLabel="Add" onClose={(ok) => { setDlg(null); if (ok) reload(); }}
        onSubmit={async (v) => { await api.createOccurrence({ resourceUri: v.uri, noteName: v.note, kind: "ATTESTATION", attestation: { serializedPayload: v.payload, signatures: [{ publicKeyId: v.kid, signature: v.sig }] } }); notify.success("Attestation stored"); }}
        fields={[{ key: "uri", label: "Image (…@sha256:…)" }, { key: "note", label: "Note name" }, { key: "payload", label: "Serialized payload (base64)", multiline: true }, { key: "kid", label: "Public key ID (optional)" }, { key: "sig", label: "Signature (base64 DER)", multiline: true }]} />
      <FormDialog open={dlg === "check"} title="Check an image against the policy" submitLabel="Check" onClose={() => setDlg(null)}
        onSubmit={async (v) => { setProbe(await api.evaluate(v.image)); dec.reload(); }}
        fields={[{ key: "image", label: "Image", default: `us-central1-docker.pkg.dev/${project}/` }]} />
    </>
  );
}

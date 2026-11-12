/* "CloudFront key pairs" on the root user's Security credentials page, plus the public keys / key groups the account holds and a
 * signed-URL validator. Backed by core/cloudfront_keys_core.py (see capabilities iam.root.cloudfront-key-pairs). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as cf from "./cloudfrontApi.js";

export default function CloudFrontKeys() {
  const notify = useNotify();
  const k = useAsync(() => cf.listRootKeyPairs(), []);
  const ov = useAsync(() => cf.overview(), []);
  const [sel, setSel] = useState([]);
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [ip, setIp] = useState("");
  const [verdict, setVerdict] = useState(null);
  const run = async (fn, ok) => { setBusy(true); try { await fn(); if (ok) notify.success(ok); setSel([]); k.reload(); } catch (e) { notify.error(e); } finally { setBusy(false); } };
  const create = () => run(async () => {
    const { publicPem, privatePem } = await cf.generateKeyPair();
    const r = await cf.createRootKeyPair(publicPem);
    cf.download(`pk-${r.id}.pem`, privatePem);
  }, "Key pair created. The private key was downloaded to your computer; Vyomi keeps only the public key.");
  const one = sel[0];
  const validate = async () => { try { setVerdict(await cf.validateSignedUrl({ url: url.trim(), ...(ip.trim() ? { clientIp: ip.trim() } : {}) })); } catch (e) { notify.error(e); } };
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="iam.root.cloudfront-key-pairs" title="CloudFront key pairs" counter={`(${(k.data || []).length})`}
        description="Account-level key pairs for signing CloudFront URLs. AWS recommends public keys and key groups instead.">
        <Table variant="embedded" items={k.data || []} loading={k.loading} selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)} trackBy="id"
          header={<SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!one || busy} onClick={() => run(() => cf.setRootKeyPairStatus(one.id, one.status !== "Active"), `Key pair ${one.status === "Active" ? "deactivated" : "activated"}.`)}>{one?.status === "Inactive" ? "Make active" : "Make inactive"}</Button>
            <Button disabled={!one || busy} onClick={() => run(() => cf.deleteRootKeyPair(one.id), "Key pair deleted.")}>Delete</Button>
            <Button variant="primary" loading={busy} disabled={(k.data || []).length >= 2} onClick={create}>Create new key pair</Button>
          </SpaceBetween>}
          columnDefinitions={[{ id: "id", header: "Access key ID", cell: (r) => r.id }, { id: "c", header: "Created", cell: (r) => fmtDate(new Date(r.created * 1000).toISOString()) },
            { id: "s", header: "Status", cell: (r) => <StatusIndicator type={r.status === "Active" ? "success" : "stopped"}>{r.status}</StatusIndicator> }]}
          empty={<Box textAlign="center" color="inherit"><b>No CloudFront key pairs</b></Box>} />
      </CapabilityContainer>
      <CapabilityContainer id="iam.root.cloudfront-key-pairs" title="CloudFront public keys and key groups">
        <SpaceBetween size="m">
          <Table variant="embedded" items={ov.data?.publicKeys || []} loading={ov.loading} header={<b>Public keys ({(ov.data?.publicKeys || []).length})</b>}
            columnDefinitions={[{ id: "i", header: "ID", cell: (r) => r.id }, { id: "n", header: "Name", cell: (r) => r.name }, { id: "g", header: "Key groups", cell: (r) => r.keyGroups.join(", ") || "-" }]}
            empty={<Box color="inherit">Create public keys and key groups with the CloudFront API (CreatePublicKey, CreateKeyGroup).</Box>} />
          <Table variant="embedded" items={ov.data?.keyGroups || []} loading={ov.loading} header={<b>Key groups ({(ov.data?.keyGroups || []).length})</b>}
            columnDefinitions={[{ id: "i", header: "ID", cell: (r) => r.id }, { id: "n", header: "Name", cell: (r) => r.name }, { id: "k", header: "Public keys", cell: (r) => r.items.join(", ") }]}
            empty={<Box color="inherit">No key groups.</Box>} />
        </SpaceBetween>
      </CapabilityContainer>
      <CapabilityContainer id="iam.root.cloudfront-key-pairs" title="Validate a signed URL" description="Checks a CloudFront signed URL the way the edge would: key, policy, expiry, IP and the RSA-SHA1 signature.">
        <SpaceBetween size="m">
          <FormField label="Signed URL"><Textarea value={url} onChange={({ detail }) => setUrl(detail.value)} ariaLabel="Signed URL" rows={3} /></FormField>
          <FormField label="Client IP - optional"><Input value={ip} onChange={({ detail }) => setIp(detail.value)} ariaLabel="Client IP" /></FormField>
          <Button onClick={validate} disabled={!url.trim()}>Validate</Button>
          {verdict && (
            <SpaceBetween size="xs">
              <StatusIndicator type={verdict.valid ? "success" : "error"}>{verdict.valid ? `Valid (${verdict.policyKind} policy${verdict.keyGroups?.length ? `, key group ${verdict.keyGroups.join(", ")}` : ""})` : "Not valid"}</StatusIndicator>
              {(verdict.reasons || []).map((r) => <Box key={r} color="text-status-error">{r}</Box>)}
            </SpaceBetween>
          )}
        </SpaceBetween>
      </CapabilityContainer>
    </SpaceBetween>
  );
}

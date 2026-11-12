/* Real credential sections of the IAM user / root "Security credentials" tab: SSH public keys,
 * HTTPS Git + Keyspaces + Bedrock service-specific credentials, X.509 signing certificates, and
 * the IAM event log table. All backed by core/iam_core.py (see capabilities iam.user.ssh-keys,
 * iam.user.service-credentials, iam.user.signing-certificates, iam.event-log). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Table from "@cloudscape-design/components/table";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const SERVICES = [
  { value: "codecommit.amazonaws.com", label: "CodeCommit (HTTPS Git credentials)" },
  { value: "cassandra.amazonaws.com", label: "Amazon Keyspaces (for Apache Cassandra)" },
  { value: "bedrock.amazonaws.com", label: "Amazon Bedrock (API key)" },
];
const statusCell = (s) => <StatusIndicator type={s === "Active" ? "success" : "stopped"}>{s}</StatusIndicator>;
const Footer = ({ onCancel, children }) => (
  <Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onCancel}>Cancel</Button>{children}</SpaceBetween></Box>
);

export function SshKeysSection({ userName }) {
  const notify = useNotify();
  const k = useAsync(() => api.listSshPublicKeys(userName), [userName]);
  const [sel, setSel] = useState([]);
  const [add, setAdd] = useState(null);
  const [view, setView] = useState(null);
  const run = async (fn, ok) => { try { await fn(); notify.success(ok); setSel([]); k.reload(); } catch (e) { notify.error(e); } };
  return (
    <CapabilityContainer id="iam.user.ssh-keys" title="SSH public keys for AWS CodeCommit" counter={`(${(k.data || []).length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={sel.length !== 1} onClick={async () => setView(await api.getSshPublicKey(userName, sel[0].SSHPublicKeyId))}>View</Button>
        <Button disabled={sel.length !== 1} onClick={() => run(() => api.updateSshPublicKey(userName, sel[0].SSHPublicKeyId, sel[0].Status === "Active" ? "Inactive" : "Active"), "SSH key status updated.")}>
          {sel[0]?.Status === "Inactive" ? "Activate" : "Deactivate"}</Button>
        <Button disabled={sel.length !== 1} onClick={() => run(() => api.deleteSshPublicKey(userName, sel[0].SSHPublicKeyId), "SSH key deleted.")}>Delete</Button>
        <Button variant="primary" onClick={() => setAdd("")}>Upload SSH public key</Button>
      </SpaceBetween>}>
      <Table variant="embedded" items={k.data || []} trackBy="SSHPublicKeyId" selectionType="single" selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        columnDefinitions={[
          { id: "id", header: "SSH key ID", cell: (r) => r.SSHPublicKeyId },
          { id: "status", header: "Status", cell: (r) => statusCell(r.Status) },
          { id: "up", header: "Uploaded", cell: (r) => fmtDate(r.UploadDate) },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No SSH public keys.</b></Box>} />
      <Modal visible={add !== null} onDismiss={() => setAdd(null)} header="Upload SSH public key"
        footer={<Footer onCancel={() => setAdd(null)}>
          <Button variant="primary" disabled={!add} onClick={async () => { const body = add; setAdd(null); await run(() => api.uploadSshPublicKey(userName, body), "SSH public key uploaded."); }}>Upload SSH public key</Button>
        </Footer>}>
        <FormField label="SSH public key" description="Paste an ssh-rsa / ssh-ed25519 / ecdsa public key (as in ~/.ssh/id_rsa.pub).">
          <Textarea value={add || ""} onChange={({ detail }) => setAdd(detail.value)} ariaLabel="SSH public key" rows={5} />
        </FormField>
      </Modal>
      <Modal visible={!!view} onDismiss={() => setView(null)} header="SSH public key"
        footer={<Box float="right"><Button variant="primary" onClick={() => setView(null)}>Close</Button></Box>}>
        {view && <SpaceBetween size="m">
          <FormField label="Fingerprint"><Input value={view.Fingerprint} readOnly ariaLabel="Fingerprint" /></FormField>
          <FormField label="Key"><Textarea value={view.SSHPublicKeyBody} readOnly rows={4} ariaLabel="Key body" /></FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

export function ServiceCredentialsSection({ userName }) {
  const notify = useNotify();
  const c = useAsync(() => api.listServiceCredentials(userName), [userName]);
  const [sel, setSel] = useState([]);
  const [gen, setGen] = useState(null);       // {service} while choosing
  const [secret, setSecret] = useState(null); // credential with ServicePassword
  const run = async (fn, ok) => { try { const r = await fn(); notify.success(ok); setSel([]); c.reload(); return r; } catch (e) { notify.error(e); } };
  return (
    <CapabilityContainer id="iam.user.service-credentials" title="HTTPS Git credentials, Keyspaces credentials and API keys" counter={`(${(c.data || []).length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={sel.length !== 1} onClick={async () => { const r = await run(() => api.resetServiceCredential(userName, sel[0].ServiceSpecificCredentialId), "Credential reset."); if (r) setSecret(r); }}>Reset password</Button>
        <Button disabled={sel.length !== 1} onClick={() => run(() => api.updateServiceCredential(userName, sel[0].ServiceSpecificCredentialId, sel[0].Status === "Active" ? "Inactive" : "Active"), "Credential status updated.")}>
          {sel[0]?.Status === "Inactive" ? "Activate" : "Deactivate"}</Button>
        <Button disabled={sel.length !== 1} onClick={() => run(() => api.deleteServiceCredential(userName, sel[0].ServiceSpecificCredentialId), "Credential deleted.")}>Delete</Button>
        <Button variant="primary" onClick={() => setGen({ service: SERVICES[0] })}>Generate credentials</Button>
      </SpaceBetween>}>
      <Table variant="embedded" items={c.data || []} trackBy="ServiceSpecificCredentialId" selectionType="single" selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        columnDefinitions={[
          { id: "svc", header: "Service", cell: (r) => r.ServiceName },
          { id: "user", header: "User name", cell: (r) => r.ServiceUserName },
          { id: "id", header: "Credential ID", cell: (r) => r.ServiceSpecificCredentialId },
          { id: "status", header: "Status", cell: (r) => statusCell(r.Status) },
          { id: "created", header: "Created", cell: (r) => fmtDate(r.CreateDate) },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No service-specific credentials.</b></Box>} />
      <Modal visible={!!gen} onDismiss={() => setGen(null)} header="Generate service-specific credentials"
        footer={<Footer onCancel={() => setGen(null)}>
          <Button variant="primary" onClick={async () => { const svc = gen.service.value; setGen(null); const r = await run(() => api.createServiceCredential(userName, svc), "Credentials generated."); if (r) setSecret(r); }}>Generate credentials</Button>
        </Footer>}>
        {gen && <FormField label="Service"><Select selectedOption={gen.service} options={SERVICES} onChange={({ detail }) => setGen({ service: detail.selectedOption })} ariaLabel="Service" /></FormField>}
      </Modal>
      <Modal visible={!!secret} onDismiss={() => setSecret(null)} header="Service-specific credentials"
        footer={<Box float="right"><Button variant="primary" onClick={() => setSecret(null)}>Close</Button></Box>}>
        {secret && <SpaceBetween size="m">
          <FormField label="User name"><Input value={secret.ServiceUserName} readOnly ariaLabel="Service user name" /></FormField>
          <FormField label="Password" description="Shown only now - save it.">
            <Input value={secret.ServicePassword} readOnly ariaLabel="Service password" />
          </FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

export function SigningCertsSection({ userName }) {
  const notify = useNotify();
  const c = useAsync(() => api.listSigningCertificates(userName), [userName]);
  const [sel, setSel] = useState([]);
  const [add, setAdd] = useState(null);
  const run = async (fn, ok) => { try { await fn(); notify.success(ok); setSel([]); c.reload(); } catch (e) { notify.error(e); } };
  return (
    <CapabilityContainer id="iam.user.signing-certificates" title="X.509 Signing certificates" counter={`(${(c.data || []).length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={sel.length !== 1} onClick={() => run(() => api.updateSigningCertificate(userName, sel[0].CertificateId, sel[0].Status === "Active" ? "Inactive" : "Active"), "Certificate status updated.")}>
          {sel[0]?.Status === "Inactive" ? "Make active" : "Make inactive"}</Button>
        <Button disabled={sel.length !== 1} onClick={() => run(() => api.deleteSigningCertificate(userName, sel[0].CertificateId), "Certificate deleted.")}>Delete</Button>
        <Button variant="primary" onClick={() => setAdd("")}>Upload X.509 certificate</Button>
      </SpaceBetween>}>
      <Table variant="embedded" items={c.data || []} trackBy="CertificateId" selectionType="single" selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        columnDefinitions={[
          { id: "id", header: "Certificate ID", cell: (r) => r.CertificateId },
          { id: "status", header: "Status", cell: (r) => statusCell(r.Status) },
          { id: "up", header: "Uploaded", cell: (r) => fmtDate(r.UploadDate) },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No X.509 signing certificates.</b></Box>} />
      <Modal visible={add !== null} onDismiss={() => setAdd(null)} header="Upload X.509 signing certificate"
        footer={<Footer onCancel={() => setAdd(null)}>
          <Button variant="primary" disabled={!add} onClick={async () => { const body = add; setAdd(null); await run(() => api.uploadSigningCertificate(userName, body), "Certificate uploaded."); }}>Upload X.509 certificate</Button>
        </Footer>}>
        <FormField label="Certificate body" description="PEM-encoded certificate (-----BEGIN CERTIFICATE-----).">
          <Textarea value={add || ""} onChange={({ detail }) => setAdd(detail.value)} ariaLabel="Certificate body" rows={8} />
        </FormField>
      </Modal>
    </CapabilityContainer>
  );
}

export function EventLog() {
  const e = useAsync(() => api.listIamEvents(100), []);
  return (
    <CapabilityContainer id="iam.event-log" title="Recent IAM activity in this account" counter={`(${(e.data || []).length})`}
      actions={<Button iconName="refresh" onClick={e.reload} ariaLabel="Refresh activity" />}>
      <Table variant="embedded" items={e.data || []} loading={e.loading}
        columnDefinitions={[
          { id: "t", header: "Time", cell: (r) => fmtDate(r.EventTime) },
          { id: "a", header: "Event", cell: (r) => r.EventName },
          { id: "p", header: "Principal", cell: (r) => r.Principal },
          { id: "r", header: "Resource", cell: (r) => r.Resource || "-" },
          { id: "s", header: "Result", cell: (r) => <StatusIndicator type={r.Status === "Success" ? "success" : "error"}>{r.Status}</StatusIndicator> },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No IAM activity recorded yet.</b></Box>} />
    </CapabilityContainer>
  );
}

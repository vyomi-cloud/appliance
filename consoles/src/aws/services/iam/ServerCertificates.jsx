/* Server certificates (IAM certificate store) - real upload / rename / view / delete over the IAM wire. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function ServerCertificates() {
  const notify = useNotify();
  const c = useAsync(() => api.listServerCertificates(), []);
  const [sel, setSel] = useState([]);
  const [dlg, setDlg] = useState(null);
  const [f, setF] = useState({});
  const set = (k) => ({ detail }) => setF((x) => ({ ...x, [k]: detail.value }));
  const run = async (fn, ok) => { try { await fn(); notify.success(ok); setDlg(null); setSel([]); c.reload(); } catch (e) { notify.error(e); } };
  const one = sel[0];
  return (
    <CapabilityContainer id="iam.server-certificates" title="Server certificates">
      <ResourceTable resourceName="Server certificates" variant="embedded" items={c.data || []} loading={c.loading} error={c.error} onRefresh={c.reload}
        trackBy="ServerCertificateName" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        empty={{ title: "No server certificates" }}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!one} onClick={async () => { try { const x = await api.getServerCertificate(one.ServerCertificateName); setF({ body: x.CertificateBody }); setDlg("view"); } catch (e) { notify.error(e); } }}>View</Button>
          <Button disabled={!one} onClick={() => { setF({ name: one.ServerCertificateName }); setDlg("rename"); }}>Rename</Button>
          <Button disabled={!one} onClick={() => run(() => api.deleteServerCertificate(one.ServerCertificateName), "Server certificate deleted.")}>Delete</Button>
          <Button variant="primary" onClick={() => { setF({}); setDlg("upload"); }}>Upload server certificate</Button>
        </SpaceBetween>}
        columns={[
          { id: "n", header: "Name", isRowHeader: true, cell: (x) => x.ServerCertificateName },
          { id: "id", header: "Certificate ID", cell: (x) => x.ServerCertificateId },
          { id: "e", header: "Expiration", cell: (x) => fmtDate(x.Expiration) },
          { id: "u", header: "Uploaded", cell: (x) => fmtDate(x.UploadDate) },
        ]} />
      <Modal visible={dlg === "upload"} onDismiss={() => setDlg(null)} header="Upload server certificate" size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setDlg(null)}>Cancel</Button>
          <Button variant="primary" disabled={!f.name || !f.body || !f.key} onClick={() => run(() => api.uploadServerCertificate(f.name, f.body, f.key, f.chain), `Server certificate "${f.name}" uploaded.`)}>Upload</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m">
          <FormField label="Certificate name"><Input ariaLabel="Certificate name" value={f.name || ""} onChange={set("name")} /></FormField>
          <FormField label="Certificate body (PEM)"><Textarea ariaLabel="Certificate body" rows={6} value={f.body || ""} onChange={set("body")} spellcheck={false} /></FormField>
          <FormField label="Private key (PEM)"><Textarea ariaLabel="Private key" rows={4} value={f.key || ""} onChange={set("key")} spellcheck={false} /></FormField>
          <FormField label="Certificate chain (optional)"><Textarea ariaLabel="Certificate chain" rows={3} value={f.chain || ""} onChange={set("chain")} spellcheck={false} /></FormField>
        </SpaceBetween>
      </Modal>
      <Modal visible={dlg === "rename"} onDismiss={() => setDlg(null)} header="Rename server certificate"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setDlg(null)}>Cancel</Button>
          <Button variant="primary" disabled={!f.name} onClick={() => run(() => api.renameServerCertificate(one.ServerCertificateName, f.name), "Server certificate renamed.")}>Save</Button></SpaceBetween></Box>}>
        <FormField label="New name"><Input ariaLabel="New name" value={f.name || ""} onChange={set("name")} /></FormField>
      </Modal>
      <Modal visible={dlg === "view"} onDismiss={() => setDlg(null)} header="Certificate body" size="large">
        <Box variant="code" fontSize="body-s"><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{f.body}</pre></Box>
      </Modal>
    </CapabilityContainer>
  );
}

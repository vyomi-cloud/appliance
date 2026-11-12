/* IAM Roles Anywhere — real trust-anchor + profile control plane (Vyomi-only wire calls,
 * see core/iam_core.py). The certificate is format-checked (a well-formed PEM block),
 * never cryptographically verified — see the iam.roles-anywhere capability notice. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Header from "@cloudscape-design/components/header";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Multiselect from "@cloudscape-design/components/multiselect";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { asList } from "../../../common/wire.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

function CreateTrustAnchorModal({ visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [cert, setCert] = useState("");
  const [busy, setBusy] = useState(false);
  const close = () => { setName(""); setCert(""); onDismiss(); };
  return (
    <Modal visible={visible} onDismiss={close} header="Create trust anchor"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={close}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name || !cert} onClick={async () => {
          setBusy(true);
          try { await api.createTrustAnchor(name, cert); notify.success(`Trust anchor "${name}" created.`); onDone(); close(); }
          catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Create trust anchor</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="m">
        <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
        <FormField label="External certificate bundle" description="A PEM-encoded X.509 certificate — format-checked, not cryptographically verified.">
          <Textarea rows={8} value={cert} onChange={({ detail }) => setCert(detail.value)} spellcheck={false}
            placeholder={"-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"} />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function CreateProfileModal({ visible, onDismiss, onDone, roles }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [sel, setSel] = useState([]);
  const [busy, setBusy] = useState(false);
  const close = () => { setName(""); setSel([]); onDismiss(); };
  return (
    <Modal visible={visible} onDismiss={close} header="Create profile"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={close}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name || !sel.length} onClick={async () => {
          setBusy(true);
          try { await api.createProfile(name, sel.map((s) => s.value)); notify.success(`Profile "${name}" created.`); onDone(); close(); }
          catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Create profile</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="m">
        <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
        <FormField label="Roles">
          <Multiselect selectedOptions={sel} onChange={({ detail }) => setSel(detail.selectedOptions)}
            options={roles.map((r) => ({ value: r.Arn, label: r.RoleName }))} placeholder="Choose roles" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function RolesAnywherePanel({ roles = [] }) {
  const notify = useNotify();
  const ta = useAsync(() => api.listTrustAnchors(), []);
  const pr = useAsync(() => api.listProfiles(), []);
  const [createTa, setCreateTa] = useState(false);
  const [createPr, setCreatePr] = useState(false);

  return (
    <CapabilityContainer id="iam.roles-anywhere" title="Roles Anywhere">
      <SpaceBetween size="l">
        <Table variant="embedded" items={ta.data || []} loading={ta.loading} trackBy="TrustAnchorArn"
          header={<Header variant="h3" counter={`(${(ta.data || []).length})`}
            actions={<Button onClick={() => setCreateTa(true)}>Create trust anchor</Button>}>Trust anchors</Header>}
          columnDefinitions={[
            { id: "name", header: "Name", cell: (x) => x.Name },
            { id: "id", header: "Trust anchor ID", cell: (x) => x.TrustAnchorId },
            { id: "created", header: "Created", cell: (x) => fmtDate(x.CreatedAt) },
            { id: "actions", header: "", cell: (x) => <Button onClick={async () => { await api.deleteTrustAnchor(x.TrustAnchorArn); notify.success("Trust anchor deleted."); ta.reload(); }}>Delete</Button> },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No trust anchors</b></Box>} />
        <Table variant="embedded" items={pr.data || []} loading={pr.loading} trackBy="ProfileArn"
          header={<Header variant="h3" counter={`(${(pr.data || []).length})`}
            actions={<Button disabled={!roles.length} onClick={() => setCreatePr(true)}>Create profile</Button>}>Profiles</Header>}
          columnDefinitions={[
            { id: "name", header: "Name", cell: (x) => x.Name },
            { id: "roles", header: "Roles", cell: (x) => asList(x.RoleArns?.member).map((a) => a.split("/").pop()).join(", ") || "-" },
            { id: "created", header: "Created", cell: (x) => fmtDate(x.CreatedAt) },
            { id: "actions", header: "", cell: (x) => <Button onClick={async () => { await api.deleteProfile(x.ProfileArn); notify.success("Profile deleted."); pr.reload(); }}>Delete</Button> },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No profiles</b></Box>} />
      </SpaceBetween>
      <CreateTrustAnchorModal visible={createTa} onDismiss={() => setCreateTa(false)} onDone={ta.reload} />
      <CreateProfileModal visible={createPr} onDismiss={() => setCreatePr(false)} onDone={pr.reload} roles={roles} />
    </CapabilityContainer>
  );
}

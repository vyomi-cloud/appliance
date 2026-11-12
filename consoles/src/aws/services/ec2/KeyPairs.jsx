import { useRef, useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Alert from "@cloudscape-design/components/alert";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import * as api from "./api.js";

export function KeyPairs() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeKeyPairs(), []);
  const rows = t.data || [];
  return (
    <ContentLayout header={<Header variant="h1">Key pairs</Header>}>
      <ResourceTable
        resourceName="Key pairs"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="keyPairId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Filter Key Pair by attribute or tag"
        empty={{ title: "No key pairs to display" }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (k) => k.keyName },
          { id: "type", header: "Type", cell: (k) => k.keyType },
          { id: "created", header: "Created", cell: (k) => k.createTime },
          { id: "fp", header: "Fingerprint", cell: (k) => k.keyFingerprint },
          { id: "id", header: "ID", cell: (k) => k.keyPairId },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[{ id: "import", text: "Import key pair" }, { id: "delete", text: "Delete" }]} onItemClick={({ detail }) => {
              if (detail.id === "import") navigate("ec2", "import-key-pair"); else setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-key-pair")} onFollow={follow}>Create key pair</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="key pair" names={sel.map((k) => k.keyName)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const k of sel) await api.deleteKeyPair(k.keyName); notify.success(`${sel.length} key pair(s) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

export function CreateKeyPair() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [keyType, setKeyType] = useState("rsa");
  const [format, setFormat] = useState(".pem");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.createKeyPair(name, keyType);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([r.keyMaterial], { type: "text/plain" }));
      a.download = `${name}${format}`; a.click();
      notify.success(`Key pair "${name}" created. Your private key has downloaded.`);
      navigate("ec2", "key-pairs");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create key pair</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "key-pairs")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create key pair</Button>
        </SpaceBetween>
      }>
        <Container header={<Header variant="h2">Key pair</Header>}>
          <SpaceBetween size="l">
            <Alert type="info">Vyomi generates a private-key-shaped document and fingerprint for this key pair, but it is not real RSA/ED25519 key material — it can't be used to open a real SSH session.</Alert>
            <FormField label="Name" constraintText="Up to 255 ASCII characters; no leading or trailing spaces."><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="Enter key pair name" ariaLabel="Name" /></FormField>
            <FormField label="Key pair type"><RadioGroup value={keyType} onChange={({ detail }) => setKeyType(detail.value)} items={[{ value: "rsa", label: "RSA" }, { value: "ed25519", label: "ED25519" }]} /></FormField>
            <FormField label="Private key file format" description=".pem: For use with OpenSSH; .ppk: For use with PuTTY">
              <RadioGroup value={format} onChange={({ detail }) => setFormat(detail.value)} items={[{ value: ".pem", label: ".pem" }, { value: ".ppk", label: ".ppk" }]} />
            </FormField>
            <FormField label="Tags - optional"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField>
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
}

export function ImportKeyPair() {
  const notify = useNotify();
  const fileRef = useRef(null);
  const [name, setName] = useState("");
  const [material, setMaterial] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const onFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setMaterial(String(reader.result || ""));
    reader.readAsText(file);
  };

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.importKeyPair(name, api.b64(material));
      notify.success(`Key pair "${name}" imported.`);
      navigate("ec2", "key-pairs");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Import key pair</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "key-pairs")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name || !material} onClick={submit}>Import key pair</Button>
        </SpaceBetween>
      }>
        <Container header={<Header variant="h2">Key pair</Header>}>
          <SpaceBetween size="l">
            <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
            <FormField label="Browse" description="Public key file (.pem / OpenSSH public key)">
              <input ref={fileRef} type="file" onChange={onFile} aria-label="Browse" />
            </FormField>
            <FormField label="Public key contents"><Textarea value={material} onChange={({ detail }) => setMaterial(detail.value)} rows={6} ariaLabel="Public key contents" /></FormField>
            <FormField label="Tags - optional"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField>
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
}

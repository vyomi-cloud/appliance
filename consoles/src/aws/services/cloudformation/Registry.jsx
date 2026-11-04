/* CloudFormation registry (sweep AWS-13): public extensions catalog + activation, activated modules, publisher registration.
 * Real wire ops over core/cloudformation_registry_core.py. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Textarea from "@cloudscape-design/components/textarea";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

const KINDS = [{ value: "RESOURCE", label: "Resource types" }, { value: "MODULE", label: "Modules" }, { value: "HOOK", label: "Hooks" }];
const PUBS = [{ value: "ALL", label: "All publishers" }, { value: "AWS_TYPES", label: "AWS" }, { value: "THIRD_PARTY", label: "Third party" }];

export function ActivateModal({ item, onDismiss, onDone }) {
  const notify = useNotify();
  const [alias, setAlias] = useState("");
  const [auto, setAuto] = useState(true);
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try { await api.activateType({ type: item.Type, typeName: item.TypeName, publisherId: item.PublisherId, alias, autoUpdate: auto, executionRoleArn: role }); notify.success(`Activated ${alias || item.TypeName}.`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={!!item} onDismiss={onDismiss} header={`Activate ${item?.TypeName || ""}`}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={go}>Activate extension</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} />}
        <FormField label="Type name alias" description="Optional. Use a different name in your templates."><Input ariaLabel="Type name alias" value={alias} onChange={({ detail }) => setAlias(detail.value)} placeholder={item?.TypeName} /></FormField>
        <FormField label="Execution role ARN" description="Optional."><Input ariaLabel="Execution role ARN" value={role} onChange={({ detail }) => setRole(detail.value)} /></FormField>
        <Checkbox checked={auto} onChange={({ detail }) => setAuto(detail.checked)}>Automatically update to new minor versions</Checkbox>
      </SpaceBetween>
    </Modal>
  );
}

export function PublicExtensions() {
  const [kind, setKind] = useState(KINDS[0]);
  const [pub, setPub] = useState(PUBS[0]);
  const [sel, setSel] = useState([]);
  const [act, setAct] = useState(null);
  const pubs = useAsync(() => api.listPublicTypes({ type: kind.value, category: pub.value === "ALL" ? undefined : pub.value }), [kind.value, pub.value]);
  const activated = useAsync(() => api.listActivatedTypes(kind.value), [kind.value]);
  const done = new Set((activated.data || []).map((a) => a.OriginalTypeName || a.TypeName));
  const rows = (pubs.data || []);
  return (
    <ContentLayout header={<Header variant="h1">Registry: Public extensions</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Filter</Header>}>
          <SpaceBetween direction="horizontal" size="l">
            <FormField label="Extension type"><Select ariaLabel="Extension type" selectedOption={kind} options={KINDS} onChange={({ detail }) => { setKind(detail.selectedOption); setSel([]); }} /></FormField>
            <FormField label="Publisher"><Select ariaLabel="Publisher" selectedOption={pub} options={PUBS} onChange={({ detail }) => { setPub(detail.selectedOption); setSel([]); }} /></FormField>
          </SpaceBetween>
        </Container>
        <ResourceTable resourceName="Public extensions" variant="container" items={rows} trackBy="TypeName" loading={pubs.loading} error={pubs.error} onRefresh={() => { pubs.reload(); activated.reload(); }}
          selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter extensions"
          columns={[
            { id: "t", header: "Type name", isRowHeader: true, cell: (t) => <Link href={href("cloudformation", "registry", "public-extensions", "resource-type", t.TypeName)} onFollow={follow}>{t.TypeName}</Link> },
            { id: "p", header: "Publisher", cell: (t) => (t.PublisherId === "AWS" ? "Amazon Web Services" : t.PublisherName || t.PublisherId) },
            { id: "d", header: "Description", cell: (t) => t.Description },
            { id: "u", header: "Last updated", cell: (t) => fmtDate(t.LastUpdated) },
            { id: "s", header: "Status", cell: (t) => (t.PublisherId === "AWS" ? "Available" : done.has(t.TypeName) ? <StatusIndicator type="success">Activated</StatusIndicator> : "Not activated") },
          ]}
          actions={<Button disabled={sel.length !== 1 || sel[0].PublisherId === "AWS"} onClick={() => setAct(sel[0])}>Activate</Button>} />
      </SpaceBetween>
      <ActivateModal item={act} onDismiss={() => setAct(null)} onDone={() => { activated.reload(); pubs.reload(); }} />
    </ContentLayout>
  );
}

export function ModulesTable() {
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listActivatedTypes("MODULE"), []);
  const [sel, setSel] = useState([]);
  return (
    <ResourceTable resourceName="Modules" items={data} trackBy="TypeName" loading={loading} error={error} onRefresh={reload}
      selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter modules"
      columns={[
        { id: "t", header: "Module name", isRowHeader: true, cell: (t) => t.TypeName },
        { id: "o", header: "Public module", cell: (t) => t.OriginalTypeName || "-" },
        { id: "d", header: "Description", cell: (t) => t.Description },
      ]}
      actions={<Button disabled={sel.length !== 1} onClick={async () => { try { await api.deactivateType("MODULE", sel[0].TypeName); notify.success("Module deactivated."); setSel([]); reload(); } catch (e) { notify.error(e); } }}>Deactivate</Button>}
      empty={{ title: "No modules activated", subtitle: "Activate a module from Registry: Public extensions, then use it as a resource Type in your templates." }} />
  );
}

export function Publisher() {
  const notify = useNotify();
  const pub = useAsync(() => api.describePublisher(), []);
  const [open, setOpen] = useState(false);
  const [conn, setConn] = useState("");
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const register = async () => {
    setBusy(true); setError(null);
    try { await api.registerPublisher(conn); notify.success("Registered as a publisher."); setOpen(false); pub.reload(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <ContentLayout header={<Header variant="h1">Registry: Publisher</Header>}>
      <Container header={<Header variant="h2" actions={<Button variant="primary" onClick={() => setOpen(true)}>{pub.data ? "Update connection" : "Register publisher"}</Button>}>Publisher registration</Header>}>
        {pub.error ? <ErrorAlert error={pub.error} /> : pub.data ? (
          <KeyValue columns={2} items={[["Publisher ID", pub.data.PublisherId], ["Status", pub.data.PublisherStatus], ["Identity provider", pub.data.IdentityProvider], ["Profile", pub.data.PublisherProfile || "-"]]} />
        ) : <StatusIndicator type="stopped">This account is not registered as a publisher.</StatusIndicator>}
      </Container>
      <Modal visible={open} onDismiss={() => setOpen(false)} header="Register as a publisher"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" disabled={!ok && !pub.data} loading={busy} onClick={register}>Register</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Connection ARN" description="Optional CodeConnections connection to verify your publisher identity."><Input ariaLabel="Connection ARN" value={conn} onChange={({ detail }) => setConn(detail.value)} /></FormField>
          <Checkbox checked={ok} onChange={({ detail }) => setOk(detail.checked)}>I accept the publisher terms and conditions</Checkbox>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}

/** Configuration tab of an extension: execution role / logging come from activation; the configuration document is real (SetTypeConfiguration). */
export function ExtensionConfiguration({ typeName, activated }) {
  const notify = useNotify();
  const cfg = useAsync(() => (activated ? api.typeConfiguration(typeName) : Promise.resolve("")), [typeName, activated]);
  const [text, setText] = useState(null);
  const [busy, setBusy] = useState(false);
  if (!activated) return <Container header={<Header variant="h2">Configuration</Header>}><Box color="text-status-inactive">{typeName} is published by AWS and is always available; there is no configuration to set. Activate a third-party extension to configure it.</Box></Container>;
  const value = text ?? cfg.data ?? "";
  return (
    <Container header={<Header variant="h2" actions={<Button variant="primary" loading={busy} onClick={async () => { setBusy(true); try { await api.setTypeConfiguration(typeName, value || "{}"); notify.success("Configuration saved."); cfg.reload(); } catch (e) { notify.error(e); } finally { setBusy(false); } }}>Save configuration</Button>}>Configuration</Header>}>
      <FormField label="Configuration (JSON)"><Textarea ariaLabel="Configuration" rows={8} value={value} onChange={({ detail }) => setText(detail.value)} spellcheck={false} /></FormField>
    </Container>
  );
}

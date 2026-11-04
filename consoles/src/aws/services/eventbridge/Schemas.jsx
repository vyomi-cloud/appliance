/* EventBridge Schemas: registries, schemas (+ versions), discoverers with real inference from PutEvents (sweep AWS-08). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import { ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const SAMPLE = JSON.stringify({ openapi: "3.0.0", info: { version: "1.0.0", title: "MyEvent" }, paths: {}, components: { schemas: { MyEvent: { type: "object", properties: { id: { type: "string" } } } } } }, null, 2);

function useAllSchemas() {
  return useAsync(async () => {
    const regs = await api.listSchemaRegistries();
    const rows = [];
    for (const r of regs) for (const s of await api.listSchemas(r.RegistryName)) rows.push({ registry: r.RegistryName, ...s });
    return { regs, rows };
  }, []);
}

function SchemaViewer({ target, onDismiss, reload }) {
  const notify = useNotify();
  const d = useAsync(() => (target ? Promise.all([api.describeSchema(target.registry, target.SchemaName), api.listSchemaVersions(target.registry, target.SchemaName)]) : Promise.resolve(null)), [target?.registry, target?.SchemaName]);
  const [ver, setVer] = useState(null);
  const shown = ver ?? d.data?.[0];
  return (
    <Modal visible={!!target} size="large" onDismiss={onDismiss} header={target ? `${target.SchemaName} (${target.registry})` : ""}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button onClick={async () => { try { await api.deleteSchema(target.registry, target.SchemaName); notify.success("Schema deleted."); onDismiss(); reload(); } catch (e) { notify.error(e); } }}>Delete schema</Button>
        <Button variant="primary" onClick={onDismiss}>Close</Button></SpaceBetween></Box>}>
      {d.error ? <ErrorAlert error={d.error} /> : !d.data ? "Loading…" : (
        <SpaceBetween size="m">
          <FormField label="Version">
            <Select ariaLabel="Schema version" selectedOption={{ value: shown?.SchemaVersion, label: `Version ${shown?.SchemaVersion}` }}
              options={(d.data[1] || []).map((v) => ({ value: v.SchemaVersion, label: `Version ${v.SchemaVersion}` }))}
              onChange={async ({ detail }) => setVer(await api.describeSchema(target.registry, target.SchemaName, detail.selectedOption.value))} />
          </FormField>
          <Box variant="awsui-key-label">{shown?.Type} · {shown?.SchemaArn}</Box>
          <pre aria-label="Schema content" style={{ maxHeight: 360, overflow: "auto", background: "rgba(127,127,127,.1)", padding: 12 }}>{(() => { try { return JSON.stringify(JSON.parse(shown?.Content || "{}"), null, 2); } catch { return shown?.Content; } })()}</pre>
        </SpaceBetween>
      )}
    </Modal>
  );
}

function SchemasTable({ rows, loading, filterRegistry, reload, title }) {
  const [sel, setSel] = useState(null);
  const [q, setQ] = useState("");
  const shown = (rows || []).filter((r) => (!filterRegistry || filterRegistry(r.registry)) && r.SchemaName.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <Table variant="container" loading={loading} items={shown} trackBy={(r) => `${r.registry}/${r.SchemaName}`}
        header={<Header variant="h2" counter={`(${shown.length})`}>{title}</Header>}
        filter={<Input type="search" ariaLabel="Search all schemas" placeholder="Search all schemas" value={q} onChange={({ detail }) => setQ(detail.value)} />}
        columnDefinitions={[
          { id: "n", header: "Schema name", cell: (r) => <Button variant="inline-link" onClick={() => setSel(r)}>{r.SchemaName}</Button> },
          { id: "r", header: "Registry", cell: (r) => r.registry },
          { id: "v", header: "Versions", cell: (r) => r.VersionCount },
          { id: "u", header: "Last updated", cell: (r) => r.LastModified },
        ]} empty={<Box textAlign="center" color="inherit"><b>No schemas</b><Box variant="p" color="inherit">Create a schema or start a discoverer and send events.</Box></Box>} />
      <SchemaViewer target={sel} onDismiss={() => setSel(null)} reload={reload} />
    </>
  );
}

function Discoverers({ reloadSchemas }) {
  const notify = useNotify();
  const d = useAsync(() => api.listDiscoverers(), []);
  const buses = useAsync(() => api.listEventBuses(), []);
  const [open, setOpen] = useState(false);
  const [bus, setBus] = useState("");
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); d.reload(); reloadSchemas(); } catch (e) { notify.error(e); } };
  return (
    <>
      <Table variant="container" loading={d.loading} items={d.data || []} trackBy="DiscovererId"
        header={<Header variant="h2" counter={`(${(d.data || []).length})`} actions={<Button onClick={() => setOpen(true)}>Start discovery on a bus</Button>}>Schema discovery</Header>}
        columnDefinitions={[
          { id: "b", header: "Event bus", cell: (x) => x.SourceArn.split("/").pop() },
          { id: "s", header: "State", cell: (x) => <StatusIndicator type={x.State === "STARTED" ? "success" : "stopped"}>{x.State}</StatusIndicator> },
          { id: "a", header: "", cell: (x) => (
            <SpaceBetween direction="horizontal" size="xs">
              {x.State === "STARTED" ? <Button variant="inline-link" onClick={() => act(() => api.stopDiscoverer(x.DiscovererId), "Discoverer stopped.")}>Stop</Button>
                : <Button variant="inline-link" onClick={() => act(() => api.startDiscoverer(x.DiscovererId), "Discoverer started.")}>Start</Button>}
              <Button variant="inline-link" onClick={() => act(() => api.deleteDiscoverer(x.DiscovererId), "Discoverer deleted.")}>Delete</Button>
            </SpaceBetween>) },
        ]} empty={<Box textAlign="center" color="inherit"><b>No discoverers</b></Box>} />
      <Modal visible={open} onDismiss={() => setOpen(false)} header="Start schema discovery"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="primary" disabled={!bus} onClick={async () => { await act(() => api.createDiscoverer(bus, ""), "Schema discovery started."); setOpen(false); }}>Start discovery</Button></SpaceBetween></Box>}>
        <FormField label="Event bus" description="Every PutEvents on this bus is inferred into the discovered-schemas registry.">
          <Select ariaLabel="Event bus" selectedOption={bus ? { value: bus, label: bus.split("/").pop() } : null} placeholder="Choose an event bus"
            options={(buses.data || []).map((b) => ({ value: b.Arn, label: b.Name }))} onChange={({ detail }) => setBus(detail.selectedOption.value)} />
        </FormField>
      </Modal>
    </>
  );
}

export default function Schemas() {
  const notify = useNotify();
  const all = useAllSchemas();
  const [regModal, setRegModal] = useState(false);
  const [schModal, setSchModal] = useState(false);
  const [f, setF] = useState({ name: "", desc: "", registry: "", sname: "", type: "OpenApi3", content: SAMPLE });
  const [error, setError] = useState(null);
  const regs = all.data?.regs || [];
  const custom = regs.filter((r) => r.RegistryName !== "discovered-schemas" && r.RegistryName !== "aws.events");
  const run = async (fn, ok, close) => { setError(null); try { await fn(); notify.success(ok); close(); all.reload(); } catch (e) { setError(e); } };
  return (
    <ContentLayout header={<Header variant="h1" description="Find, create and discover the structure of the events on your buses."
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => { setError(null); setF({ ...f, name: "" }); setRegModal(true); }}>Create a schema registry</Button>
        <Button variant="primary" onClick={() => { setError(null); setF({ ...f, registry: custom[0]?.RegistryName || "", sname: "", content: SAMPLE }); setSchModal(true); }}>Create schema</Button>
      </SpaceBetween>}>Schemas</Header>}>
      <SpaceBetween size="l">
        <Tabs tabs={[
          { id: "all", label: "All schemas", content: <SchemasTable rows={all.data?.rows} loading={all.loading} reload={all.reload} title="All schemas" /> },
          { id: "aws", label: "AWS event schema registry", content: <SchemasTable rows={all.data?.rows} loading={all.loading} reload={all.reload} filterRegistry={(r) => r === "aws.events"} title="AWS event schemas" /> },
          { id: "custom", label: "Custom schema registry", content: (
            <SpaceBetween size="l">
              <Table variant="container" items={custom} trackBy="RegistryName" header={<Header variant="h2" counter={`(${custom.length})`}>Custom registries</Header>}
                columnDefinitions={[{ id: "n", header: "Registry", cell: (r) => r.RegistryName }, { id: "d", header: "Description", cell: (r) => r.Description || "-" },
                  { id: "x", header: "", cell: (r) => <Button variant="inline-link" onClick={() => run(() => api.deleteSchemaRegistry(r.RegistryName), "Registry deleted.", () => {})}>Delete</Button> }]}
                empty={<Box textAlign="center" color="inherit"><b>No custom registries</b></Box>} />
              <SchemasTable rows={all.data?.rows} loading={all.loading} reload={all.reload} filterRegistry={(r) => r !== "aws.events"} title="Schemas in custom and discovered registries" />
            </SpaceBetween>) },
          { id: "discovery", label: "Discovery", content: <Discoverers reloadSchemas={all.reload} /> },
        ]} />
        <Box variant="small" color="text-body-secondary">The AWS event schema registry (aws.events) is not shipped with Vyomi — only schemas you create or discover are listed.</Box>
      </SpaceBetween>
      <Modal visible={regModal} onDismiss={() => setRegModal(false)} header="Create a schema registry"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setRegModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!f.name} onClick={() => run(() => api.createSchemaRegistry(f.name, f.desc), `Registry ${f.name} created.`, () => setRegModal(false))}>Create registry</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m">{error && <ErrorAlert error={error} />}
          <FormField label="Registry name"><Input ariaLabel="Registry name" value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} /></FormField>
          <FormField label="Description - optional"><Input ariaLabel="Registry description" value={f.desc} onChange={({ detail }) => setF({ ...f, desc: detail.value })} /></FormField></SpaceBetween>
      </Modal>
      <Modal visible={schModal} size="large" onDismiss={() => setSchModal(false)} header="Create schema"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setSchModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!f.registry || !f.sname} onClick={() => run(() => api.createSchema(f.registry, f.sname, f.type, f.content, ""), `Schema ${f.sname} created.`, () => setSchModal(false))}>Create schema</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m">{error && <ErrorAlert error={error} />}
          <FormField label="Registry"><Select ariaLabel="Registry" selectedOption={f.registry ? { value: f.registry, label: f.registry } : null} placeholder="Choose a registry"
            options={custom.map((r) => ({ value: r.RegistryName, label: r.RegistryName }))} onChange={({ detail }) => setF({ ...f, registry: detail.selectedOption.value })} /></FormField>
          <FormField label="Schema name"><Input ariaLabel="Schema name" value={f.sname} onChange={({ detail }) => setF({ ...f, sname: detail.value })} /></FormField>
          <FormField label="Schema type"><Select ariaLabel="Schema type" selectedOption={{ value: f.type, label: f.type }} options={["OpenApi3", "JSONSchemaDraft4"].map((v) => ({ value: v, label: v }))} onChange={({ detail }) => setF({ ...f, type: detail.selectedOption.value })} /></FormField>
          <FormField label="Schema content"><Textarea ariaLabel="Schema content input" rows={12} value={f.content} spellcheck={false} onChange={({ detail }) => setF({ ...f, content: detail.value })} /></FormField></SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}

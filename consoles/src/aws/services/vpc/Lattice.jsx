/* VPC Lattice (AWS-12): service networks, services (listeners/rules), target groups (targets), resource gateways,
 * resource configurations, domain verifications - all real control-plane objects (core/vpc_lattice_core.py).
 * No traffic is routed (no netsim data path) - see aws.vpc.lattice's limitations. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
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
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import SimPanel from "../../kit/SimPanel.jsx";
import * as api from "./latticeApi.js";
import * as vpcApi from "./api.js";

const CAP = "aws.vpc.lattice";
const opt = (v, l) => ({ value: v, label: l ?? v });
const status = (s) => <StatusIndicator type={/ACTIVE|VERIFIED|HEALTHY/.test(s) ? "success" : /FAIL|UNHEALTHY/.test(s) ? "error" : "pending"}>{s}</StatusIndicator>;
const link = (href, text) => <Button variant="inline-link" href={href}>{text}</Button>;

/** Generic "create" modal. fields: {key,label,description,kind:'text'|'select'|'textarea',options:[{value,label}],placeholder,required,default} */
function CreateModal({ header, fields, onDismiss, onCreated, create, success }) {
  const notify = useNotify();
  const [v, setV] = useState(Object.fromEntries(fields.map((f) => [f.key, f.default ?? ""])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, x) => setV((o) => ({ ...o, [k]: x }));
  const ok = fields.filter((f) => f.required).every((f) => v[f.key]);
  const submit = async () => {
    setBusy(true); setError(null);
    try { const r = await create(v); notify.success(success(r, v)); onCreated(r); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible size="medium" onDismiss={onDismiss} header={header}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!ok} onClick={submit}>Create</Button></SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="m">
          {fields.map((f) => (
            <FormField key={f.key} label={f.label} description={f.description}>
              {f.kind === "select" ? (
                <Select ariaLabel={f.label} placeholder={f.placeholder || "Choose an option"} selectedOption={f.options.find((o) => o.value === v[f.key]) || null}
                  options={f.options} onChange={({ detail }) => set(f.key, detail.selectedOption.value)} empty="No options available" />
              ) : f.kind === "textarea" ? (
                <Textarea ariaLabel={f.label} rows={8} value={v[f.key]} placeholder={f.placeholder} spellcheck={false} onChange={({ detail }) => set(f.key, detail.value)} />
              ) : (
                <Input ariaLabel={f.label} value={v[f.key]} placeholder={f.placeholder} onChange={({ detail }) => set(f.key, detail.value)} />
              )}
            </FormField>
          ))}
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

/** A list page with Create + Delete, rows linking to their detail page. */
function LatticeList({ title, resourceName, trackBy = "id", list, del, columns, createLabel, deleteLabel, buildCreate }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [showDel, setShowDel] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const t = useAsync(list, []);
  const rows = t.data || [];
  const Create = buildCreate;
  return (
    <ContentLayout header={<Header variant="h1">{title}</Header>}>
      <CapabilityContainer id={CAP} title={title} counter={`(${rows.length})`}>
        <ResourceTable resourceName={resourceName} items={rows} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy={trackBy}
          selectionType="multi" selectedItems={sel} onSelectionChange={setSel} columns={columns}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: deleteLabel }]} onItemClick={() => setShowDel(true)}>Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => setShowCreate(true)}>{createLabel}</Button>
          </SpaceBetween>} />
      </CapabilityContainer>
      <DeleteModal visible={showDel} resourceType={resourceName.toLowerCase()} names={sel.map((r) => r.name || r.id)} confirmText="delete" onDismiss={() => setShowDel(false)}
        onConfirm={async () => { for (const r of sel) await del(r.id); notify.success(`${sel.length} deleted.`); setSel([]); t.reload(); }} />
      {showCreate && <Create onDismiss={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); t.reload(); }} />}
    </ContentLayout>
  );
}

const KV = ({ items }) => (
  <Container header={<Header variant="h2">Details</Header>}>
    <ColumnLayout columns={3} variant="text-grid">
      {items.map(([k, v]) => <div key={k}><Box variant="awsui-key-label">{k}</Box><div>{v ?? "-"}</div></div>)}
    </ColumnLayout>
  </Container>
);

function useVpcs() { return useAsync(() => vpcApi.describeVpcs(), []); }

// ── service networks ─────────────────────────────────────────────────────────────────
export function ServiceNetworks() {
  return (
    <LatticeList title="Service networks" resourceName="Service networks" list={api.listServiceNetworks} del={api.deleteServiceNetwork}
      createLabel="Create service network" deleteLabel="Delete service network"
      columns={[
        { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (r) => link(`#/vpc/service-networks/${r.id}`, r.name) },
        { id: "id", header: "ID", cell: (r) => r.id },
        { id: "vpc", header: "Associated VPCs", cell: (r) => r.numberOfAssociatedVPCs },
        { id: "svc", header: "Associated services", cell: (r) => r.numberOfAssociatedServices },
        { id: "rc", header: "Associated resource configurations", cell: (r) => r.numberOfAssociatedResourceConfigurations },
        { id: "created", header: "Created", cell: (r) => r.createdAt },
      ]}
      buildCreate={(p) => <CreateModal {...p} header="Create service network" success={(r) => `Service network ${r.id} created.`}
        fields={[{ key: "name", label: "Service network name", required: true, placeholder: "my-service-network", description: "3-63 lowercase letters, digits and hyphens." },
          { key: "authType", label: "Auth type", kind: "select", default: "NONE", options: [opt("NONE", "None"), opt("AWS_IAM", "AWS IAM")] }]}
        create={(v) => api.createServiceNetwork({ name: v.name, authType: v.authType })} />} />
  );
}

function AssocTable({ title, rows, loading, cols, onDelete, onCreate, createLabel, reload }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  return (
    <Table variant="container" items={rows} loading={loading} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
      header={<Header variant="h2" counter={`(${rows.length})`} actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={async () => { try { await onDelete(sel[0].id); notify.success("Association deleted."); setSel([]); reload(); } catch (e) { notify.error(e); } }}>Delete association</Button>
        <Button variant="primary" onClick={onCreate}>{createLabel}</Button></SpaceBetween>}>{title}</Header>}
      columnDefinitions={cols} empty={<Box textAlign="center" color="inherit">No associations</Box>} />
  );
}

function TagsTab({ arn }) {
  const notify = useNotify();
  const t = useAsync(() => api.listTags(arn), [arn]);
  const [k, setK] = useState(""); const [v, setV] = useState("");
  const rows = Object.entries(t.data || {}).map(([key, value]) => ({ key, value }));
  const run = async (fn, msg) => { try { await fn(); notify.success(msg); t.reload(); } catch (e) { notify.error(e); } };
  return (
    <Table variant="container" items={rows} loading={t.loading} trackBy="key" header={<Header variant="h2" counter={`(${rows.length})`}>Tags</Header>}
      columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.key }, { id: "v", header: "Value", cell: (r) => r.value },
        { id: "x", header: "", cell: (r) => <Button variant="inline-link" onClick={() => run(() => api.untagResource(arn, [r.key]), "Tag removed.")}>Remove</Button> }]}
      footer={<SpaceBetween direction="horizontal" size="xs"><Input ariaLabel="Tag key" placeholder="Key" value={k} onChange={({ detail }) => setK(detail.value)} />
        <Input ariaLabel="Tag value" placeholder="Value" value={v} onChange={({ detail }) => setV(detail.value)} />
        <Button disabled={!k} onClick={() => run(() => api.tagResource(arn, { [k]: v }).then(() => { setK(""); setV(""); }), "Tag added.")}>Add tag</Button></SpaceBetween>}
      empty={<Box textAlign="center" color="inherit">No tags</Box>} />
  );
}

function AuthPolicyTab({ id, authType }) {
  const notify = useNotify();
  const p = useAsync(() => api.getAuthPolicy(id).catch(() => null), [id]);
  const [text, setText] = useState(null);
  const shown = text ?? (p.data?.policy ? (() => { try { return JSON.stringify(JSON.parse(p.data.policy), null, 2); } catch { return p.data.policy; } })() : "");
  const run = async (fn, msg) => { try { await fn(); notify.success(msg); setText(null); p.reload(); } catch (e) { notify.error(e); } };
  return (
    <Container header={<Header variant="h2" description={authType === "AWS_IAM" ? "Applied to requests from clients in associated VPCs." : "Set the auth type to AWS IAM to use an auth policy."}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!p.data} onClick={() => run(() => api.deleteAuthPolicy(id), "Auth policy deleted.")}>Delete policy</Button>
        <Button variant="primary" disabled={authType !== "AWS_IAM" || !shown} onClick={() => run(() => api.putAuthPolicy(id, shown), "Auth policy saved.")}>Save policy</Button></SpaceBetween>}>Auth policy</Header>}>
      <Textarea ariaLabel="Auth policy" rows={12} spellcheck={false} value={shown} disabled={authType !== "AWS_IAM"} onChange={({ detail }) => setText(detail.value)}
        placeholder={'{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*","Action":"vpc-lattice-svcs:Invoke","Resource":"*"}]}'} />
    </Container>
  );
}

export function ServiceNetworkDetail({ params }) {
  const notify = useNotify();
  const id = params.id;
  const sn = useAsync(() => api.getServiceNetwork(id), [id]);
  const vpcA = useAsync(() => api.listVpcAssociations(id), [id]);
  const svcA = useAsync(() => api.listServiceAssociations(id), [id]);
  const resA = useAsync(() => api.listResourceAssociations(id), [id]);
  const vpcs = useVpcs();
  const svcs = useAsync(() => api.listServices(), []);
  const rcs = useAsync(() => api.listResourceConfigurations(), []);
  const [modal, setModal] = useState(null);
  const reload = () => { sn.reload(); vpcA.reload(); svcA.reload(); resA.reload(); };
  if (sn.error) return <ErrorAlert error={sn.error} />;
  const d = sn.data;
  const done = () => { setModal(null); reload(); };
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={async () => { try { await api.deleteServiceNetwork(id); notify.success("Service network deleted."); location.hash = "#/vpc/service-networks"; } catch (e) { notify.error(e); } }}>Delete</Button>}>{d?.name || id}</Header>}>
      <SpaceBetween size="l">
        <KV items={[["Name", d?.name], ["ID", id], ["ARN", d?.arn], ["Auth type", d?.authType], ["Created", d?.createdAt],
          ["Associated VPCs", d?.numberOfAssociatedVPCs], ["Associated services", d?.numberOfAssociatedServices], ["Associated resource configurations", d?.numberOfAssociatedResourceConfigurations]]} />
        <Tabs tabs={[
          { id: "vpc", label: "VPC associations", content: <AssocTable title="VPC associations" rows={vpcA.data || []} loading={vpcA.loading} reload={reload} onDelete={api.deleteVpcAssociation} createLabel="Create VPC association" onCreate={() => setModal("vpc")}
            cols={[{ id: "id", header: "Association ID", cell: (r) => r.id }, { id: "v", header: "VPC", cell: (r) => r.vpcId }, { id: "s", header: "Status", cell: (r) => status(r.status) }, { id: "c", header: "Created", cell: (r) => r.createdAt }]} /> },
          { id: "svc", label: "Service associations", content: <AssocTable title="Service associations" rows={svcA.data || []} loading={svcA.loading} reload={reload} onDelete={api.deleteServiceAssociation} createLabel="Associate service" onCreate={() => setModal("svc")}
            cols={[{ id: "id", header: "Association ID", cell: (r) => r.id }, { id: "n", header: "Service", cell: (r) => link(`#/vpc/lattice-services/${r.serviceId}`, r.serviceName) }, { id: "d", header: "DNS name", cell: (r) => r.dnsEntry?.domainName }, { id: "s", header: "Status", cell: (r) => status(r.status) }]} /> },
          { id: "res", label: "Resource configuration associations", content: <AssocTable title="Resource configuration associations" rows={resA.data || []} loading={resA.loading} reload={reload} onDelete={api.deleteResourceAssociation} createLabel="Associate resource configuration" onCreate={() => setModal("res")}
            cols={[{ id: "id", header: "Association ID", cell: (r) => r.id }, { id: "n", header: "Resource configuration", cell: (r) => r.resourceConfigurationName }, { id: "s", header: "Status", cell: (r) => status(r.status) }]} /> },
          { id: "auth", label: "Auth policy", content: <AuthPolicyTab id={id} authType={d?.authType} /> },
          { id: "tags", label: "Tags", content: d ? <TagsTab arn={d.arn} /> : null },
        ]} />
      </SpaceBetween>
      {modal === "vpc" && <CreateModal header="Create VPC association" onDismiss={() => setModal(null)} onCreated={done} success={(r) => `VPC association ${r.id} created.`}
        fields={[{ key: "vpc", label: "VPC", kind: "select", required: true, options: (vpcs.data || []).map((x) => opt(x.VpcId, `${x.VpcId} (${x.CidrBlock})`)), description: "A VPC can belong to only one service network." }]}
        create={(v) => api.createVpcAssociation({ serviceNetworkIdentifier: id, vpcIdentifier: v.vpc })} />}
      {modal === "svc" && <CreateModal header="Associate service" onDismiss={() => setModal(null)} onCreated={done} success={(r) => `Service association ${r.id} created.`}
        fields={[{ key: "svc", label: "Service", kind: "select", required: true, options: (svcs.data || []).map((x) => opt(x.id, x.name)) }]}
        create={(v) => api.createServiceAssociation({ serviceNetworkIdentifier: id, serviceIdentifier: v.svc })} />}
      {modal === "res" && <CreateModal header="Associate resource configuration" onDismiss={() => setModal(null)} onCreated={done} success={(r) => `Association ${r.id} created.`}
        fields={[{ key: "rc", label: "Resource configuration", kind: "select", required: true, options: (rcs.data || []).map((x) => opt(x.id, x.name)) }]}
        create={(v) => api.createResourceAssociation({ serviceNetworkIdentifier: id, resourceConfigurationIdentifier: v.rc })} />}
    </ContentLayout>
  );
}

// ── services ─────────────────────────────────────────────────────────────────────────
export function LatticeServices() {
  return (
    <LatticeList title="Lattice services" resourceName="Lattice services" list={api.listServices} del={api.deleteService}
      createLabel="Create service" deleteLabel="Delete service"
      columns={[
        { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (r) => link(`#/vpc/lattice-services/${r.id}`, r.name) },
        { id: "id", header: "ID", cell: (r) => r.id },
        { id: "dns", header: "DNS name", cell: (r) => r.dnsEntry?.domainName },
        { id: "st", header: "Status", cell: (r) => status(r.status) },
        { id: "created", header: "Created", cell: (r) => r.createdAt },
      ]}
      buildCreate={(p) => <CreateModal {...p} header="Create service" success={(r) => `Service ${r.id} created.`}
        fields={[{ key: "name", label: "Service name", required: true, placeholder: "my-service", description: "3-40 lowercase letters, digits and hyphens." },
          { key: "authType", label: "Auth type", kind: "select", default: "NONE", options: [opt("NONE", "None"), opt("AWS_IAM", "AWS IAM")] },
          { key: "customDomainName", label: "Custom domain name - optional", placeholder: "orders.example.com" }]}
        create={(v) => api.createService({ name: v.name, authType: v.authType, ...(v.customDomainName ? { customDomainName: v.customDomainName } : {}) })} />} />
  );
}

function fwd(tg) { return { forward: { targetGroups: [{ targetGroupIdentifier: tg, weight: 100 }] } }; }
const describeAction = (a) => (a?.fixedResponse ? `Fixed response ${a.fixedResponse.statusCode}` : (a?.forward?.targetGroups || []).map((t) => `${t.targetGroupIdentifier} (${t.weight})`).join(", "));
const describeMatch = (m) => { const h = m?.httpMatch || {}; return [h.method, h.pathMatch && (h.pathMatch.match.exact ? `= ${h.pathMatch.match.exact}` : `${h.pathMatch.match.prefix}*`), ...(h.headerMatches || []).map((x) => `header ${x.name}`)].filter(Boolean).join(" ") || "-"; };

function RulesPanel({ sid, listener, tgs }) {
  const notify = useNotify();
  const rules = useAsync(async () => { const rs = await api.listRules(sid, listener.id); return Promise.all(rs.map((r) => api.getRule(sid, listener.id, r.id))); }, [sid, listener.id]);
  const [show, setShow] = useState(false);
  const [sel, setSel] = useState([]);
  return (
    <>
      <Table variant="container" items={rules.data || []} loading={rules.loading} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h3" counter={`(${(rules.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length || sel[0].isDefault} onClick={async () => { try { await api.deleteRule(sid, listener.id, sel[0].id); notify.success("Rule deleted."); setSel([]); rules.reload(); } catch (e) { notify.error(e); } }}>Delete rule</Button>
          <Button disabled={listener.protocol === "TLS_PASSTHROUGH"} onClick={() => setShow(true)}>Add rule</Button></SpaceBetween>}>Rules of {listener.name}</Header>}
        columnDefinitions={[{ id: "p", header: "Priority", cell: (r) => (r.isDefault ? "Default" : r.priority) }, { id: "n", header: "Name", cell: (r) => r.name },
          { id: "m", header: "Match", cell: (r) => (r.isDefault ? "Anything not matched" : describeMatch(r.match)) }, { id: "a", header: "Action", cell: (r) => describeAction(r.action) }]} />
      {show && <CreateModal header="Add rule" onDismiss={() => setShow(false)} onCreated={() => { setShow(false); rules.reload(); }} success={(r) => `Rule ${r.id} created.`}
        fields={[{ key: "name", label: "Rule name", required: true }, { key: "priority", label: "Priority (1-100)", required: true, default: "10" },
          { key: "prefix", label: "Path prefix", required: true, default: "/" },
          { key: "action", label: "Action", kind: "select", default: "forward", options: [opt("forward", "Forward to target group"), opt("fixed", "Fixed response")] },
          { key: "tg", label: "Target group (forward)", kind: "select", options: tgs.map((t) => opt(t.id, t.name)) }, { key: "code", label: "Status code (fixed response)", default: "404" }]}
        create={(v) => api.createRule(sid, listener.id, { name: v.name, priority: Number(v.priority), match: { httpMatch: { pathMatch: { match: { prefix: v.prefix }, caseSensitive: false } } },
          action: v.action === "fixed" ? { fixedResponse: { statusCode: Number(v.code) } } : fwd(v.tg) })} />}
    </>
  );
}

function InvokePanel({ host }) {
  const vpcs = useVpcs();
  return (
    <SimPanel title="Test invoke" testId="invoke" description="Evaluates one request through Lattice's data plane (DNS per VPC, associations, security groups, listener, auth policy, rules, target health). Simulator verb: POST /vyomi/invoke."
      fields={[{ key: "host", label: "Host", default: host }, { key: "sourceVpcId", label: "Source VPC", options: (vpcs.data || []).map((x) => ({ value: x.VpcId, label: `${x.VpcId} (${x.CidrBlock})` })) },
        { key: "method", label: "Method", default: "GET", options: ["GET", "POST", "PUT", "DELETE"].map((m) => ({ value: m, label: m })) }, { key: "path", label: "Path", default: "/" },
        { key: "port", label: "Port", default: "80" }, { key: "protocol", label: "Protocol", default: "HTTP", options: ["HTTP", "HTTPS"].map((m) => ({ value: m, label: m })) },
        { key: "principal", label: "Caller principal ARN (AWS_IAM auth)", default: "" }]}
      run={(f) => api.testInvoke({ host: f.host, sourceVpcId: f.sourceVpcId, method: f.method, path: f.path, port: Number(f.port) || undefined, protocol: f.protocol, ...(f.principal ? { principal: f.principal } : {}) })}
      verdict={(r) => (r.statusCode && r.statusCode < 400 ? ["success", `HTTP ${r.statusCode} - ${r.message || ""}`] : r.statusCode ? ["warning", `HTTP ${r.statusCode} - ${r.message || ""}`] : ["error", `No response - ${r.message || r.dnsResult}`])}
      steps={(r) => r.steps} />
  );
}

export function LatticeServiceDetail({ params }) {
  const notify = useNotify();
  const id = params.id;
  const svc = useAsync(() => api.getService(id), [id]);
  const lis = useAsync(() => api.listListeners(id), [id]);
  const assoc = useAsync(() => api.listServiceAssociations(null, id), [id]);
  const tgs = useAsync(() => api.listTargetGroups(), []);
  const [modal, setModal] = useState(false);
  const [open, setOpen] = useState(null);
  if (svc.error) return <ErrorAlert error={svc.error} />;
  const d = svc.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={async () => { try { await api.deleteService(id); notify.success("Service deleted."); location.hash = "#/vpc/lattice-services"; } catch (e) { notify.error(e); } }}>Delete</Button>}>{d?.name || id}</Header>}>
      <SpaceBetween size="l">
        <KV items={[["Name", d?.name], ["ID", id], ["ARN", d?.arn], ["Status", d && status(d.status)], ["Auth type", d?.authType], ["DNS name", d?.dnsEntry?.domainName], ["Custom domain", d?.customDomainName], ["Created", d?.createdAt]]} />
        <Tabs tabs={[
          { id: "lis", label: "Listeners", content: (
            <SpaceBetween size="m">
              <Table variant="container" items={lis.data || []} loading={lis.loading} trackBy="id" selectionType="single" selectedItems={open ? [open] : []} onSelectionChange={({ detail }) => setOpen(detail.selectedItems[0] || null)}
                header={<Header variant="h2" counter={`(${(lis.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
                  <Button disabled={!open} onClick={async () => { try { await api.deleteListener(id, open.id); notify.success("Listener deleted."); setOpen(null); lis.reload(); } catch (e) { notify.error(e); } }}>Delete listener</Button>
                  <Button variant="primary" onClick={() => setModal(true)}>Add listener</Button></SpaceBetween>}>Listeners</Header>}
                columnDefinitions={[{ id: "n", header: "Name", cell: (l) => l.name }, { id: "p", header: "Protocol", cell: (l) => l.protocol }, { id: "o", header: "Port", cell: (l) => l.port }, { id: "i", header: "ID", cell: (l) => l.id }]}
                empty={<Box textAlign="center" color="inherit">No listeners. Add one to route requests to target groups.</Box>} />
              {open && <RulesPanel sid={id} listener={open} tgs={tgs.data || []} />}
            </SpaceBetween>) },
          { id: "invoke", label: "Test invoke", content: d ? <InvokePanel host={d.dnsEntry?.domainName || d.customDomainName || d.name} /> : null },
          { id: "assoc", label: "Service network associations", content: <AssocTable title="Service network associations" rows={assoc.data || []} loading={assoc.loading} reload={assoc.reload} onDelete={api.deleteServiceAssociation} createLabel="Manage in service network" onCreate={() => { location.hash = "#/vpc/service-networks"; }}
            cols={[{ id: "id", header: "Association ID", cell: (r) => r.id }, { id: "n", header: "Service network", cell: (r) => link(`#/vpc/service-networks/${r.serviceNetworkId}`, r.serviceNetworkName) }, { id: "s", header: "Status", cell: (r) => status(r.status) }]} /> },
          { id: "auth", label: "Auth policy", content: <AuthPolicyTab id={id} authType={d?.authType} /> },
          { id: "tags", label: "Tags", content: d ? <TagsTab arn={d.arn} /> : null },
        ]} />
      </SpaceBetween>
      {modal && <CreateModal header="Add listener" onDismiss={() => setModal(false)} onCreated={() => { setModal(false); lis.reload(); }} success={(r) => `Listener ${r.id} created.`}
        fields={[{ key: "name", label: "Listener name", required: true, placeholder: "http-80" },
          { key: "protocol", label: "Protocol", kind: "select", default: "HTTP", options: [opt("HTTP"), opt("HTTPS"), opt("TLS_PASSTHROUGH")] },
          { key: "port", label: "Port", default: "80", required: true },
          { key: "action", label: "Default action", kind: "select", default: "forward", options: [opt("forward", "Forward to target group"), opt("fixed", "Fixed response")] },
          { key: "tg", label: "Target group (forward)", kind: "select", options: (tgs.data || []).map((t) => opt(t.id, t.name)) }, { key: "code", label: "Status code (fixed response)", default: "404" }]}
        create={(v) => api.createListener(id, { name: v.name, protocol: v.protocol, port: Number(v.port), defaultAction: v.action === "fixed" ? { fixedResponse: { statusCode: Number(v.code) } } : fwd(v.tg) })} />}
    </ContentLayout>
  );
}

// ── target groups ────────────────────────────────────────────────────────────────────
export function LatticeTargetGroups() {
  const vpcs = useVpcs();
  return (
    <LatticeList title="Target groups" resourceName="Target groups" list={api.listTargetGroups} del={api.deleteTargetGroup}
      createLabel="Create target group" deleteLabel="Delete target group"
      columns={[
        { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (r) => link(`#/vpc/lattice-target-groups/${r.id}`, r.name) },
        { id: "id", header: "ID", cell: (r) => r.id }, { id: "type", header: "Target type", cell: (r) => r.type },
        { id: "proto", header: "Protocol : port", cell: (r) => (r.protocol ? `${r.protocol} : ${r.port}` : "-") }, { id: "vpc", header: "VPC", cell: (r) => r.vpcIdentifier || "-" },
        { id: "svc", header: "Associated services", cell: (r) => (r.serviceArns || []).length }, { id: "st", header: "Status", cell: (r) => status(r.status) },
      ]}
      buildCreate={(p) => <CreateModal {...p} header="Create target group" success={(r) => `Target group ${r.id} created.`}
        fields={[{ key: "name", label: "Target group name", required: true, placeholder: "my-targets" },
          { key: "type", label: "Target type", kind: "select", default: "IP", options: [opt("IP", "IP addresses"), opt("INSTANCE", "Instances"), opt("ALB", "Application Load Balancer"), opt("LAMBDA", "Lambda function")] },
          { key: "protocol", label: "Protocol (not for Lambda)", kind: "select", default: "HTTP", options: [opt("HTTP"), opt("HTTPS"), opt("TCP")] },
          { key: "port", label: "Port (not for Lambda)", default: "80" },
          { key: "vpc", label: "VPC (not for Lambda)", kind: "select", options: (vpcs.data || []).map((x) => opt(x.VpcId, `${x.VpcId} (${x.CidrBlock})`)) }]}
        create={(v) => api.createTargetGroup({ name: v.name, type: v.type, ...(v.type === "LAMBDA" ? {} : { config: { protocol: v.protocol, port: Number(v.port), vpcIdentifier: v.vpc } }) })} />} />
  );
}

export function TargetGroupDetail({ params }) {
  const notify = useNotify();
  const id = params.id;
  const tg = useAsync(() => api.getTargetGroup(id), [id]);
  const targets = useAsync(() => api.listTargets(id), [id]);
  const [show, setShow] = useState(false);
  const [sel, setSel] = useState([]);
  if (tg.error) return <ErrorAlert error={tg.error} />;
  const d = tg.data;
  const hc = d?.config?.healthCheck;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={async () => { try { await api.deleteTargetGroup(id); notify.success("Target group deleted."); location.hash = "#/vpc/lattice-target-groups"; } catch (e) { notify.error(e); } }}>Delete</Button>}>{d?.name || id}</Header>}>
      <SpaceBetween size="l">
        <KV items={[["Name", d?.name], ["ID", id], ["ARN", d?.arn], ["Target type", d?.type], ["Protocol : port", d?.config?.protocol ? `${d.config.protocol} : ${d.config.port}` : "-"], ["VPC", d?.config?.vpcIdentifier],
          ["Health check", hc ? `${hc.protocol} ${hc.path} every ${hc.healthCheckIntervalSeconds}s` : "-"], ["Used by services", (d?.serviceArns || []).length]]} />
        <Tabs tabs={[
          { id: "t", label: "Targets", content: (
            <Table variant="container" items={targets.data || []} loading={targets.loading} trackBy={(t) => `${t.id}|${t.port}`} selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              header={<Header variant="h2" counter={`(${(targets.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
                <Button disabled={!sel.length} onClick={async () => { try { await api.deregisterTargets(id, [{ id: sel[0].id, ...(sel[0].port ? { port: sel[0].port } : {}) }]); notify.success("Target deregistered."); setSel([]); targets.reload(); } catch (e) { notify.error(e); } }}>Deregister</Button>
                <Button variant="primary" onClick={() => setShow(true)}>Register targets</Button></SpaceBetween>}>Registered targets</Header>}
              columnDefinitions={[{ id: "i", header: d?.type === "LAMBDA" || d?.type === "ALB" ? "ARN" : d?.type === "INSTANCE" ? "Instance ID" : "IP address", cell: (t) => t.id }, { id: "p", header: "Port", cell: (t) => t.port ?? "-" },
                { id: "s", header: "Status", cell: (t) => <span title={t.reasonCode}>{status(t.status)}</span> }, { id: "r", header: "Reason", cell: (t) => t.reasonCode }]}
              empty={<Box textAlign="center" color="inherit">No targets registered</Box>} />) },
          { id: "tags", label: "Tags", content: d ? <TagsTab arn={d.arn} /> : null },
        ]} />
        <Box variant="small" color="text-body-secondary">Vyomi does not probe targets: health stays Initial (or Unused when no listener uses the group).</Box>
      </SpaceBetween>
      {show && <CreateModal header="Register targets" onDismiss={() => setShow(false)} onCreated={() => { setShow(false); targets.reload(); }} success={() => "Target registered."}
        fields={[{ key: "id", label: d?.type === "INSTANCE" ? "Instance ID" : d?.type === "IP" ? "IP address" : "ARN", required: true }, ...(d?.type === "LAMBDA" ? [] : [{ key: "port", label: "Port - optional" }])]}
        create={async (v) => { const r = await api.registerTargets(id, [{ id: v.id, ...(v.port ? { port: Number(v.port) } : {}) }]); if (r.unsuccessful?.length) throw new Error(r.unsuccessful[0].failureMessage); return r; }} />}
    </ContentLayout>
  );
}

// ── resource gateways / configurations ───────────────────────────────────────────────
export function ResourceGateways() {
  const vpcs = useVpcs();
  const subs = useAsync(() => vpcApi.describeSubnets(), []);
  return (
    <LatticeList title="Resource gateways" resourceName="Resource gateways" list={api.listResourceGateways} del={api.deleteResourceGateway}
      createLabel="Create resource gateway" deleteLabel="Delete resource gateway"
      columns={[
        { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (r) => r.name }, { id: "id", header: "ID", cell: (r) => r.id },
        { id: "vpc", header: "VPC", cell: (r) => r.vpcIdentifier }, { id: "sn", header: "Subnets", cell: (r) => (r.subnetIds || []).join(", ") },
        { id: "ip", header: "IP address type", cell: (r) => r.ipAddressType }, { id: "st", header: "Status", cell: (r) => status(r.status) },
      ]}
      buildCreate={(p) => <GatewayCreate {...p} vpcs={vpcs.data || []} subs={subs.data || []} />} />
  );
}

function GatewayCreate({ vpcs, subs, ...p }) {
  return (
    <CreateModal {...p} header="Create resource gateway" success={(r) => `Resource gateway ${r.id} created.`}
      fields={[{ key: "name", label: "Resource gateway name", required: true, placeholder: "my-gateway" },
        { key: "vpc", label: "VPC", kind: "select", required: true, options: vpcs.map((x) => opt(x.VpcId, `${x.VpcId} (${x.CidrBlock})`)) },
        { key: "subnet", label: "Subnet", kind: "select", required: true, options: subs.map((s) => opt(s.SubnetId, `${s.SubnetId} (${s.CidrBlock}, ${s.VpcId})`)), description: "A subnet in the chosen VPC." },
        { key: "ipt", label: "IP address type", kind: "select", default: "IPV4", options: [opt("IPV4"), opt("IPV6"), opt("DUALSTACK")] }]}
      create={(v) => api.createResourceGateway({ name: v.name, vpcIdentifier: v.vpc, subnetIds: [v.subnet], ipAddressType: v.ipt })} />
  );
}

export function ResourceConfigurations() {
  const gws = useAsync(() => api.listResourceGateways(), []);
  return (
    <LatticeList title="Resource configurations" resourceName="Resource configurations" list={api.listResourceConfigurations} del={api.deleteResourceConfiguration}
      createLabel="Create resource configuration" deleteLabel="Delete resource configuration"
      columns={[
        { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (r) => r.name }, { id: "id", header: "ID", cell: (r) => r.id },
        { id: "type", header: "Type", cell: (r) => r.type }, { id: "gw", header: "Resource gateway", cell: (r) => r.resourceGatewayId || "-" }, { id: "st", header: "Status", cell: (r) => status(r.status) },
      ]}
      buildCreate={(p) => <CreateModal {...p} header="Create resource configuration" success={(r) => `Resource configuration ${r.id} created.`}
        fields={[{ key: "name", label: "Name", required: true, placeholder: "my-database" },
          { key: "gw", label: "Resource gateway", kind: "select", required: true, options: (gws.data || []).map((g) => opt(g.id, g.name)) },
          { key: "kind", label: "Resource definition", kind: "select", default: "ip", options: [opt("ip", "IP address"), opt("dns", "DNS name")] },
          { key: "target", label: "IP address or domain name", required: true, placeholder: "10.0.1.20 or db.example.com" },
          { key: "ports", label: "Port ranges (comma separated)", required: true, default: "443" }]}
        create={(v) => api.createResourceConfiguration({ name: v.name, type: "SINGLE", resourceGatewayIdentifier: v.gw, protocol: "TCP", portRanges: v.ports.split(",").map((x) => x.trim()),
          resourceConfigurationDefinition: v.kind === "ip" ? { ipResource: { ipAddress: v.target } } : { dnsResource: { domainName: v.target, ipAddressType: "IPV4" } } })} />} />
  );
}

export function DomainVerifications() {
  return (
    <LatticeList title="Domain verifications" resourceName="Domain verifications" list={api.listDomainVerifications} del={api.deleteDomainVerification}
      createLabel="Start domain verification" deleteLabel="Delete domain verification"
      columns={[
        { id: "d", header: "Domain", isRowHeader: true, sortingField: "domainName", cell: (r) => r.domainName }, { id: "st", header: "Status", cell: (r) => status(r.status) },
        { id: "n", header: "TXT record name", cell: (r) => r.txtMethodConfig?.name }, { id: "v", header: "TXT record value", cell: (r) => <code>{r.txtMethodConfig?.value}</code> },
        { id: "c", header: "Created", cell: (r) => r.createdAt },
      ]}
      buildCreate={(p) => <CreateModal {...p} header="Start domain verification" success={(r) => `Verification ${r.id} started: publish the TXT record to prove ownership.`}
        fields={[{ key: "domain", label: "Domain name", required: true, placeholder: "example.com" }]} create={(v) => api.startDomainVerification(v.domain)} />} />
  );
}

/* AWS Network Manager console: global networks and, per network, sites, devices, links (+ device<->link associations) and transit
 * gateway registrations. Every control is a real Network Manager API call; transit gateways come from the account's real EC2 model. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Tabs from "@cloudscape-design/components/tabs";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate, useRoute } from "../../../common/router.js";
import { awsQuery, asList } from "../../../common/wire.js";
import * as api from "./api.js";

const when = (t) => (t ? fmtDate(new Date(t * 1000).toISOString()) : "-");
const state = (s) => <StatusIndicator type={s === "AVAILABLE" ? "success" : "in-progress"}>{s}</StatusIndicator>;

function Dlg({ title, visible, onDismiss, onSubmit, children, cta }) {
  const [err, setErr] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={title}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" onClick={async () => { try { setErr(null); await onSubmit(); } catch (e) { setErr(e); } }}>{cta || title}</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />{children}</SpaceBetween>
    </Modal>
  );
}
const Fld = ({ label, v, set, ph, desc }) => <FormField label={label} description={desc}><Input ariaLabel={label} value={v} placeholder={ph} onChange={({ detail }) => set(detail.value)} /></FormField>;

/* ── Global networks ───────────────────────────────────────────────────────── */
export function GlobalNetworks() {
  const notify = useNotify();
  const t = useAsync(() => api.listGlobalNetworks(), []);
  const [sel, setSel] = useState([]);
  const [dlg, setDlg] = useState(false);
  const [del, setDel] = useState(false);
  const [desc, setDesc] = useState("");
  const [tag, setTag] = useState("");
  return (
    <>
      <ResourceTable resourceName="Global networks" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="GlobalNetworkId" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        filterPlaceholder="Find global networks" empty={{ title: "No global networks", description: "Create a global network to register transit gateways and model your on-premises sites." }}
        columns={[{ id: "id", header: "Global network ID", isRowHeader: true, sortingField: "GlobalNetworkId", cell: (g) => <Link href={`#/networkmanager/global-networks/view?id=${g.GlobalNetworkId}`} onFollow={follow}>{g.GlobalNetworkId}</Link> },
          { id: "n", header: "Name", cell: (g) => (g.Tags || []).find((x) => x.Key === "Name")?.Value || "-" }, { id: "d", header: "Description", cell: (g) => g.Description || "-" },
          { id: "s", header: "State", cell: (g) => state(g.State) }, { id: "c", header: "Created", cell: (g) => when(g.CreatedAt) }]}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button><Button variant="primary" onClick={() => setDlg(true)}>Create global network</Button></SpaceBetween>} />
      <Dlg title="Create global network" visible={dlg} onDismiss={() => setDlg(false)} onSubmit={async () => {
        const g = await api.createGlobalNetwork(desc, tag ? [{ Key: "Name", Value: tag }] : []); notify.success(`Created global network ${g.GlobalNetworkId}.`); setDlg(false); setDesc(""); setTag(""); t.reload(); }}>
        <Fld label="Name" v={tag} set={setTag} ph="corporate-wan" /><Fld label="Description" v={desc} set={setDesc} />
      </Dlg>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="global network" names={sel.map((g) => g.GlobalNetworkId)}
        onConfirm={async () => { await api.deleteGlobalNetwork(sel[0].GlobalNetworkId); notify.success("Deleted global network."); setSel([]); t.reload(); }} />
    </>
  );
}

/* ── Detail tabs ───────────────────────────────────────────────────────────── */
function Pane({ name, load, columns, trackBy, create, onDelete, delType, extra, gid }) {
  const notify = useNotify();
  const t = useAsync(load, [gid]);
  const [sel, setSel] = useState([]);
  const [dlg, setDlg] = useState(false);
  const [del, setDel] = useState(false);
  return (
    <>
      <ResourceTable resourceName={name} items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy={trackBy} selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        empty={{ title: `No ${name.toLowerCase()}` }} columns={columns} variant="container"
        actions={<SpaceBetween direction="horizontal" size="xs">{extra?.(sel, t.reload)}{onDelete && <Button disabled={!sel.length} onClick={() => setDel(true)}>{delType === "registration" ? "Deregister" : "Delete"}</Button>}
          {create && <Button variant="primary" onClick={() => setDlg(true)}>{create.cta}</Button>}</SpaceBetween>} />
      {create?.render({ visible: dlg, onDismiss: () => setDlg(false), done: (m) => { notify.success(m); setDlg(false); t.reload(); } })}
      {onDelete && <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType={delType} names={sel.map((x) => x[trackBy])}
        onConfirm={async () => { await onDelete(sel[0]); notify.success(`Removed ${delType}.`); setSel([]); t.reload(); }} />}
    </>
  );
}

const nameTag = (x) => (x.Tags || []).find((t) => t.Key === "Name")?.Value || "-";

function SiteDlg({ gid, visible, onDismiss, done }) {
  const [f, setF] = useState({ name: "", desc: "", addr: "", lat: "", lon: "" });
  return <Dlg title="Create site" visible={visible} onDismiss={onDismiss} onSubmit={async () => {
    const s = (await api.createSite(gid, { Description: f.desc, Tags: f.name ? [{ Key: "Name", Value: f.name }] : [], Location: { ...(f.addr ? { Address: f.addr } : {}), ...(f.lat ? { Latitude: f.lat } : {}), ...(f.lon ? { Longitude: f.lon } : {}) } })).Site;
    done(`Created site ${s.SiteId}.`); }}>
    <Fld label="Name" v={f.name} set={(v) => setF({ ...f, name: v })} /><Fld label="Description" v={f.desc} set={(v) => setF({ ...f, desc: v })} />
    <Fld label="Address" v={f.addr} set={(v) => setF({ ...f, addr: v })} /><Fld label="Latitude" v={f.lat} set={(v) => setF({ ...f, lat: v })} ph="47.6" /><Fld label="Longitude" v={f.lon} set={(v) => setF({ ...f, lon: v })} ph="-122.3" />
  </Dlg>;
}

function DeviceDlg({ gid, visible, onDismiss, done }) {
  const sites = useAsync(() => api.listSites(gid), [gid, visible]);
  const [f, setF] = useState({ name: "", site: null, type: "", vendor: "", model: "" });
  return <Dlg title="Create device" visible={visible} onDismiss={onDismiss} onSubmit={async () => {
    const d = (await api.createDevice(gid, { ...(f.site ? { SiteId: f.site.value } : {}), Tags: f.name ? [{ Key: "Name", Value: f.name }] : [], ...(f.type ? { Type: f.type } : {}), ...(f.vendor ? { Vendor: f.vendor } : {}), ...(f.model ? { Model: f.model } : {}) })).Device;
    done(`Created device ${d.DeviceId}.`); }}>
    <Fld label="Name" v={f.name} set={(v) => setF({ ...f, name: v })} />
    <FormField label="Site"><Select ariaLabel="Site" selectedOption={f.site} placeholder="Choose a site" options={(sites.data || []).map((s) => ({ value: s.SiteId, label: `${nameTag(s) === "-" ? s.SiteId : nameTag(s)} (${s.SiteId})` }))} onChange={({ detail }) => setF({ ...f, site: detail.selectedOption })} /></FormField>
    <Fld label="Type" v={f.type} set={(v) => setF({ ...f, type: v })} ph="router" /><Fld label="Vendor" v={f.vendor} set={(v) => setF({ ...f, vendor: v })} /><Fld label="Model" v={f.model} set={(v) => setF({ ...f, model: v })} />
  </Dlg>;
}

function LinkDlg({ gid, visible, onDismiss, done }) {
  const sites = useAsync(() => api.listSites(gid), [gid, visible]);
  const [f, setF] = useState({ name: "", site: null, up: "100", down: "100", provider: "" });
  return <Dlg title="Create link" visible={visible} onDismiss={onDismiss} onSubmit={async () => {
    const l = (await api.createLink(gid, { SiteId: f.site?.value, Tags: f.name ? [{ Key: "Name", Value: f.name }] : [], Bandwidth: { UploadSpeed: Number(f.up), DownloadSpeed: Number(f.down) }, ...(f.provider ? { Provider: f.provider } : {}) })).Link;
    done(`Created link ${l.LinkId}.`); }}>
    <Fld label="Name" v={f.name} set={(v) => setF({ ...f, name: v })} />
    <FormField label="Site"><Select ariaLabel="Site" selectedOption={f.site} placeholder="Choose a site" options={(sites.data || []).map((s) => ({ value: s.SiteId, label: s.SiteId }))} onChange={({ detail }) => setF({ ...f, site: detail.selectedOption })} /></FormField>
    <Fld label="Upload speed (Mbps)" v={f.up} set={(v) => setF({ ...f, up: v })} /><Fld label="Download speed (Mbps)" v={f.down} set={(v) => setF({ ...f, down: v })} /><Fld label="Provider" v={f.provider} set={(v) => setF({ ...f, provider: v })} />
  </Dlg>;
}

function AssocBar({ gid, devices, links, reload, sel }) {
  const notify = useNotify();
  const [dlg, setDlg] = useState(false);
  const [d, setD] = useState(null);
  const [l, setL] = useState(null);
  return (<>
    <Button onClick={() => setDlg(true)}>Associate link</Button>
    <Button disabled={!sel.length} onClick={async () => { try { await api.disassociate(gid, sel[0].DeviceId, sel[0].LinkId); notify.success("Disassociated link."); reload(); } catch (e) { notify.error(e.message); } }}>Disassociate</Button>
    <Dlg title="Associate link" visible={dlg} onDismiss={() => setDlg(false)} onSubmit={async () => { await api.associate(gid, d?.value, l?.value); notify.success("Associated link with device."); setDlg(false); reload(); }}>
      <FormField label="Device"><Select ariaLabel="Device" selectedOption={d} options={devices.map((x) => ({ value: x.DeviceId, label: x.DeviceId }))} onChange={({ detail }) => setD(detail.selectedOption)} placeholder="Choose a device" /></FormField>
      <FormField label="Link"><Select ariaLabel="Link" selectedOption={l} options={links.map((x) => ({ value: x.LinkId, label: x.LinkId }))} onChange={({ detail }) => setL(detail.selectedOption)} placeholder="Choose a link" /></FormField>
    </Dlg></>);
}

function TgwDlg({ gid, visible, onDismiss, done }) {
  const tg = useAsync(async () => { const r = await awsQuery("ec2", "DescribeTransitGateways", {}, { version: "2016-11-15" }); return asList(r.DescribeTransitGatewaysResponse?.transitGatewaySet?.item); }, [visible]);
  const [pick, setPick] = useState(null);
  return <Dlg title="Register transit gateway" visible={visible} onDismiss={onDismiss} onSubmit={async () => { await api.registerTgw(gid, pick?.value); done("Registered the transit gateway."); }} cta="Register">
    <FormField label="Transit gateway" description="Transit gateways in this account's Region."><Select ariaLabel="Transit gateway" selectedOption={pick} placeholder="Choose a transit gateway"
      options={(tg.data || []).map((x) => ({ value: x.transitGatewayArn || `arn:aws:ec2:us-east-1:123456789012:transit-gateway/${x.transitGatewayId}`, label: x.transitGatewayId, description: x.description || undefined }))}
      onChange={({ detail }) => setPick(detail.selectedOption)} /></FormField>
  </Dlg>;
}

export function GlobalNetworkDetail() {
  const { query } = useRoute();
  const gid = query.id;
  const g = useAsync(async () => (await api.listGlobalNetworks()).find((x) => x.GlobalNetworkId === gid), [gid]);
  const devs = useAsync(() => api.listDevices(gid), [gid]);
  const links = useAsync(() => api.listLinks(gid), [gid]);
  if (g.error) return <ErrorAlert error={g.error} />;
  if (g.data === null || (!g.loading && !g.data)) return <Alert type="error" header="Global network not found">{gid}</Alert>;
  const gn = g.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={() => navigate("networkmanager", "global-networks")}>Back to global networks</Button>}>{gid}</Header>}>
      {gn && <SpaceBetween size="l">
        <KeyValue title="Details" columns={3} items={[["Global network ID", gn.GlobalNetworkId], ["ARN", gn.GlobalNetworkArn], ["State", state(gn.State)], ["Description", gn.Description], ["Created", when(gn.CreatedAt)]]} />
        <Alert type="info">Inventory and registration control plane only: Vyomi does not collect topology telemetry, events or route analysis, and has no Connect, customer-gateway or Direct Connect associations.</Alert>
        <Tabs tabs={[
          { id: "sites", label: "Sites", content: <Pane gid={gid} name="Sites" load={() => api.listSites(gid)} trackBy="SiteId" onDelete={(s) => api.deleteSite(gid, s.SiteId)} delType="site"
            create={{ cta: "Create site", render: (p) => <SiteDlg gid={gid} {...p} /> }}
            columns={[{ id: "i", header: "Site ID", isRowHeader: true, cell: (s) => s.SiteId }, { id: "n", header: "Name", cell: nameTag }, { id: "d", header: "Description", cell: (s) => s.Description || "-" },
              { id: "a", header: "Address", cell: (s) => s.Location?.Address || "-" }, { id: "s", header: "State", cell: (s) => state(s.State) }]} /> },
          { id: "devices", label: "Devices", content: <Pane gid={gid} name="Devices" load={() => api.listDevices(gid)} trackBy="DeviceId" onDelete={(d) => api.deleteDevice(gid, d.DeviceId)} delType="device"
            create={{ cta: "Create device", render: (p) => <DeviceDlg gid={gid} {...p} /> }}
            columns={[{ id: "i", header: "Device ID", isRowHeader: true, cell: (d) => d.DeviceId }, { id: "n", header: "Name", cell: nameTag }, { id: "s", header: "Site", cell: (d) => d.SiteId || "-" },
              { id: "t", header: "Type", cell: (d) => d.Type || "-" }, { id: "v", header: "Vendor / model", cell: (d) => [d.Vendor, d.Model].filter(Boolean).join(" ") || "-" }, { id: "st", header: "State", cell: (d) => state(d.State) }]} /> },
          { id: "links", label: "Links", content: <Pane gid={gid} name="Links" load={() => api.listLinks(gid)} trackBy="LinkId" onDelete={(l) => api.deleteLink(gid, l.LinkId)} delType="link"
            create={{ cta: "Create link", render: (p) => <LinkDlg gid={gid} {...p} /> }}
            columns={[{ id: "i", header: "Link ID", isRowHeader: true, cell: (l) => l.LinkId }, { id: "n", header: "Name", cell: nameTag }, { id: "s", header: "Site", cell: (l) => l.SiteId },
              { id: "b", header: "Bandwidth (up / down Mbps)", cell: (l) => `${l.Bandwidth?.UploadSpeed ?? "-"} / ${l.Bandwidth?.DownloadSpeed ?? "-"}` }, { id: "p", header: "Provider", cell: (l) => l.Provider || "-" }]} /> },
          { id: "assoc", label: "Link associations", content: <Pane gid={gid} name="Link associations" load={() => api.listAssociations(gid)} trackBy="k" extra={(sel, reload) => <AssocBar gid={gid} devices={devs.data || []} links={links.data || []} reload={reload} sel={sel} />}
            columns={[{ id: "d", header: "Device", isRowHeader: true, cell: (a) => a.DeviceId }, { id: "l", header: "Link", cell: (a) => a.LinkId }, { id: "s", header: "State", cell: (a) => state(a.LinkAssociationState) }]} /> },
          { id: "tgw", label: "Transit gateways", content: <Pane gid={gid} name="Transit gateway registrations" load={() => api.listRegistrations(gid)} trackBy="TransitGatewayArn" onDelete={(r) => api.deregisterTgw(gid, r.TransitGatewayArn)} delType="registration"
            create={{ cta: "Register transit gateway", render: (p) => <TgwDlg gid={gid} {...p} /> }}
            columns={[{ id: "a", header: "Transit gateway ARN", isRowHeader: true, cell: (r) => r.TransitGatewayArn }, { id: "s", header: "State", cell: (r) => state(r.State?.Code) }]} /> },
        ]} />
      </SpaceBetween>}
    </ContentLayout>
  );
}

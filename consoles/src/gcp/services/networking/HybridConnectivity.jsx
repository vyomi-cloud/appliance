/* Bring your own IP + VPC connectivity (Interconnects, VLAN attachments) over core/gcp_hybrid_core.
 * Control plane only: no circuit, BGP session or routed traffic backs an ACTIVE state (see the capability text). */
import { useState } from "react";
import { Button, Chip, Tab, Tabs } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import { ListPage } from "../compute/Ext.jsx";
import * as api from "./api.js";

const nm = (v) => String(v || "").split("/").pop();
const REGION_OPTS = ["us-central1", "us-east4", "us-west1", "europe-west1", "europe-west2", "asia-southeast1"].map((r) => [r, r]);
const COLOR = { ACTIVE: "success", VALIDATED: "info", ANNOUNCED_TO_INTERNET: "success", ANNOUNCED: "success", READY_TO_ANNOUNCE: "info", UNPROVISIONED: "default", PENDING_PARTNER: "warning" };
const St = ({ s }) => <Chip size="small" label={s} color={COLOR[s] || "default"} />;

function AdvertisedPrefixes() {
  const notify = useNotify();
  const act = (name, verb, reload) => async () => { try { await api.prefixAction(name, verb); notify.success(`Prefix ${verb === "announce" ? "announced" : "withdrawn"}`); reload(); } catch (e) { notify.error?.(e.message); } };
  return (
    <ListPage title="Bring your own IP" capId="gcp.networking.byoip" sectionTitle="Public advertised prefixes" resourceName="public advertised prefixes"
      load={api.listPublicAdvertisedPrefixes} rowKey={(p) => p.name} deleteTitle={(s) => `Delete ${s.length} prefix(es)?`} deleteFn={(p) => api.deletePublicAdvertisedPrefix(p.name)}
      emptyText="No public advertised prefixes. Add a prefix you own to advertise it through Google."
      extraActions={({ sel, data, reload }) => {
        const p = sel.length === 1 ? data.find((x) => x.name === sel[0]) : null;
        return <>
          <Button disabled={!p || p.status === "ANNOUNCED_TO_INTERNET"} onClick={act(sel[0], "announce", reload)}>Announce</Button>
          <Button disabled={!p || p.status !== "ANNOUNCED_TO_INTERNET"} onClick={act(sel[0], "withdraw", reload)}>Withdraw</Button>
        </>;
      }}
      create={{ label: "Add prefix", fields: [
        { key: "name", label: "Name", required: true },
        { key: "cidr", label: "IP range (CIDR)", default: "203.0.113.0/24", required: true },
        { key: "dns", label: "DNS verification IP (inside the range)", default: "203.0.113.5" },
        { key: "scope", label: "Delegated prefix scope", options: [["REGIONAL_PDP", "Regional"], ["GLOBAL_PDP", "Global"]], default: "REGIONAL_PDP" },
        { key: "desc", label: "Description" },
      ], submit: (v) => api.insertPublicAdvertisedPrefix({ name: v.name, ipCidrRange: v.cidr, dnsVerificationIp: v.dns, pdpScope: v.scope, description: v.desc }), done: (v) => `Added prefix "${v.name}"` }}
      columns={[
        { id: "n", header: "Name", sortField: "name", cell: (p) => p.name },
        { id: "r", header: "IP range", cell: (p) => p.ipCidrRange },
        { id: "s", header: "Status", cell: (p) => <St s={p.status} /> },
        { id: "sc", header: "Scope", cell: (p) => p.pdpScope },
        { id: "d", header: "Delegated prefixes", cell: (p) => (p.publicDelegatedPrefixs || []).length },
        { id: "sec", header: "Verification secret", cell: (p) => p.sharedSecret },
        { id: "c", header: "Created", cell: (p) => fmtDate(p.creationTimestamp) },
      ]} />
  );
}

function DelegatedPrefixes() {
  const notify = useNotify();
  const project = useProject();
  const { data: parents = [] } = useAsync(api.listPublicAdvertisedPrefixes, [project]);
  const act = (r, name, verb, reload) => async () => { try { await api.delegatedAction(r, name, verb); notify.success(`Prefix ${verb === "announce" ? "announced" : "withdrawn"}`); reload(); } catch (e) { notify.error?.(e.message); } };
  return (
    <ListPage title="Bring your own IP" capId="gcp.networking.byoip" sectionTitle="Public delegated prefixes" resourceName="public delegated prefixes"
      load={api.listPublicDelegatedPrefixes} rowKey={(p) => `${p._region}/${p.name}`} deleteTitle={(s) => `Delete ${s.length} delegated prefix(es)?`}
      deleteFn={(p) => api.deletePublicDelegatedPrefix(p._region, p.name)} emptyText="No delegated prefixes."
      extraActions={({ sel, data, reload }) => {
        const p = sel.length === 1 ? data.find((x) => `${x._region}/${x.name}` === sel[0]) : null;
        return <>
          <Button disabled={!p || p.status === "ANNOUNCED"} onClick={act(p?._region, p?.name, "announce", reload)}>Announce</Button>
          <Button disabled={!p || p.status !== "ANNOUNCED"} onClick={act(p?._region, p?.name, "withdraw", reload)}>Withdraw</Button>
        </>;
      }}
      create={{ label: "Create delegated prefix", fields: [
        { key: "name", label: "Name", required: true },
        { key: "region", label: "Region", options: REGION_OPTS, default: "us-central1" },
        { key: "parent", label: "Parent advertised prefix", options: parents.map((p) => [p.name, `${p.name} (${p.ipCidrRange})`]), default: parents[0]?.name || "" },
        { key: "cidr", label: "IP range (CIDR, inside the parent)", default: "203.0.113.0/25" },
      ], submit: (v) => api.insertPublicDelegatedPrefix(v.region, { name: v.name, parentPrefix: `projects/${project}/global/publicAdvertisedPrefixes/${v.parent}`, ipCidrRange: v.cidr }),
      done: (v) => `Created delegated prefix "${v.name}"` }}
      columns={[
        { id: "n", header: "Name", sortField: "name", cell: (p) => p.name },
        { id: "reg", header: "Region", cell: (p) => p._region },
        { id: "p", header: "Parent", cell: (p) => nm(p.parentPrefix) },
        { id: "r", header: "IP range", cell: (p) => p.ipCidrRange },
        { id: "s", header: "Status", cell: (p) => <St s={p.status} /> },
        { id: "m", header: "Mode", cell: (p) => p.mode },
      ]} />
  );
}

export function Byoip() {
  const [tab, setTab] = useState("advertised");
  return (
    <>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 1 }} aria-label="BYOIP tabs">
        <Tab value="advertised" label="Advertised prefixes" />
        <Tab value="delegated" label="Delegated prefixes" />
      </Tabs>
      {tab === "advertised" ? <AdvertisedPrefixes /> : <DelegatedPrefixes />}
    </>
  );
}

export function VlanAttachments({ title = "VPC connectivity" }) {
  const notify = useNotify();
  const project = useProject();
  const { data: ics = [] } = useAsync(api.listInterconnects, [project]);
  const [region, setRegion] = useState("us-central1");
  const { data: routers = [] } = useAsync(() => api.listRoutersIn(region), [project, region]);
  return (
    <ListPage title={title} capId="gcp.networking.hybrid-connectivity" sectionTitle="VLAN attachments" resourceName="VLAN attachments" load={api.listVlanAttachments}
      rowKey={(a) => `${a._region}/${a.name}`} deleteTitle={(s) => `Delete ${s.length} VLAN attachment(s)?`} deleteFn={(a) => api.deleteVlanAttachment(a._region, a.name)}
      emptyText="No VLAN attachments."
      extraActions={({ sel, data, reload }) => {
        const a = sel.length === 1 ? data.find((x) => `${x._region}/${x.name}` === sel[0]) : null;
        return <Button disabled={!a} onClick={async () => { try { await api.patchVlanAttachment(a._region, a.name, { adminEnabled: !a.adminEnabled }); notify.success(a.adminEnabled ? "Attachment disabled" : "Attachment enabled"); reload(); } catch (e) { notify.error?.(e.message); } }}>
          {a?.adminEnabled === false ? "Enable" : "Disable"}</Button>;
      }}
      create={{ label: "Create VLAN attachment", fields: [
        { key: "name", label: "Name", required: true },
        { key: "region", label: "Region", options: REGION_OPTS, default: "us-central1" },
        { key: "type", label: "Type", options: [["DEDICATED", "Dedicated Interconnect"], ["PARTNER", "Partner Interconnect"]], default: "DEDICATED" },
        { key: "ic", label: "Interconnect", options: ics.map((i) => [i.name, i.name]), default: ics[0]?.name || "", show: (v) => v.type === "DEDICATED" },
        { key: "router", label: "Cloud Router name (same region)", default: routers[0]?.name || "" },
        { key: "bw", label: "Bandwidth", options: ["BPS_50M", "BPS_100M", "BPS_500M", "BPS_1G", "BPS_2G", "BPS_5G", "BPS_10G"].map((b) => [b, b.replace("BPS_", "")]), default: "BPS_1G", show: (v) => v.type === "DEDICATED" },
        { key: "vlan", label: "VLAN ID (blank = auto)", type: "number", show: (v) => v.type === "DEDICATED" },
      ], submit: (v) => { setRegion(v.region); return api.insertVlanAttachment(v.region, {
        name: v.name, type: v.type, router: `projects/${project}/regions/${v.region}/routers/${v.router}`,
        ...(v.type === "DEDICATED" ? { interconnect: `projects/${project}/global/interconnects/${v.ic}`, bandwidth: v.bw, ...(v.vlan ? { vlanTag8021q: Number(v.vlan) } : {}) } : { edgeAvailabilityDomain: "AVAILABILITY_DOMAIN_1" }) }); },
      done: (v) => `Created VLAN attachment "${v.name}"` }}
      columns={[
        { id: "n", header: "Name", sortField: "name", cell: (a) => a.name },
        { id: "t", header: "Type", cell: (a) => a.type },
        { id: "s", header: "Status", cell: (a) => <St s={a.state} /> },
        { id: "reg", header: "Region", cell: (a) => a._region },
        { id: "ic", header: "Interconnect", cell: (a) => nm(a.interconnect) || "—" },
        { id: "v", header: "VLAN ID", cell: (a) => a.vlanTag8021q ?? "—" },
        { id: "bw", header: "Bandwidth", cell: (a) => (a.bandwidth || "—").replace("BPS_", "") },
        { id: "r", header: "Cloud Router", cell: (a) => nm(a.router) },
        { id: "ip", header: "Cloud router BGP IP", cell: (a) => a.cloudRouterIpAddress },
        { id: "pk", header: "Pairing key", cell: (a) => a.pairingKey || "—" },
      ]} />
  );
}

export function Interconnects() {
  const notify = useNotify();
  const project = useProject();
  const { data: locs = [] } = useAsync(api.listInterconnectLocations, [project]);
  return (
    <ListPage title="VPC connectivity" capId="gcp.networking.hybrid-connectivity" sectionTitle="Interconnects" resourceName="Interconnects" load={api.listInterconnects}
      rowKey={(i) => i.name} deleteTitle={(s) => `Delete ${s.length} interconnect(s)?`} deleteFn={(i) => api.deleteInterconnect(i.name)} emptyText="No Interconnects."
      extraActions={({ sel, data, reload }) => {
        const i = sel.length === 1 ? data.find((x) => x.name === sel[0]) : null;
        return <Button disabled={!i} onClick={async () => { try { await api.patchInterconnect(i.name, { adminEnabled: !i.adminEnabled }); notify.success(i.adminEnabled ? "Interconnect disabled" : "Interconnect enabled"); reload(); } catch (e) { notify.error?.(e.message); } }}>
          {i?.adminEnabled === false ? "Enable" : "Disable"}</Button>;
      }}
      create={{ label: "Order Interconnect", fields: [
        { key: "name", label: "Name", required: true },
        { key: "type", label: "Type", options: [["DEDICATED", "Dedicated"], ["PARTNER", "Partner"]], default: "DEDICATED" },
        { key: "loc", label: "Colocation facility", options: locs.map((l) => [l.name, `${l.name} - ${l.city}`]), default: locs[0]?.name || "" },
        { key: "link", label: "Port type", options: [["LINK_TYPE_ETHERNET_10G_LR", "10 Gbps"], ["LINK_TYPE_ETHERNET_100G_LR", "100 Gbps"]], default: "LINK_TYPE_ETHERNET_10G_LR" },
        { key: "n", label: "Number of links", type: "number", default: 1 },
        { key: "cust", label: "Customer name", default: "Vyomi Demo" },
        { key: "noc", label: "NOC contact email", default: "noc@example.com" },
        { key: "en", label: "Admin state", options: [["true", "Enabled"], ["false", "Disabled"]], default: "true" },
      ], submit: (v) => api.insertInterconnect({ name: v.name, interconnectType: v.type, linkType: v.link, requestedLinkCount: Number(v.n), customerName: v.cust,
        nocContactEmail: v.noc, adminEnabled: v.en === "true", location: `projects/${project}/global/interconnectLocations/${v.loc}` }), done: (v) => `Ordered Interconnect "${v.name}"` }}
      columns={[
        { id: "n", header: "Name", sortField: "name", cell: (i) => i.name },
        { id: "t", header: "Type", cell: (i) => i.interconnectType },
        { id: "s", header: "Status", cell: (i) => <St s={i.state} /> },
        { id: "l", header: "Location", cell: (i) => nm(i.location) },
        { id: "lk", header: "Links (provisioned / requested)", cell: (i) => `${i.provisionedLinkCount} / ${i.requestedLinkCount}` },
        { id: "a", header: "Attachments", cell: (i) => (i.interconnectAttachments || []).length },
        { id: "c", header: "Created", cell: (i) => fmtDate(i.creationTimestamp) },
      ]} />
  );
}

export function VpcConnectivity() {
  const [tab, setTab] = useState("vlan");
  return (
    <>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 1 }} aria-label="VPC connectivity tabs">
        <Tab value="vlan" label="VLAN attachments" />
        <Tab value="ic" label="Interconnects" />
      </Tabs>
      {tab === "vlan" ? <VlanAttachments /> : <Interconnects />}
    </>
  );
}

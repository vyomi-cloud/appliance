/* Create a storage account: Basics, Advanced, Networking, Data protection, Encryption, Tags,
 * Review + create → one native ARM PUT. */
import { useState } from "react";
import { Button, Checkbox, Input, Link, Radio, RadioGroup, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, InfoBar, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const NAME_RE = /^[a-z0-9]{3,24}$/;
const RG_RE = /^[-\w._()]{1,90}$/;
const ENFORCEMENT = "Saved on the storage account resource (ARM) and returned to your SDKs and the az CLI. The Vyomi Blob data plane does not enforce these settings.";

export default function CreateStorageAccount() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listStorageAccounts(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus", performance: "Standard", premiumKind: "BlockBlobStorage",
    redundancy: "GRS", readAccess: true,
    secureTransfer: true, allowBlobPublicAccess: false, allowSharedKeyAccess: true, defaultToOAuth: false, minimumTls: "TLS1_2", copyScope: "any",
    hns: false, accessTier: "Hot",
    networkAccess: "all", routing: "MicrosoftRouting",
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const rg = newRg ?? f.resourceGroup;
  const redOpts = api.REDUNDANCY[f.performance];
  const geo = f.performance === "Standard" && (f.redundancy === "GRS" || f.redundancy === "GZRS");

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Storage account name must be between 3 and 24 characters in length and use numbers and lower-case letters only.");
    else if ((existing.data || []).some((a) => a.name === f.name)) e.push(`The storage account named ${f.name} is already taken.`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Storage account name") || m.startsWith("The storage account"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription in which to create the new storage account. Choose a new or existing resource group to organize and manage your storage account together with other resources.">
        <FormRow label="Subscription" required htmlFor="sa-sub">
          <Select id="sa-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="sa-rg">
          {newRg === null ? (
            <>
              <Select id="sa-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="sa-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Storage account name" required htmlFor="sa-name">
          <Input id="sa-name" value={f.name} onChange={set("name")} aria-label="Storage account name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="sa-region">
          <Select id="sa-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>({id.includes("us") ? "US" : id.includes("europe") || id === "uksouth" ? "Europe" : "Asia Pacific"}) {l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Performance" required>
          <RadioGroup value={f.performance} onChange={(_, d) => setF((x) => ({ ...x, performance: d.value, redundancy: d.value === "Premium" ? "LRS" : x.redundancy }))} aria-label="Performance">
            <Radio value="Standard" label="Standard: Recommended for most scenarios (general-purpose v2 account)" />
            <Radio value="Premium" label="Premium: Recommended for scenarios that require low latency." />
          </RadioGroup>
        </FormRow>
        {f.performance === "Premium" && (
          <FormRow label="Premium account type" required htmlFor="sa-pk">
            <Select id="sa-pk" value={f.premiumKind} onChange={set("premiumKind")} aria-label="Premium account type">
              {api.PREMIUM_KINDS.map(([k, l]) => <option key={l} value={k}>{l}</option>)}
            </Select>
          </FormRow>
        )}
        <FormRow label="Redundancy" required htmlFor="sa-red">
          <Select id="sa-red" value={f.redundancy} onChange={set("redundancy")} aria-label="Redundancy">
            {redOpts.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Select>
          {geo && <Checkbox checked={f.readAccess} onChange={chk("readAccess")} label="Make read access to data available in the event of regional unavailability." />}
        </FormRow>
        <InfoBar>Vyomi records the SKU on the account; data is stored once, locally — replication is not simulated.</InfoBar>
      </FormSection>
    </>
  );

  const advanced = (
    <>
      <InfoBar>{ENFORCEMENT}</InfoBar>
      <FormSection title="Security" description="Configure security settings that impact your storage account.">
        <FormRow label="Require secure transfer for REST API operations"><Checkbox checked={f.secureTransfer} onChange={chk("secureTransfer")} aria-label="Require secure transfer for REST API operations" /></FormRow>
        <FormRow label="Allow enabling anonymous access on individual containers"><Checkbox checked={f.allowBlobPublicAccess} onChange={chk("allowBlobPublicAccess")} aria-label="Allow enabling anonymous access on individual containers" /></FormRow>
        <FormRow label="Enable storage account key access"><Checkbox checked={f.allowSharedKeyAccess} onChange={chk("allowSharedKeyAccess")} aria-label="Enable storage account key access" /></FormRow>
        <FormRow label="Default to Microsoft Entra authorization in the Azure portal"><Checkbox checked={f.defaultToOAuth} onChange={chk("defaultToOAuth")} aria-label="Default to Microsoft Entra authorization in the Azure portal" /></FormRow>
        <FormRow label="Minimum TLS version" htmlFor="sa-tls">
          <Select id="sa-tls" value={f.minimumTls} onChange={set("minimumTls")} aria-label="Minimum TLS version">
            <option value="TLS1_0">Version 1.0</option><option value="TLS1_1">Version 1.1</option><option value="TLS1_2">Version 1.2</option>
          </Select>
        </FormRow>
        <FormRow label="Permitted scope for copy operations (preview)" htmlFor="sa-copy">
          <Select id="sa-copy" value={f.copyScope} onChange={set("copyScope")} aria-label="Permitted scope for copy operations">
            <option value="any">From any storage account</option>
            <option value="AAD">From storage accounts in the same Microsoft Entra tenant</option>
            <option value="PrivateLink">From storage accounts that have a private endpoint to the same virtual network</option>
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Hierarchical Namespace" description="Hierarchical namespace, complemented by Data Lake Storage Gen2 endpoint, enables file and directory semantics.">
        <FormRow label="Enable hierarchical namespace"><Checkbox checked={f.hns} onChange={chk("hns")} aria-label="Enable hierarchical namespace" /></FormRow>
      </FormSection>
      <NotSimulatedContainer title="Access protocols" feature="SFTP and network file system (NFS v3) access" />
      {f.performance === "Standard" && (
        <FormSection title="Blob storage">
          <FormRow label="Access tier">
            <RadioGroup value={f.accessTier} onChange={set("accessTier")} aria-label="Access tier">
              <Radio value="Hot" label="Hot: Optimized for frequently accessed data and everyday usage scenarios" />
              <Radio value="Cool" label="Cool: Optimized for infrequently accessed data and backup scenarios" />
              <Radio value="Cold" label="Cold: Optimized for rarely accessed data and backup scenarios" />
            </RadioGroup>
          </FormRow>
        </FormSection>
      )}
      <NotSimulatedContainer title="Azure Files" feature="Azure Files (large file shares)" />
    </>
  );

  const networking = (
    <>
      <InfoBar>{ENFORCEMENT}</InfoBar>
      <FormSection title="Network connectivity" description="You can connect to your storage account either publicly, via public IP addresses or service endpoints, or privately, using a private endpoint.">
        <FormRow label="Network access" required>
          <RadioGroup value={f.networkAccess} onChange={set("networkAccess")} aria-label="Network access">
            <Radio value="all" label="Enable public access from all networks" />
            <Radio value="selected" label="Enable public access from selected virtual networks and IP addresses" />
            <Radio value="disabled" label="Disable public access and use private access" />
          </RadioGroup>
        </FormRow>
      </FormSection>
      {f.networkAccess === "selected" && <NotSimulatedContainer title="Virtual networks" feature="Virtual network and IP address rules for storage accounts" />}
      <NotSimulatedContainer title="Private endpoint" feature="Private endpoints for storage accounts" />
      <FormSection title="Network routing" description="Determine how to route your traffic as it travels from the source to its Azure endpoint.">
        <FormRow label="Routing preference">
          <RadioGroup value={f.routing} onChange={set("routing")} aria-label="Routing preference">
            <Radio value="MicrosoftRouting" label="Microsoft network routing" />
            <Radio value="InternetRouting" label="Internet routing" />
          </RadioGroup>
        </FormRow>
      </FormSection>
    </>
  );

  const dataProtection = (
    <>
      <NotSimulatedContainer title="Recovery" feature="Point-in-time restore and soft delete for blobs, containers and file shares"
        note="Deleted blobs and containers are removed immediately in Vyomi." />
      <NotSimulatedContainer title="Tracking" feature="Blob versioning and the blob change feed" />
      <NotSimulatedContainer title="Access control" feature="Version-level immutability support" />
    </>
  );

  const encryption = (
    <>
      <FormSection title="Encryption type">
        <FormRow label="Encryption type">
          <RadioGroup value="mmk" aria-label="Encryption type">
            <Radio value="mmk" label="Microsoft-managed keys (MMK)" />
          </RadioGroup>
        </FormRow>
      </FormSection>
      <NotSimulatedContainer title="Customer-managed keys (CMK)" feature="Customer-managed keys for storage encryption" />
      <NotSimulatedContainer title="Infrastructure encryption" feature="Infrastructure (double) encryption" />
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Storage account" />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body(), p = b.properties;
    const yes = (v) => (v ? "Enabled" : "Disabled");
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Location", locationLabel(f.location)], ["Storage account name", f.name || "--"],
          ["Deployment model", "Resource manager"], ["Performance", f.performance], ["Replication", api.skuLabel(b.sku.name)]])}
        <h3>Advanced</h3>
        {dl([["Secure transfer", yes(p.supportsHttpsTrafficOnly)], ["Blob anonymous access", yes(p.allowBlobPublicAccess)], ["Allow storage account key access", yes(p.allowSharedKeyAccess)],
          ["Default to Microsoft Entra authorization in the Azure portal", yes(p.defaultToOAuthAuthentication)], ["Minimum TLS version", p.minimumTlsVersion.replace("TLS", "Version ").replace("_", ".")],
          ["Permitted scope for copy operations (preview)", f.copyScope === "any" ? "From any storage account" : f.copyScope], ["Enable hierarchical namespace", yes(p.isHnsEnabled)],
          ...(p.accessTier ? [["Access tier", p.accessTier]] : [])])}
        <h3>Networking</h3>
        {dl([["Network connectivity", { all: "Public endpoint (all networks)", selected: "Public endpoint (selected networks)", disabled: "Private endpoint" }[f.networkAccess]],
          ["Default routing tier", f.routing === "MicrosoftRouting" ? "Microsoft network routing" : "Internet routing"]])}
        <h3>Data protection</h3>
        {dl([["Point-in-time restore / soft delete / versioning / change feed", <span data-vyomi-not-simulated="Data protection">Not simulated in Vyomi</span>]])}
        <h3>Encryption</h3>
        {dl([["Encryption type", "Microsoft-managed keys (MMK)"]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createStorageAccount(rg, f.name, body());
      notify.success(`Deployment of storage account '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("storage", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create a storage account" closeHref="#/storage" glyph={<Glyph text="SA" color="#0b7a75" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "advanced", label: "Advanced", content: advanced },
        { id: "networking", label: "Networking", content: networking },
        { id: "dataprotection", label: "Data protection", content: dataProtection },
        { id: "encryption", label: "Encryption", content: encryption },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}

/** Name / Value / Resource tag rows; a blank row is always available at the end. */
export function TagRows({ tags, onChange, resource }) {
  const upd = (i, k, v) => {
    const xs = tags.map((t, j) => (j === i ? { ...t, [k]: v } : t));
    if (xs[xs.length - 1].name || xs[xs.length - 1].value) xs.push({ name: "", value: "" });
    onChange(xs);
  };
  return (
    <Table size="small" aria-label="Tags" style={{ maxWidth: 760 }}>
      <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell>Resource</TableHeaderCell><TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
      <TableBody>
        {tags.map((t, i) => (
          <TableRow key={i}>
            <TableCell><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label={`Tag name ${i + 1}`} /></TableCell>
            <TableCell><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label={`Tag value ${i + 1}`} /></TableCell>
            <TableCell>{resource}</TableCell>
            <TableCell>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

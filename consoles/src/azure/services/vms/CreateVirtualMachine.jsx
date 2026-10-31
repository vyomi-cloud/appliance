/* Create a virtual machine: Basics, Disks, Networking, Management, Monitoring, Advanced, Tags,
 * Review + create. One native ARM PUT for the virtual machine, plus the network interface it
 * references (and, when requested, a real Microsoft.Network/publicIPAddresses resource the NIC's
 * IP configuration points at, and/or a network security group + its inbound rule) — see api.js's
 * toVmBody/toNicBody/toPublicIpBody/toNsgBody and core/capabilities/azure/vms.json. */
import { useState } from "react";
import { Checkbox, Input, Link, Radio, RadioGroup, Select, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "./VmBlade.jsx";

const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9-]{0,13}[a-zA-Z0-9]$/;
const RG_RE = /^[-\w._()]{1,90}$/;
const PORTS = ["HTTP (80)", "HTTPS (443)", "SSH (22)", "RDP (3389)"];
const portNum = (label) => (label.match(/\((\d+)\)/) || [, "22"])[1];

export default function CreateVirtualMachine() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listVms(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "vm-cloudlearn", location: "eastus",
    availability: "Availability zone", zone: "Zone 1", securityType: "Trusted launch virtual machines",
    image: "Ubuntu Server 24.04 LTS - x64 Gen2", architecture: "x64", spot: false, size: "Standard_D2s_v5",
    authType: "SSH public key", adminUsername: "azureuser", sshKeySource: "Generate new key pair", sshKeyType: "RSA SSH Format",
    keyPairName: "vm-cloudlearn_key", password: "", confirmPassword: "",
    inboundMode: "Allow selected ports", inboundPort: "SSH (22)",
    encryptionAtHost: false, osDiskSize: "Image default (30 GiB)", osDiskType: "Premium SSD (locally-redundant storage)",
    deleteWithVm: true, keyManagement: "Platform-managed key", ultraDisk: false, dataDisks: [],
    vnet: "(new) vm-cloudlearn-vnet", subnet: "default", publicIp: "None", nicNsg: "Basic",
    deletePublicIpWithVm: false, acceleratedNetworking: false, loadBalancing: "None",
    identity: false, entraId: false, autoShutdown: false, autoShutdownTime: "19:00", autoShutdownTz: "UTC",
    backup: false, patchOrchestration: "Image Default",
    alerts: false, bootDiagnostics: "Enable with managed storage account (recommended)", osGuestDiagnostics: false, appHealth: false,
    customData: "", userData: false, hostGroup: "", capacityReservationGroup: "", proximityPlacementGroup: "",
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const checked = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const rg = newRg ?? f.resourceGroup;
  const sizes = useAsync(() => api.listSizesForLocation(f.location), [f.location]);

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Virtual machine name must be 1-15 characters, start and end with a letter or number, and may contain hyphens.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase() && v.resourceGroup.toLowerCase() === rg.toLowerCase()))
      e.push(`A virtual machine named "${f.name}" already exists in resource group "${rg}".`);
    if (!f.adminUsername) e.push("Username is required.");
    if (f.authType === "Password" && (!f.password || f.password !== f.confirmPassword)) e.push("Password and confirm password must match.");
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Virtual machine") || m.startsWith("A virtual"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription to manage deployed resources and costs. Use resource groups like folders to organize and manage all your resources.">
        <FormRow label="Subscription" required htmlFor="vm-sub"><Select id="vm-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select></FormRow>
        <FormRow label="Resource group" required htmlFor="vm-rg">
          {newRg === null ? (
            <>
              <Select id="vm-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="vm-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Virtual machine name" required htmlFor="vm-name">
          <Input id="vm-name" value={f.name} onChange={set("name")} aria-label="Virtual machine name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="vm-region">
          <Select id="vm-region" value={f.location} onChange={set("location")} aria-label="Region">{LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</Select>
        </FormRow>
        <FormRow label="Availability options" htmlFor="vm-avail">
          <Select id="vm-avail" value={f.availability} onChange={set("availability")} aria-label="Availability options">
            {["No infrastructure redundancy required", "Availability zone", "Virtual machine scale set", "Availability set"].map((o) => <option key={o}>{o}</option>)}
          </Select>
        </FormRow>
        {f.availability === "Availability zone" && (
          <>
            <FormRow label="Zone options"><RadioGroup layout="horizontal" value="Self-selected zone" aria-label="Zone options"><Radio value="Self-selected zone" label="Self-selected zone" /><Radio value="Azure-selected zone (Preview)" label="Azure-selected zone (Preview)" /></RadioGroup></FormRow>
            <FormRow label="Availability zone" htmlFor="vm-zone"><Select id="vm-zone" value={f.zone} onChange={set("zone")} aria-label="Availability zone">{["Zone 1", "Zone 2", "Zone 3"].map((o) => <option key={o}>{o}</option>)}</Select></FormRow>
          </>
        )}
        <FormRow label="Security type" htmlFor="vm-sectype">
          <Select id="vm-sectype" value={f.securityType} onChange={set("securityType")} aria-label="Security type">{["Standard", "Trusted launch virtual machines", "Confidential virtual machines"].map((o) => <option key={o}>{o}</option>)}</Select>
        </FormRow>
        <FormRow label="Image" required htmlFor="vm-image">
          <Select id="vm-image" value={f.image} onChange={set("image")} aria-label="Image"><option>Ubuntu Server 24.04 LTS - x64 Gen2</option><option>Windows Server 2022 Datacenter</option><option>Debian 12</option></Select>
        </FormRow>
        <FormRow label="VM architecture"><RadioGroup layout="horizontal" value={f.architecture} onChange={set("architecture")} aria-label="VM architecture"><Radio value="Arm64" label="Arm64" /><Radio value="x64" label="x64" /></RadioGroup></FormRow>
        <FormRow label="Run with Azure Spot discount"><Checkbox checked={f.spot} onChange={checked("spot")} aria-label="Run with Azure Spot discount" /></FormRow>
        <FormRow label="Size" required htmlFor="vm-size">
          <Select id="vm-size" value={f.size} onChange={set("size")} aria-label="Size">{(sizes.data || []).map((s) => <option key={s.name} value={s.name}>{s.name} ({s.numberOfCores} vcpu, {s.memoryInMB / 1024} GiB memory)</option>)}</Select>
        </FormRow>
      </FormSection>
      <FormSection title="Administrator account">
        <FormRow label="Authentication type"><RadioGroup layout="horizontal" value={f.authType} onChange={set("authType")} aria-label="Authentication type"><Radio value="SSH public key" label="SSH public key" /><Radio value="Password" label="Password" /></RadioGroup></FormRow>
        <FormRow label="Username" required htmlFor="vm-user"><Input id="vm-user" value={f.adminUsername} onChange={set("adminUsername")} aria-label="Username" /></FormRow>
        {f.authType === "SSH public key" ? (
          <>
            <FormRow label="SSH public key source" htmlFor="vm-sshsrc"><Select id="vm-sshsrc" value={f.sshKeySource} onChange={set("sshKeySource")} aria-label="SSH public key source">{["Generate new key pair", "Use existing key stored in Azure", "Use existing public key"].map((o) => <option key={o}>{o}</option>)}</Select></FormRow>
            {f.sshKeySource === "Generate new key pair" && (
              <>
                <FormRow label="SSH Key Type"><RadioGroup layout="horizontal" value={f.sshKeyType} onChange={set("sshKeyType")} aria-label="SSH Key Type"><Radio value="RSA SSH Format" label="RSA SSH Format" /><Radio value="Ed25519 SSH Format" label="Ed25519 SSH Format" /></RadioGroup></FormRow>
                <FormRow label="Key pair name" required htmlFor="vm-keypair"><Input id="vm-keypair" value={f.keyPairName} onChange={set("keyPairName")} aria-label="Key pair name" /></FormRow>
              </>
            )}
          </>
        ) : (
          <>
            <FormRow label="Password" required htmlFor="vm-pw"><Input id="vm-pw" type="password" value={f.password} onChange={set("password")} aria-label="Password" /></FormRow>
            <FormRow label="Confirm password" required htmlFor="vm-pw2"><Input id="vm-pw2" type="password" value={f.confirmPassword} onChange={set("confirmPassword")} aria-label="Confirm password" /></FormRow>
          </>
        )}
      </FormSection>
      <FormSection title="Inbound port rules">
        <FormRow label="Public inbound ports"><RadioGroup layout="horizontal" value={f.inboundMode} onChange={set("inboundMode")} aria-label="Public inbound ports"><Radio value="None" label="None" /><Radio value="Allow selected ports" label="Allow selected ports" /></RadioGroup></FormRow>
        {f.inboundMode === "Allow selected ports" && (
          <FormRow label="Select inbound ports" htmlFor="vm-ports"><Select id="vm-ports" value={f.inboundPort} onChange={set("inboundPort")} aria-label="Select inbound ports">{PORTS.map((o) => <option key={o}>{o}</option>)}</Select></FormRow>
        )}
      </FormSection>
    </>
  );

  const disks = (
    <>
      <FormSection title="VM disk encryption"><FormRow label="Encryption at host"><Checkbox checked={f.encryptionAtHost} onChange={checked("encryptionAtHost")} aria-label="Encryption at host" /></FormRow></FormSection>
      <FormSection title="OS disk">
        <FormRow label="OS disk size" htmlFor="vm-osdisksize"><Select id="vm-osdisksize" value={f.osDiskSize} onChange={set("osDiskSize")} aria-label="OS disk size"><option>Image default (30 GiB)</option><option>64 GiB</option><option>128 GiB</option></Select></FormRow>
        <FormRow label="OS disk type" htmlFor="vm-osdisktype">
          <Select id="vm-osdisktype" value={f.osDiskType} onChange={set("osDiskType")} aria-label="OS disk type">
            {["Premium SSD (locally-redundant storage)", "Standard SSD (locally-redundant storage)", "Standard HDD (locally-redundant storage)", "Premium SSD (zone-redundant storage)", "Standard SSD (zone-redundant storage)"].map((o) => <option key={o}>{o}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Delete with VM"><Checkbox checked={f.deleteWithVm} onChange={checked("deleteWithVm")} aria-label="Delete with VM" /></FormRow>
        <FormRow label="Key management" htmlFor="vm-km"><Select id="vm-km" value={f.keyManagement} onChange={set("keyManagement")} aria-label="Key management">{["Platform-managed key", "Customer-managed key", "Platform-managed and customer-managed keys"].map((o) => <option key={o}>{o}</option>)}</Select></FormRow>
        <FormRow label="Enable Ultra Disk compatibility"><Checkbox checked={f.ultraDisk} onChange={checked("ultraDisk")} aria-label="Enable Ultra Disk compatibility" /></FormRow>
      </FormSection>
      <FormSection title={`Data disks for ${f.name}`}>
        <FormRow label="Data disks">
          <DataDiskTable disks={f.dataDisks} onChange={(ds) => setF((x) => ({ ...x, dataDisks: ds }))} />
        </FormRow>
      </FormSection>
    </>
  );

  const networking = (
    <>
      <FormSection title="Network interface">
        <FormRow label="Virtual network" required htmlFor="vm-vnet"><Input id="vm-vnet" value={f.vnet} onChange={set("vnet")} aria-label="Virtual network" /></FormRow>
        <FormRow label="Subnet" required htmlFor="vm-subnet"><Input id="vm-subnet" value={f.subnet} onChange={set("subnet")} aria-label="Subnet" /></FormRow>
        <FormRow label="Public IP" htmlFor="vm-pip"><Select id="vm-pip" value={f.publicIp} onChange={set("publicIp")} aria-label="Public IP"><option>None</option><option>{`(new) ${f.name}-ip`}</option></Select></FormRow>
        <FormRow label="NIC network security group"><RadioGroup layout="horizontal" value={f.nicNsg} onChange={set("nicNsg")} aria-label="NIC network security group"><Radio value="None" label="None" /><Radio value="Basic" label="Basic" /><Radio value="Advanced" label="Advanced" /></RadioGroup></FormRow>
        <FormRow label="Delete public IP and NIC when VM is deleted"><Checkbox checked={f.deletePublicIpWithVm} onChange={checked("deletePublicIpWithVm")} aria-label="Delete public IP and NIC when VM is deleted" /></FormRow>
        <FormRow label="Enable accelerated networking"><Checkbox checked={f.acceleratedNetworking} onChange={checked("acceleratedNetworking")} aria-label="Enable accelerated networking" /></FormRow>
      </FormSection>
      <FormSection title="Load balancing">
        <FormRow label="Load balancing options"><RadioGroup layout="horizontal" value={f.loadBalancing} onChange={set("loadBalancing")} aria-label="Load balancing options"><Radio value="None" label="None" /><Radio value="Azure load balancer" label="Azure load balancer" /><Radio value="Application gateway" label="Application gateway" /></RadioGroup></FormRow>
      </FormSection>
    </>
  );

  const management = (
    <>
      <FormSection title="Microsoft Defender for Cloud"><p style={{ fontSize: 13 }}>Your subscription is protected by Microsoft Defender for Cloud basic plan.</p></FormSection>
      <FormSection title="Identity"><FormRow label="Enable system assigned managed identity"><Checkbox checked={f.identity} onChange={checked("identity")} aria-label="Enable system assigned managed identity" /></FormRow></FormSection>
      <FormSection title="Microsoft Entra ID"><FormRow label="Login with Microsoft Entra ID"><Checkbox checked={f.entraId} onChange={checked("entraId")} aria-label="Login with Microsoft Entra ID" /></FormRow></FormSection>
      <FormSection title="Auto-shutdown"><FormRow label="Enable auto-shutdown"><Checkbox checked={f.autoShutdown} onChange={checked("autoShutdown")} aria-label="Enable auto-shutdown" /></FormRow></FormSection>
      <FormSection title="Backup"><FormRow label="Enable backup"><Checkbox checked={f.backup} onChange={checked("backup")} aria-label="Enable backup" /></FormRow></FormSection>
      <FormSection title="Guest OS updates"><FormRow label="Patch orchestration options" htmlFor="vm-patch"><Select id="vm-patch" value={f.patchOrchestration} onChange={set("patchOrchestration")} aria-label="Patch orchestration options">{["Azure orchestrated", "Image Default", "Manual updates"].map((o) => <option key={o}>{o}</option>)}</Select></FormRow></FormSection>
    </>
  );

  const monitoring = (
    <>
      <FormSection title="Alerts"><FormRow label="Enable recommended alert rules"><Checkbox checked={f.alerts} onChange={checked("alerts")} aria-label="Enable recommended alert rules" /></FormRow></FormSection>
      <FormSection title="Diagnostics">
        <FormRow label="Boot diagnostics"><RadioGroup value={f.bootDiagnostics} onChange={set("bootDiagnostics")} aria-label="Boot diagnostics">
          {["Enable with managed storage account (recommended)", "Enable with custom storage account", "Disable"].map((o) => <Radio key={o} value={o} label={o} />)}
        </RadioGroup></FormRow>
        <FormRow label="Enable OS guest diagnostics"><Checkbox checked={f.osGuestDiagnostics} onChange={checked("osGuestDiagnostics")} aria-label="Enable OS guest diagnostics" /></FormRow>
      </FormSection>
      <FormSection title="Health"><FormRow label="Enable application health monitoring"><Checkbox checked={f.appHealth} onChange={checked("appHealth")} aria-label="Enable application health monitoring" /></FormRow></FormSection>
    </>
  );

  const advanced = (
    <>
      <FormSection title="Extensions"><FormRow label="Extensions"><p className="vy-muted" style={{ fontSize: 13 }}>No extensions configured. <Link as="button" onClick={() => {}}>Select an extension to install</Link></p></FormRow></FormSection>
      <FormSection title="VM applications"><FormRow label="VM applications"><p className="vy-muted" style={{ fontSize: 13 }}>No VM applications configured. <Link as="button" onClick={() => {}}>Select a VM application to install</Link></p></FormRow></FormSection>
      <FormSection title="Custom data and cloud init"><FormRow label="Custom data"><Textarea value={f.customData} onChange={set("customData")} aria-label="Custom data" style={{ width: "100%", minHeight: 80 }} /></FormRow></FormSection>
      <FormSection title="User data"><FormRow label="Enable user data"><Checkbox checked={f.userData} onChange={checked("userData")} aria-label="Enable user data" /></FormRow></FormSection>
      <FormSection title="Host"><FormRow label="Host group" htmlFor="vm-host"><Select id="vm-host" value={f.hostGroup} onChange={set("hostGroup")} aria-label="Host group"><option value="">None</option></Select></FormRow></FormSection>
      <FormSection title="Capacity reservations"><FormRow label="Capacity reservation group" htmlFor="vm-capres"><Select id="vm-capres" value={f.capacityReservationGroup} onChange={set("capacityReservationGroup")} aria-label="Capacity reservation group"><option value="">None</option></Select></FormRow></FormSection>
      <FormSection title="Proximity placement group"><FormRow label="Proximity placement group" htmlFor="vm-ppg"><Select id="vm-ppg" value={f.proximityPlacementGroup} onChange={set("proximityPlacementGroup")} aria-label="Proximity placement group"><option value="">None</option></Select></FormRow></FormSection>
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Virtual machine" />
    </>
  );

  const review = () => {
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource group", rg || "--"], ["Virtual machine name", f.name], ["Region", locationLabel(f.location)], ["Image", f.image], ["Size", f.size], ["Username", f.adminUsername], ["Authentication type", f.authType]])}
        <h3>Networking</h3>
        {dl([["Virtual network", f.vnet], ["Subnet", f.subnet], ["Public IP", f.publicIp], ["NIC network security group", f.nicNsg]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      const ff = { ...f, resourceGroup: rg };
      const nicName = api.nicNameFor(f.name);
      const nicBody = api.toNicBody(ff);
      if (f.publicIp !== "None") {
        await api.putPublicIp(rg, api.publicIpNameFor(f.name), api.toPublicIpBody(ff));
      }
      if (f.nicNsg !== "None") {
        const nsgName = api.nsgNameFor(f.name);
        await api.putNsg(rg, nsgName, api.toNsgBody(f));
        if (f.inboundMode === "Allow selected ports") {
          await api.putSecurityRule(rg, nsgName, `Allow-${portNum(f.inboundPort)}`, {
            properties: { priority: 300, direction: "Inbound", access: "Allow", protocol: "Tcp", sourceAddressPrefix: "*", sourcePortRange: "*", destinationAddressPrefix: "*", destinationPortRange: portNum(f.inboundPort) },
          });
        }
        nicBody.properties.networkSecurityGroup = { id: `/subscriptions/${sub.id}/resourceGroups/${rg}/providers/Microsoft.Network/networkSecurityGroups/${nsgName}` };
      }
      await api.putNic(rg, nicName, nicBody);
      await api.createVm(rg, f.name, api.toVmBody(ff));
      notify.success(`Deployment of virtual machine '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("vms", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create a virtual machine" closeHref="#/vms" glyph={<Glyph id="vms" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "disks", label: "Disks", content: disks },
        { id: "networking", label: "Networking", content: networking },
        { id: "management", label: "Management", content: management },
        { id: "monitoring", label: "Monitoring", content: monitoring },
        { id: "advanced", label: "Advanced", content: advanced },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}

function DataDiskTable({ disks, onChange }) {
  const add = () => onChange([...disks, { lun: disks.length, name: `disk-${disks.length + 1}`, sizeGiB: 128, type: "Premium SSD LRS", caching: "None", deleteWithVm: true }]);
  const remove = (lun) => onChange(disks.filter((d) => d.lun !== lun));
  return (
    <div>
      <table className="vy-grid" style={{ marginBottom: 8 }}>
        <thead><tr><th>LUN</th><th>Name</th><th>Size (GiB)</th><th>Disk type</th><th>Host caching</th><th>Delete with VM</th><th /></tr></thead>
        <tbody>
          {disks.length ? disks.map((d) => (
            <tr key={d.lun}><td>{d.lun}</td><td>{d.name}</td><td>{d.sizeGiB}</td><td>{d.type}</td><td>{d.caching}</td><td>{d.deleteWithVm ? "Yes" : "No"}</td>
              <td><Link as="button" onClick={() => remove(d.lun)}>Remove</Link></td></tr>
          )) : <tr><td colSpan={7} className="vy-muted">No data disks attached.</td></tr>}
        </tbody>
      </table>
      <Link as="button" onClick={add}>Create and attach a new disk</Link>{" · "}
      <Link as="button" onClick={add}>Attach an existing disk</Link>
    </div>
  );
}

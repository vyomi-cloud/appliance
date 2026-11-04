/* Create an Azure Cosmos DB account: the API picker, then (NoSQL only — the other APIs are
 * an honest gap) the Basics / Global Distribution / Networking / Backup Policy / Encryption /
 * Tags / Review + create wizard → one native ARM PUT. */
import { useState } from "react";
import { Button, Checkbox, Input, Link, Radio, RadioGroup, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const NAME_RE = /^[a-z0-9-]{3,44}$/;
const APIS = [
  "Azure Cosmos DB for NoSQL", "Azure Cosmos DB for PostgreSQL", "Azure Cosmos DB for MongoDB",
  "Azure Cosmos DB for Apache Cassandra", "Azure Cosmos DB for Table", "Azure Cosmos DB for Apache Gremlin",
];

function TagRows({ tags, onChange }) {
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
            <TableCell>Azure Cosmos DB account</TableCell>
            <TableCell>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** The API picker: "Which API best suits your workload?" — only NoSQL is built. */
function ApiPicker({ onSelect }) {
  const [api_, setApi] = useState(APIS[0]);
  const [gap, setGap] = useState(null);
  return (
    <>
      <TitleRow title="Create an Azure Cosmos DB account" closeHref="#/cosmos" glyph={<Glyph id="cosmos" />} />
      <div className="vy-page">
        <FormSection title="Which API best suits your workload?" description="Azure Cosmos DB offers multiple database APIs. Pick the one that matches your application's data model.">
          <FormRow label="API" required>
            <RadioGroup value={api_} onChange={(_, d) => setApi(d.value)} aria-label="API">
              {APIS.map((a) => <Radio key={a} value={a} label={a} />)}
            </RadioGroup>
          </FormRow>
        </FormSection>
        {gap && <NotSimulatedContainer title={gap} feature={`${gap} support`} note="Only the NoSQL (Core) API has a Vyomi data plane; pick Azure Cosmos DB for NoSQL to continue." />}
        <div style={{ marginTop: 16 }}>
          <Button appearance="primary" onClick={() => (api_ === APIS[0] ? onSelect() : setGap(api_))}>Create</Button>
        </div>
      </div>
    </>
  );
}

export default function CreateCosmosAccount() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listAccounts(), [sub.id]);
  const [picked, setPicked] = useState(false);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    workloadType: "Development/Testing", resourceGroup: DEFAULT_RG, name: "", availabilityZones: "Disable", location: "eastus",
    capacityMode: "Provisioned throughput", freeTier: "Do Not Apply", limitThroughput: true,
    geoRedundancy: "Disable", multiRegionWrites: "Disable", gdAvailabilityZones: "Disable",
    connectivity: "All networks", minimumTls: "TLS 1.2",
    backupPolicy: "Periodic", backupInterval: 240, backupRetention: 8, backupRedundancy: "Geo-redundant backup storage",
    dataEncryption: "Service-managed key",
    tags: [{ name: "", value: "" }],
  });
  const rg = newRg ?? f.resourceGroup ?? DEFAULT_RG;
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));

  if (!picked) return <ApiPicker onSelect={() => setPicked(true)} />;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    if (!NAME_RE.test(f.name)) e.push("Account name must be between 3 and 44 characters in length and use numbers, lower-case letters and hyphens only.");
    else if ((existing.data || []).some((a) => a.name === f.name)) e.push(`Account name '${f.name}' is already in use.`);
    return e;
  };

  const basics = (
    <>
      <FormSection title="Workload Type">
        <FormRow label="Workload Type" required>
          <RadioGroup value={f.workloadType} onChange={set("workloadType")} aria-label="Workload Type">
            <Radio value="Learning" label="Learning" />
            <Radio value="Development/Testing" label="Development/Testing" />
            <Radio value="Production" label="Production" />
          </RadioGroup>
        </FormRow>
      </FormSection>
      <FormSection title="Project Details">
        <FormRow label="Subscription" required htmlFor="cosmos-sub">
          <Select id="cosmos-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource Group" required htmlFor="cosmos-rg">
          {newRg === null ? (
            <>
              <Select id="cosmos-rg" value={rg} onChange={set("resourceGroup")} aria-label="Resource Group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="cosmos-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance Details">
        <FormRow label="Account Name" required htmlFor="cosmos-name">
          <Input id="cosmos-name" value={f.name} onChange={set("name")} aria-label="Account Name" style={{ width: "100%" }} />
          <div style={{ fontSize: 12, marginTop: 4 }} className="vy-muted">.documents.azure.com; 3-44 lowercase letters, numbers, hyphens</div>
        </FormRow>
        <FormRow label="Availability Zones" required>
          <RadioGroup layout="horizontal" value={f.availabilityZones} onChange={set("availabilityZones")} aria-label="Availability Zones">
            <Radio value="Enable" label="Enable" /><Radio value="Disable" label="Disable" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Location" required htmlFor="cosmos-location">
          <Select id="cosmos-location" value={f.location} onChange={set("location")} aria-label="Location">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Capacity mode" required>
          <RadioGroup value={f.capacityMode} onChange={set("capacityMode")} aria-label="Capacity mode">
            <Radio value="Provisioned throughput" label="Provisioned throughput" />
            <Radio value="Serverless" label="Serverless" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Apply Free Tier Discount" required>
          <RadioGroup layout="horizontal" value={f.freeTier} onChange={set("freeTier")} aria-label="Apply Free Tier Discount">
            <Radio value="Apply" label="Apply" /><Radio value="Do Not Apply" label="Do Not Apply" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Limit total account throughput">
          <Checkbox checked={f.limitThroughput} onChange={(_, d) => setF((x) => ({ ...x, limitThroughput: !!d.checked }))} label="Limit total account throughput" />
        </FormRow>
      </FormSection>
    </>
  );

  const globalDistribution = (
    <FormSection title="Global Distribution">
      <FormRow label="Geo-Redundancy" required>
        <RadioGroup layout="horizontal" value={f.geoRedundancy} onChange={set("geoRedundancy")} aria-label="Geo-Redundancy">
          <Radio value="Enable" label="Enable" /><Radio value="Disable" label="Disable" />
        </RadioGroup>
      </FormRow>
      <FormRow label="Multi-region Writes" required>
        <RadioGroup layout="horizontal" value={f.multiRegionWrites} onChange={set("multiRegionWrites")} aria-label="Multi-region Writes">
          <Radio value="Enable" label="Enable" /><Radio value="Disable" label="Disable" />
        </RadioGroup>
      </FormRow>
      <FormRow label="Availability Zones" required>
        <RadioGroup layout="horizontal" value={f.gdAvailabilityZones} onChange={set("gdAvailabilityZones")} aria-label="Availability Zones (Global Distribution)">
          <Radio value="Enable" label="Enable" /><Radio value="Disable" label="Disable" />
        </RadioGroup>
      </FormRow>
    </FormSection>
  );

  const networking = (
    <>
      <FormSection title="Network connectivity">
        <FormRow label="Connectivity method" required>
          <RadioGroup value={f.connectivity} onChange={set("connectivity")} aria-label="Connectivity method">
            <Radio value="All networks" label="All networks" />
            <Radio value="Public endpoint (selected networks)" label="Public endpoint (selected networks)" />
            <Radio value="Private endpoint" label="Private endpoint" />
          </RadioGroup>
        </FormRow>
      </FormSection>
      {f.connectivity !== "All networks" && <NotSimulatedContainer title="Network rules" feature="Virtual network / private endpoint rules for Cosmos DB" />}
      <FormSection title="Connection Security Settings">
        <FormRow label="Minimum Transport Layer Security Protocol" htmlFor="cosmos-tls">
          <Select id="cosmos-tls" value={f.minimumTls} onChange={set("minimumTls")} aria-label="Minimum Transport Layer Security Protocol">
            <option value="TLS 1.0">TLS 1.0</option><option value="TLS 1.1">TLS 1.1</option><option value="TLS 1.2">TLS 1.2</option>
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const backupPolicy = (
    <FormSection title="Backup Policy">
      <FormRow label="Backup policy" required>
        <RadioGroup value={f.backupPolicy} onChange={set("backupPolicy")} aria-label="Backup policy">
          <Radio value="Periodic" label="Periodic" />
          <Radio value="Continuous (7 days)" label="Continuous (7 days)" />
          <Radio value="Continuous (30 days)" label="Continuous (30 days)" />
        </RadioGroup>
      </FormRow>
      {f.backupPolicy === "Periodic" && (
        <>
          <FormRow label="Backup interval" htmlFor="cosmos-backup-interval">
            <Input id="cosmos-backup-interval" type="number" value={String(f.backupInterval)} onChange={set("backupInterval")} aria-label="Backup interval" /> Minutes
          </FormRow>
          <FormRow label="Backup retention" htmlFor="cosmos-backup-retention">
            <Input id="cosmos-backup-retention" type="number" value={String(f.backupRetention)} onChange={set("backupRetention")} aria-label="Backup retention" /> Hours
          </FormRow>
          <FormRow label="Copies of data retained"><span>2</span></FormRow>
        </>
      )}
      <FormRow label="Backup storage redundancy" required>
        <RadioGroup value={f.backupRedundancy} onChange={set("backupRedundancy")} aria-label="Backup storage redundancy">
          <Radio value="Geo-redundant backup storage" label="Geo-redundant backup storage" />
          <Radio value="Zone-redundant backup storage" label="Zone-redundant backup storage" />
          <Radio value="Locally-redundant backup storage" label="Locally-redundant backup storage" />
        </RadioGroup>
      </FormRow>
    </FormSection>
  );

  const encryption = (
    <FormSection title="Data Encryption">
      <FormRow label="Data Encryption" required>
        <RadioGroup value={f.dataEncryption} onChange={set("dataEncryption")} aria-label="Data Encryption">
          <Radio value="Service-managed key" label="Service-managed key" />
          <Radio value="Customer-managed key (CMK)" label="Customer-managed key (CMK)" />
        </RadioGroup>
      </FormRow>
      {f.dataEncryption !== "Service-managed key" && <NotSimulatedContainer feature="Customer-managed keys (CMK) for Cosmos DB encryption" />}
    </FormSection>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body(), p = b.properties;
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Account Name", f.name || "--"], ["Location", locationLabel(f.location)],
          ["Capacity mode", f.capacityMode], ["Apply Free Tier Discount", f.freeTier]])}
        <h3>Global Distribution</h3>
        {dl([["Geo-Redundancy", f.geoRedundancy], ["Multi-region Writes", f.multiRegionWrites]])}
        <h3>Networking</h3>
        {dl([["Connectivity method", f.connectivity], ["Minimum TLS version", f.minimumTls]])}
        <h3>Backup Policy</h3>
        {dl([["Backup policy", f.backupPolicy], ["Backup storage redundancy", f.backupRedundancy]])}
        <h3>Encryption</h3>
        {dl([["Data Encryption", f.dataEncryption]])}
        <h3>Tags</h3>
        {dl(Object.keys(p ? b.tags : {}).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createAccount(rg, f.name, body());
      notify.success(`Deployment of Azure Cosmos DB account '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("cosmos", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Azure Cosmos DB Account - Azure Cosmos DB for NoSQL" closeHref="#/cosmos" glyph={<Glyph id="cosmos" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "global-distribution", label: "Global Distribution", content: globalDistribution },
        { id: "networking", label: "Networking", content: networking },
        { id: "backup-policy", label: "Backup Policy", content: backupPolicy },
        { id: "encryption", label: "Encryption", content: encryption },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}

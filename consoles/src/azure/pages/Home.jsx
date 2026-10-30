/* Portal Home: "Azure services" tile strip and the "Resources" list (Recent / Favorite). */
import { useState } from "react";
import { Button, Tab, TabList, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Link, Tooltip } from "@fluentui/react-components";
import {
  Add24Regular, ArrowRight24Regular, Key24Regular, Cube24Regular, Grid24Regular, Board24Regular, Copy16Regular, Checkmark16Regular,
  Book24Regular, Pulse24Regular, Money24Regular, PlugConnected24Regular,
} from "@fluentui/react-icons";
import { useAsync } from "../../common/useAsync.js";
import { sdkEndpoint } from "../../common/connect.js";
import { listStorageAccounts, listKeys } from "../services/storage/api.js";
import { Glyph, NotSimulated } from "../kit/common.jsx";
import { recent } from "../kit/recent.js";
import { HOME_TILES, byId } from "../services/registry.js";

const ago = (t) => {
  const s = Math.max(1, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "a few seconds ago";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
};

function ToolLink({ icon: I, title, text, href, external }) {
  return (
    <a className="vy-tool" href={href} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
      <I style={{ color: "#0078d4", flexShrink: 0 }} />
      <span><span className="vy-tool-title">{title}</span><span className="vy-muted vy-tool-text">{text}</span></span>
    </a>
  );
}

function Code({ code, label }) {
  const [ok, setOk] = useState(false);
  return (
    <div className="vy-code">
      <pre>{code}</pre>
      <Tooltip content={ok ? "Copied" : `Copy ${label}`} relationship="label">
        <Button size="small" appearance="subtle" icon={ok ? <Checkmark16Regular /> : <Copy16Regular />} className="vy-code-copy"
          onClick={async () => { try { await navigator.clipboard.writeText(code); setOk(true); setTimeout(() => setOk(false), 1500); } catch {} }} />
      </Tooltip>
    </div>
  );
}

/** Tools → "Connect the Azure CLI or an SDK": tabbed snippets with a live connection string
 *  (first storage account's real access key from listKeys; Nano → the vyomi-tunnel relay). */
function ConnectTool() {
  const [tab, setTab] = useState("cli");
  const ep = sdkEndpoint();
  const acct = useAsync(async () => {
    const a = (await listStorageAccounts())[0];
    if (!a) return null;
    const key = (await listKeys(a.resourceGroup, a.name))[0]?.value;
    return { name: a.name, key };
  }, []);
  const name = acct.data?.name || "<storage-account>";
  const conn = `DefaultEndpointsProtocol=http;AccountName=${name};AccountKey=${acct.data?.key || "<key from Access keys>"};BlobEndpoint=${ep.url}/${name}`;
  const cli = [
    `export AZURE_STORAGE_CONNECTION_STRING="${conn}"`,
    "az storage container create -n demo",
    "az storage blob upload -c demo -f ./hello.txt -n hello.txt",
    "az storage blob list -c demo -o table",
  ].join("\n");
  const py = [
    "from azure.storage.blob import BlobServiceClient",
    "",
    `svc = BlobServiceClient.from_connection_string("${conn}")`,
    'container = svc.get_container_client("demo")',
    'container.upload_blob("hello.txt", b"hello", overwrite=True)',
    'print([b.name for b in container.list_blobs()])',
  ].join("\n");
  return (
    <div className="vy-tool-card">
      <div className="vy-tool-head"><PlugConnected24Regular style={{ color: "#0078d4" }} /><span className="vy-tool-title">Connect the Azure CLI or an SDK</span></div>
      <TabList size="small" selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Connect">
        <Tab value="cli">Azure CLI</Tab>
        <Tab value="py">Python (azure-storage-blob)</Tab>
      </TabList>
      {tab === "cli" ? <Code code={cli} label="Azure CLI commands" /> : <Code code={py} label="Python snippet" />}
      <div className="vy-muted" style={{ fontSize: 12, marginTop: 6 }}>
        {acct.data ? `Uses storage account ${name} (key from its Access keys).` : acct.loading ? "Loading your storage account…" : "Create a storage account to fill in a real connection string."}
        {ep.note ? ` ${ep.note}` : ""}
      </div>
    </div>
  );
}

export default function Home() {
  const [tab, setTab] = useState("recent");
  const rows = recent();
  return (
    <div className="vy-home">
      <h2>Azure services</h2>
      <div className="vy-tiles">
        <a className="vy-tile vy-link" href="#/allservices"><Add24Regular style={{ width: 32, height: 32 }} />Create a resource</a>
        {HOME_TILES.map((id) => byId[id]).map((s) => (
          <a key={s.id} className="vy-tile" href={`#/${s.id}`}><Glyph id={s.icon} />{s.title}</a>
        ))}
        <a className="vy-tile vy-link" href="#/allservices"><ArrowRight24Regular style={{ width: 32, height: 32 }} />More services</a>
      </div>

      <h2>Resources</h2>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Resources">
        <Tab value="recent">Recent</Tab>
        <Tab value="favorite">Favorite</Tab>
      </TabList>
      {tab === "recent" ? (
        <>
          <Table size="small" aria-label="Recent resources" style={{ marginTop: 8 }}>
            <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Last Viewed</TableHeaderCell></TableRow></TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.href}>
                  <TableCell><Link href={r.href}>{r.name}</Link></TableCell>
                  <TableCell>{r.type}</TableCell>
                  <TableCell>{ago(r.viewed)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {!rows.length && (
            <div className="vy-empty">
              <h3>No resources have been viewed recently</h3>
              <Button as="a" href="#/allresources" appearance="primary" style={{ marginTop: 8 }}>View all resources</Button>
            </div>
          )}
        </>
      ) : (
        <div style={{ marginTop: 12 }}><NotSimulated feature="Favorite resources" /></div>
      )}

      <h2>Navigate</h2>
      <div className="vy-nav-row">
        {[["Subscriptions", "#/subscriptions", Key24Regular], ["Resource groups", "#/resourcegroups", Cube24Regular],
          ["All resources", "#/allresources", Grid24Regular], ["Dashboard", "#/dashboard", Board24Regular]].map(([t, h, I]) => (
          <a key={t} className="vy-nav-item" href={h}><I style={{ color: "#0078d4" }} />{t}</a>
        ))}
      </div>

      <h2>Tools</h2>
      <div className="vy-tools">
        <ConnectTool />
        <div className="vy-tool-col">
          <ToolLink icon={Pulse24Regular} title="Azure Monitor" text="Monitor your apps and infrastructure" href="#/monitor" />
          <ToolLink icon={Money24Regular} title="Cost Management" text="Resources in Vyomi are free — cost analysis is not simulated" href="#/cost" />
          <ToolLink icon={Book24Regular} title="Vyomi documentation" text="Guides for every simulated Azure service" href="https://vyomi.cloud" external />
        </div>
      </div>
    </div>
  );
}

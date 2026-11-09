/* Web app Overview > Capabilities: a status tile per feature, derived from the live site, slot, domain and backup
 * ARM state (no separate backend). Tiles deep-link to the blade that configures the feature. */
import { Badge, Link } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

const Tile = ({ title, on, detail, href }) => (
  <div style={{ border: "1px solid var(--colorNeutralStroke2)", borderRadius: 8, padding: "12px 14px", width: 250 }} data-testid={`cap-${title}`}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
      <Link href={href}><b>{title}</b></Link>
      <Badge appearance={on ? "filled" : "outline"} color={on ? "success" : "informative"}>{on ? "Enabled" : "Not configured"}</Badge>
    </div>
    <div style={{ fontSize: 12, color: "var(--colorNeutralForeground3)", marginTop: 6 }}>{detail}</div>
  </div>
);

export default function CapabilitiesTab({ a, self }) {
  const p = a.properties || {};
  const c = p.siteConfig || {};
  const rg = a.resourceGroup;
  const st = useAsync(async () => {
    const [slots, domains, backup, logs] = await Promise.all([
      api.listSlots(rg, a.name).catch(() => []),
      api.listCustomDomains(rg, a.name).catch(() => []),
      api.getBackupConfig(rg, a.name).catch(() => null),
      api.getAppServiceLogs(rg, a.name).catch(() => null),
    ]);
    return { slots, domains, backup, logs };
  }, [a.id]);
  const d = st.data;
  const idType = a.identity?.type;
  const nDomains = d ? Math.max(d.domains.length, (p.hostNames || []).length - 1) : 0;
  const logLevel = d?.logs?.properties?.applicationLogs?.fileSystem?.level;
  const tiles = d && [
    { title: "Deployment slots", on: d.slots.length > 0, detail: `${d.slots.length} slot(s) besides production`, href: `${self}/slots` },
    { title: "Custom domains", on: nDomains > 0, detail: `${nDomains} custom domain(s)`, href: `${self}/customdomains` },
    { title: "HTTPS only", on: !!p.httpsOnly, detail: p.httpsOnly ? "HTTP requests are redirected to HTTPS" : "HTTP is allowed", href: `${self}/configuration` },
    { title: "Always on", on: !!c.alwaysOn, detail: c.alwaysOn ? "App is kept loaded" : "App may idle out", href: `${self}/configuration` },
    { title: "Health check", on: !!c.healthCheckPath, detail: c.healthCheckPath || "No probe path set", href: `${self}/healthcheck` },
    { title: "Managed identity", on: !!idType && idType !== "None", detail: idType && idType !== "None" ? idType : "No identity assigned", href: `${self}/identity` },
    { title: "Backups", on: !!d.backup?.properties?.storageAccountUrl, detail: d.backup?.properties?.storageAccountUrl ? "Backup schedule configured" : "No backup configuration", href: `${self}/backups` },
    { title: "VNet integration", on: !!p.virtualNetworkSubnetId, detail: p.virtualNetworkSubnetId ? "Integrated with a subnet" : "Not integrated", href: `${self}/networking` },
    { title: "App Service logs", on: !!logLevel && logLevel !== "Off", detail: "Application logging to the file system", href: `${self}/appservicelogs` },
  ];
  return (
    <CapabilityContainer id="azure.appservices.webapp.capabilities" title="Capabilities">
      <ErrorBar error={st.error} />
      {st.loading ? <Loading /> : tiles && <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>{tiles.map((t) => <Tile key={t.title} {...t} />)}</div>}
    </CapabilityContainer>
  );
}

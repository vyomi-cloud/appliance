/* VM blade: Azure Backup (Recovery Services vault) status and Site Recovery (Disaster recovery) for THIS VM, read from the real
 * Microsoft.RecoveryServices vaults (core/azure_backup_core.py); actions open the vault blade. */
import { Link } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { getSubscription, locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { InfoBar } from "../../kit/common.jsx";
import * as rs from "../recoveryservices/api.js";

const loadAll = async (a) => {
  const vaults = await rs.listVaults();
  const rep = [], items = [];
  for (const v of vaults) {
    for (const r of await rs.replicated(v).catch(() => [])) if ((r.properties?.providerSpecificDetails?.fabricObjectId || "").toLowerCase() === a.id.toLowerCase()) rep.push({ ...r, vault: v });
    for (const i of await rs.items(v).catch(() => [])) if ((i.properties?.sourceResourceId || "").toLowerCase() === a.id.toLowerCase()) items.push({ ...i, vault: v });
  }
  return { vaults, rep, items };
};
const vlink = (v, panel) => `#/recoveryservices/${encodeURIComponent(v.resourceGroup)}/${encodeURIComponent(v.name)}/${panel}`;

export function VmDisasterRecovery({ a }) {
  const t = useAsync(() => loadAll(a), [a.id]);
  const d = t.data || { vaults: [], rep: [], items: [] };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Disaster recovery</div>
      <InfoBar title="Site Recovery in Vyomi">Replication is configuration-based in one data plane: enabling it validates the target region and resource group, test failover and failover create a real replica VM in the target network, and cleanup/commit/re-protect move the state machine. RPO is always 0; no disk blocks are streamed.</InfoBar>
      <p style={{ fontSize: 13 }}>Enable replication, run failovers and see jobs in a Recovery Services vault: {d.vaults.length ? d.vaults.map((v) => <span key={v.id}><Link href={vlink(v, "replicated")}>{v.name}</Link>{" "}</span>) : <Link href="#/recoveryservices">create a vault</Link>}</p>
      <BrowseGrid resourceName="replicated item" rowKey={(r) => r.id} items={d.rep} loading={t.loading} error={t.error} onRefresh={t.reload} csvName="vm-replication.csv"
        columns={[{ key: "v", label: "Vault", render: (r) => <Link href={vlink(r.vault, "replicated")}>{r.vault.name}</Link>, value: (r) => r.vault.name }, { key: "h", label: "Replication health", value: (r) => r.properties?.replicationHealth },
          { key: "s", label: "Status", value: (r) => r.properties?.protectionState }, { key: "a", label: "Active location", value: (r) => r.properties?.activeLocation || "Primary" },
          { key: "t", label: "Target region", value: (r) => locationLabel(r.properties?.providerSpecificDetails?.recoveryAzureLocation) }]}
        emptyAction={d.vaults.length ? <Link href={vlink(d.vaults[0], "replicated")}>Enable replication</Link> : null} />
    </>
  );
}

/** Rendered under the VM's snapshot-based Backup panel. */
export function VmVaultBackup({ a }) {
  const t = useAsync(() => loadAll(a), [a.id]);
  const status = useAsync(() => restJson("POST", `/subscriptions/${getSubscription()}/providers/Microsoft.RecoveryServices/locations/${a.location}/backupStatus`, { query: { "api-version": "2024-04-01" }, body: { resourceId: a.id, resourceType: "VM" } }), [a.id]);
  const d = t.data || { vaults: [], items: [] };
  return (
    <div style={{ marginTop: 24 }}>
      <div className="vy-panel-title">Azure Backup (Recovery Services vault)</div>
      <p style={{ fontSize: 13 }}>Protection status: <b>{status.data?.properties?.protectionStatus || status.data?.protectionStatus || "NotProtected"}</b>. Manage vault backup, policies and restore in {d.vaults.length ? d.vaults.map((v) => <span key={v.id}><Link href={vlink(v, "items")}>{v.name}</Link>{" "}</span>) : <Link href="#/recoveryservices">a Recovery Services vault</Link>}.</p>
      <BrowseGrid resourceName="vault backup item" rowKey={(r) => r.id} items={d.items} loading={t.loading} onRefresh={t.reload} csvName="vm-vault-backup.csv"
        columns={[{ key: "v", label: "Vault", value: (r) => r.vault.name }, { key: "s", label: "Protection state", value: (r) => r.properties?.protectionState }, { key: "p", label: "Policy", value: (r) => (r.properties?.policyId || "").split("/").pop() }]}
        emptyAction={d.vaults.length ? <Link href={vlink(d.vaults[0], "items")}>Enable backup</Link> : null} />
    </div>
  );
}

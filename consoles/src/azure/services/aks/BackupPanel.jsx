/* Azure Backup for AKS: split-screen dashboard + terminal (shared layer: consoles/src/common/kube) driven entirely by native ARM
 * calls (Microsoft.DataProtection + the AKS runCommand action). Persistent-volume data is the honest gap. */
import { useMemo } from "react";
import BackupDashboard from "../../../common/kube/BackupDashboard.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { makeAdapter } from "./backupApi.js";

export default function BackupPanel({ a }) {
  const adapter = useMemo(() => {
    const ad = makeAdapter({ id: a.id, name: a.name, resourceGroup: a.resourceGroup, location: a.location, k8sVersion: a.properties?.currentKubernetesVersion || a.properties?.kubernetesVersion, createdAt: a.systemData?.createdAt });
    ad.footer = (
      <>
        <div className="vk-card" data-testid="backend-note" style={{ fontSize: 12.5 }}>
          <b>In-browser cluster (emulated k3s-flavoured control plane).</b> This cluster's Kubernetes objects live in Vyomi's in-browser store and persist across reloads. External Kubernetes
          clients such as Lens or kubectl on your machine cannot connect to it; that needs the booster, which backs a cluster with a real API server.
        </div>
        <CapabilityContainer id="azure.aks.backup" title="What a backup captures" >
          <div style={{ fontSize: 12.5 }}>User namespaces and their namespaced objects, stored as a JSON blob in the simulator's Blob store.</div>
        </CapabilityContainer>
      </>
    );
    return ad;
  }, [a.id]);
  return (
    <>
      <div className="vy-panel-title">Azure Backup for AKS</div>
      <BackupDashboard adapter={adapter} />
    </>
  );
}

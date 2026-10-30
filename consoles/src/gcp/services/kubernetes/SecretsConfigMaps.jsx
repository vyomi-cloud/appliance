/* Secrets & ConfigMaps — Kubernetes-native Secret/ConfigMap objects live in a cluster's
 * API server, which Vyomi does not run. Honest gap. */
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

export default function SecretsConfigMaps() {
  return (
    <>
      <PageHeader title="Secrets & ConfigMaps" />
      <CapabilityContainer id="gcp.kubernetes.secrets-configmaps" title="Secrets & ConfigMaps"
        description="Would list Name, Type, Namespace and Cluster." />
    </>
  );
}

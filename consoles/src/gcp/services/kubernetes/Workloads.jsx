/* Workloads — Deployments/StatefulSets/Pods/Jobs are Kubernetes-native objects that live in
 * a cluster's API server. Vyomi models the GKE control plane (clusters, node pools) but
 * runs no Kubernetes API server behind a cluster's endpoint, so this page is an honest gap. */
import { useState } from "react";
import { Button } from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/esm/CloudUpload.js";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeployDialog from "./DeployDialog.jsx";

export default function Workloads() {
  const [deploy, setDeploy] = useState(false);
  return (
    <>
      <PageHeader title="Workloads" actions={<Button startIcon={<CloudUploadIcon />} onClick={() => setDeploy(true)}>Deploy</Button>} />
      <CapabilityContainer id="gcp.kubernetes.workloads" title="Workloads"
        description="Would list Name, Status, Type, Pods, Namespace and Cluster, with a Filter box to search them." />
      <DeployDialog open={deploy} onClose={() => setDeploy(false)} />
    </>
  );
}

/* Object Browser — a generic viewer over every real Kubernetes kind Vyomi models, for one
 * cluster at a time (exactly like the real console's Object Browser), over the data plane
 * bridge (core/gcp_gke_dataplane_core.py). */
import { useEffect, useState } from "react";
import { Box, FormControl, InputLabel, MenuItem, Select, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

const KINDS = [
  ["Namespace", "Namespaces", false, api.listNamespaces],
  ["Node", "Nodes", false, api.listK8sNodes],
  ["Pod", "Pods", true, api.listPods],
  ["Deployment", "Deployments", true, api.listDeployments],
  ["StatefulSet", "StatefulSets", true, api.listStatefulSets],
  ["Job", "Jobs", true, api.listJobs],
  ["Service", "Services", true, api.listServices],
  ["Ingress", "Ingresses", true, api.listIngresses],
  ["Gateway", "Gateways", true, api.listGateways],
  ["Secret", "Secrets", true, api.listSecrets],
  ["ConfigMap", "ConfigMaps", true, api.listConfigMaps],
  ["PersistentVolumeClaim", "PersistentVolumeClaims", true, api.listPvcs],
  ["PersistentVolume", "PersistentVolumes", false, api.listPvs],
  ["StorageClass", "StorageClasses", false, api.listStorageClasses],
];

export default function ObjectBrowser() {
  const clusters = useAsync(() => api.listClusters(), []);
  const [cluster, setCluster] = useState("");
  const [kindId, setKindId] = useState("Pod");
  const [ns, setNs] = useState("");

  useEffect(() => {
    if (!cluster && clusters.data?.length) setCluster(clusters.data[0].name);
  }, [clusters.data]);

  const cl = (clusters.data || []).find((c) => c.name === cluster);
  const [, kindLabel, namespaced, listFn] = KINDS.find(([id]) => id === kindId);
  const namespaces = useAsync(() => (cl ? api.listNamespaces(cl.location, cl.name) : Promise.resolve([])), [cl?.name]);
  const list = useAsync(() => (cl ? listFn(cl.location, cl.name, namespaced ? (ns || undefined) : undefined) : Promise.resolve([])), [cl?.name, kindId, ns]);
  const data = list.data || [];

  return (
    <>
      <PageHeader title="Object Browser" />
      <Stack direction="row" spacing={2} sx={{ mb: 2.5, flexWrap: "wrap", rowGap: 1 }}>
        <FormControl sx={{ minWidth: 220 }} disabled={!(clusters.data || []).length}>
          <InputLabel id="ob-cluster-l">Cluster</InputLabel>
          <Select labelId="ob-cluster-l" label="Cluster" value={cluster} onChange={(e) => setCluster(e.target.value)} inputProps={{ "aria-label": "Cluster" }}>
            {(clusters.data || []).map((c) => <MenuItem key={`${c.location}/${c.name}`} value={c.name}>{c.name} ({c.location})</MenuItem>)}
          </Select>
        </FormControl>
        <FormControl sx={{ minWidth: 200 }}>
          <InputLabel id="ob-kind-l">Kind</InputLabel>
          <Select labelId="ob-kind-l" label="Kind" value={kindId} onChange={(e) => { setKindId(e.target.value); setNs(""); }} inputProps={{ "aria-label": "Kind" }}>
            {KINDS.map(([id, label]) => <MenuItem key={id} value={id}>{label}</MenuItem>)}
          </Select>
        </FormControl>
        {namespaced && (
          <FormControl sx={{ minWidth: 200 }}>
            <InputLabel id="ob-ns-l">Namespace</InputLabel>
            <Select labelId="ob-ns-l" label="Namespace" value={ns} onChange={(e) => setNs(e.target.value)} inputProps={{ "aria-label": "Namespace" }}>
              <MenuItem value="">All namespaces</MenuItem>
              {(namespaces.data || []).map((n) => <MenuItem key={n.metadata.name} value={n.metadata.name}>{n.metadata.name}</MenuItem>)}
            </Select>
          </FormControl>
        )}
      </Stack>
      {!(clusters.data || []).length && !clusters.loading ? (
        <Typography variant="body2" color="text.secondary">Create a cluster first — the Object Browser needs one to browse.</Typography>
      ) : (
        <Box>
          <ErrorAlert error={list.error} title={`Failed to load ${kindLabel.toLowerCase()}`} />
          <ResourceTable
            resourceName={kindLabel.toLowerCase()}
            items={data}
            rowKey={(o) => `${o.metadata.namespace || ""}/${o.metadata.name}`}
            loading={list.loading}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", sortField: "metadata.name", cell: (o) => o.metadata.name },
              { id: "kind", header: "Kind", cell: (o) => o.kind || kindId },
              ...(namespaced ? [{ id: "ns", header: "Namespace", cell: (o) => o.metadata.namespace }] : []),
              { id: "created", header: "Created", cell: (o) => o.metadata.creationTimestamp || "—" },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No {kindLabel.toLowerCase()} found.</Typography>}
          />
        </Box>
      )}
    </>
  );
}

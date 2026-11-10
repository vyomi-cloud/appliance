import com.google.api.gax.core.NoCredentialsProvider;
import com.google.api.gax.rpc.ApiException;
import com.google.api.gax.rpc.NotFoundException;
import com.google.cloud.container.v1.ClusterManagerClient;
import com.google.cloud.container.v1.ClusterManagerSettings;
import com.google.container.v1.Cluster;
import com.google.container.v1.ClusterUpdate;
import com.google.container.v1.CreateClusterRequest;
import com.google.container.v1.CreateNodePoolRequest;
import com.google.container.v1.DeleteClusterRequest;
import com.google.container.v1.DeleteNodePoolRequest;
import com.google.container.v1.GetClusterRequest;
import com.google.container.v1.GetNodePoolRequest;
import com.google.container.v1.GetOperationRequest;
import com.google.container.v1.GetServerConfigRequest;
import com.google.container.v1.ListClustersRequest;
import com.google.container.v1.ListNodePoolsRequest;
import com.google.container.v1.ListOperationsRequest;
import com.google.container.v1.NodeConfig;
import com.google.container.v1.NodePool;
import com.google.container.v1.Operation;
import com.google.container.v1.SetLabelsRequest;
import com.google.container.v1.SetNodePoolSizeRequest;
import com.google.container.v1.UpdateClusterRequest;

/**
 * Real google-cloud-container (Java, REST/httpjson transport) conformance against Vyomi's
 * Kubernetes Engine API. Endpoint comes from env ENDPOINT (default http://127.0.0.1:9000),
 * project from PROJECT. One [PASS]/[FAIL] line per check; exits non-zero on any failure.
 */
public class ContainerConformance {
  static int pass = 0, fail = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name
        + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (ok) pass++; else fail++;
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "vyomi-project");
    String region = "us-central1";
    System.out.println("== google-cloud-container (Java) against " + endpoint + " project=" + project + " ==");

    ClusterManagerSettings settings = ClusterManagerSettings.newHttpJsonBuilder()
        .setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(ClusterManagerSettings.defaultHttpJsonTransportProviderBuilder()
            .setEndpoint(endpoint).build())
        .build();
    String id = "java-gke-" + (System.currentTimeMillis() % 1000000);
    String parent = "projects/" + project + "/locations/" + region;
    String name = parent + "/clusters/" + id;

    try (ClusterManagerClient c = ClusterManagerClient.create(settings)) {
      try {
        Operation op = c.createCluster(CreateClusterRequest.newBuilder().setParent(parent)
            .setCluster(Cluster.newBuilder().setName(id).setDescription("created by the Java SDK")
                .addNodePools(NodePool.newBuilder().setName("default-pool").setInitialNodeCount(2)
                    .setConfig(NodeConfig.newBuilder().setMachineType("e2-standard-2").build()).build()).build()).build());
        check("CreateCluster -> CREATE_CLUSTER operation, DONE",
            op.getOperationType() == Operation.Type.CREATE_CLUSTER && op.getStatus() == Operation.Status.DONE, op.toString());
      } catch (Exception e) { check("CreateCluster -> CREATE_CLUSTER operation, DONE", false, e.toString()); }

      try {
        c.createCluster(CreateClusterRequest.newBuilder().setParent(parent)
            .setCluster(Cluster.newBuilder().setName(id).setInitialNodeCount(1).build()).build());
        check("CreateCluster duplicate -> ALREADY_EXISTS", false, "no error");
      } catch (com.google.api.gax.rpc.AlreadyExistsException | com.google.api.gax.rpc.AbortedException e) {
        // HTTP 409 maps to ABORTED in gax's REST transport; the body carries status ALREADY_EXISTS.
        check("CreateCluster duplicate -> ALREADY_EXISTS", true, "");
      } catch (Exception e) { check("CreateCluster duplicate -> ALREADY_EXISTS", false, e.toString()); }

      try {
        c.createCluster(CreateClusterRequest.newBuilder().setParent(parent)
            .setCluster(Cluster.newBuilder().setName("Bad_Name").setInitialNodeCount(1).build()).build());
        check("CreateCluster bad name -> INVALID_ARGUMENT", false, "no error");
      } catch (com.google.api.gax.rpc.InvalidArgumentException e) {
        check("CreateCluster bad name -> INVALID_ARGUMENT", true, "");
      } catch (Exception e) { check("CreateCluster bad name -> INVALID_ARGUMENT", false, e.toString()); }

      try {
        Cluster g = c.getCluster(GetClusterRequest.newBuilder().setName(name).build());
        check("GetCluster (RUNNING, endpoint, version, pool)", g.getStatus() == Cluster.Status.RUNNING
            && !g.getEndpoint().isEmpty() && !g.getCurrentMasterVersion().isEmpty()
            && g.getNodePoolsCount() == 1 && "e2-standard-2".equals(g.getNodePools(0).getConfig().getMachineType())
            && "created by the Java SDK".equals(g.getDescription()), g.toString());
      } catch (Exception e) { check("GetCluster (RUNNING, endpoint, version, pool)", false, e.toString()); }

      try {
        c.getCluster(GetClusterRequest.newBuilder().setName(parent + "/clusters/missing-" + id).build());
        check("GetCluster missing -> NOT_FOUND", false, "no error");
      } catch (NotFoundException e) { check("GetCluster missing -> NOT_FOUND", true, "");
      } catch (Exception e) { check("GetCluster missing -> NOT_FOUND", false, e.toString()); }

      try {
        boolean found = c.listClusters(ListClustersRequest.newBuilder().setParent(parent).build())
            .getClustersList().stream().anyMatch(x -> id.equals(x.getName()));
        check("ListClusters contains the cluster", found, "");
      } catch (Exception e) { check("ListClusters contains the cluster", false, e.toString()); }

      try {
        Operation op = c.createNodePool(CreateNodePoolRequest.newBuilder().setParent(name)
            .setNodePool(NodePool.newBuilder().setName("pool-2").setInitialNodeCount(1)
                .setConfig(NodeConfig.newBuilder().setMachineType("e2-medium").build()).build()).build());
        NodePool np = c.getNodePool(GetNodePoolRequest.newBuilder().setName(name + "/nodePools/pool-2").build());
        check("CreateNodePool + GetNodePool", op.getOperationType() == Operation.Type.CREATE_NODE_POOL
            && "pool-2".equals(np.getName()) && np.getInitialNodeCount() == 1, np.toString());
      } catch (Exception e) { check("CreateNodePool + GetNodePool", false, e.toString()); }

      try {
        c.setNodePoolSize(SetNodePoolSizeRequest.newBuilder().setName(name + "/nodePools/pool-2").setNodeCount(4).build());
        NodePool np = c.getNodePool(GetNodePoolRequest.newBuilder().setName(name + "/nodePools/pool-2").build());
        check("SetNodePoolSize persisted", np.getInitialNodeCount() == 4, np.toString());
      } catch (Exception e) { check("SetNodePoolSize persisted", false, e.toString()); }

      try {
        int n = c.listNodePools(ListNodePoolsRequest.newBuilder().setParent(name).build()).getNodePoolsCount();
        check("ListNodePools (2 pools)", n == 2, "got " + n);
      } catch (Exception e) { check("ListNodePools (2 pools)", false, e.toString()); }

      try {
        Cluster before = c.getCluster(GetClusterRequest.newBuilder().setName(name).build());
        c.setLabels(SetLabelsRequest.newBuilder().setName(name).putResourceLabels("env", "dev")
            .setLabelFingerprint(before.getLabelFingerprint()).build());
        Cluster after = c.getCluster(GetClusterRequest.newBuilder().setName(name).build());
        check("SetLabels persisted", "dev".equals(after.getResourceLabelsMap().get("env")), after.toString());
      } catch (Exception e) { check("SetLabels persisted", false, e.toString()); }

      try {
        Operation op = c.updateCluster(UpdateClusterRequest.newBuilder().setName(name)
            .setUpdate(ClusterUpdate.newBuilder().setDesiredMasterVersion("1.31").build()).build());
        Cluster after = c.getCluster(GetClusterRequest.newBuilder().setName(name).build());
        check("UpdateCluster (upgrade master)", op.getOperationType() == Operation.Type.UPGRADE_MASTER
            && after.getCurrentMasterVersion().startsWith("1.31"), after.getCurrentMasterVersion());
      } catch (Exception e) { check("UpdateCluster (upgrade master)", false, e.toString()); }

      try {
        Operation any = c.listOperations(ListOperationsRequest.newBuilder().setParent(parent).build()).getOperations(0);
        Operation got = c.getOperation(GetOperationRequest.newBuilder()
            .setName(parent + "/operations/" + any.getName()).build());
        check("ListOperations + GetOperation", got.getStatus() == Operation.Status.DONE, got.toString());
      } catch (Exception e) { check("ListOperations + GetOperation", false, e.toString()); }

      try {
        check("GetServerConfig", !c.getServerConfig(GetServerConfigRequest.newBuilder().setName(parent).build())
            .getDefaultClusterVersion().isEmpty(), "");
      } catch (Exception e) { check("GetServerConfig", false, e.toString()); }

      try {
        c.deleteNodePool(DeleteNodePoolRequest.newBuilder().setName(name + "/nodePools/pool-2").build());
        Operation op = c.deleteCluster(DeleteClusterRequest.newBuilder().setName(name).build());
        boolean gone = false;
        try { c.getCluster(GetClusterRequest.newBuilder().setName(name).build()); } catch (NotFoundException e) { gone = true; }
        check("DeleteNodePool + DeleteCluster", op.getOperationType() == Operation.Type.DELETE_CLUSTER && gone, op.toString());
      } catch (Exception e) { check("DeleteNodePool + DeleteCluster", false, e.toString()); }
    }
    System.out.println("RESULT pass=" + pass + " fail=" + fail);
    if (fail > 0) System.exit(1);
  }
}

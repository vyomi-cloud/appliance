import com.google.api.gax.core.NoCredentialsProvider;
import com.google.api.gax.rpc.AlreadyExistsException;
import com.google.api.gax.rpc.AbortedException;
import com.google.api.gax.rpc.InvalidArgumentException;
import com.google.api.gax.rpc.NotFoundException;
import com.google.cloud.redis.v1.CloudRedisClient;
import com.google.cloud.redis.v1.CloudRedisSettings;
import com.google.cloud.redis.v1.CreateInstanceRequest;
import com.google.cloud.redis.v1.DeleteInstanceRequest;
import com.google.cloud.redis.v1.FailoverInstanceRequest;
import com.google.cloud.redis.v1.GcsDestination;
import com.google.cloud.redis.v1.GcsSource;
import com.google.cloud.redis.v1.GetInstanceAuthStringRequest;
import com.google.cloud.redis.v1.GetInstanceRequest;
import com.google.cloud.redis.v1.ImportInstanceRequest;
import com.google.cloud.redis.v1.ExportInstanceRequest;
import com.google.cloud.redis.v1.InputConfig;
import com.google.cloud.redis.v1.Instance;
import com.google.cloud.redis.v1.ListInstancesRequest;
import com.google.cloud.redis.v1.OutputConfig;
import com.google.cloud.redis.v1.UpdateInstanceRequest;
import com.google.cloud.redis.v1.UpgradeInstanceRequest;
import com.google.protobuf.FieldMask;

/**
 * Real google-cloud-redis (Java, REST/httpjson transport) conformance against Vyomi's Memorystore
 * for Redis API. Endpoint comes from env ENDPOINT (default http://127.0.0.1:9000), project from
 * PROJECT. One [PASS]/[FAIL] line per check; exits non-zero on any failure.
 */
public class RedisConformance {
  static int pass = 0, fail = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name
        + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (ok) pass++; else fail++;
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "java-redis-proj");
    String region = "us-central1";
    System.out.println("== google-cloud-redis (Java) against " + endpoint + " project=" + project + " ==");

    CloudRedisSettings settings = CloudRedisSettings.newHttpJsonBuilder()
        .setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(CloudRedisSettings.defaultHttpJsonTransportProviderBuilder()
            .setEndpoint(endpoint).build())
        .build();
    String id = "java-redis-" + (System.currentTimeMillis() % 1000000);
    String parent = "projects/" + project + "/locations/" + region;
    String name = parent + "/instances/" + id;
    String haId = id + "-ha";
    String haName = parent + "/instances/" + haId;

    try (CloudRedisClient c = CloudRedisClient.create(settings)) {
      try {
        Instance i = c.createInstanceAsync(CreateInstanceRequest.newBuilder().setParent(parent).setInstanceId(id)
            .setInstance(Instance.newBuilder().setDisplayName("created by the Java SDK").setTier(Instance.Tier.BASIC)
                .setMemorySizeGb(2).setRedisVersion("REDIS_7_0").putLabels("env", "dev").build()).build()).get();
        check("CreateInstance (LRO) -> Instance READY with host/port", i.getState() == Instance.State.READY
            && !i.getHost().isEmpty() && i.getPort() == 6379 && name.equals(i.getName()), i.toString());
      } catch (Exception e) { check("CreateInstance (LRO) -> Instance READY with host/port", false, e.toString()); }

      try {
        c.createInstanceAsync(CreateInstanceRequest.newBuilder().setParent(parent).setInstanceId(id)
            .setInstance(Instance.newBuilder().setTier(Instance.Tier.BASIC).setMemorySizeGb(1).build()).build()).get();
        check("CreateInstance duplicate -> ALREADY_EXISTS", false, "no error");
      } catch (Exception e) {
        // HTTP 409 maps to ABORTED in gax's REST transport; the body carries status ALREADY_EXISTS.
        Throwable t = e.getCause() != null ? e.getCause() : e;
        check("CreateInstance duplicate -> ALREADY_EXISTS", t instanceof AlreadyExistsException || t instanceof AbortedException, e.toString());
      }

      try {
        c.createInstanceAsync(CreateInstanceRequest.newBuilder().setParent(parent).setInstanceId("Bad_Id")
            .setInstance(Instance.newBuilder().setTier(Instance.Tier.BASIC).setMemorySizeGb(1).build()).build()).get();
        check("CreateInstance bad id -> INVALID_ARGUMENT", false, "no error");
      } catch (Exception e) {
        Throwable t = e.getCause() != null ? e.getCause() : e;
        check("CreateInstance bad id -> INVALID_ARGUMENT", t instanceof InvalidArgumentException, e.toString());
      }

      try {
        Instance g = c.getInstance(GetInstanceRequest.newBuilder().setName(name).build());
        check("GetInstance (READY, 2 GB, BASIC, version, labels, node)", g.getState() == Instance.State.READY
            && g.getMemorySizeGb() == 2 && g.getTier() == Instance.Tier.BASIC && "REDIS_7_0".equals(g.getRedisVersion())
            && "dev".equals(g.getLabelsMap().get("env")) && g.getNodesCount() == 1
            && "created by the Java SDK".equals(g.getDisplayName()), g.toString());
      } catch (Exception e) { check("GetInstance (READY, 2 GB, BASIC, version, labels, node)", false, e.toString()); }

      try {
        c.getInstance(GetInstanceRequest.newBuilder().setName(parent + "/instances/missing-" + id).build());
        check("GetInstance missing -> NOT_FOUND", false, "no error");
      } catch (NotFoundException e) { check("GetInstance missing -> NOT_FOUND", true, "");
      } catch (Exception e) { check("GetInstance missing -> NOT_FOUND", false, e.toString()); }

      try {
        boolean found = false;
        for (Instance x : c.listInstances(ListInstancesRequest.newBuilder().setParent(parent).build()).iterateAll())
          found = found || name.equals(x.getName());
        check("ListInstances contains the instance", found, "");
      } catch (Exception e) { check("ListInstances contains the instance", false, e.toString()); }

      try {
        Instance u = c.updateInstanceAsync(UpdateInstanceRequest.newBuilder()
            .setUpdateMask(FieldMask.newBuilder().addPaths("memory_size_gb").addPaths("labels").build())
            .setInstance(Instance.newBuilder().setName(name).setMemorySizeGb(5).putLabels("team", "core").build()).build()).get();
        Instance g = c.getInstance(GetInstanceRequest.newBuilder().setName(name).build());
        check("UpdateInstance (memory + labels) persisted", u.getMemorySizeGb() == 5 && g.getMemorySizeGb() == 5
            && "core".equals(g.getLabelsMap().get("team")), g.toString());
      } catch (Exception e) { check("UpdateInstance (memory + labels) persisted", false, e.toString()); }

      try {
        c.failoverInstanceAsync(FailoverInstanceRequest.newBuilder().setName(name)
            .setDataProtectionMode(FailoverInstanceRequest.DataProtectionMode.LIMITED_DATA_LOSS).build()).get();
        check("FailoverInstance on BASIC -> FAILED_PRECONDITION", false, "no error");
      } catch (Exception e) {
        Throwable t = e.getCause() != null ? e.getCause() : e;
        check("FailoverInstance on BASIC -> FAILED_PRECONDITION", t instanceof com.google.api.gax.rpc.FailedPreconditionException
            || t instanceof InvalidArgumentException, e.toString());
      }

      try {
        Instance ha = c.createInstanceAsync(CreateInstanceRequest.newBuilder().setParent(parent).setInstanceId(haId)
            .setInstance(Instance.newBuilder().setTier(Instance.Tier.STANDARD_HA).setMemorySizeGb(1)
                .setAuthEnabled(true).setRedisVersion("REDIS_6_X").build()).build()).get();
        check("CreateInstance STANDARD_HA (alt zone, 2 nodes, AUTH)", (region + "-b").equals(ha.getAlternativeLocationId())
            && ha.getNodesCount() == 2 && ha.getAuthEnabled(), ha.toString());
      } catch (Exception e) { check("CreateInstance STANDARD_HA (alt zone, 2 nodes, AUTH)", false, e.toString()); }

      try {
        Instance f = c.failoverInstanceAsync(FailoverInstanceRequest.newBuilder().setName(haName)
            .setDataProtectionMode(FailoverInstanceRequest.DataProtectionMode.LIMITED_DATA_LOSS).build()).get();
        check("FailoverInstance swaps the primary zone", (region + "-b").equals(f.getCurrentLocationId()), f.toString());
      } catch (Exception e) { check("FailoverInstance swaps the primary zone", false, e.toString()); }

      try {
        Instance up = c.upgradeInstanceAsync(UpgradeInstanceRequest.newBuilder().setName(haName).setRedisVersion("REDIS_7_2").build()).get();
        check("UpgradeInstance -> REDIS_7_2", "REDIS_7_2".equals(up.getRedisVersion()), up.toString());
      } catch (Exception e) { check("UpgradeInstance -> REDIS_7_2", false, e.toString()); }

      try {
        check("GetInstanceAuthString", !c.getInstanceAuthString(GetInstanceAuthStringRequest.newBuilder().setName(haName).build())
            .getAuthString().isEmpty(), "");
      } catch (Exception e) { check("GetInstanceAuthString", false, e.toString()); }
      try {
        c.getInstanceAuthString(GetInstanceAuthStringRequest.newBuilder().setName(name).build());
        check("GetInstanceAuthString without AUTH -> error", false, "no error");
      } catch (Exception e) { check("GetInstanceAuthString without AUTH -> error", e instanceof com.google.api.gax.rpc.ApiException, e.toString()); }

      try {
        c.exportInstanceAsync(ExportInstanceRequest.newBuilder().setName(name).setOutputConfig(OutputConfig.newBuilder()
            .setGcsDestination(GcsDestination.newBuilder().setUri("gs://java-redis-bkt/dump.rdb").build()).build()).build()).get();
        c.importInstanceAsync(ImportInstanceRequest.newBuilder().setName(name).setInputConfig(InputConfig.newBuilder()
            .setGcsSource(GcsSource.newBuilder().setUri("gs://java-redis-bkt/dump.rdb").build()).build()).build()).get();
        check("ExportInstance + ImportInstance (gs:// URIs)", true, "");
      } catch (Exception e) { check("ExportInstance + ImportInstance (gs:// URIs)", false, e.toString()); }

      try {
        c.deleteInstanceAsync(DeleteInstanceRequest.newBuilder().setName(haName).build()).get();
        c.deleteInstanceAsync(DeleteInstanceRequest.newBuilder().setName(name).build()).get();
        boolean gone = false;
        try { c.getInstance(GetInstanceRequest.newBuilder().setName(name).build()); } catch (NotFoundException e) { gone = true; }
        check("DeleteInstance (LRO) removes the instance", gone, "");
      } catch (Exception e) { check("DeleteInstance (LRO) removes the instance", false, e.toString()); }
    }
    System.out.println("RESULT pass=" + pass + " fail=" + fail);
    if (fail > 0) System.exit(1);
  }
}

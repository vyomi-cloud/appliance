import com.google.api.gax.core.NoCredentialsProvider;
import com.google.api.gax.rpc.ApiException;
import com.google.api.gax.rpc.StatusCode;
import com.google.cloud.tasks.v2.*;
import com.google.iam.v1.Binding;
import com.google.iam.v1.Policy;
import com.google.protobuf.ByteString;
import com.google.protobuf.Duration;
import com.google.protobuf.FieldMask;

import java.util.concurrent.Callable;

/**
 * Real google-cloud-tasks (Java, HTTP/JSON transport) conformance against Vyomi. Only the endpoint is
 * overridden. One [PASS]/[FAIL] line per check; non-zero exit on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=CloudTasksConformance
 */
public class CloudTasksConformance {
  // Tasks are really dispatched now; park these an hour out so the checks see them queued.
  static final com.google.protobuf.Timestamp FUTURE = com.google.protobuf.Timestamp.newBuilder().setSeconds(java.time.Instant.now().getEpochSecond() + 3600).build();

  static int pass = 0, fail = 0;

  static void chk(String name, boolean ok, String detail) {
    if (ok) { pass++; System.out.println("[PASS] " + name); }
    else { fail++; System.out.println("[FAIL] " + name + " :: " + detail); }
  }

  static <T> T step(String name, Callable<T> op) {
    try { T r = op.call(); chk(name, r != null, "null result"); return r; }
    catch (Throwable t) { chk(name, false, String.valueOf(t)); return null; }
  }

  // The HTTP/JSON transport maps the HTTP status (409 → ABORTED), exactly as against the real service.
  static void expect(String name, StatusCode.Code code, Runnable op) {
    try { op.run(); chk(name, false, "expected " + code); }
    catch (ApiException e) {
      StatusCode.Code got = e.getStatusCode().getCode();
      boolean ok = got == code || (code == StatusCode.Code.ALREADY_EXISTS && got == StatusCode.Code.ABORTED);
      chk(name, ok, got + ": " + e.getMessage());
    }
    catch (Throwable t) { chk(name, false, String.valueOf(t)); }
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "cloudlearn");
    System.out.println("== google-cloud-tasks (Java) against " + endpoint + " project=" + project + " ==");

    CloudTasksSettings settings = CloudTasksSettings.newHttpJsonBuilder()
        .setEndpoint(endpoint)
        .setCredentialsProvider(NoCredentialsProvider.create())
        .build();
    try (CloudTasksClient c = CloudTasksClient.create(settings)) {
      String sfx = Long.toString(System.nanoTime() % 1000000);
      String parent = "projects/" + project + "/locations/us-central1";
      String qname = parent + "/queues/java-q-" + sfx;

      Queue q = step("CreateQueue", () -> c.createQueue(CreateQueueRequest.newBuilder().setParent(parent)
          .setQueue(Queue.newBuilder().setName(qname)
              .setRateLimits(RateLimits.newBuilder().setMaxDispatchesPerSecond(40).setMaxConcurrentDispatches(8))
              .setRetryConfig(RetryConfig.newBuilder().setMaxAttempts(4)
                  .setMinBackoff(Duration.newBuilder().setSeconds(3)).setMaxBackoff(Duration.newBuilder().setSeconds(90))))
          .build()));
      if (q != null) {
        chk("CreateQueue echoes name and RUNNING state", q.getName().equals(qname) && q.getState() == Queue.State.RUNNING, q.toString());
        chk("CreateQueue keeps rate limits", q.getRateLimits().getMaxDispatchesPerSecond() == 40 && q.getRateLimits().getMaxConcurrentDispatches() == 8, q.getRateLimits().toString());
        chk("CreateQueue keeps retry config", q.getRetryConfig().getMaxAttempts() == 4 && q.getRetryConfig().getMinBackoff().getSeconds() == 3, q.getRetryConfig().toString());
      }
      expect("CreateQueue duplicate → ALREADY_EXISTS", StatusCode.Code.ALREADY_EXISTS, () ->
          c.createQueue(CreateQueueRequest.newBuilder().setParent(parent).setQueue(Queue.newBuilder().setName(qname)).build()));
      expect("CreateQueue invalid id → INVALID_ARGUMENT", StatusCode.Code.INVALID_ARGUMENT, () ->
          c.createQueue(CreateQueueRequest.newBuilder().setParent(parent).setQueue(Queue.newBuilder().setName(parent + "/queues/bad_name")).build()));

      Queue got = step("GetQueue", () -> c.getQueue(qname));
      if (got != null) chk("GetQueue returns the queue", got.getName().equals(qname), got.getName());
      expect("GetQueue missing → NOT_FOUND", StatusCode.Code.NOT_FOUND, () -> c.getQueue(parent + "/queues/missing-" + sfx));

      boolean found = false;
      for (Queue x : c.listQueues(parent).iterateAll()) if (x.getName().equals(qname)) found = true;
      chk("ListQueues lists the new queue", found, "not listed");

      Queue up = step("UpdateQueue", () -> c.updateQueue(UpdateQueueRequest.newBuilder()
          .setQueue(Queue.newBuilder().setName(qname).setRateLimits(RateLimits.newBuilder().setMaxDispatchesPerSecond(6)))
          .setUpdateMask(FieldMask.newBuilder().addPaths("rate_limits.max_dispatches_per_second")).build()));
      if (up != null) {
        chk("UpdateQueue applied the masked field", up.getRateLimits().getMaxDispatchesPerSecond() == 6, up.getRateLimits().toString());
        chk("UpdateQueue left unmasked fields", up.getRateLimits().getMaxConcurrentDispatches() == 8, up.getRateLimits().toString());
      }
      Queue paused = step("PauseQueue", () -> c.pauseQueue(qname));
      if (paused != null) chk("PauseQueue → PAUSED", paused.getState() == Queue.State.PAUSED, paused.getState().toString());
      Queue resumed = step("ResumeQueue", () -> c.resumeQueue(qname));
      if (resumed != null) chk("ResumeQueue → RUNNING", resumed.getState() == Queue.State.RUNNING, resumed.getState().toString());

      step("SetIamPolicy", () -> c.setIamPolicy(com.google.iam.v1.SetIamPolicyRequest.newBuilder().setResource(qname)
          .setPolicy(Policy.newBuilder().addBindings(Binding.newBuilder().setRole("roles/cloudtasks.enqueuer").addMembers("user:dev@example.com"))).build()));
      Policy pol = step("GetIamPolicy", () -> c.getIamPolicy(com.google.iam.v1.GetIamPolicyRequest.newBuilder().setResource(qname).build()));
      if (pol != null) chk("GetIamPolicy returns the binding", pol.getBindingsCount() == 1 && pol.getBindings(0).getRole().equals("roles/cloudtasks.enqueuer"), pol.toString());

      Task t1 = step("CreateTask", () -> c.createTask(CreateTaskRequest.newBuilder().setParent(qname).setTask(Task.newBuilder().setScheduleTime(FUTURE)
          .setHttpRequest(HttpRequest.newBuilder().setUrl("https://example.com/handler").setHttpMethod(HttpMethod.POST)
              .putHeaders("X-Test", "1").setBody(ByteString.copyFromUtf8("hello-task")))).build()));
      if (t1 != null) {
        chk("CreateTask assigns an id under the queue", t1.getName().startsWith(qname + "/tasks/"), t1.getName());
        chk("CreateTask BASIC view hides the body", t1.getHttpRequest().getBody().isEmpty(), "body leaked");
        Task full = step("GetTask FULL", () -> c.getTask(GetTaskRequest.newBuilder().setName(t1.getName()).setResponseView(Task.View.FULL).build()));
        if (full != null) {
          chk("GetTask FULL returns the body", full.getHttpRequest().getBody().toStringUtf8().equals("hello-task"), full.getHttpRequest().getBody().toStringUtf8());
          chk("GetTask returns custom headers", "1".equals(full.getHttpRequest().getHeadersMap().get("X-Test")), full.getHttpRequest().getHeadersMap().toString());
        }
      }
      String named = qname + "/tasks/named-" + sfx;
      Task nt = Task.newBuilder().setName(named).setScheduleTime(FUTURE).setHttpRequest(HttpRequest.newBuilder().setUrl("https://example.com/n")).build();
      step("CreateTask with an explicit name", () -> c.createTask(qname, nt));
      expect("CreateTask duplicate name → ALREADY_EXISTS", StatusCode.Code.ALREADY_EXISTS, () -> c.createTask(qname, nt));
      expect("CreateTask bad URL → INVALID_ARGUMENT", StatusCode.Code.INVALID_ARGUMENT, () -> c.createTask(qname,
          Task.newBuilder().setHttpRequest(HttpRequest.newBuilder().setUrl("ftp://nope")).build()));

      int n = 0;
      for (Task x : c.listTasks(qname).iterateAll()) n++;
      chk("ListTasks lists both tasks", n == 2, Integer.toString(n));

      Task ran = step("RunTask", () -> c.runTask(named));
      if (ran != null) chk("RunTask records a dispatch", ran.getDispatchCount() == 1, Integer.toString(ran.getDispatchCount()));
      expect("a completed task is removed → NOT_FOUND", StatusCode.Code.NOT_FOUND, () -> c.getTask(named));
      if (t1 != null) {
        step("DeleteTask", () -> { c.deleteTask(t1.getName()); return Boolean.TRUE; });
        expect("GetTask after delete → NOT_FOUND", StatusCode.Code.NOT_FOUND, () -> c.getTask(t1.getName()));
      }
      c.createTask(qname, Task.newBuilder().setScheduleTime(FUTURE).setHttpRequest(HttpRequest.newBuilder().setUrl("https://example.com/p")).build());
      step("PurgeQueue", () -> c.purgeQueue(qname));
      chk("PurgeQueue empties the queue", !c.listTasks(qname).iterateAll().iterator().hasNext(), "tasks remain");

      step("DeleteQueue", () -> { c.deleteQueue(qname); return Boolean.TRUE; });
      expect("GetQueue after delete → NOT_FOUND", StatusCode.Code.NOT_FOUND, () -> c.getQueue(qname));
    }
    System.out.println("\n" + pass + " passed, " + fail + " failed");
    if (fail > 0) System.exit(1);
  }
}

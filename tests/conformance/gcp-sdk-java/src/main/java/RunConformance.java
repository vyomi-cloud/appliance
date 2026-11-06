import com.google.api.gax.core.NoCredentialsProvider;
import com.google.api.gax.rpc.ApiException;
import com.google.api.gax.rpc.NotFoundException;
import com.google.cloud.run.v2.Container;
import com.google.cloud.run.v2.CreateJobRequest;
import com.google.cloud.run.v2.CreateServiceRequest;
import com.google.cloud.run.v2.DeleteJobRequest;
import com.google.cloud.run.v2.DeleteServiceRequest;
import com.google.cloud.run.v2.Execution;
import com.google.cloud.run.v2.ExecutionTemplate;
import com.google.cloud.run.v2.ExecutionsClient;
import com.google.cloud.run.v2.ExecutionsSettings;
import com.google.cloud.run.v2.GetExecutionRequest;
import com.google.cloud.run.v2.GetJobRequest;
import com.google.cloud.run.v2.GetRevisionRequest;
import com.google.cloud.run.v2.GetServiceRequest;
import com.google.cloud.run.v2.Job;
import com.google.cloud.run.v2.JobsClient;
import com.google.cloud.run.v2.JobsSettings;
import com.google.cloud.run.v2.ListExecutionsRequest;
import com.google.cloud.run.v2.ListRevisionsRequest;
import com.google.cloud.run.v2.ListServicesRequest;
import com.google.cloud.run.v2.ListTasksRequest;
import com.google.cloud.run.v2.Revision;
import com.google.cloud.run.v2.RevisionScaling;
import com.google.cloud.run.v2.RevisionTemplate;
import com.google.cloud.run.v2.RevisionsClient;
import com.google.cloud.run.v2.RevisionsSettings;
import com.google.cloud.run.v2.RunJobRequest;
import com.google.cloud.run.v2.Service;
import com.google.cloud.run.v2.ServicesClient;
import com.google.cloud.run.v2.ServicesSettings;
import com.google.cloud.run.v2.Task;
import com.google.cloud.run.v2.TaskTemplate;
import com.google.cloud.run.v2.TasksClient;
import com.google.cloud.run.v2.TasksSettings;
import com.google.cloud.run.v2.UpdateServiceRequest;
import com.google.iam.v1.Binding;
import com.google.iam.v1.GetIamPolicyRequest;
import com.google.iam.v1.Policy;
import com.google.iam.v1.SetIamPolicyRequest;
import com.google.iam.v1.TestIamPermissionsRequest;

/**
 * Real google-cloud-run (Java, REST/httpjson transport) conformance against Vyomi's Cloud Run
 * Admin API v2. Endpoint comes from env ENDPOINT (default http://127.0.0.1:9000), project from
 * PROJECT. One [PASS]/[FAIL] line per check; exits non-zero on any failure.
 */
public class RunConformance {
  static int pass = 0, fail = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name
        + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (ok) pass++; else fail++;
  }

  static int status(Exception e) {
    Throwable t = e;
    while (t != null && !(t instanceof ApiException)) t = t.getCause();
    if (t instanceof ApiException) {
      String m = String.valueOf(((ApiException) t).getStatusCode().getCode());
      switch (m) {
        case "NOT_FOUND": return 404;
        case "ALREADY_EXISTS": case "ABORTED": return 409;
        case "INVALID_ARGUMENT": case "FAILED_PRECONDITION": case "OUT_OF_RANGE": return 400;
        default: return -1;
      }
    }
    return -1;
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "java-run-proj");
    String region = "us-central1";
    System.out.println("== google-cloud-run (Java) against " + endpoint + " project=" + project + " ==");
    String parent = "projects/" + project + "/locations/" + region;
    String sid = "java-svc-" + (System.currentTimeMillis() % 1000000);
    String sname = parent + "/services/" + sid;
    String jid = "java-job-" + (System.currentTimeMillis() % 1000000);
    String jname = parent + "/jobs/" + jid;

    ServicesSettings ss = ServicesSettings.newHttpJsonBuilder().setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(ServicesSettings.defaultHttpJsonTransportProviderBuilder().setEndpoint(endpoint).build()).build();
    RevisionsSettings rs = RevisionsSettings.newHttpJsonBuilder().setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(RevisionsSettings.defaultHttpJsonTransportProviderBuilder().setEndpoint(endpoint).build()).build();
    JobsSettings js = JobsSettings.newHttpJsonBuilder().setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(JobsSettings.defaultHttpJsonTransportProviderBuilder().setEndpoint(endpoint).build()).build();
    ExecutionsSettings es = ExecutionsSettings.newHttpJsonBuilder().setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(ExecutionsSettings.defaultHttpJsonTransportProviderBuilder().setEndpoint(endpoint).build()).build();
    TasksSettings ts = TasksSettings.newHttpJsonBuilder().setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(TasksSettings.defaultHttpJsonTransportProviderBuilder().setEndpoint(endpoint).build()).build();

    try (ServicesClient sc = ServicesClient.create(ss); RevisionsClient rc = RevisionsClient.create(rs);
         JobsClient jc = JobsClient.create(js); ExecutionsClient ec = ExecutionsClient.create(es);
         TasksClient tc = TasksClient.create(ts)) {
      Service svc = null;
      try {
        svc = sc.createServiceAsync(CreateServiceRequest.newBuilder().setParent(parent).setServiceId(sid)
            .setService(Service.newBuilder().putLabels("env", "dev").setDescription("created by the Java SDK")
                .setTemplate(RevisionTemplate.newBuilder()
                    .addContainers(Container.newBuilder().setImage("us-docker.pkg.dev/cloudrun/container/hello").build())
                    .setScaling(RevisionScaling.newBuilder().setMaxInstanceCount(5).build()).build()).build()).build()).get();
        check("createService -> LRO resolves to the Service", svc.getName().equals(sname), svc.getName());
        check("Service has URI, Ready condition, generation 1, latest ready revision",
            svc.getUri().endsWith(".run.app") && svc.getTerminalCondition().getState() == com.google.cloud.run.v2.Condition.State.CONDITION_SUCCEEDED
                && svc.getGeneration() == 1 && !svc.getLatestReadyRevision().isEmpty(), svc.toString());
      } catch (Exception e) { check("createService -> LRO resolves to the Service", false, e.toString()); }

      try {
        sc.createServiceAsync(CreateServiceRequest.newBuilder().setParent(parent).setServiceId(sid)
            .setService(Service.newBuilder().setTemplate(RevisionTemplate.newBuilder()
                .addContainers(Container.newBuilder().setImage("x").build()).build()).build()).build()).get();
        check("createService duplicate -> ALREADY_EXISTS", false, "no error");
      } catch (Exception e) { check("createService duplicate -> ALREADY_EXISTS", status(e) == 409, e.toString()); }
      try {
        sc.createServiceAsync(CreateServiceRequest.newBuilder().setParent(parent).setServiceId("Bad_Name")
            .setService(Service.newBuilder().setTemplate(RevisionTemplate.newBuilder()
                .addContainers(Container.newBuilder().setImage("x").build()).build()).build()).build()).get();
        check("createService bad id -> INVALID_ARGUMENT", false, "no error");
      } catch (Exception e) { check("createService bad id -> INVALID_ARGUMENT", status(e) == 400, e.toString()); }

      try {
        Service g = sc.getService(GetServiceRequest.newBuilder().setName(sname).build());
        check("getService round-trips template and labels", g.getLabelsOrDefault("env", "").equals("dev")
            && g.getTemplate().getContainers(0).getImage().endsWith("/hello") && g.getTemplate().getScaling().getMaxInstanceCount() == 5
            && g.getTemplate().getTimeout().getSeconds() == 300, g.toString());
      } catch (Exception e) { check("getService round-trips template and labels", false, e.toString()); }
      try {
        sc.getService(GetServiceRequest.newBuilder().setName(parent + "/services/nope").build());
        check("getService missing -> NOT_FOUND", false, "no error");
      } catch (NotFoundException e) { check("getService missing -> NOT_FOUND", true, ""); }
      catch (Exception e) { check("getService missing -> NOT_FOUND", false, e.toString()); }

      try {
        boolean found = false;
        for (Service s : sc.listServices(ListServicesRequest.newBuilder().setParent(parent).build()).iterateAll()) found |= s.getName().equals(sname);
        check("listServices contains the service", found, "");
      } catch (Exception e) { check("listServices contains the service", false, e.toString()); }

      try {
        Service u = sc.updateServiceAsync(UpdateServiceRequest.newBuilder().setService(Service.newBuilder().setName(sname)
            .setTemplate(RevisionTemplate.newBuilder().addContainers(Container.newBuilder()
                .setImage("us-docker.pkg.dev/cloudrun/container/hello:v2").build()).build()).build()).build()).get();
        check("updateService (new image) -> generation 2", u.getGeneration() == 2 && u.getTemplate().getContainers(0).getImage().endsWith(":v2"), u.toString());
        svc = u;
      } catch (Exception e) { check("updateService (new image) -> generation 2", false, e.toString()); }

      try {
        java.util.List<Revision> revs = new java.util.ArrayList<>();
        for (Revision r : rc.listRevisions(ListRevisionsRequest.newBuilder().setParent(sname).build()).iterateAll()) revs.add(r);
        check("listRevisions shows both revisions", revs.size() == 2, String.valueOf(revs.size()));
        Revision r0 = rc.getRevision(GetRevisionRequest.newBuilder().setName(revs.get(0).getName()).build());
        check("getRevision", r0.getService().equals(sname), r0.toString());
        try {
          rc.deleteRevisionAsync(com.google.cloud.run.v2.DeleteRevisionRequest.newBuilder().setName(svc.getLatestReadyRevision()).build()).get();
          check("deleteRevision serving traffic -> FAILED_PRECONDITION", false, "no error");
        } catch (Exception e) { check("deleteRevision serving traffic -> FAILED_PRECONDITION", status(e) == 400, e.toString()); }
        String old = revs.get(0).getName().equals(svc.getLatestReadyRevision()) ? revs.get(1).getName() : revs.get(0).getName();
        rc.deleteRevisionAsync(com.google.cloud.run.v2.DeleteRevisionRequest.newBuilder().setName(old).build()).get();
        check("deleteRevision (old) succeeds", true, "");
      } catch (Exception e) { check("revisions", false, e.toString()); }

      try {
        Policy p = sc.getIamPolicy(GetIamPolicyRequest.newBuilder().setResource(sname).build());
        check("getIamPolicy (empty)", p.getBindingsCount() == 0, p.toString());
        p = sc.setIamPolicy(SetIamPolicyRequest.newBuilder().setResource(sname).setPolicy(Policy.newBuilder()
            .addBindings(Binding.newBuilder().setRole("roles/run.invoker").addMembers("allUsers").build()).build()).build());
        check("setIamPolicy allUsers invoker", p.getBindingsCount() == 1, p.toString());
        p = sc.getIamPolicy(GetIamPolicyRequest.newBuilder().setResource(sname).build());
        check("getIamPolicy round-trips", p.getBindings(0).getMembers(0).equals("allUsers"), p.toString());
        int n = sc.testIamPermissions(TestIamPermissionsRequest.newBuilder().setResource(sname)
            .addPermissions("run.services.get").addPermissions("bogus.perm").build()).getPermissionsCount();
        check("testIamPermissions filters unknown permissions", n == 1, String.valueOf(n));
      } catch (Exception e) { check("iam", false, e.toString()); }

      // ── jobs / executions / tasks ───────────────────────────────────────
      try {
        Job job = jc.createJobAsync(CreateJobRequest.newBuilder().setParent(parent).setJobId(jid).setJob(Job.newBuilder()
            .setTemplate(ExecutionTemplate.newBuilder().setTaskCount(2).setTemplate(TaskTemplate.newBuilder().setMaxRetries(1)
                .addContainers(Container.newBuilder().setImage("us-docker.pkg.dev/cloudrun/container/job").addArgs("--once").build()).build()).build()).build()).build()).get();
        check("createJob -> LRO resolves to the Job", job.getName().equals(jname) && job.getTemplate().getTaskCount() == 2, job.toString());
      } catch (Exception e) { check("createJob -> LRO resolves to the Job", false, e.toString()); }
      try {
        jc.createJobAsync(CreateJobRequest.newBuilder().setParent(parent).setJobId(jid).setJob(Job.newBuilder().setTemplate(
            ExecutionTemplate.newBuilder().setTemplate(TaskTemplate.newBuilder().addContainers(Container.newBuilder().setImage("x").build()).build()).build()).build()).build()).get();
        check("createJob duplicate -> ALREADY_EXISTS", false, "no error");
      } catch (Exception e) { check("createJob duplicate -> ALREADY_EXISTS", status(e) == 409, e.toString()); }
      try {
        Job g = jc.getJob(GetJobRequest.newBuilder().setName(jname).build());
        check("getJob", g.getTemplate().getTemplate().getContainers(0).getArgs(0).equals("--once"), g.toString());
        Execution ex = jc.runJobAsync(RunJobRequest.newBuilder().setName(jname).build()).get();
        check("runJob -> Execution (2 tasks succeeded)", ex.getTaskCount() == 2 && ex.getSucceededCount() == 2, ex.toString());
        Execution eg = ec.getExecution(GetExecutionRequest.newBuilder().setName(ex.getName()).build());
        check("getExecution", eg.getJob().equals(jid), eg.toString());
        int n = 0;
        for (Execution x : ec.listExecutions(ListExecutionsRequest.newBuilder().setParent(jname).build()).iterateAll()) n++;
        check("listExecutions", n == 1, String.valueOf(n));
        java.util.List<Task> tasks = new java.util.ArrayList<>();
        for (Task t : tc.listTasks(ListTasksRequest.newBuilder().setParent(ex.getName()).build()).iterateAll()) tasks.add(t);
        check("listTasks returns 2 completed tasks", tasks.size() == 2 && tasks.get(0).getLastAttemptResult().getStatus().getCode() == 0, String.valueOf(tasks.size()));
        try {
          ec.cancelExecutionAsync(com.google.cloud.run.v2.CancelExecutionRequest.newBuilder().setName(ex.getName()).build()).get();
          check("cancelExecution on a completed execution -> FAILED_PRECONDITION", false, "no error");
        } catch (Exception e) { check("cancelExecution on a completed execution -> FAILED_PRECONDITION", status(e) == 400, e.toString()); }
        ec.deleteExecutionAsync(com.google.cloud.run.v2.DeleteExecutionRequest.newBuilder().setName(ex.getName()).build()).get();
        check("deleteExecution", true, "");
      } catch (Exception e) { check("job run flow", false, e.toString()); }
      try {
        jc.deleteJobAsync(DeleteJobRequest.newBuilder().setName(jname).build()).get();
        try { jc.getJob(GetJobRequest.newBuilder().setName(jname).build()); check("deleteJob -> gone", false, "still there"); }
        catch (NotFoundException nf) { check("deleteJob -> gone", true, ""); }
      } catch (Exception e) { check("deleteJob -> gone", false, e.toString()); }

      try {
        Service d = sc.deleteServiceAsync(DeleteServiceRequest.newBuilder().setName(sname).build()).get();
        check("deleteService -> LRO resolves to the deleted Service", d.getName().equals(sname), d.toString());
        try { sc.getService(GetServiceRequest.newBuilder().setName(sname).build()); check("deleted service is gone", false, "still there"); }
        catch (NotFoundException nf) { check("deleted service is gone", true, ""); }
      } catch (Exception e) { check("deleteService", false, e.toString()); }
    }
    System.out.println("RESULT pass=" + pass + " fail=" + fail);
    if (fail > 0) System.exit(1);
  }
}

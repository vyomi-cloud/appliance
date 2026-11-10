import com.google.api.gax.core.NoCredentialsProvider;
import com.google.api.gax.rpc.AlreadyExistsException;
import com.google.api.gax.rpc.InvalidArgumentException;
import com.google.api.gax.rpc.NotFoundException;
import com.google.cloud.scheduler.v1.CloudSchedulerClient;
import com.google.cloud.scheduler.v1.CloudSchedulerSettings;
import com.google.cloud.scheduler.v1.HttpMethod;
import com.google.cloud.scheduler.v1.HttpTarget;
import com.google.cloud.scheduler.v1.Job;
import com.google.cloud.scheduler.v1.JobName;
import com.google.cloud.scheduler.v1.LocationName;
import com.google.cloud.scheduler.v1.PubsubTarget;
import com.google.protobuf.ByteString;
import com.google.protobuf.FieldMask;

import java.util.ArrayList;
import java.util.List;

/**
 * Real google-cloud-scheduler (Java, REST/httpjson transport) conformance against Vyomi's
 * Cloud Scheduler API. Endpoint comes from env ENDPOINT (default http://127.0.0.1:9000),
 * project from PROJECT. One [PASS]/[FAIL] line per check; exits non-zero on any failure.
 */
public class CloudSchedulerConformance {
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
    System.out.println("== google-cloud-scheduler (Java) against " + endpoint + " project=" + project + " ==");

    CloudSchedulerSettings settings = CloudSchedulerSettings.newHttpJsonBuilder()
        .setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(CloudSchedulerSettings.defaultHttpJsonTransportProviderBuilder()
            .setEndpoint(endpoint).build())
        .build();
    String id = "java-job-" + (System.currentTimeMillis() % 1000000);
    LocationName parent = LocationName.of(project, region);
    JobName name = JobName.of(project, region, id);

    try (CloudSchedulerClient c = CloudSchedulerClient.create(settings)) {
      try {
        Job j = c.createJob(parent, Job.newBuilder().setName(name.toString())
            .setDescription("created by the Java SDK").setSchedule("*/10 * * * *").setTimeZone("America/New_York")
            .setHttpTarget(HttpTarget.newBuilder().setUri("https://example.com/hook").setHttpMethod(HttpMethod.POST)
                .setBody(ByteString.copyFromUtf8("{\"hello\":\"world\"}")).build()).build());
        check("CreateJob (http target)", name.toString().equals(j.getName()) && j.getState() == Job.State.ENABLED
            && "America/New_York".equals(j.getTimeZone()) && j.hasScheduleTime(), j.toString());
      } catch (Exception e) { check("CreateJob (http target)", false, e.toString()); }

      try {
        c.createJob(parent, Job.newBuilder().setName(name.toString()).setSchedule("* * * * *")
            .setHttpTarget(HttpTarget.newBuilder().setUri("https://example.com/").build()).build());
        check("CreateJob duplicate -> ALREADY_EXISTS", false, "no error");
      } catch (AlreadyExistsException | com.google.api.gax.rpc.AbortedException e) {
        // HTTP 409 maps to ABORTED in gax's REST transport; the body carries status ALREADY_EXISTS.
        check("CreateJob duplicate -> ALREADY_EXISTS", true, "");
      } catch (Exception e) { check("CreateJob duplicate -> ALREADY_EXISTS", false, e.toString()); }

      try {
        c.createJob(parent, Job.newBuilder().setName(JobName.of(project, region, id + "-bad").toString())
            .setSchedule("not a cron")
            .setHttpTarget(HttpTarget.newBuilder().setUri("https://example.com/").build()).build());
        check("CreateJob bad schedule -> INVALID_ARGUMENT", false, "no error");
      } catch (InvalidArgumentException e) { check("CreateJob bad schedule -> INVALID_ARGUMENT", true, "");
      } catch (Exception e) { check("CreateJob bad schedule -> INVALID_ARGUMENT", false, e.toString()); }

      try {
        Job j = c.getJob(name);
        check("GetJob", j.getDescription().equals("created by the Java SDK")
            && j.getHttpTarget().getBody().toStringUtf8().contains("world"), j.toString());
      } catch (Exception e) { check("GetJob", false, e.toString()); }

      try {
        c.getJob(JobName.of(project, region, "missing-" + id));
        check("GetJob missing -> NOT_FOUND", false, "no error");
      } catch (NotFoundException e) { check("GetJob missing -> NOT_FOUND", true, "");
      } catch (Exception e) { check("GetJob missing -> NOT_FOUND", false, e.toString()); }

      try {
        c.createJob(parent, Job.newBuilder().setName(JobName.of(project, region, id + "-ps").toString())
            .setSchedule("0 9 * * 1-5")
            .setPubsubTarget(PubsubTarget.newBuilder().setTopicName("projects/" + project + "/topics/t1")
                .setData(ByteString.copyFromUtf8("tick")).build()).build());
        List<String> names = new ArrayList<>();
        for (Job j : c.listJobs(parent).iterateAll()) names.add(j.getName());
        check("ListJobs", names.contains(name.toString()) && names.contains(JobName.of(project, region, id + "-ps").toString()),
            names.toString());
      } catch (Exception e) { check("ListJobs", false, e.toString()); }

      try {
        Job j = c.updateJob(Job.newBuilder().setName(name.toString()).setSchedule("0 * * * *")
            .setDescription("updated").build(),
            FieldMask.newBuilder().addPaths("schedule").addPaths("description").build());
        check("UpdateJob (patch schedule+description)", "0 * * * *".equals(j.getSchedule())
            && "updated".equals(j.getDescription()) && j.getHttpTarget().getUri().equals("https://example.com/hook"), j.toString());
      } catch (Exception e) { check("UpdateJob (patch schedule+description)", false, e.toString()); }

      try {
        Job j = c.pauseJob(name);
        check("PauseJob", j.getState() == Job.State.PAUSED, j.getState().toString());
      } catch (Exception e) { check("PauseJob", false, e.toString()); }

      try {
        c.runJob(name);
        check("RunJob on paused job -> FAILED_PRECONDITION", false, "no error");
      } catch (com.google.api.gax.rpc.ApiException e) {
        // The REST (httpjson) transport maps by HTTP status only: the API's HTTP 400 FAILED_PRECONDITION
        // surfaces as INVALID_ARGUMENT/FAILED_PRECONDITION depending on the gax version.
        com.google.api.gax.rpc.StatusCode.Code code = e.getStatusCode().getCode();
        check("RunJob on paused job -> FAILED_PRECONDITION", code == com.google.api.gax.rpc.StatusCode.Code.FAILED_PRECONDITION
            || code == com.google.api.gax.rpc.StatusCode.Code.INVALID_ARGUMENT, code.toString());
      } catch (Exception e) { check("RunJob on paused job -> FAILED_PRECONDITION", false, e.toString()); }

      try {
        Job j = c.resumeJob(name);
        check("ResumeJob", j.getState() == Job.State.ENABLED && j.hasScheduleTime(), j.toString());
      } catch (Exception e) { check("ResumeJob", false, e.toString()); }

      try {
        Job j = c.runJob(name);
        check("RunJob stamps lastAttemptTime", j.hasLastAttemptTime(), j.toString());
      } catch (Exception e) { check("RunJob stamps lastAttemptTime", false, e.toString()); }

      try {
        c.deleteJob(name);
        c.deleteJob(JobName.of(project, region, id + "-ps"));
        try { c.getJob(name); check("DeleteJob", false, "still exists"); }
        catch (NotFoundException nf) { check("DeleteJob", true, ""); }
      } catch (Exception e) { check("DeleteJob", false, e.toString()); }
    }
    System.out.println("RESULT pass=" + pass + " fail=" + fail);
    System.exit(fail == 0 ? 0 : 1);
  }
}

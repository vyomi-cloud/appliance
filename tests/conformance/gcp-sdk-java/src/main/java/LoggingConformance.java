import com.google.api.client.googleapis.json.GoogleJsonResponseException;
import com.google.api.client.http.javanet.NetHttpTransport;
import com.google.api.client.json.gson.GsonFactory;
import com.google.api.services.logging.v2.Logging;
import com.google.api.services.logging.v2.model.ListLogEntriesRequest;
import com.google.api.services.logging.v2.model.ListLogEntriesResponse;
import com.google.api.services.logging.v2.model.LogBucket;
import com.google.api.services.logging.v2.model.LogEntry;
import com.google.api.services.logging.v2.model.LogExclusion;
import com.google.api.services.logging.v2.model.LogMetric;
import com.google.api.services.logging.v2.model.LogSink;
import com.google.api.services.logging.v2.model.MonitoredResource;
import com.google.api.services.logging.v2.model.WriteLogEntriesRequest;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Real google-api-services-logging (Java, Google API Client Library, REST/JSON) conformance against
 * Vyomi's Cloud Logging API. Endpoint comes from env ENDPOINT (default http://127.0.0.1:9000), project
 * from PROJECT. One [PASS]/[FAIL] line per check; exits non-zero on any failure.
 */
public class LoggingConformance {
  static int pass = 0, fail = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name
        + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (ok) pass++; else fail++;
  }

  static int code(Exception e) {
    return e instanceof GoogleJsonResponseException ? ((GoogleJsonResponseException) e).getStatusCode() : -1;
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "java-log-proj");
    System.out.println("== google-api-services-logging (Java) against " + endpoint + " project=" + project + " ==");

    Logging log = new Logging.Builder(new NetHttpTransport(), GsonFactory.getDefaultInstance(), null)
        .setRootUrl(endpoint.endsWith("/") ? endpoint : endpoint + "/").setApplicationName("vyomi-conformance").build();
    String sfx = String.valueOf(System.currentTimeMillis() % 1000000);
    String logId = "java-log-" + sfx;
    String logName = "projects/" + project + "/logs/" + logId;
    String parent = "projects/" + project;

    try {
      MonitoredResource res = new MonitoredResource().setType("gce_instance").setLabels(Map.of("zone", "us-central1-a", "instance_id", "123"));
      List<LogEntry> entries = new ArrayList<>();
      entries.add(new LogEntry().setTextPayload("hello from the Java SDK").setSeverity("INFO"));
      entries.add(new LogEntry().setJsonPayload(Map.of("user", "ada", "code", 42)).setSeverity("ERROR"));
      entries.add(new LogEntry().setTextPayload("noisy debug line").setSeverity("DEBUG").setLabels(Map.of("env", "test")));
      log.entries().write(new WriteLogEntriesRequest().setLogName(logName).setResource(res).setEntries(entries)).execute();
      check("entries.write (3 entries)", true, "");
    } catch (Exception e) { check("entries.write (3 entries)", false, e.toString()); }

    try {
      log.entries().write(new WriteLogEntriesRequest().setEntries(List.of(new LogEntry().setTextPayload("x")))).execute();
      check("entries.write without a log name → 400", false, "no error");
    } catch (Exception e) { check("entries.write without a log name → 400", code(e) == 400, e.toString()); }

    try {
      ListLogEntriesResponse r = log.entries().list(new ListLogEntriesRequest().setResourceNames(List.of(parent))
          .setFilter("logName=\"" + logName + "\"").setOrderBy("timestamp asc")).execute();
      List<LogEntry> es = r.getEntries();
      check("entries.list (all, oldest first)", es != null && es.size() == 3 && "hello from the Java SDK".equals(es.get(0).getTextPayload())
          && es.get(0).getInsertId() != null && es.get(0).getTimestamp() != null, String.valueOf(r));
    } catch (Exception e) { check("entries.list (all, oldest first)", false, e.toString()); }

    try {
      ListLogEntriesResponse r = log.entries().list(new ListLogEntriesRequest().setResourceNames(List.of(parent))
          .setFilter("logName=\"" + logName + "\" AND severity>=ERROR")).execute();
      check("entries.list severity>=ERROR", r.getEntries() != null && r.getEntries().size() == 1
          && "ERROR".equals(r.getEntries().get(0).getSeverity()) && "ada".equals(r.getEntries().get(0).getJsonPayload().get("user")), String.valueOf(r));
    } catch (Exception e) { check("entries.list severity>=ERROR", false, e.toString()); }

    try {
      ListLogEntriesResponse r = log.entries().list(new ListLogEntriesRequest().setResourceNames(List.of(parent))
          .setFilter("resource.type=\"gce_instance\" AND resource.labels.zone:\"central1\" AND labels.env=\"test\"")).execute();
      check("entries.list by resource + labels", r.getEntries() != null && r.getEntries().size() == 1, String.valueOf(r));
    } catch (Exception e) { check("entries.list by resource + labels", false, e.toString()); }

    try {
      ListLogEntriesResponse r = log.entries().list(new ListLogEntriesRequest().setResourceNames(List.of(parent))
          .setFilter("logName=\"" + logName + "\"").setOrderBy("timestamp desc").setPageSize(2)).execute();
      ListLogEntriesResponse r2 = log.entries().list(new ListLogEntriesRequest().setResourceNames(List.of(parent))
          .setFilter("logName=\"" + logName + "\"").setOrderBy("timestamp desc").setPageSize(2).setPageToken(r.getNextPageToken())).execute();
      check("entries.list pagination", r.getEntries().size() == 2 && r.getNextPageToken() != null && r2.getEntries().size() == 1, String.valueOf(r));
    } catch (Exception e) { check("entries.list pagination", false, e.toString()); }

    try {
      log.entries().list(new ListLogEntriesRequest().setResourceNames(List.of(parent)).setFilter("severity=(")).execute();
      check("entries.list with a bad filter → 400", false, "no error");
    } catch (Exception e) { check("entries.list with a bad filter → 400", code(e) == 400, e.toString()); }

    try {
      List<String> names = log.projects().logs().list(parent).execute().getLogNames();
      check("logs.list contains the log", names != null && names.contains(logName), String.valueOf(names));
    } catch (Exception e) { check("logs.list contains the log", false, e.toString()); }

    // sinks
    String sinkId = "java-sink-" + sfx;
    try {
      LogSink s = log.projects().sinks().create(parent, new LogSink().setName(sinkId)
          .setDestination("storage.googleapis.com/java-archive-" + sfx).setFilter("severity>=ERROR").setDescription("java sink"))
          .setUniqueWriterIdentity(true).execute();
      check("sinks.create", sinkId.equals(s.getName()) && s.getWriterIdentity() != null && s.getWriterIdentity().startsWith("serviceAccount:")
          && s.getCreateTime() != null, String.valueOf(s));
    } catch (Exception e) { check("sinks.create", false, e.toString()); }
    try {
      log.projects().sinks().create(parent, new LogSink().setName(sinkId).setDestination("storage.googleapis.com/x")).execute();
      check("sinks.create duplicate → 409", false, "no error");
    } catch (Exception e) { check("sinks.create duplicate → 409", code(e) == 409, e.toString()); }
    try {
      log.projects().sinks().create(parent, new LogSink().setName("bad-" + sfx).setDestination("ftp://nope")).execute();
      check("sinks.create invalid destination → 400", false, "no error");
    } catch (Exception e) { check("sinks.create invalid destination → 400", code(e) == 400, e.toString()); }
    try {
      LogSink s = log.projects().sinks().get(parent + "/sinks/" + sinkId).execute();
      check("sinks.get", "severity>=ERROR".equals(s.getFilter()) && s.getDestination().endsWith(sfx), String.valueOf(s));
    } catch (Exception e) { check("sinks.get", false, e.toString()); }
    try {
      LogSink s = log.projects().sinks().patch(parent + "/sinks/" + sinkId,
          new LogSink().setFilter("severity>=WARNING").setDisabled(true)).setUpdateMask("filter,disabled").execute();
      check("sinks.patch (update mask)", "severity>=WARNING".equals(s.getFilter()) && Boolean.TRUE.equals(s.getDisabled()), String.valueOf(s));
    } catch (Exception e) { check("sinks.patch (update mask)", false, e.toString()); }
    try {
      List<LogSink> l = log.projects().sinks().list(parent).execute().getSinks();
      check("sinks.list", l != null && l.stream().anyMatch(x -> sinkId.equals(x.getName())), String.valueOf(l));
    } catch (Exception e) { check("sinks.list", false, e.toString()); }
    try {
      log.projects().sinks().delete(parent + "/sinks/" + sinkId).execute();
      try { log.projects().sinks().get(parent + "/sinks/" + sinkId).execute(); check("sinks.delete", false, "still there"); }
      catch (Exception e) { check("sinks.delete (then get → 404)", code(e) == 404, e.toString()); }
    } catch (Exception e) { check("sinks.delete", false, e.toString()); }

    // metrics
    String metricId = "java_metric_" + sfx;
    try {
      LogMetric m = log.projects().metrics().create(parent, new LogMetric().setName(metricId).setFilter("severity>=ERROR").setDescription("errors")).execute();
      check("metrics.create", metricId.equals(m.getName()) && m.getMetricDescriptor() != null
          && ("logging.googleapis.com/user/" + metricId).equals(m.getMetricDescriptor().getType()), String.valueOf(m));
    } catch (Exception e) { check("metrics.create", false, e.toString()); }
    try {
      log.projects().metrics().create(parent, new LogMetric().setName("nofilter_" + sfx)).execute();
      check("metrics.create without a filter → 400", false, "no error");
    } catch (Exception e) { check("metrics.create without a filter → 400", code(e) == 400, e.toString()); }
    try {
      LogMetric m = log.projects().metrics().update(parent + "/metrics/" + metricId,
          new LogMetric().setName(metricId).setFilter("severity>=WARNING").setDescription("warnings")).execute();
      check("metrics.update", "severity>=WARNING".equals(m.getFilter()) && "warnings".equals(m.getDescription()), String.valueOf(m));
    } catch (Exception e) { check("metrics.update", false, e.toString()); }
    try {
      List<LogMetric> l = log.projects().metrics().list(parent).execute().getMetrics();
      check("metrics.list", l != null && l.stream().anyMatch(x -> metricId.equals(x.getName())), String.valueOf(l));
    } catch (Exception e) { check("metrics.list", false, e.toString()); }
    try {
      log.projects().metrics().delete(parent + "/metrics/" + metricId).execute();
      try { log.projects().metrics().get(parent + "/metrics/" + metricId).execute(); check("metrics.delete", false, "still there"); }
      catch (Exception e) { check("metrics.delete (then get → 404)", code(e) == 404, e.toString()); }
    } catch (Exception e) { check("metrics.delete", false, e.toString()); }

    // exclusions
    String exId = "java-excl-" + sfx;
    try {
      LogExclusion x = log.projects().exclusions().create(parent, new LogExclusion().setName(exId).setFilter("severity<WARNING").setDescription("noise")).execute();
      check("exclusions.create", exId.equals(x.getName()) && x.getCreateTime() != null, String.valueOf(x));
    } catch (Exception e) { check("exclusions.create", false, e.toString()); }
    try {
      LogExclusion x = log.projects().exclusions().patch(parent + "/exclusions/" + exId, new LogExclusion().setDisabled(true)).setUpdateMask("disabled").execute();
      check("exclusions.patch", Boolean.TRUE.equals(x.getDisabled()), String.valueOf(x));
    } catch (Exception e) { check("exclusions.patch", false, e.toString()); }
    try {
      log.projects().exclusions().delete(parent + "/exclusions/" + exId).execute();
      check("exclusions.delete", log.projects().exclusions().list(parent).execute().getExclusions() == null, "");
    } catch (Exception e) { check("exclusions.delete", false, e.toString()); }

    // buckets
    String bucketId = "java-bucket-" + sfx;
    String bp = parent + "/locations/global";
    try {
      LogBucket b = log.projects().locations().buckets().create(bp, new LogBucket().setRetentionDays(14).setDescription("java bucket")).setBucketId(bucketId).execute();
      check("buckets.create", b.getName().endsWith("/buckets/" + bucketId) && b.getRetentionDays() == 14 && "ACTIVE".equals(b.getLifecycleState()), String.valueOf(b));
    } catch (Exception e) { check("buckets.create", false, e.toString()); }
    try {
      List<LogBucket> l = log.projects().locations().buckets().list(bp).execute().getBuckets();
      check("buckets.list includes _Default and the custom bucket", l != null && l.stream().anyMatch(x -> x.getName().endsWith("/_Default"))
          && l.stream().anyMatch(x -> x.getName().endsWith("/" + bucketId)), String.valueOf(l));
    } catch (Exception e) { check("buckets.list includes _Default and the custom bucket", false, e.toString()); }
    try {
      LogBucket b = log.projects().locations().buckets().patch(bp + "/buckets/" + bucketId, new LogBucket().setRetentionDays(60)).setUpdateMask("retentionDays").execute();
      check("buckets.patch (retention)", b.getRetentionDays() == 60, String.valueOf(b));
    } catch (Exception e) { check("buckets.patch (retention)", false, e.toString()); }
    try {
      log.projects().locations().buckets().delete(bp + "/buckets/_Default").execute();
      check("buckets.delete _Default → 400", false, "no error");
    } catch (Exception e) { check("buckets.delete _Default → 400", code(e) == 400, e.toString()); }
    try {
      log.projects().locations().buckets().delete(bp + "/buckets/" + bucketId).execute();
      LogBucket b = log.projects().locations().buckets().get(bp + "/buckets/" + bucketId).execute();
      check("buckets.delete (soft: DELETE_REQUESTED)", "DELETE_REQUESTED".equals(b.getLifecycleState()), String.valueOf(b));
    } catch (Exception e) { check("buckets.delete (soft: DELETE_REQUESTED)", false, e.toString()); }

    try {
      int n = log.monitoredResourceDescriptors().list().execute().getResourceDescriptors().size();
      check("monitoredResourceDescriptors.list", n > 3, String.valueOf(n));
    } catch (Exception e) { check("monitoredResourceDescriptors.list", false, e.toString()); }

    try {
      log.projects().logs().delete(logName).execute();
      ListLogEntriesResponse r = log.entries().list(new ListLogEntriesRequest().setResourceNames(List.of(parent)).setFilter("logName=\"" + logName + "\"")).execute();
      check("logs.delete removes the entries", r.getEntries() == null || r.getEntries().isEmpty(), String.valueOf(r));
    } catch (Exception e) { check("logs.delete removes the entries", false, e.toString()); }

    System.out.println("RESULT pass=" + pass + " fail=" + fail);
    if (fail > 0) System.exit(1);
  }
}

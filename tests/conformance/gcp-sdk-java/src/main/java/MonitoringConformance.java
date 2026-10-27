import com.google.api.client.googleapis.json.GoogleJsonResponseException;
import com.google.api.client.http.javanet.NetHttpTransport;
import com.google.api.client.json.gson.GsonFactory;
import com.google.api.services.monitoring.v3.Monitoring;
import com.google.api.services.monitoring.v3.model.AlertPolicy;
import com.google.api.services.monitoring.v3.model.Aggregation;
import com.google.api.services.monitoring.v3.model.Condition;
import com.google.api.services.monitoring.v3.model.CreateTimeSeriesRequest;
import com.google.api.services.monitoring.v3.model.Documentation;
import com.google.api.services.monitoring.v3.model.Group;
import com.google.api.services.monitoring.v3.model.HttpCheck;
import com.google.api.services.monitoring.v3.model.LabelDescriptor;
import com.google.api.services.monitoring.v3.model.ListTimeSeriesResponse;
import com.google.api.services.monitoring.v3.model.Metric;
import com.google.api.services.monitoring.v3.model.MetricDescriptor;
import com.google.api.services.monitoring.v3.model.MetricThreshold;
import com.google.api.services.monitoring.v3.model.MonitoredResource;
import com.google.api.services.monitoring.v3.model.NotificationChannel;
import com.google.api.services.monitoring.v3.model.Point;
import com.google.api.services.monitoring.v3.model.TimeInterval;
import com.google.api.services.monitoring.v3.model.TimeSeries;
import com.google.api.services.monitoring.v3.model.TypedValue;
import com.google.api.services.monitoring.v3.model.UptimeCheckConfig;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Real Google API client for Cloud Monitoring v3 (Java; google-cloud-monitoring itself is gRPC-only)
 * conformance against Vyomi's Cloud Monitoring API. Endpoint comes from env ENDPOINT (default
 * http://127.0.0.1:9000), project from PROJECT. One [PASS]/[FAIL] line per check; exits non-zero
 * on any failure.
 */
public class MonitoringConformance {
  static int pass = 0, fail = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name
        + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (ok) pass++; else fail++;
  }

  static int code(Exception e) {
    return e instanceof GoogleJsonResponseException ? ((GoogleJsonResponseException) e).getStatusCode() : 0;
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "java-mon-proj");
    System.out.println("== google-api-services-monitoring (Java) against " + endpoint + " project=" + project + " ==");
    String sfx = String.valueOf(System.currentTimeMillis() % 1000000);
    String pn = "projects/" + project;
    Monitoring m = new Monitoring.Builder(new NetHttpTransport(), GsonFactory.getDefaultInstance(), null)
        .setRootUrl(endpoint.replaceAll("/+$", "") + "/").setApplicationName("vyomi-conformance").build();

    // ── notification channels ────────────────────────────────────────
    NotificationChannel ch = null;
    try {
      ch = m.projects().notificationChannels().create(pn, new NotificationChannel().setType("email")
          .setDisplayName("java-ops-" + sfx).setLabels(Map.of("email_address", "ops@example.com")).setEnabled(true)).execute();
      check("notificationChannels.create (email)", ch.getName().startsWith(pn + "/notificationChannels/")
          && "VERIFIED".equals(ch.getVerificationStatus()) && Boolean.TRUE.equals(ch.getEnabled()), ch.toString());
    } catch (Exception e) { check("notificationChannels.create (email)", false, e.toString()); }
    try {
      m.projects().notificationChannels().create(pn, new NotificationChannel().setType("email").setLabels(Map.of())).execute();
      check("notificationChannels.create missing label -> 400", false, "no error");
    } catch (Exception e) { check("notificationChannels.create missing label -> 400", code(e) == 400, e.toString()); }
    try {
      NotificationChannel g = m.projects().notificationChannels().get(ch.getName()).execute();
      check("notificationChannels.get", "ops@example.com".equals(g.getLabels().get("email_address")), g.toString());
    } catch (Exception e) { check("notificationChannels.get", false, e.toString()); }
    try {
      NotificationChannel u = m.projects().notificationChannels().patch(ch.getName(),
          new NotificationChannel().setDisplayName("java-ops-renamed-" + sfx)).setUpdateMask("display_name").execute();
      check("notificationChannels.patch (update mask)", u.getDisplayName().startsWith("java-ops-renamed")
          && "ops@example.com".equals(u.getLabels().get("email_address")), u.toString());
    } catch (Exception e) { check("notificationChannels.patch (update mask)", false, e.toString()); }
    try {
      List<String> names = new ArrayList<>();
      for (NotificationChannel c : m.projects().notificationChannels().list(pn).execute().getNotificationChannels()) names.add(c.getName());
      check("notificationChannels.list", names.contains(ch.getName()), names.toString());
    } catch (Exception e) { check("notificationChannels.list", false, e.toString()); }

    // ── alert policies ───────────────────────────────────────────────
    AlertPolicy pol = null;
    try {
      pol = m.projects().alertPolicies().create(pn, new AlertPolicy().setDisplayName("java-cpu-" + sfx)
          .setCombiner("OR").setEnabled(true).setNotificationChannels(List.of(ch.getName()))
          .setDocumentation(new Documentation().setContent("CPU is high").setMimeType("text/markdown"))
          .setUserLabels(Map.of("team", "sre"))
          .setConditions(List.of(new Condition().setDisplayName("cpu above 80%").setConditionThreshold(new MetricThreshold()
              .setFilter("metric.type=\"compute.googleapis.com/instance/cpu/utilization\" AND resource.type=\"gce_instance\"")
              .setComparison("COMPARISON_GT").setThresholdValue(0.8).setDuration("300s")
              .setAggregations(List.of(new Aggregation().setAlignmentPeriod("60s").setPerSeriesAligner("ALIGN_MEAN"))))))).execute();
      MetricThreshold t = pol.getConditions().get(0).getConditionThreshold();
      check("alertPolicies.create", pol.getName().startsWith(pn + "/alertPolicies/") && Boolean.TRUE.equals(pol.getEnabled())
          && pol.getConditions().get(0).getName().contains("/conditions/") && "COMPARISON_GT".equals(t.getComparison())
          && t.getThresholdValue() == 0.8 && "300s".equals(t.getDuration())
          && "ALIGN_MEAN".equals(t.getAggregations().get(0).getPerSeriesAligner())
          && pol.getCreationRecord() != null && pol.getNotificationChannels().size() == 1, pol.toString());
    } catch (Exception e) { check("alertPolicies.create", false, e.toString()); }
    try {
      m.projects().alertPolicies().create(pn, new AlertPolicy().setDisplayName("bad").setCombiner("OR")).execute();
      check("alertPolicies.create without conditions -> 400", false, "no error");
    } catch (Exception e) { check("alertPolicies.create without conditions -> 400", code(e) == 400, e.toString()); }
    try {
      AlertPolicy g = m.projects().alertPolicies().get(pol.getName()).execute();
      check("alertPolicies.get", g.getDisplayName().equals("java-cpu-" + sfx) && "sre".equals(g.getUserLabels().get("team"))
          && "CPU is high".equals(g.getDocumentation().getContent()), g.toString());
    } catch (Exception e) { check("alertPolicies.get", false, e.toString()); }
    try {
      AlertPolicy u = m.projects().alertPolicies().patch(pol.getName(),
          new AlertPolicy().setDisplayName("java-cpu-renamed-" + sfx).setEnabled(false)).setUpdateMask("enabled,display_name").execute();
      check("alertPolicies.patch (disable + rename)", Boolean.FALSE.equals(u.getEnabled())
          && u.getDisplayName().equals("java-cpu-renamed-" + sfx) && u.getConditions().size() == 1, u.toString());
    } catch (Exception e) { check("alertPolicies.patch (disable + rename)", false, e.toString()); }
    try {
      var l = m.projects().alertPolicies().list(pn).setFilter("display_name = \"java-cpu-renamed-" + sfx + "\"").execute();
      check("alertPolicies.list (filter)", l.getAlertPolicies() != null && l.getAlertPolicies().size() == 1, String.valueOf(l));
    } catch (Exception e) { check("alertPolicies.list (filter)", false, e.toString()); }
    try {
      m.projects().alertPolicies().get(pn + "/alertPolicies/1").execute();
      check("alertPolicies.get missing -> 404", false, "no error");
    } catch (Exception e) { check("alertPolicies.get missing -> 404", code(e) == 404, e.toString()); }
    try {
      m.projects().notificationChannels().delete(ch.getName()).execute();
      check("notificationChannels.delete in use -> 400", false, "no error");
    } catch (Exception e) { check("notificationChannels.delete in use -> 400", code(e) == 400, e.toString()); }
    try {
      m.projects().alertPolicies().delete(pol.getName()).execute();
      m.projects().notificationChannels().delete(ch.getName()).execute();
      check("alertPolicies.delete + notificationChannels.delete", true, "");
    } catch (Exception e) { check("alertPolicies.delete + notificationChannels.delete", false, e.toString()); }

    // ── metric descriptors + time series ─────────────────────────────
    String mtype = "custom.googleapis.com/java/latency_" + sfx;
    try {
      MetricDescriptor md = m.projects().metricDescriptors().create(pn, new MetricDescriptor().setType(mtype)
          .setMetricKind("GAUGE").setValueType("DOUBLE").setUnit("ms").setDescription("request latency")
          .setLabels(List.of(new LabelDescriptor().setKey("route").setValueType("STRING")))).execute();
      check("metricDescriptors.create (custom)", md.getType().equals(mtype)
          && md.getName().equals(pn + "/metricDescriptors/" + mtype) && "GAUGE".equals(md.getMetricKind()), md.toString());
    } catch (Exception e) { check("metricDescriptors.create (custom)", false, e.toString()); }
    try {
      m.projects().metricDescriptors().create(pn, new MetricDescriptor().setType("compute.googleapis.com/mine")
          .setMetricKind("GAUGE").setValueType("DOUBLE")).execute();
      check("metricDescriptors.create non-custom -> 400", false, "no error");
    } catch (Exception e) { check("metricDescriptors.create non-custom -> 400", code(e) == 400, e.toString()); }
    try {
      MetricDescriptor g = m.projects().metricDescriptors().get(pn + "/metricDescriptors/" + mtype).execute();
      check("metricDescriptors.get (id with slashes)", "ms".equals(g.getUnit()), g.toString());
    } catch (Exception e) { check("metricDescriptors.get (id with slashes)", false, e.toString()); }

    Instant now = Instant.now().truncatedTo(ChronoUnit.SECONDS);
    try {
      for (int i = 0; i < 4; i++) {
        m.projects().timeSeries().create(pn, new CreateTimeSeriesRequest().setTimeSeries(List.of(new TimeSeries()
            .setMetric(new Metric().setType(mtype).setLabels(Map.of("route", "/a")))
            .setResource(new MonitoredResource().setType("global").setLabels(Map.of("project_id", project)))
            .setPoints(List.of(new Point().setInterval(new TimeInterval().setEndTime(now.minusSeconds((5 - i) * 60L).toString()))
                .setValue(new TypedValue().setDoubleValue((i + 1) * 10.0))))))).execute();
      }
      check("timeSeries.create (4 points)", true, "");
    } catch (Exception e) { check("timeSeries.create (4 points)", false, e.toString()); }
    try {
      m.projects().timeSeries().create(pn, new CreateTimeSeriesRequest().setTimeSeries(List.of(new TimeSeries()
          .setMetric(new Metric().setType(mtype).setLabels(Map.of("route", "/a")))
          .setResource(new MonitoredResource().setType("global").setLabels(Map.of("project_id", project)))
          .setPoints(List.of(new Point().setInterval(new TimeInterval().setEndTime(now.minusSeconds(540).toString()))
              .setValue(new TypedValue().setDoubleValue(1.0))))))).execute();
      check("timeSeries.create out-of-order -> 400", false, "no error");
    } catch (Exception e) { check("timeSeries.create out-of-order -> 400", code(e) == 400, e.toString()); }
    try {
      ListTimeSeriesResponse r = m.projects().timeSeries().list(pn).setFilter("metric.type=\"" + mtype + "\"")
          .setIntervalStartTime(now.minusSeconds(3600).toString()).setIntervalEndTime(now.toString()).setView("FULL").execute();
      TimeSeries s = r.getTimeSeries().get(0);
      check("timeSeries.list (newest first)", r.getTimeSeries().size() == 1 && s.getPoints().size() == 4
          && s.getPoints().get(0).getValue().getDoubleValue() == 40.0 && "/a".equals(s.getMetric().getLabels().get("route"))
          && "GAUGE".equals(s.getMetricKind()), String.valueOf(r));
    } catch (Exception e) { check("timeSeries.list (newest first)", false, e.toString()); }
    try {
      ListTimeSeriesResponse r = m.projects().timeSeries().list(pn).setFilter("metric.type=\"" + mtype + "\"")
          .setIntervalStartTime(now.minusSeconds(3600).toString()).setIntervalEndTime(now.toString())
          .setAggregationAlignmentPeriod("3600s").setAggregationPerSeriesAligner("ALIGN_MAX").execute();
      check("timeSeries.list aggregated (ALIGN_MAX)", r.getTimeSeries().size() == 1
          && r.getTimeSeries().get(0).getPoints().get(0).getValue().getDoubleValue() == 40.0, String.valueOf(r));
    } catch (Exception e) { check("timeSeries.list aggregated (ALIGN_MAX)", false, e.toString()); }
    try {
      var l = m.projects().metricDescriptors().list(pn).setFilter("metric.type = starts_with(\"custom.googleapis.com/java/\")").execute();
      check("metricDescriptors.list (starts_with filter)", l.getMetricDescriptors() != null && l.getMetricDescriptors().size() >= 1, String.valueOf(l));
    } catch (Exception e) { check("metricDescriptors.list (starts_with filter)", false, e.toString()); }
    try {
      m.projects().metricDescriptors().delete(pn + "/metricDescriptors/" + mtype).execute();
      m.projects().metricDescriptors().get(pn + "/metricDescriptors/" + mtype).execute();
      check("metricDescriptors.delete then get -> 404", false, "no error");
    } catch (Exception e) { check("metricDescriptors.delete then get -> 404", code(e) == 404, e.toString()); }

    // ── uptime checks ────────────────────────────────────────────────
    try {
      UptimeCheckConfig u = m.projects().uptimeCheckConfigs().create(pn, new UptimeCheckConfig().setDisplayName("java-home-" + sfx)
          .setMonitoredResource(new MonitoredResource().setType("uptime_url").setLabels(Map.of("host", "example.com", "project_id", project)))
          .setHttpCheck(new HttpCheck().setPath("/").setPort(443).setUseSsl(true)).setPeriod("300s").setTimeout("10s")).execute();
      UptimeCheckConfig up = m.projects().uptimeCheckConfigs().patch(u.getName(),
          new UptimeCheckConfig().setDisplayName("java-home-2-" + sfx)).setUpdateMask("display_name").execute();
      boolean ok = u.getName().startsWith(pn + "/uptimeCheckConfigs/") && u.getHttpCheck().getPort() == 443;
      m.projects().uptimeCheckConfigs().delete(u.getName()).execute();
      check("uptimeCheckConfigs create/patch/delete", ok && up.getDisplayName().startsWith("java-home-2"), up.toString());
    } catch (Exception e) { check("uptimeCheckConfigs create/patch/delete", false, e.toString()); }

    // ── groups ───────────────────────────────────────────────────────
    try {
      Group g = m.projects().groups().create(pn, new Group().setDisplayName("java-prod-" + sfx)
          .setFilter("resource.metadata.name=has_substring(\"prod\")")).execute();
      Group u = m.projects().groups().update(g.getName(), new Group().setName(g.getName()).setDisplayName("java-prod-2-" + sfx)
          .setFilter("resource.metadata.name=has_substring(\"prod2\")")).execute();
      m.projects().groups().delete(g.getName()).execute();
      check("groups create/update/delete", g.getName().startsWith(pn + "/groups/") && u.getDisplayName().startsWith("java-prod-2"), u.toString());
    } catch (Exception e) { check("groups create/update/delete", false, e.toString()); }

    System.out.println("\n" + pass + " passed, " + fail + " failed");
    System.exit(fail > 0 ? 1 : 0);
  }
}

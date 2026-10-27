import com.google.cloud.NoCredentials;
import com.google.cloud.dns.ChangeRequest;
import com.google.cloud.dns.ChangeRequestInfo;
import com.google.cloud.dns.Dns;
import com.google.cloud.dns.DnsException;
import com.google.cloud.dns.DnsOptions;
import com.google.cloud.dns.RecordSet;
import com.google.cloud.dns.Zone;
import com.google.cloud.dns.ZoneInfo;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Real google-cloud-dns (Java) conformance against Vyomi's Cloud DNS API. Endpoint comes
 * from env ENDPOINT (default http://127.0.0.1:9000), project from PROJECT. One
 * [PASS]/[FAIL] line per check; exits non-zero on any failure.
 */
public class DnsConformance {
  static int pass = 0, fail = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name
        + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (ok) pass++; else fail++;
  }

  static boolean has(Iterable<RecordSet> rs, String name, RecordSet.Type type) {
    for (RecordSet r : rs) if (r.getName().equals(name) && r.getType() == type) return true;
    return false;
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "java-dns-proj");
    System.out.println("== google-cloud-dns (Java) against " + endpoint + " project=" + project + " ==");

    Dns dns = DnsOptions.newBuilder().setProjectId(project).setHost(endpoint)
        .setCredentials(NoCredentials.getInstance()).build().getService();
    String zoneName = "java-zone-" + (System.currentTimeMillis() % 1000000);
    String domain = zoneName + ".example.org.";

    Zone zone = null;
    try {
      zone = dns.create(ZoneInfo.newBuilder(zoneName).setDnsName(domain).setDescription("created by the Java SDK").build());
      check("create managed zone", zone != null && zoneName.equals(zone.getName()) && domain.equals(zone.getDnsName())
          && zone.getGeneratedId() != null && zone.getNameServers().size() == 4, String.valueOf(zone));
    } catch (Exception e) { check("create managed zone", false, e.toString()); }

    try {
      dns.create(ZoneInfo.newBuilder(zoneName).setDnsName(domain).setDescription("dup").build());
      check("duplicate zone → 409", false, "no exception");
    } catch (DnsException e) { check("duplicate zone → 409", e.getCode() == 409, e.toString()); }

    try {
      Zone z = dns.getZone(zoneName);
      check("get managed zone", z != null && "created by the Java SDK".equals(z.getDescription()), String.valueOf(z));
    } catch (Exception e) { check("get managed zone", false, e.toString()); }

    try {
      List<String> names = new ArrayList<>();
      for (Zone z : dns.listZones().iterateAll()) names.add(z.getName());
      check("list managed zones contains the zone", names.contains(zoneName), names.toString());
    } catch (Exception e) { check("list managed zones contains the zone", false, e.toString()); }

    try {
      List<RecordSet> rs = new ArrayList<>();
      for (RecordSet r : dns.listRecordSets(zoneName).iterateAll()) rs.add(r);
      check("new zone has default NS + SOA", has(rs, domain, RecordSet.Type.NS) && has(rs, domain, RecordSet.Type.SOA), rs.toString());
    } catch (Exception e) { check("new zone has default NS + SOA", false, e.toString()); }

    String www = "www." + domain;
    try {
      ChangeRequest ch = dns.applyChangeRequest(zoneName, ChangeRequestInfo.newBuilder()
          .add(RecordSet.newBuilder(www, RecordSet.Type.A).setTtl(120, TimeUnit.SECONDS).addRecord("10.1.2.3").build())
          .add(RecordSet.newBuilder("mail." + domain, RecordSet.Type.CNAME).setTtl(300, TimeUnit.SECONDS).addRecord(www).build())
          .build());
      check("apply change request (add A + CNAME)", ch != null && ch.getGeneratedId() != null
          && ch.status() == ChangeRequest.Status.DONE, String.valueOf(ch));
    } catch (Exception e) { check("apply change request (add A + CNAME)", false, e.toString()); }

    try {
      RecordSet got = null;
      for (RecordSet r : dns.listRecordSets(zoneName, Dns.RecordSetListOption.dnsName(www), Dns.RecordSetListOption.type(RecordSet.Type.A)).iterateAll()) got = r;
      check("list record sets filtered by name+type", got != null && got.getTtl() == 120 && got.getRecords().contains("10.1.2.3"), String.valueOf(got));
    } catch (Exception e) { check("list record sets filtered by name+type", false, e.toString()); }

    try {
      dns.applyChangeRequest(zoneName, ChangeRequestInfo.newBuilder()
          .add(RecordSet.newBuilder(www, RecordSet.Type.A).setTtl(120, TimeUnit.SECONDS).addRecord("10.9.9.9").build()).build());
      check("adding an existing record set → 409", false, "no exception");
    } catch (DnsException e) { check("adding an existing record set → 409", e.getCode() == 409, e.toString()); }

    try {
      dns.applyChangeRequest(zoneName, ChangeRequestInfo.newBuilder()
          .delete(RecordSet.newBuilder(www, RecordSet.Type.A).setTtl(60, TimeUnit.SECONDS).addRecord("10.1.2.3").build()).build());
      check("deleting with a mismatched TTL → 412", false, "no exception");
    } catch (DnsException e) { check("deleting with a mismatched TTL → 412", e.getCode() == 412, e.toString()); }

    try {
      ChangeRequest ch = dns.applyChangeRequest(zoneName, ChangeRequestInfo.newBuilder()
          .delete(RecordSet.newBuilder(www, RecordSet.Type.A).setTtl(120, TimeUnit.SECONDS).addRecord("10.1.2.3").build())
          .add(RecordSet.newBuilder(www, RecordSet.Type.A).setTtl(600, TimeUnit.SECONDS).addRecord("10.4.5.6").build()).build());
      boolean ok = ch != null;
      RecordSet got = null;
      for (RecordSet r : dns.listRecordSets(zoneName, Dns.RecordSetListOption.dnsName(www), Dns.RecordSetListOption.type(RecordSet.Type.A)).iterateAll()) got = r;
      check("atomic replace (delete + add in one change)", ok && got != null && got.getTtl() == 600 && got.getRecords().contains("10.4.5.6"), String.valueOf(got));
    } catch (Exception e) { check("atomic replace (delete + add in one change)", false, e.toString()); }

    try {
      List<ChangeRequest> chs = new ArrayList<>();
      for (ChangeRequest c : dns.listChangeRequests(zoneName).iterateAll()) chs.add(c);
      ChangeRequest first = dns.getChangeRequest(zoneName, chs.get(0).getGeneratedId());
      check("list + get change requests", chs.size() >= 2 && first != null && first.getAdditions().size() >= 1, String.valueOf(chs.size()));
    } catch (Exception e) { check("list + get change requests", false, e.toString()); }

    try {
      com.google.cloud.dns.ProjectInfo pi = dns.getProject();
      check("get project quota", pi != null && pi.getQuota() != null && pi.getQuota().getZones() > 0, String.valueOf(pi));
    } catch (Exception e) { check("get project quota", false, e.toString()); }

    try {
      boolean deleted = dns.delete(zoneName);
      check("delete non-empty zone is rejected", !deleted, "deleted=" + deleted);
    } catch (DnsException e) { check("delete non-empty zone is rejected", e.getCode() == 400, e.toString()); }

    try {
      dns.applyChangeRequest(zoneName, ChangeRequestInfo.newBuilder()
          .delete(RecordSet.newBuilder(www, RecordSet.Type.A).setTtl(600, TimeUnit.SECONDS).addRecord("10.4.5.6").build())
          .delete(RecordSet.newBuilder("mail." + domain, RecordSet.Type.CNAME).setTtl(300, TimeUnit.SECONDS).addRecord(www).build()).build());
      boolean deleted = dns.delete(zoneName);
      check("delete emptied zone", deleted && dns.getZone(zoneName) == null, "deleted=" + deleted);
    } catch (Exception e) { check("delete emptied zone", false, e.toString()); }

    System.out.println("RESULT pass=" + pass + " fail=" + fail);
    System.exit(fail == 0 ? 0 : 1);
  }
}

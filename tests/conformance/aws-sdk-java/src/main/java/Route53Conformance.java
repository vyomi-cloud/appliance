// Real aws-sdk-java-v2 Route 53 conformance probe against Vyomi.
//
// Unmodified software.amazon.awssdk.services.route53 with only the endpoint
// overridden. One [PASS]/[FAIL] line per check; exit code 1 on any failure.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=Route53Conformance

import java.net.URI;
import java.util.List;
import java.util.function.Supplier;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.route53.Route53Client;
import software.amazon.awssdk.services.route53.model.*;

public class Route53Conformance {

    static int pass = 0;
    static int fail = 0;

    static void chk(String name, boolean ok, String detail) {
        if (ok) {
            pass++;
            System.out.println("[PASS] " + name);
        } else {
            fail++;
            System.out.println("[FAIL] " + name + (detail == null || detail.isEmpty() ? "" : " :: " + detail));
        }
    }

    static <T> T run(String name, Supplier<T> fn) {
        try {
            T v = fn.get();
            chk(name, true, "");
            return v;
        } catch (Exception e) {
            chk(name, false, e.toString());
            return null;
        }
    }

    static ResourceRecordSet rr(String name, RRType type, long ttl, String... values) {
        List<ResourceRecord> recs = new java.util.ArrayList<>();
        for (String v : values) recs.add(ResourceRecord.builder().value(v).build());
        return ResourceRecordSet.builder().name(name).type(type).ttl(ttl).resourceRecords(recs).build();
    }

    static Change ch(ChangeAction a, ResourceRecordSet rs) {
        return Change.builder().action(a).resourceRecordSet(rs).build();
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        Route53Client r53 = Route53Client.builder()
                .endpointOverride(URI.create(endpoint))
                .region(Region.AWS_GLOBAL)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
                .build();
        String sfx = Long.toString(System.currentTimeMillis() % 1000000);
        String zone = "java-" + sfx + ".example.com";

        CreateHostedZoneResponse cz = run("CreateHostedZone", () -> r53.createHostedZone(
                CreateHostedZoneRequest.builder().name(zone).callerReference("java-" + sfx)
                        .hostedZoneConfig(HostedZoneConfig.builder().comment("java sdk").build()).build()));
        if (cz == null) System.exit(1);
        String zid = cz.hostedZone().id();   // the SDK strips the /hostedzone/ prefix
        chk("zone id is real-shaped and name is absolute",
                cz.hostedZone().id().startsWith("Z") && cz.hostedZone().name().equals(zone + "."), cz.hostedZone().id() + " " + cz.hostedZone().name());
        chk("four name servers and a PENDING change",
                cz.delegationSet().nameServers().size() == 4 && cz.changeInfo().status() == ChangeStatus.PENDING, "");

        GetHostedZoneResponse gz = run("GetHostedZone", () -> r53.getHostedZone(GetHostedZoneRequest.builder().id(zid).build()));
        chk("GetHostedZone has SOA+NS and the comment",
                gz != null && gz.hostedZone().resourceRecordSetCount() == 2 && "java sdk".equals(gz.hostedZone().config().comment()), "");
        try {
            r53.createHostedZone(CreateHostedZoneRequest.builder().name(zone).callerReference("java-" + sfx).build());
            chk("duplicate caller reference -> HostedZoneAlreadyExistsException", false, "no error");
        } catch (HostedZoneAlreadyExistsException e) {
            chk("duplicate caller reference -> HostedZoneAlreadyExistsException", true, "");
        } catch (Exception e) {
            chk("duplicate caller reference -> HostedZoneAlreadyExistsException", false, e.toString());
        }
        try {
            r53.getHostedZone(GetHostedZoneRequest.builder().id("ZNOSUCHZONE").build());
            chk("unknown zone -> NoSuchHostedZoneException", false, "no error");
        } catch (NoSuchHostedZoneException e) {
            chk("unknown zone -> NoSuchHostedZoneException", true, "");
        } catch (Exception e) {
            chk("unknown zone -> NoSuchHostedZoneException", false, e.toString());
        }
        ListHostedZonesResponse lz = run("ListHostedZones", () -> r53.listHostedZones());
        chk("ListHostedZones contains the zone", lz != null && lz.hostedZones().stream().anyMatch(z -> z.name().equals(zone + ".")), "");
        ListHostedZonesByNameResponse lbn = run("ListHostedZonesByName",
                () -> r53.listHostedZonesByName(ListHostedZonesByNameRequest.builder().dnsName(zone).build()));
        chk("ListHostedZonesByName starts at the zone", lbn != null && !lbn.hostedZones().isEmpty() && lbn.hostedZones().get(0).name().equals(zone + "."), "");
        GetHostedZoneCountResponse cnt = run("GetHostedZoneCount", () -> r53.getHostedZoneCount());
        chk("GetHostedZoneCount >= 1", cnt != null && cnt.hostedZoneCount() >= 1, "");

        ChangeResourceRecordSetsResponse crr = run("ChangeResourceRecordSets (CREATE x3)", () -> r53.changeResourceRecordSets(
                ChangeResourceRecordSetsRequest.builder().hostedZoneId(zid).changeBatch(ChangeBatch.builder().changes(List.of(
                        ch(ChangeAction.CREATE, rr("www." + zone, RRType.A, 300, "192.0.2.10", "192.0.2.11")),
                        ch(ChangeAction.CREATE, rr("*." + zone, RRType.TXT, 60, "\"wild\"")),
                        ch(ChangeAction.CREATE, rr("mail." + zone, RRType.MX, 300, "10 mx." + zone)))).build()).build()));
        if (crr != null) {
            chk("change is PENDING with a change id", crr.changeInfo().status() == ChangeStatus.PENDING && crr.changeInfo().id().startsWith("C"), crr.changeInfo().id());
            GetChangeResponse gc = run("GetChange", () -> r53.getChange(GetChangeRequest.builder().id(crr.changeInfo().id()).build()));
            chk("GetChange is INSYNC", gc != null && gc.changeInfo().status() == ChangeStatus.INSYNC, "");
            run("ResourceRecordSetsChanged waiter", () -> r53.waiter().waitUntilResourceRecordSetsChanged(
                    GetChangeRequest.builder().id(crr.changeInfo().id()).build()));
        }
        ListResourceRecordSetsResponse lr = run("ListResourceRecordSets",
                () -> r53.listResourceRecordSets(ListResourceRecordSetsRequest.builder().hostedZoneId(zid).build()));
        if (lr != null) {
            chk("A record round-trips (2 values, TTL 300)", lr.resourceRecordSets().stream().anyMatch(
                    r -> r.name().equals("www." + zone + ".") && r.type() == RRType.A && r.resourceRecords().size() == 2 && r.ttl() == 300L), lr.resourceRecordSets().toString());
            chk("wildcard name uses the \\052 escape", lr.resourceRecordSets().stream().anyMatch(r -> r.name().startsWith("\\052.")), "");
            chk("5 record sets incl. SOA and NS", lr.resourceRecordSets().size() == 5, String.valueOf(lr.resourceRecordSets().size()));
        }
        ListResourceRecordSetsResponse page = run("ListResourceRecordSets (MaxItems=2)",
                () -> r53.listResourceRecordSets(ListResourceRecordSetsRequest.builder().hostedZoneId(zid).maxItems("2").build()));
        chk("pagination is truncated with a next record", page != null && page.isTruncated() && page.nextRecordName() != null, "");
        try {
            r53.changeResourceRecordSets(ChangeResourceRecordSetsRequest.builder().hostedZoneId(zid).changeBatch(ChangeBatch.builder()
                    .changes(ch(ChangeAction.CREATE, rr("www." + zone, RRType.A, 300, "1.1.1.1"))).build()).build());
            chk("CREATE of an existing record -> InvalidChangeBatchException", false, "no error");
        } catch (InvalidChangeBatchException e) {
            chk("CREATE of an existing record -> InvalidChangeBatchException", true, "");
        } catch (Exception e) {
            chk("CREATE of an existing record -> InvalidChangeBatchException", false, e.toString());
        }
        run("UPSERT", () -> r53.changeResourceRecordSets(ChangeResourceRecordSetsRequest.builder().hostedZoneId(zid)
                .changeBatch(ChangeBatch.builder().changes(ch(ChangeAction.UPSERT, rr("www." + zone, RRType.A, 120, "192.0.2.99"))).build()).build()));
        TestDnsAnswerResponse ans = run("TestDNSAnswer", () -> r53.testDNSAnswer(TestDnsAnswerRequest.builder()
                .hostedZoneId(zid).recordName("www." + zone).recordType(RRType.A).build()));
        chk("TestDNSAnswer returns the upserted value", ans != null && ans.recordData().equals(List.of("192.0.2.99")) && "NOERROR".equals(ans.responseCode()), "");
        try {
            r53.deleteHostedZone(DeleteHostedZoneRequest.builder().id(zid).build());
            chk("non-empty zone -> HostedZoneNotEmptyException", false, "no error");
        } catch (HostedZoneNotEmptyException e) {
            chk("non-empty zone -> HostedZoneNotEmptyException", true, "");
        } catch (Exception e) {
            chk("non-empty zone -> HostedZoneNotEmptyException", false, e.toString());
        }

        run("ChangeTagsForResource", () -> r53.changeTagsForResource(ChangeTagsForResourceRequest.builder()
                .resourceType(TagResourceType.HOSTEDZONE).resourceId(zid).addTags(Tag.builder().key("env").value("java").build()).build()));
        ListTagsForResourceResponse lt = run("ListTagsForResource", () -> r53.listTagsForResource(
                ListTagsForResourceRequest.builder().resourceType(TagResourceType.HOSTEDZONE).resourceId(zid).build()));
        chk("tag round-trips", lt != null && lt.resourceTagSet().tags().size() == 1 && lt.resourceTagSet().tags().get(0).value().equals("java"), "");
        run("UpdateHostedZoneComment", () -> r53.updateHostedZoneComment(UpdateHostedZoneCommentRequest.builder().id(zid).comment("updated").build()));

        CreateHealthCheckResponse hc = run("CreateHealthCheck", () -> r53.createHealthCheck(CreateHealthCheckRequest.builder()
                .callerReference("hc-" + sfx).healthCheckConfig(HealthCheckConfig.builder().type(HealthCheckType.HTTPS)
                        .fullyQualifiedDomainName("www." + zone).resourcePath("/health").build()).build()));
        if (hc != null) {
            HealthCheckConfig c = hc.healthCheck().healthCheckConfig();
            chk("health check defaults (port 443, interval 30, threshold 3)", c.port() == 443 && c.requestInterval() == 30 && c.failureThreshold() == 3, "");
            String hid = hc.healthCheck().id();
            run("UpdateHealthCheck", () -> r53.updateHealthCheck(UpdateHealthCheckRequest.builder().healthCheckId(hid).failureThreshold(5).build()));
            GetHealthCheckResponse g = run("GetHealthCheck", () -> r53.getHealthCheck(GetHealthCheckRequest.builder().healthCheckId(hid).build()));
            chk("update bumped threshold and version", g != null && g.healthCheck().healthCheckConfig().failureThreshold() == 5 && g.healthCheck().healthCheckVersion() == 2, "");
            GetHealthCheckStatusResponse st = run("GetHealthCheckStatus", () -> r53.getHealthCheckStatus(GetHealthCheckStatusRequest.builder().healthCheckId(hid).build()));
            chk("status has observations", st != null && !st.healthCheckObservations().isEmpty(), "");
            ListHealthChecksResponse lh = run("ListHealthChecks", () -> r53.listHealthChecks());
            chk("ListHealthChecks contains it", lh != null && lh.healthChecks().stream().anyMatch(h -> h.id().equals(hid)), "");
            run("DeleteHealthCheck", () -> r53.deleteHealthCheck(DeleteHealthCheckRequest.builder().healthCheckId(hid).build()));
            try {
                r53.getHealthCheck(GetHealthCheckRequest.builder().healthCheckId(hid).build());
                chk("deleted health check -> NoSuchHealthCheckException", false, "no error");
            } catch (NoSuchHealthCheckException e) {
                chk("deleted health check -> NoSuchHealthCheckException", true, "");
            } catch (Exception e) {
                chk("deleted health check -> NoSuchHealthCheckException", false, e.toString());
            }
        }

        CreateReusableDelegationSetResponse ds = run("CreateReusableDelegationSet", () -> r53.createReusableDelegationSet(
                CreateReusableDelegationSetRequest.builder().callerReference("ds-" + sfx).build()));
        if (ds != null) {
            run("GetReusableDelegationSet", () -> r53.getReusableDelegationSet(GetReusableDelegationSetRequest.builder().id(ds.delegationSet().id()).build()));
            run("DeleteReusableDelegationSet", () -> r53.deleteReusableDelegationSet(DeleteReusableDelegationSetRequest.builder().id(ds.delegationSet().id()).build()));
        }
        GetAccountLimitResponse lim = run("GetAccountLimit", () -> r53.getAccountLimit(
                GetAccountLimitRequest.builder().type(AccountLimitType.MAX_HOSTED_ZONES_BY_OWNER).build()));
        chk("hosted zone limit is 500", lim != null && lim.limit().value() == 500, "");

        run("ChangeResourceRecordSets (DELETE x3)", () -> r53.changeResourceRecordSets(
                ChangeResourceRecordSetsRequest.builder().hostedZoneId(zid).changeBatch(ChangeBatch.builder().changes(List.of(
                        ch(ChangeAction.DELETE, rr("www." + zone, RRType.A, 120, "192.0.2.99")),
                        ch(ChangeAction.DELETE, rr("*." + zone, RRType.TXT, 60, "\"wild\"")),
                        ch(ChangeAction.DELETE, rr("mail." + zone, RRType.MX, 300, "10 mx." + zone)))).build()).build()));
        run("DeleteHostedZone", () -> r53.deleteHostedZone(DeleteHostedZoneRequest.builder().id(zid).build()));
        try {
            r53.getHostedZone(GetHostedZoneRequest.builder().id(zid).build());
            chk("deleted zone -> NoSuchHostedZoneException", false, "no error");
        } catch (NoSuchHostedZoneException e) {
            chk("deleted zone -> NoSuchHostedZoneException", true, "");
        }

        System.out.println("== " + pass + " passed, " + fail + " failed ==");
        System.exit(fail == 0 ? 0 : 1);
    }
}

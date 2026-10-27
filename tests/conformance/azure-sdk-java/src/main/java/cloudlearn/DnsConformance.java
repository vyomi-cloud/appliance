package cloudlearn;

import com.azure.core.http.HttpClient;
import com.azure.core.http.HttpPipeline;
import com.azure.core.http.HttpPipelineBuilder;
import com.azure.core.http.policy.HttpLogDetailLevel;
import com.azure.core.http.policy.HttpLogOptions;
import com.azure.core.http.policy.HttpLoggingPolicy;
import com.azure.core.http.policy.RetryPolicy;
import com.azure.core.management.AzureEnvironment;
import com.azure.core.management.exception.ManagementException;
import com.azure.core.management.profile.AzureProfile;
import com.azure.resourcemanager.dns.DnsZoneManager;
import com.azure.resourcemanager.dns.fluent.models.RecordSetInner;
import com.azure.resourcemanager.dns.fluent.models.ZoneInner;
import com.azure.resourcemanager.dns.models.ARecord;
import com.azure.resourcemanager.dns.models.DnsZone;
import com.azure.resourcemanager.dns.models.RecordType;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Azure DNS conformance: the real azure-resourcemanager-dns fluent SDK against Vyomi, only the ARM
 * endpoint changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.DnsConformance
 */
public class DnsConformance {
    static int fail = 0;

    static void check(String name, Supplier<Boolean> r) {
        try {
            if (r.get()) {
                System.out.println("[PASS] " + name);
            } else {
                fail++;
                System.out.println("[FAIL] " + name + " (assertion false)");
            }
        } catch (Throwable t) {
            fail++;
            System.out.println("[FAIL] " + name + ": " + t.getMessage());
        }
    }

    static int status(Throwable t) {
        return t instanceof ManagementException ? ((ManagementException) t).getResponse().getStatusCode() : -1;
    }

    static boolean fails(Supplier<Object> r, int expected) {
        try {
            r.get();
            return false;
        } catch (Throwable t) {
            return status(t) == expected;
        }
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        String sub = System.getenv().getOrDefault("SUB", "00000000-0000-0000-0000-cloudlearn01");
        long n = System.currentTimeMillis() / 1000 % 1000000;
        String rg = "cloudlearn-rg";
        String zone = "java" + n + ".example.com";

        Map<String, String> endpoints = new HashMap<>();
        for (String k : new String[] {"resourceManagerEndpointUrl", "managementEndpointUrl", "activeDirectoryEndpointUrl",
                "activeDirectoryResourceId", "activeDirectoryGraphResourceId", "microsoftGraphResourceId", "galleryEndpointUrl"}) {
            endpoints.put(k, endpoint + "/");
        }
        endpoints.put("storageEndpointSuffix", "core.windows.net");
        endpoints.put("keyVaultDnsSuffix", "vault.azure.net");
        endpoints.put("sqlServerHostnameSuffix", "database.windows.net");
        endpoints.put("azureDataLakeStoreFileSystemEndpointSuffix", "azuredatalakestore.net");
        endpoints.put("azureDataLakeAnalyticsCatalogAndJobEndpointSuffix", "azuredatalakeanalytics.net");
        AzureProfile profile = new AzureProfile("cloudlearn-tenant", sub, new AzureEnvironment(endpoints));
        // No bearer-token policy (it refuses plain HTTP); the appliance ignores credentials.
        HttpPipeline pipeline = new HttpPipelineBuilder().httpClient(HttpClient.createDefault())
                .policies(new RetryPolicy(), new HttpLoggingPolicy(new HttpLogOptions().setLogLevel(HttpLogDetailLevel.NONE)))
                .build();
        DnsZoneManager mgr = DnsZoneManager.authenticate(pipeline, profile);

        DnsZone[] z = new DnsZone[1];
        check("zones.define().create()", () -> {
            z[0] = mgr.zones().define(zone).withExistingResourceGroup(rg).withTag("env", "conf").create();
            return zone.equals(z[0].name()) && z[0].tags().get("env").equals("conf");
        });
        check("zone has 4 name servers and the record-set limits", () ->
                z[0].nameServers().size() == 4 && z[0].maxNumberOfRecordSets() == 10000 && z[0].numberOfRecordSets() >= 2);
        check("getByResourceGroup", () -> zone.equals(mgr.zones().getByResourceGroup(rg, zone).name()));
        check("getByResourceGroup missing → 404", () -> fails(() -> mgr.zones().getByResourceGroup(rg, "nosuch.example.com"), 404));
        check("invalid zone name → 400", () -> fails(() ->
                mgr.serviceClient().getZones().createOrUpdate(rg, "nodots", new ZoneInner().withLocation("global")), 400));
        check("listByResourceGroup", () -> mgr.zones().listByResourceGroup(rg).stream().anyMatch(x -> zone.equals(x.name())));
        check("list (subscription)", () -> mgr.zones().list().stream().anyMatch(x -> zone.equals(x.name())));

        check("A record set via the zone update", () -> {
            z[0].update()
                    .defineARecordSet("www").withIPv4Address("10.0.0.4").withIPv4Address("10.0.0.5").withTimeToLive(300).attach()
                    .defineCNameRecordSet("alias").withAlias("www." + zone).attach()
                    .defineMXRecordSet("@").withMailExchange("mail." + zone, 10).attach()
                    .defineTxtRecordSet("@").withText("v=spf1 -all").attach()
                    .defineSrvRecordSet("_sip._tcp").withRecord("sip." + zone, 5060, 1, 5).attach()
                    .defineCaaRecordSet("@").withRecord(0, "issue", "letsencrypt.org").attach()
                    .apply();
            return true;
        });
        check("aRecordSets().getByName has both addresses and ttl 300", () -> {
            var rs = mgr.zones().getByResourceGroup(rg, zone).aRecordSets().getByName("www");
            return rs.ipv4Addresses().size() == 2 && rs.timeToLive() == 300 && rs.fqdn().startsWith("www." + zone);
        });
        check("cNameRecordSets().getByName", () ->
                mgr.zones().getByResourceGroup(rg, zone).cNameRecordSets().getByName("alias").canonicalName().startsWith("www." + zone));
        check("mxRecordSets / txtRecordSets / srvRecordSets / caaRecordSets", () -> {
            DnsZone cur = mgr.zones().getByResourceGroup(rg, zone);
            return cur.mxRecordSets().list().stream().anyMatch(r -> r.records().get(0).preference() == 10)
                    && cur.txtRecordSets().list().stream().anyMatch(r -> r.records().get(0).value().get(0).equals("v=spf1 -all"))
                    && cur.srvRecordSets().list().stream().anyMatch(r -> r.records().get(0).port() == 5060)
                    && cur.caaRecordSets().list().stream().anyMatch(r -> "issue".equals(r.records().get(0).tag()));
        });
        check("A next to a CNAME of the same name → 409", () -> fails(() ->
                mgr.serviceClient().getRecordSets().createOrUpdate(rg, zone, "alias", RecordType.A,
                        new RecordSetInner().withTtl(60L).withARecords(Arrays.asList(new ARecord().withIpv4Address("10.0.0.9")))), 409));
        check("CNAME at the apex → 400", () -> fails(() ->
                mgr.serviceClient().getRecordSets().createOrUpdate(rg, zone, "@", RecordType.CNAME,
                        new RecordSetInner().withCnameRecord(new com.azure.resourcemanager.dns.models.CnameRecord().withCname("x.example.org"))), 400));
        check("invalid IPv4 → 400", () -> fails(() ->
                mgr.serviceClient().getRecordSets().createOrUpdate(rg, zone, "bad", RecordType.A,
                        new RecordSetInner().withARecords(Arrays.asList(new ARecord().withIpv4Address("999.1.1.1")))), 400));
        check("recordSets.getByType missing → 404", () -> fails(() ->
                mgr.serviceClient().getRecordSets().get(rg, zone, "nosuch", RecordType.A), 404));
        check("listAllByDnsZone sees every record set (SOA, NS and 6 added)", () ->
                mgr.serviceClient().getRecordSets().listAllByDnsZone(rg, zone).stream().count() == 8);
        check("listByType(A) with top", () ->
                mgr.serviceClient().getRecordSets().listByType(rg, zone, RecordType.A, 1, null, com.azure.core.util.Context.NONE).stream().count() == 1);
        check("deleting the SOA record set → 400", () -> fails(() -> {
            mgr.serviceClient().getRecordSets().delete(rg, zone, "@", RecordType.SOA);
            return null;
        }, 400));
        check("remove a record set through the zone update", () -> {
            mgr.zones().getByResourceGroup(rg, zone).update().withoutCNameRecordSet("alias").apply();
            return fails(() -> mgr.serviceClient().getRecordSets().get(rg, zone, "alias", RecordType.CNAME), 404);
        });

        check("deleteByResourceGroup (LRO)", () -> {
            mgr.zones().deleteByResourceGroup(rg, zone);
            return fails(() -> mgr.zones().getByResourceGroup(rg, zone), 404);
        });

        if (fail > 0) {
            System.out.println(fail + " check(s) failed");
            System.exit(1);
        }
        System.out.println("all checks passed");
    }
}

package cloudlearn;

import com.azure.core.http.HttpClient;
import com.azure.core.http.HttpPipeline;
import com.azure.core.http.HttpPipelineBuilder;
import com.azure.core.http.policy.HttpLogDetailLevel;
import com.azure.core.http.policy.HttpLogOptions;
import com.azure.core.http.policy.HttpLoggingPolicy;
import com.azure.core.http.policy.RetryPolicy;
import com.azure.core.management.AzureEnvironment;
import com.azure.core.management.Region;
import com.azure.core.management.exception.ManagementException;
import com.azure.core.management.profile.AzureProfile;
import com.azure.resourcemanager.redis.RedisManager;
import com.azure.resourcemanager.redis.fluent.models.RedisFirewallRuleInner;
import com.azure.resourcemanager.redis.models.RebootType;
import com.azure.resourcemanager.redis.models.RedisCache;
import com.azure.resourcemanager.redis.models.RedisKeyType;
import com.azure.resourcemanager.redis.models.SkuName;

import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Azure Cache for Redis conformance: the real azure-resourcemanager-redis fluent SDK against Vyomi, only the
 * ARM endpoint changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.RedisConformance
 */
public class RedisConformance {
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
        String cache = "java-cache-" + n;
        String prem = "java-prem-" + n;

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
        RedisManager mgr = RedisManager.authenticate(pipeline, profile);

        RedisCache[] c = new RedisCache[1];
        try {
            check("redisCaches.define().withBasicSku().create()", () -> {
                c[0] = mgr.redisCaches().define(cache).withRegion(Region.US_EAST).withExistingResourceGroup(rg)
                        .withBasicSku().withTag("env", "conf").create();
                return cache.equals(c[0].name()) && "conf".equals(c[0].tags().get("env"));
            });
            check("Basic C0 shape: host name, ports, sku, version", () ->
                    c[0].hostname().equals(cache + ".redis.cache.windows.net") && c[0].sslPort() == 6380 && c[0].nonSslPort() == false
                            && c[0].sku().name() == SkuName.BASIC && c[0].sku().capacity() == 0 && c[0].redisVersion().startsWith("6"));
            check("provisioningState Succeeded and non-SSL port disabled", () ->
                    "Succeeded".equals(c[0].provisioningState()) && !c[0].nonSslPort());
            check("getByResourceGroup", () -> cache.equals(mgr.redisCaches().getByResourceGroup(rg, cache).name()));
            check("getByResourceGroup missing → 404", () -> fails(() -> mgr.redisCaches().getByResourceGroup(rg, "java-missing-" + n), 404));
            check("listByResourceGroup", () -> mgr.redisCaches().listByResourceGroup(rg).stream().anyMatch(x -> cache.equals(x.name())));
            check("list (subscription)", () -> mgr.redisCaches().list().stream().anyMatch(x -> cache.equals(x.name())));
            check("invalid name (double hyphen) → 400", () -> fails(() ->
                    mgr.redisCaches().define("bad--name").withRegion(Region.US_EAST).withExistingResourceGroup(rg).withBasicSku().create(), 400));

            check("update: tag + non-SSL port + eviction policy", () -> {
                RedisCache u = c[0].update().withTag("env", "updated").withNonSslPort()
                        .withRedisConfiguration("maxmemory-policy", "allkeys-lru").apply();
                return "updated".equals(u.tags().get("env")) && u.nonSslPort() && "allkeys-lru".equals(u.redisConfiguration().get("maxmemory-policy"));
            });
            check("update: scale Basic C0 → Standard C1", () -> {
                RedisCache u = mgr.redisCaches().getByResourceGroup(rg, cache).update().withStandardSku(1).apply();
                return u.sku().name() == SkuName.STANDARD && u.sku().capacity() == 1;
            });
            check("update: invalid eviction policy → 400", () -> fails(() ->
                    mgr.redisCaches().getByResourceGroup(rg, cache).update().withRedisConfiguration("maxmemory-policy", "bogus").apply(), 400));

            check("regenerateKey rotates only the primary", () -> {
                RedisCache cur = mgr.redisCaches().getByResourceGroup(rg, cache);
                var before = cur.keys();
                var after = cur.regenerateKey(RedisKeyType.PRIMARY);
                return before.primaryKey().length() == 44 && !before.primaryKey().equals(after.primaryKey())
                        && before.secondaryKey().equals(after.secondaryKey());
            });
            check("forceReboot AllNodes", () -> {
                mgr.redisCaches().getByResourceGroup(rg, cache).forceReboot(RebootType.ALL_NODES);
                return true;
            });

            check("firewall rule create + get + list + delete", () -> {
                var fw = mgr.serviceClient().getFirewallRules();
                fw.createOrUpdate(rg, cache, "office", new RedisFirewallRuleInner().withStartIp("10.0.0.1").withEndIp("10.0.0.20"));
                boolean got = "10.0.0.20".equals(fw.get(rg, cache, "office").endIp());
                boolean listed = fw.list(rg, cache).stream().anyMatch(r -> r.name().equals("office"));
                fw.delete(rg, cache, "office");
                return got && listed && fails(() -> fw.get(rg, cache, "office"), 404);
            });
            check("firewall rule with an invalid IP → 400", () -> fails(() ->
                    mgr.serviceClient().getFirewallRules().createOrUpdate(rg, cache, "bad",
                            new RedisFirewallRuleInner().withStartIp("nope").withEndIp("10.0.0.20")), 400));

            check("patch schedule on a Standard cache → 400", () -> fails(() -> mgr.redisCaches().getByResourceGroup(rg, cache).update()
                    .withPatchSchedule(com.azure.resourcemanager.redis.models.DayOfWeek.MONDAY, 3).apply(), 400));
            check("Premium P1 create with shards", () -> {
                RedisCache p = mgr.redisCaches().define(prem).withRegion(Region.US_EAST).withExistingResourceGroup(rg)
                        .withPremiumSku(1).withShardCount(2).create();
                return p.sku().name() == SkuName.PREMIUM && p.shardCount() == 2 && p.sku().family().toString().equals("P");
            });
            check("Premium patch schedule via update()", () -> {
                RedisCache p = mgr.redisCaches().getByResourceGroup(rg, prem).update()
                        .withPatchSchedule(com.azure.resourcemanager.redis.models.DayOfWeek.SUNDAY, 2).apply();
                return p.patchSchedules().stream().anyMatch(s -> s.dayOfWeek() == com.azure.resourcemanager.redis.models.DayOfWeek.SUNDAY && s.startHourUtc() == 2);
            });
        } finally {
            check("deleteByResourceGroup (LRO) removes both caches", () -> {
                for (String d : new String[] {cache, prem}) {
                    try {
                        mgr.redisCaches().deleteByResourceGroup(rg, d);
                    } catch (Throwable ignored) {
                    }
                }
                return fails(() -> mgr.redisCaches().getByResourceGroup(rg, cache), 404)
                        && fails(() -> mgr.redisCaches().getByResourceGroup(rg, prem), 404);
            });
        }

        if (fail > 0) {
            System.out.println(fail + " check(s) failed");
            System.exit(1);
        }
        System.out.println("all checks passed");
    }
}

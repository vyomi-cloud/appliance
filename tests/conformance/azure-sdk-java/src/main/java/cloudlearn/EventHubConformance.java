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
import com.azure.resourcemanager.eventhubs.EventHubsManager;
import com.azure.resourcemanager.eventhubs.fluent.EventHubManagementClient;
import com.azure.resourcemanager.eventhubs.fluent.models.AccessKeysInner;
import com.azure.resourcemanager.eventhubs.fluent.models.AuthorizationRuleInner;
import com.azure.resourcemanager.eventhubs.fluent.models.ConsumerGroupInner;
import com.azure.resourcemanager.eventhubs.fluent.models.EHNamespaceInner;
import com.azure.resourcemanager.eventhubs.fluent.models.EventhubInner;
import com.azure.resourcemanager.eventhubs.models.AccessRights;
import com.azure.resourcemanager.eventhubs.models.CheckNameAvailabilityParameter;
import com.azure.resourcemanager.eventhubs.models.EntityStatus;
import com.azure.resourcemanager.eventhubs.models.KeyType;
import com.azure.resourcemanager.eventhubs.models.RegenerateAccessKeyParameters;
import com.azure.resourcemanager.eventhubs.models.Sku;
import com.azure.resourcemanager.eventhubs.models.SkuName;
import com.azure.resourcemanager.eventhubs.models.SkuTier;

import java.net.URI;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Azure Event Hubs conformance: the real azure-resourcemanager-eventhubs SDK against Vyomi, only the ARM endpoint
 * changed, plus the Event Hubs REST send API (the AMQP / Kafka wires are not exposed) read back through the
 * ARM-path events extension. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.EventHubConformance
 */
public class EventHubConformance {
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

    public static void main(String[] args) throws Exception {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        String sub = System.getenv().getOrDefault("SUB", "00000000-0000-0000-0000-cloudlearn01");
        long n = System.currentTimeMillis() / 1000 % 1000000;
        String rg = "rg-java-eh-" + n;
        String ns = "javaeh" + n;

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
        EventHubManagementClient c = EventHubsManager.authenticate(pipeline, profile).serviceClient();

        EHNamespaceInner[] created = new EHNamespaceInner[1];
        check("namespaces.createOrUpdate (LRO)", () -> {
            created[0] = c.getNamespaces().beginCreateOrUpdate(rg, ns, new EHNamespaceInner().withLocation("eastus")
                    .withSku(new Sku().withName(SkuName.STANDARD).withTier(SkuTier.STANDARD).withCapacity(2))
                    .withTags(Map.of("env", "conf"))).getFinalResult();
            return ns.equals(created[0].name());
        });
        check("namespace is Succeeded, Standard x2 TU, Kafka on, with an endpoint", () ->
                "Succeeded".equals(created[0].provisioningState()) && created[0].sku().capacity() == 2
                        && Boolean.TRUE.equals(created[0].kafkaEnabled()) && created[0].serviceBusEndpoint() != null);
        check("getByResourceGroup", () -> "conf".equals(c.getNamespaces().getByResourceGroup(rg, ns).tags().get("env")));
        check("getByResourceGroup missing → 404", () -> fails(() -> c.getNamespaces().getByResourceGroup(rg, "nosuchns99"), 404));
        check("update (tags)", () -> "updated".equals(c.getNamespaces().update(rg, ns,
                new EHNamespaceInner().withTags(Map.of("env", "updated"))).tags().get("env")));
        check("listByResourceGroup", () -> c.getNamespaces().listByResourceGroup(rg).stream().anyMatch(x -> ns.equals(x.name())));
        check("list (subscription)", () -> c.getNamespaces().list().stream().anyMatch(x -> ns.equals(x.name())));
        check("duplicate namespace name → 409", () -> fails(() ->
                c.getNamespaces().createOrUpdate(rg + "b", ns, new EHNamespaceInner().withLocation("eastus")), 409));
        check("invalid namespace name → 400", () -> fails(() ->
                c.getNamespaces().createOrUpdate(rg, "ab", new EHNamespaceInner().withLocation("eastus")), 400));
        check("checkNameAvailability: taken", () -> !c.getNamespaces()
                .checkNameAvailability(new CheckNameAvailabilityParameter().withName(ns)).nameAvailable());
        check("checkNameAvailability: free", () -> c.getNamespaces()
                .checkNameAvailability(new CheckNameAvailabilityParameter().withName("free-" + ns)).nameAvailable());

        AccessKeysInner[] keys = new AccessKeysInner[1];
        check("listKeys (RootManageSharedAccessKey)", () -> {
            keys[0] = c.getNamespaces().listKeys(rg, ns, "RootManageSharedAccessKey");
            return keys[0].primaryConnectionString().startsWith("Endpoint=sb://" + ns + ".servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;");
        });
        check("regenerateKeys rotates the primary key only", () -> {
            AccessKeysInner k = c.getNamespaces().regenerateKeys(rg, ns, "RootManageSharedAccessKey",
                    new RegenerateAccessKeyParameters().withKeyType(KeyType.PRIMARY_KEY));
            return !k.primaryKey().equals(keys[0].primaryKey()) && k.secondaryKey().equals(keys[0].secondaryKey());
        });
        check("namespace authorization rule (Send)", () -> c.getNamespaces().createOrUpdateAuthorizationRule(rg, ns, "send-only",
                new AuthorizationRuleInner().withRights(List.of(AccessRights.SEND))).rights().contains(AccessRights.SEND));
        check("Manage without Listen+Send → 400", () -> fails(() -> c.getNamespaces().createOrUpdateAuthorizationRule(rg, ns, "bad",
                new AuthorizationRuleInner().withRights(List.of(AccessRights.MANAGE))), 400));

        check("eventHubs.createOrUpdate", () -> {
            EventhubInner h = c.getEventHubs().createOrUpdate(rg, ns, "orders",
                    new EventhubInner().withPartitionCount(4L).withMessageRetentionInDays(3L));
            return "orders".equals(h.name()) && h.partitionIds().size() == 4 && h.messageRetentionInDays() == 3
                    && h.status() == EntityStatus.ACTIVE;
        });
        check("partitionCount over the limit → 400", () -> fails(() ->
                c.getEventHubs().createOrUpdate(rg, ns, "toomany", new EventhubInner().withPartitionCount(500L)), 400));
        check("partitionCount can't change on Standard → 400", () -> fails(() ->
                c.getEventHubs().createOrUpdate(rg, ns, "orders", new EventhubInner().withPartitionCount(8L)), 400));
        check("eventHubs.get / missing → 404", () -> c.getEventHubs().get(rg, ns, "orders").partitionCount() == 4
                && fails(() -> c.getEventHubs().get(rg, ns, "nohub"), 404));
        check("eventHubs.listByNamespace", () -> c.getEventHubs().listByNamespace(rg, ns).stream().count() == 1);
        check("event hub authorization rule + keys carry EntityPath", () -> {
            c.getEventHubs().createOrUpdateAuthorizationRule(rg, ns, "orders", "listen",
                    new AuthorizationRuleInner().withRights(List.of(AccessRights.LISTEN)));
            return c.getEventHubs().listKeys(rg, ns, "orders", "listen").primaryConnectionString().endsWith(";EntityPath=orders");
        });

        check("$Default consumer group exists", () -> c.getConsumerGroups().listByEventHub(rg, ns, "orders").stream()
                .anyMatch(g -> "$Default".equals(g.name())));
        check("consumerGroups.createOrUpdate", () -> "reporting".equals(c.getConsumerGroups().createOrUpdate(rg, ns, "orders", "analytics",
                new ConsumerGroupInner().withUserMetadata("reporting")).userMetadata()));
        check("deleting $Default → 400", () -> fails(() -> { c.getConsumerGroups().delete(rg, ns, "orders", "$Default"); return null; }, 400));
        check("consumerGroups.delete", () -> { c.getConsumerGroups().delete(rg, ns, "orders", "analytics"); return true; });

        // data plane: REST send, read back through the ARM-path events extension
        java.net.http.HttpClient http = java.net.http.HttpClient.newBuilder().version(java.net.http.HttpClient.Version.HTTP_1_1).build();
        String data = endpoint + "/azure-data/eventhub/" + ns;
        check("REST send single event → 201", () -> send(http, data + "/orders/messages", "application/atom+xml;type=entry;charset=utf-8",
                "hello-java", "{\"PartitionKey\":\"k1\"}") == 201);
        check("REST send batch → 201", () -> send(http, data + "/orders/messages", "application/vnd.microsoft.servicebus.json",
                "[{\"Body\":\"b1\"},{\"Body\":\"b2\",\"BrokerProperties\":{\"PartitionKey\":\"k1\"}}]", null) == 201);
        check("REST send to partition 3 → 201", () -> send(http, data + "/orders/partitions/3/messages", "text/plain", "to-p3", null) == 201);
        check("REST send to unknown hub → 404", () -> send(http, data + "/nohub/messages", "text/plain", "x", null) == 404);
        check("sent events are readable per partition", () -> {
            String url = endpoint + "/subscriptions/" + sub + "/resourceGroups/" + rg + "/providers/Microsoft.EventHub/namespaces/" + ns
                    + "/eventhubs/orders/events?api-version=2024-01-01&maxCount=50";
            String body = get(http, url);
            return body.contains("\"count\":4") && body.contains("hello-java") && body.contains("to-p3");
        });

        check("eventHubs.delete", () -> { c.getEventHubs().delete(rg, ns, "orders"); return true; });
        check("namespaces.delete (LRO) then 404", () -> {
            c.getNamespaces().delete(rg, ns);
            return fails(() -> c.getNamespaces().getByResourceGroup(rg, ns), 404);
        });

        System.out.println(fail == 0 ? "all checks passed" : fail + " check(s) failed");
        System.exit(fail == 0 ? 0 : 1);
    }

    static int send(java.net.http.HttpClient http, String url, String ctype, String body, String broker) {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(url)).header("Content-Type", ctype)
                .POST(HttpRequest.BodyPublishers.ofString(body));
        if (broker != null) {
            b.header("BrokerProperties", broker);
        }
        try {
            return http.send(b.build(), HttpResponse.BodyHandlers.discarding()).statusCode();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    static String get(java.net.http.HttpClient http, String url) {
        try {
            return http.send(HttpRequest.newBuilder(URI.create(url)).GET().build(), HttpResponse.BodyHandlers.ofString()).body();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}

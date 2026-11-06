package cloudlearn;

import com.azure.core.exception.HttpResponseException;
import com.azure.core.http.HttpClient;
import com.azure.core.http.HttpPipeline;
import com.azure.core.http.HttpPipelineBuilder;
import com.azure.core.http.policy.HttpLogDetailLevel;
import com.azure.core.http.policy.HttpLogOptions;
import com.azure.core.http.policy.HttpLoggingPolicy;
import com.azure.core.http.policy.RetryPolicy;
import com.azure.core.management.AzureEnvironment;
import com.azure.core.management.Region;
import com.azure.core.management.profile.AzureProfile;
import com.azure.resourcemanager.containerregistry.ContainerRegistryManager;
import com.azure.resourcemanager.containerregistry.models.Registry;
import com.azure.resourcemanager.containerregistry.models.RegistryCredentials;
import com.azure.resourcemanager.containerregistry.models.CheckNameAvailabilityResult;
import com.azure.resourcemanager.containerregistry.models.RegistryNameCheckRequest;
import com.azure.resourcemanager.containerregistry.models.RegistryUsage;
import com.azure.resourcemanager.containerregistry.models.Sku;
import com.azure.resourcemanager.containerregistry.models.SkuName;
import com.azure.resourcemanager.containerregistry.models.WebhookAction;

import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * Azure Container Registry conformance: the real azure-resourcemanager-containerregistry fluent SDK
 * against Vyomi, only the endpoint changed. One [PASS]/[FAIL] line per check; exits non-zero on failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.ContainerRegistryConformance
 */
public class ContainerRegistryConformance {
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

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        String sub = System.getenv().getOrDefault("SUB", "00000000-0000-0000-0000-cloudlearn01");
        long n = System.currentTimeMillis() / 1000 % 1000000;
        String rg = "rg-java-acr-" + n;
        String name = "javaacr" + n;

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
        ContainerRegistryManager mgr = ContainerRegistryManager.authenticate(pipeline, profile);
        var inner = mgr.serviceClient().getRegistries();

        Registry[] reg = new Registry[1];
        check("registries.define().create() Standard + admin (LRO)", () -> {
            reg[0] = mgr.containerRegistries().define(name).withRegion(Region.US_EAST).withNewResourceGroup(rg)
                    .withStandardSku().withRegistryNameAsAdminUser().withTag("env", "conf").create();
            return reg[0].name().equals(name) && reg[0].loginServerUrl().equals(name + ".azurecr.io");
        });
        check("getByResourceGroup: sku Standard, admin enabled, tags", () -> {
            Registry r = mgr.containerRegistries().getByResourceGroup(rg, name);
            return r.sku().name() == SkuName.STANDARD && r.adminUserEnabled() && "conf".equals(r.tags().get("env"));
        });
        check("getByResourceGroup missing -> 404", () -> {
            try {
                mgr.containerRegistries().getByResourceGroup(rg, "nosuchregistry99");
                return false;
            } catch (HttpResponseException e) {
                return e.getResponse().getStatusCode() == 404;
            }
        });
        check("list (subscription) contains registry", () ->
                mgr.containerRegistries().list().stream().anyMatch(r -> name.equals(r.name())));
        check("listByResourceGroup contains registry", () ->
                mgr.containerRegistries().listByResourceGroup(rg).stream().anyMatch(r -> name.equals(r.name())));
        check("update tags", () -> mgr.containerRegistries().getByResourceGroup(rg, name).update()
                .withTag("env", "updated").apply().tags().get("env").equals("updated"));
        check("listCredentials: username + two passwords", () -> {
            RegistryCredentials c = mgr.containerRegistries().getByResourceGroup(rg, name).getCredentials();
            return name.equals(c.username()) && c.accessKeys().size() == 2;
        });
        check("regenerateCredential rotates password", () -> {
            Registry r = mgr.containerRegistries().getByResourceGroup(rg, name);
            String before = r.getCredentials().accessKeys().get(com.azure.resourcemanager.containerregistry.models.AccessKeyType.PRIMARY);
            String after = r.regenerateCredential(com.azure.resourcemanager.containerregistry.models.AccessKeyType.PRIMARY)
                    .accessKeys().get(com.azure.resourcemanager.containerregistry.models.AccessKeyType.PRIMARY);
            return before != null && after != null && !before.equals(after);
        });
        check("checkNameAvailability: taken", () -> {
            CheckNameAvailabilityResult s = mgr.containerRegistries().checkNameAvailability(name);
            return !s.isAvailable() && "AlreadyExists".equals(s.unavailabilityReason());
        });
        check("checkNameAvailability: invalid", () -> {
            CheckNameAvailabilityResult s = mgr.containerRegistries().checkNameAvailability("ab-c");
            return !s.isAvailable() && "Invalid".equals(s.unavailabilityReason());
        });
        check("checkNameAvailability: free", () -> mgr.containerRegistries().checkNameAvailability("freeacr" + n).isAvailable());
        check("listUsages: Size and Webhooks", () -> {
            List<String> names = inner.listUsages(rg, name).value().stream().map(RegistryUsage::name).collect(Collectors.toList());
            return names.contains("Size") && names.contains("Webhooks");
        });

        var wh = mgr.serviceClient().getWebhooks();
        check("webhooks create", () -> {
            var w = wh.create(rg, name, "hookjava", new com.azure.resourcemanager.containerregistry.models.WebhookCreateParameters()
                    .withLocation("eastus").withServiceUri("https://example.com/hook")
                    .withActions(Arrays.asList(WebhookAction.PUSH, WebhookAction.DELETE)));
            return "hookjava".equals(w.name());
        });
        check("webhooks get", () -> wh.get(rg, name, "hookjava").actions().size() == 2);
        check("webhooks getCallbackConfig", () -> "https://example.com/hook".equals(wh.getCallbackConfig(rg, name, "hookjava").serviceUri()));
        check("webhooks list", () -> wh.list(rg, name).stream().anyMatch(w -> "hookjava".equals(w.name())));
        check("webhooks delete", () -> {
            wh.delete(rg, name, "hookjava");
            return wh.list(rg, name).stream().noneMatch(w -> "hookjava".equals(w.name()));
        });

        check("replication on Standard -> 400", () -> {
            try {
                mgr.serviceClient().getReplications().create(rg, name, "westus",
                        new com.azure.resourcemanager.containerregistry.fluent.models.ReplicationInner().withLocation("westus"),
                        com.azure.core.util.Context.NONE);
                return false;
            } catch (HttpResponseException e) {
                return e.getResponse().getStatusCode() == 400;
            }
        });
        check("upgrade to Premium", () -> mgr.containerRegistries().getByResourceGroup(rg, name).update()
                .withPremiumSku().apply().sku().name() == SkuName.PREMIUM);
        check("replication create on Premium + list", () -> {
            mgr.serviceClient().getReplications().create(rg, name, "westus",
                    new com.azure.resourcemanager.containerregistry.fluent.models.ReplicationInner().withLocation("westus"),
                    com.azure.core.util.Context.NONE);
            return mgr.serviceClient().getReplications().list(rg, name).stream().anyMatch(r -> "westus".equals(r.name()));
        });
        check("replication delete", () -> {
            mgr.serviceClient().getReplications().delete(rg, name, "westus", com.azure.core.util.Context.NONE);
            return mgr.serviceClient().getReplications().list(rg, name).stream().noneMatch(r -> "westus".equals(r.name()));
        });

        check("deleteByResourceGroup", () -> {
            mgr.containerRegistries().deleteByResourceGroup(rg, name);
            return true;
        });
        check("deleted registry -> 404", () -> {
            try {
                mgr.containerRegistries().getByResourceGroup(rg, name);
                return false;
            } catch (HttpResponseException e) {
                return e.getResponse().getStatusCode() == 404;
            }
        });
        System.out.println(fail == 0 ? "all checks passed" : fail + " check(s) failed");
        System.exit(fail == 0 ? 0 : 1);
    }
}

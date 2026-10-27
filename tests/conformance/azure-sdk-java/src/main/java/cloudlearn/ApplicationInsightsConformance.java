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
import com.azure.resourcemanager.applicationinsights.ApplicationInsightsManager;
import com.azure.resourcemanager.applicationinsights.models.ApiKeyRequest;
import com.azure.resourcemanager.applicationinsights.models.ApplicationInsightsComponent;
import com.azure.resourcemanager.applicationinsights.models.ApplicationInsightsComponentApiKey;
import com.azure.resourcemanager.applicationinsights.models.ApplicationType;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Azure Application Insights (Microsoft.Insights) conformance: the real
 * azure-resourcemanager-applicationinsights fluent SDK against Vyomi, only the ARM endpoint
 * changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.ApplicationInsightsConformance
 */
public class ApplicationInsightsConformance {
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
        String rg = "rg-java-ai-" + (System.currentTimeMillis() / 1000 % 100000);
        String name = "appi-java";

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
        ApplicationInsightsManager mgr = ApplicationInsightsManager.authenticate(pipeline, profile);

        ApplicationInsightsComponent[] c = new ApplicationInsightsComponent[1];
        check("components.define().create()", () -> {
            c[0] = mgr.components().define(name).withRegion("eastus").withExistingResourceGroup(rg)
                    .withKind("web").withApplicationType(ApplicationType.WEB).withRetentionInDays(30)
                    .withTags(Map.of("env", "test")).create();
            return c[0].id() != null && c[0].instrumentationKey() != null && !c[0].instrumentationKey().isEmpty();
        });
        check("connection string embeds the instrumentation key", () ->
                c[0].connectionString().contains("InstrumentationKey=" + c[0].instrumentationKey())
                        && c[0].connectionString().contains("IngestionEndpoint="));
        check("defaults: retention 30 as requested, provisioning Succeeded, app id", () ->
                c[0].retentionInDays() == 30 && "Succeeded".equals(c[0].provisioningState()) && c[0].appId() != null);
        check("components.getByResourceGroup", () ->
                mgr.components().getByResourceGroup(rg, name).instrumentationKey().equals(c[0].instrumentationKey()));
        check("components.update().withTags()", () -> {
            ApplicationInsightsComponent u = mgr.components().getByResourceGroup(rg, name).update()
                    .withTags(Map.of("env", "prod", "team", "obs")).apply();
            return "prod".equals(u.tags().get("env")) && u.tags().size() == 2;
        });
        check("components.listByResourceGroup", () -> {
            int n = 0;
            for (ApplicationInsightsComponent ignored : mgr.components().listByResourceGroup(rg)) n++;
            return n == 1;
        });
        check("components.list (subscription)", () -> {
            for (ApplicationInsightsComponent x : mgr.components().list()) if (name.equals(x.name())) return true;
            return false;
        });

        String[] keyId = new String[1];
        check("apiKeys.create returns the key value", () -> {
            ApplicationInsightsComponentApiKey k = mgr.apiKeys().create(rg, name, new ApiKeyRequest().withName("reader")
                    .withLinkedReadProperties(List.of(c[0].id() + "/api")).withLinkedWriteProperties(List.of(c[0].id() + "/annotations")));
            keyId[0] = k.id().substring(k.id().lastIndexOf('/') + 1);
            return k.apiKey() != null && !k.apiKey().isEmpty() && "reader".equals(k.name());
        });
        check("apiKeys.get hides the key value", () -> mgr.apiKeys().get(rg, name, keyId[0]).apiKey() == null);
        check("apiKeys.list", () -> {
            int n = 0;
            for (ApplicationInsightsComponentApiKey ignored : mgr.apiKeys().list(rg, name)) n++;
            return n == 1;
        });
        check("apiKeys.delete then get → 404", () -> {
            mgr.apiKeys().delete(rg, name, keyId[0]);
            try {
                mgr.apiKeys().get(rg, name, keyId[0]);
                return false;
            } catch (ManagementException e) {
                return e.getResponse().getStatusCode() == 404;
            }
        });
        check("webTests.listByComponent (none yet)", () -> {
            int n = 0;
            for (var ignored : mgr.webTests().listByComponent(name, rg)) n++;
            return n == 0;
        });
        check("invalid retention → 400", () -> {
            try {
                mgr.components().define("appi-bad").withRegion("eastus").withExistingResourceGroup(rg)
                        .withKind("web").withApplicationType(ApplicationType.WEB).withRetentionInDays(31).create();
                return false;
            } catch (ManagementException e) {
                return e.getResponse().getStatusCode() == 400;
            }
        });
        check("missing component → 404 ResourceNotFound", () -> {
            try {
                mgr.components().getByResourceGroup(rg, "does-not-exist");
                return false;
            } catch (ManagementException e) {
                return e.getResponse().getStatusCode() == 404 && "ResourceNotFound".equals(e.getValue().getCode());
            }
        });
        check("components.deleteByResourceGroup then get → 404", () -> {
            mgr.components().deleteByResourceGroup(rg, name);
            try {
                mgr.components().getByResourceGroup(rg, name);
                return false;
            } catch (ManagementException e) {
                return e.getResponse().getStatusCode() == 404;
            }
        });
        System.exit(fail == 0 ? 0 : 1);
    }
}

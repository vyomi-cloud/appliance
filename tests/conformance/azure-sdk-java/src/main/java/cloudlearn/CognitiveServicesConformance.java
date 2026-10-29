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
import com.azure.resourcemanager.cognitiveservices.CognitiveServicesManager;
import com.azure.resourcemanager.cognitiveservices.models.Account;
import com.azure.resourcemanager.cognitiveservices.models.AccountProperties;
import com.azure.resourcemanager.cognitiveservices.models.ApiKeys;
import com.azure.resourcemanager.cognitiveservices.models.Deployment;
import com.azure.resourcemanager.cognitiveservices.models.DeploymentModel;
import com.azure.resourcemanager.cognitiveservices.models.DeploymentProperties;
import com.azure.resourcemanager.cognitiveservices.models.KeyName;
import com.azure.resourcemanager.cognitiveservices.models.RegenerateKeyParameters;
import com.azure.resourcemanager.cognitiveservices.models.Sku;

import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Azure AI services / Cognitive Services conformance: the real azure-resourcemanager-cognitiveservices
 * fluent SDK against Vyomi, only the ARM endpoint changed. Prints one [PASS]/[FAIL] line per check and
 * exits non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.CognitiveServicesConformance
 */
public class CognitiveServicesConformance {
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
        String rg = "rg-java-ai-" + n;
        String name = "javaai" + n;

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
        CognitiveServicesManager mgr = CognitiveServicesManager.authenticate(pipeline, profile);

        Account[] acct = new Account[1];
        check("accounts.define().create() (LRO)", () -> {
            acct[0] = mgr.accounts().define(name).withExistingResourceGroup(rg).withRegion("eastus")
                    .withKind("OpenAI").withSku(new Sku().withName("S0"))
                    .withProperties(new AccountProperties().withCustomSubDomainName(name))
                    .withTags(Map.of("env", "conf")).create();
            return name.equals(acct[0].name()) && "OpenAI".equals(acct[0].kind()) && acct[0].properties().endpoint() != null;
        });
        check("account is Succeeded with S0 sku and an openai endpoint", () ->
                "Succeeded".equals(acct[0].properties().provisioningState().toString())
                        && "S0".equals(acct[0].sku().name()) && acct[0].properties().endpoint().contains(name));
        check("getByResourceGroup", () -> mgr.accounts().getByResourceGroup(rg, name).tags().get("env").equals("conf"));
        check("getByResourceGroup missing → 404", () -> fails(() -> mgr.accounts().getByResourceGroup(rg, "nosuchaccount99"), 404));
        check("update (tags)", () -> mgr.accounts().getByResourceGroup(rg, name).update().withTags(Map.of("env", "updated")).apply()
                .tags().get("env").equals("updated"));
        check("listByResourceGroup", () -> mgr.accounts().listByResourceGroup(rg).stream().anyMatch(a -> name.equals(a.name())));
        check("list (subscription)", () -> mgr.accounts().list().stream().anyMatch(a -> name.equals(a.name())));
        check("duplicate custom subdomain → 409", () -> fails(() ->
                mgr.accounts().define("dup" + name).withExistingResourceGroup(rg).withRegion("eastus").withKind("OpenAI")
                        .withSku(new Sku().withName("S0")).withProperties(new AccountProperties().withCustomSubDomainName(name)).create(), 409));
        check("unknown kind → 400", () -> fails(() ->
                mgr.accounts().define("bad" + name).withExistingResourceGroup(rg).withRegion("eastus").withKind("NoSuchKind")
                        .withSku(new Sku().withName("S0")).create(), 400));

        ApiKeys[] keys = new ApiKeys[1];
        check("listKeys returns two distinct keys", () -> {
            keys[0] = mgr.accounts().listKeys(rg, name);
            return keys[0].key1() != null && keys[0].key2() != null && !keys[0].key1().equals(keys[0].key2());
        });
        check("regenerateKey rotates key1 only", () -> {
            ApiKeys k = mgr.accounts().regenerateKey(rg, name, new RegenerateKeyParameters().withKeyName(KeyName.KEY1));
            return !k.key1().equals(keys[0].key1()) && k.key2().equals(keys[0].key2());
        });
        check("listSkus", () -> mgr.accounts().listSkus(rg, name).value().size() > 0);
        check("models.list (location) has OpenAI models", () -> mgr.models().list("eastus").stream().count() > 5);
        check("resourceSkus.list", () -> mgr.resourceSkus().list().stream().count() > 5);
        check("checkDomainAvailability: taken", () -> !mgr.resourceProviders().checkDomainAvailability(
                new com.azure.resourcemanager.cognitiveservices.models.CheckDomainAvailabilityParameter()
                        .withSubdomainName(name).withType("Microsoft.CognitiveServices/accounts")).isSubdomainAvailable());
        check("checkDomainAvailability: free", () -> mgr.resourceProviders().checkDomainAvailability(
                new com.azure.resourcemanager.cognitiveservices.models.CheckDomainAvailabilityParameter()
                        .withSubdomainName("free-" + name).withType("Microsoft.CognitiveServices/accounts")).isSubdomainAvailable());

        check("checkSkuAvailability: S0 ok for OpenAI, F0 not", () -> {
            var r = mgr.resourceProviders().checkSkuAvailability("eastus",
                    new com.azure.resourcemanager.cognitiveservices.models.CheckSkuAvailabilityParameter()
                            .withSkus(java.util.List.of("S0", "F0")).withKind("OpenAI").withType("Microsoft.CognitiveServices/accounts"));
            return r.value().size() == 2 && r.value().get(0).skuAvailable() && !r.value().get(1).skuAvailable();
        });

        // ── deployments ──
        check("deployments.define().create()", () -> {
            Deployment d = mgr.deployments().define("chat").withExistingAccount(rg, name)
                    .withSku(new com.azure.resourcemanager.cognitiveservices.models.Sku().withName("Standard").withCapacity(10))
                    .withProperties(new DeploymentProperties().withModel(
                            new DeploymentModel().withFormat("OpenAI").withName("gpt-4o").withVersion("2024-08-06"))).create();
            return "chat".equals(d.name()) && "gpt-4o".equals(d.properties().model().name()) && d.sku().capacity() == 10;
        });
        check("deployments.get is Succeeded", () ->
                "Succeeded".equals(mgr.deployments().get(rg, name, "chat").properties().provisioningState().toString()));
        check("deployments.list", () -> mgr.deployments().list(rg, name).stream().count() == 1);
        check("deployment with unknown model → 400", () -> fails(() ->
                mgr.deployments().define("bad").withExistingAccount(rg, name)
                        .withSku(new com.azure.resourcemanager.cognitiveservices.models.Sku().withName("Standard").withCapacity(10))
                        .withProperties(new DeploymentProperties().withModel(
                                new DeploymentModel().withFormat("OpenAI").withName("no-such-model").withVersion("1"))).create(), 400));
        check("account listModels", () -> mgr.accounts().listModels(rg, name).stream().count() > 5);
        check("deployments.delete + get → 404", () -> {
            mgr.deployments().delete(rg, name, "chat");
            return fails(() -> mgr.deployments().get(rg, name, "chat"), 404);
        });

        // ── delete / soft-delete / restore / purge ──
        check("accounts.delete", () -> {
            mgr.accounts().delete(rg, name, com.azure.core.util.Context.NONE);
            return fails(() -> mgr.accounts().getByResourceGroup(rg, name), 404);
        });
        check("deletedAccounts.get shows the soft-deleted account", () -> name.equals(mgr.deletedAccounts().get("eastus", rg, name).name()));
        check("re-create while soft-deleted → 409", () -> fails(() ->
                mgr.accounts().define(name).withExistingResourceGroup(rg).withRegion("eastus").withKind("OpenAI")
                        .withSku(new Sku().withName("S0")).withProperties(new AccountProperties().withCustomSubDomainName(name)).create(), 409));
        check("restore soft-deleted account (restore=true)", () ->
                mgr.accounts().define(name).withExistingResourceGroup(rg).withRegion("eastus").withKind("OpenAI")
                        .withSku(new Sku().withName("S0")).withProperties(new AccountProperties().withCustomSubDomainName(name).withRestore(true))
                        .create().name().equals(name));
        check("deletedAccounts.purge", () -> {
            mgr.accounts().delete(rg, name, com.azure.core.util.Context.NONE);
            mgr.deletedAccounts().purge("eastus", rg, name);
            return fails(() -> mgr.deletedAccounts().get("eastus", rg, name), 404);
        });

        System.out.println(fail == 0 ? "all checks passed" : fail + " check(s) failed");
        System.exit(fail == 0 ? 0 : 1);
    }
}

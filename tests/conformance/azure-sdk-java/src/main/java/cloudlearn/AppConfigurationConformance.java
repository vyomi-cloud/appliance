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
import com.azure.core.exception.HttpResponseException;
import com.azure.core.exception.ResourceModifiedException;
import com.azure.core.exception.ResourceNotFoundException;
import com.azure.data.appconfiguration.ConfigurationClient;
import com.azure.data.appconfiguration.ConfigurationClientBuilder;
import com.azure.data.appconfiguration.models.ConfigurationSetting;
import com.azure.data.appconfiguration.models.SettingSelector;
import com.azure.resourcemanager.appconfiguration.AppConfigurationManager;
import com.azure.resourcemanager.appconfiguration.models.ApiKey;
import com.azure.resourcemanager.appconfiguration.models.ConfigurationStore;
import com.azure.resourcemanager.appconfiguration.models.Sku;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.ArrayList;
import java.util.function.Supplier;

/**
 * Azure App Configuration conformance: the real azure-resourcemanager-appconfiguration fluent SDK
 * (control plane) and azure-data-appconfiguration ConfigurationClient (HMAC connection string, data
 * plane) against Vyomi, only the endpoints changed. Prints one [PASS]/[FAIL] line per check and exits
 * non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.AppConfigurationConformance
 */
public class AppConfigurationConformance {
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
        if (t instanceof HttpResponseException) {
            return ((HttpResponseException) t).getResponse().getStatusCode();
        }
        return -1;
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        String sub = System.getenv().getOrDefault("SUB", "00000000-0000-0000-0000-cloudlearn01");
        long n = System.currentTimeMillis() / 1000 % 1000000;
        String rg = "rg-java-appcfg-" + n;
        String name = "javacfg" + n;

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
        AppConfigurationManager mgr = AppConfigurationManager.authenticate(pipeline, profile);

        // ── control plane ──
        ConfigurationStore[] store = new ConfigurationStore[1];
        check("configurationStores.define().create() (LRO)", () -> {
            store[0] = mgr.configurationStores().define(name).withRegion("eastus").withExistingResourceGroup(rg)
                    .withSku(new Sku().withName("Standard")).withTags(Map.of("env", "conf")).create();
            return name.equals(store[0].name()) && store[0].endpoint() != null && "Standard".equals(store[0].sku().name());
        });
        check("store is Succeeded with soft delete (7 days)", () ->
                "Succeeded".equals(store[0].provisioningState().toString()) && store[0].softDeleteRetentionInDays() == 7);
        check("getByResourceGroup", () -> mgr.configurationStores().getByResourceGroup(rg, name).tags().get("env").equals("conf"));
        check("getByResourceGroup missing → 404", () -> {
            try {
                mgr.configurationStores().getByResourceGroup(rg, "nosuchstore99");
                return false;
            } catch (ManagementException e) {
                return e.getResponse().getStatusCode() == 404;
            }
        });
        check("update (tags + disableLocalAuth=false)", () ->
                mgr.configurationStores().getByResourceGroup(rg, name).update().withTags(Map.of("env", "updated")).apply().tags().get("env").equals("updated"));
        check("listByResourceGroup", () -> mgr.configurationStores().listByResourceGroup(rg).stream().anyMatch(s -> name.equals(s.name())));
        check("list (subscription)", () -> mgr.configurationStores().list().stream().anyMatch(s -> name.equals(s.name())));
        List<ApiKey> keys = new ArrayList<>();
        check("listKeys returns 4 keys with connection strings", () -> {
            mgr.configurationStores().listKeys(rg, name).forEach(keys::add);
            return keys.size() == 4 && keys.get(0).connectionString().startsWith("Endpoint=");
        });
        String[] conn = new String[1];
        check("regenerateKey rotates the secret", () -> {
            ApiKey nk = mgr.configurationStores().regenerateKey(rg, name,
                    new com.azure.resourcemanager.appconfiguration.models.RegenerateKeyParameters().withId(keys.get(0).id()));
            conn[0] = nk.connectionString();
            return nk.id().equals(keys.get(0).id()) && !nk.value().equals(keys.get(0).value());
        });
        check("checkNameAvailability reports the name taken", () -> !mgr.operations().checkNameAvailability(
                new com.azure.resourcemanager.appconfiguration.models.CheckNameAvailabilityParameters().withName(name)
                        .withType(com.azure.resourcemanager.appconfiguration.models.ConfigurationResourceType.MICROSOFT_APP_CONFIGURATION_CONFIGURATION_STORES))
                .nameAvailable());

        // ── data plane (ConfigurationClient + HMAC connection string, plain HTTP) ──
        ConfigurationClient dp = new ConfigurationClientBuilder().connectionString(conn[0]).buildClient();
        check("setConfigurationSetting", () -> {
            ConfigurationSetting s = dp.setConfigurationSetting(new ConfigurationSetting().setKey("app:color").setLabel("dev")
                    .setValue("blue").setContentType("text/plain").setTags(Map.of("t", "1")));
            return "blue".equals(s.getValue()) && s.getETag() != null && "dev".equals(s.getLabel());
        });
        check("getConfigurationSetting (value, label, content type, tags)", () -> {
            ConfigurationSetting s = dp.getConfigurationSetting("app:color", "dev");
            return "blue".equals(s.getValue()) && "text/plain".equals(s.getContentType()) && "1".equals(s.getTags().get("t"));
        });
        check("get missing → 404", () -> {
            try {
                dp.getConfigurationSetting("nope", null);
                return false;
            } catch (HttpResponseException e) {
                return status(e) == 404;
            }
        });
        check("addConfigurationSetting on an existing key → 412", () -> {
            try {
                dp.addConfigurationSetting("app:color", "dev", "x");
                return false;
            } catch (HttpResponseException e) {
                return status(e) == 412;
            }
        });
        check("addConfigurationSetting new key", () -> dp.addConfigurationSetting("app:size", "dev", "L") != null);
        check("setConfigurationSetting without a label", () -> dp.setConfigurationSetting("other", null, "v1") != null);
        check("set with a stale ETag (ifUnchanged) → 412", () -> {
            ConfigurationSetting old = dp.getConfigurationSetting("app:color", "dev");
            dp.setConfigurationSetting("app:color", "dev", "red");
            try {
                dp.setConfigurationSettingWithResponse(old.setValue("green"), true, com.azure.core.util.Context.NONE);
                return false;
            } catch (ResourceModifiedException e) {
                return true;
            } catch (HttpResponseException e) {
                return status(e) == 412;
            }
        });
        check("listConfigurationSettings key/label filter", () -> {
            List<String> seen = new ArrayList<>();
            dp.listConfigurationSettings(new SettingSelector().setKeyFilter("app:*").setLabelFilter("dev")).forEach(s -> seen.add(s.getKey()));
            return seen.equals(List.of("app:color", "app:size"));
        });
        check("setReadOnly locks the key; writes → 409", () -> {
            dp.setReadOnly("other", null, true);
            try {
                dp.setConfigurationSetting("other", null, "v2");
                return false;
            } catch (HttpResponseException e) {
                return status(e) == 409;
            }
        });
        check("unlock then write", () -> {
            dp.setReadOnly("other", null, false);
            return "v2".equals(dp.setConfigurationSetting("other", null, "v2").getValue());
        });
        check("listRevisions keeps history", () -> {
            int[] c = {0};
            dp.listRevisions(new SettingSelector().setKeyFilter("other")).forEach(s -> c[0]++);
            return c[0] >= 2;
        });
        check("deleteConfigurationSetting returns the deleted setting", () ->
                "v2".equals(dp.deleteConfigurationSetting("other", null).getValue()));
        check("deleted key is gone", () -> {
            try {
                dp.getConfigurationSetting("other", null);
                return false;
            } catch (HttpResponseException e) {
                return status(e) == 404;
            }
        });
        check("paging: 120 settings come back across pages", () -> {
            for (int i = 0; i < 120; i++) {
                dp.setConfigurationSetting("bulk/" + String.format("%03d", i), null, String.valueOf(i));
            }
            int[] c = {0};
            dp.listConfigurationSettings(new SettingSelector().setKeyFilter("bulk/*")).forEach(s -> c[0]++);
            return c[0] == 120;
        });
        check("snapshot create/get/list", () -> {
            var snap = dp.beginCreateSnapshot("snap-java",
                    new com.azure.data.appconfiguration.models.ConfigurationSnapshot(
                            List.of(new com.azure.data.appconfiguration.models.ConfigurationSettingsFilter("app:*"))), null)
                    .getFinalResult();
            int[] c = {0};
            dp.listConfigurationSettingsForSnapshot("snap-java").forEach(s -> c[0]++);
            return "snap-java".equals(snap.getName()) && c[0] == 2
                    && "ready".equals(dp.getSnapshot("snap-java").getStatus().toString());
        });

        // ── ARM keyValues view of the same data ──
        check("ARM keyValues.createOrUpdate is visible on the data plane", () -> {
            mgr.keyValues().define("arm:key").withExistingConfigurationStore(rg, name).withValue("from-arm").create();
            return "from-arm".equals(dp.getConfigurationSetting("arm:key", null).getValue());
        });

        // ── delete → soft delete → purge ──
        check("delete store", () -> {
            mgr.configurationStores().deleteByResourceGroup(rg, name);
            try {
                mgr.configurationStores().getByResourceGroup(rg, name);
                return false;
            } catch (ManagementException e) {
                return e.getResponse().getStatusCode() == 404;
            }
        });
        check("purgeDeleted", () -> {
            mgr.configurationStores().purgeDeleted("eastus", name);
            return mgr.configurationStores().listDeleted().stream().noneMatch(d -> name.equals(d.name()));
        });

        System.out.println(fail == 0 ? "all checks passed" : fail + " check(s) failed");
        System.exit(fail == 0 ? 0 : 1);
    }
}

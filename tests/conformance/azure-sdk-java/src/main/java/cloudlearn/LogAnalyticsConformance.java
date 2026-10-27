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
import com.azure.resourcemanager.loganalytics.LogAnalyticsManager;
import com.azure.resourcemanager.loganalytics.fluent.models.DataSourceInner;
import com.azure.resourcemanager.loganalytics.fluent.models.SavedSearchInner;
import com.azure.resourcemanager.loganalytics.fluent.models.TableInner;
import com.azure.resourcemanager.loganalytics.models.Column;
import com.azure.resourcemanager.loganalytics.models.ColumnTypeEnum;
import com.azure.resourcemanager.loganalytics.models.DataSourceKind;
import com.azure.resourcemanager.loganalytics.models.Schema;
import com.azure.resourcemanager.loganalytics.models.Workspace;
import com.azure.resourcemanager.loganalytics.models.WorkspaceSku;
import com.azure.resourcemanager.loganalytics.models.WorkspaceSkuNameEnum;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Azure Log Analytics conformance: the real azure-resourcemanager-loganalytics fluent SDK against Vyomi, only the ARM
 * endpoint changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.LogAnalyticsConformance
 */
public class LogAnalyticsConformance {
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
        String ws = "law-java-" + n;

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
        LogAnalyticsManager mgr = LogAnalyticsManager.authenticate(pipeline, profile);

        Workspace[] w = new Workspace[1];
        check("workspaces.define().create() (LRO)", () -> {
            w[0] = mgr.workspaces().define(ws).withRegion("eastus").withExistingResourceGroup(rg).withTags(java.util.Collections.singletonMap("env", "conf"))
                    .withSku(new WorkspaceSku().withName(WorkspaceSkuNameEnum.PER_GB2018)).withRetentionInDays(60).create();
            return ws.equals(w[0].name()) && "conf".equals(w[0].tags().get("env"));
        });
        check("workspace has customerId, retention 60 and PerGB2018", () ->
                w[0].customerId() != null && w[0].retentionInDays() == 60 && w[0].sku().name() == WorkspaceSkuNameEnum.PER_GB2018);
        check("getByResourceGroup", () -> ws.equals(mgr.workspaces().getByResourceGroup(rg, ws).name()));
        check("getByResourceGroup missing → 404", () -> fails(() -> mgr.workspaces().getByResourceGroup(rg, "law-missing"), 404));
        check("invalid workspace name → 400", () -> fails(() ->
                mgr.workspaces().define("x").withRegion("eastus").withExistingResourceGroup(rg).create(), 400));
        check("update retention to 90", () -> {
            w[0] = w[0].update().withRetentionInDays(90).apply();
            return mgr.workspaces().getByResourceGroup(rg, ws).retentionInDays() == 90;
        });
        check("listByResourceGroup", () -> mgr.workspaces().listByResourceGroup(rg).stream().anyMatch(x -> ws.equals(x.name())));
        check("list (subscription)", () -> mgr.workspaces().list().stream().anyMatch(x -> ws.equals(x.name())));

        check("sharedKeys.getSharedKeys has two different keys", () -> {
            var k = mgr.sharedKeysOperations().getSharedKeys(rg, ws);
            return k.primarySharedKey() != null && k.secondarySharedKey() != null && !k.primarySharedKey().equals(k.secondarySharedKey());
        });
        check("usages.list reports metrics", () -> mgr.usages().list(rg, ws).stream().count() >= 1);

        check("savedSearches.createOrUpdate", () -> {
            SavedSearchInner s = mgr.serviceClient().getSavedSearches().createOrUpdate(rg, ws, "top-computers",
                    new SavedSearchInner().withCategory("General").withDisplayName("Top computers")
                            .withQuery("Heartbeat | summarize count() by Computer").withVersion(2L));
            return "Top computers".equals(s.displayName());
        });
        check("savedSearches.get / listByWorkspace", () ->
                mgr.savedSearches().get(rg, ws, "top-computers").query().startsWith("Heartbeat")
                        && mgr.savedSearches().listByWorkspace(rg, ws).value().size() == 1);
        check("saved search with an invalid functionAlias → 400", () -> fails(() ->
                mgr.serviceClient().getSavedSearches().createOrUpdate(rg, ws, "bad", new SavedSearchInner().withCategory("General").withDisplayName("Bad")
                        .withQuery("Heartbeat").withFunctionAlias("1-bad")), 400));
        check("savedSearches.delete then get → 404", () -> {
            mgr.savedSearches().delete(rg, ws, "top-computers");
            return fails(() -> mgr.savedSearches().get(rg, ws, "top-computers"), 404);
        });

        check("tables.listByWorkspace has built-in tables", () -> mgr.tables().listByWorkspace(rg, ws).stream().count() >= 5);
        check("tables.createOrUpdate custom table", () -> {
            TableInner t = mgr.serviceClient().getTables().createOrUpdate(rg, ws, "Orders_CL", new TableInner()
                    .withRetentionInDays(30).withTotalRetentionInDays(90)
                    .withSchema(new Schema().withName("Orders_CL").withColumns(Arrays.asList(
                            new Column().withName("TimeGenerated").withType(ColumnTypeEnum.DATE_TIME),
                            new Column().withName("OrderId").withType(ColumnTypeEnum.STRING)))));
            return "Orders_CL".equals(t.name()) && t.totalRetentionInDays() == 90;
        });
        check("custom table name without _CL → 400", () -> fails(() ->
                mgr.serviceClient().getTables().createOrUpdate(rg, ws, "Orders", new TableInner().withRetentionInDays(30)), 400));
        check("tables.update retention", () -> {
            TableInner t = mgr.serviceClient().getTables().update(rg, ws, "Orders_CL",
                    new TableInner().withRetentionInDays(45).withTotalRetentionInDays(120));
            return t.retentionInDays() == 45 && mgr.tables().get(rg, ws, "Orders_CL").totalRetentionInDays() == 120;
        });
        check("deleting a built-in table → 400", () -> fails(() -> { mgr.tables().delete(rg, ws, "Heartbeat"); return null; }, 400));
        check("tables.delete custom table then get → 404", () -> {
            mgr.tables().delete(rg, ws, "Orders_CL");
            return fails(() -> mgr.tables().get(rg, ws, "Orders_CL"), 404);
        });

        check("dataSources.createOrUpdate / listByWorkspace(kind filter)", () -> {
            Map<String, Object> props = new HashMap<>();
            props.put("eventLogName", "Application");
            mgr.serviceClient().getDataSources().createOrUpdate(rg, ws, "WinApp",
                    new DataSourceInner().withKind(DataSourceKind.WINDOWS_EVENT).withProperties(props));
            return mgr.serviceClient().getDataSources().listByWorkspace(rg, ws, "kind eq 'WindowsEvent'").stream().count() == 1;
        });
        check("dataSources.delete", () -> {
            mgr.dataSources().delete(rg, ws, "WinApp");
            return fails(() -> mgr.dataSources().get(rg, ws, "WinApp"), 404);
        });

        check("workspaces.delete (LRO)", () -> {
            mgr.workspaces().delete(rg, ws);
            return fails(() -> mgr.workspaces().getByResourceGroup(rg, ws), 404);
        });

        if (fail > 0) {
            System.out.println(fail + " check(s) failed");
            System.exit(1);
        }
        System.out.println("all checks passed");
    }
}

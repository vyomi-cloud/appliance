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
import com.azure.resourcemanager.monitor.MonitorManager;
import com.azure.resourcemanager.monitor.fluent.models.ActionGroupResourceInner;
import com.azure.resourcemanager.monitor.fluent.models.ActivityLogAlertResourceInner;
import com.azure.resourcemanager.monitor.fluent.models.MetricAlertResourceInner;
import com.azure.resourcemanager.monitor.models.ActionGroupPatchBody;
import com.azure.resourcemanager.monitor.models.ActionList;
import com.azure.resourcemanager.monitor.models.ActivityLogAlertAllOfCondition;
import com.azure.resourcemanager.monitor.models.ActivityLogAlertLeafCondition;
import com.azure.resourcemanager.monitor.models.AggregationTypeEnum;
import com.azure.resourcemanager.monitor.models.CriterionType;
import com.azure.resourcemanager.monitor.models.EmailReceiver;
import com.azure.resourcemanager.monitor.models.MetricAlertAction;
import com.azure.resourcemanager.monitor.models.MetricAlertSingleResourceMultipleMetricCriteria;
import com.azure.resourcemanager.monitor.models.MetricCriteria;
import com.azure.resourcemanager.monitor.models.Operator;

import java.time.Duration;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Azure Monitor conformance: the real azure-resourcemanager-monitor SDK against Vyomi, only the ARM
 * endpoint changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.MonitorConformance
 */
public class MonitorConformance {
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
        String ag = "java-ag-" + n, alert = "java-cpu-" + n, act = "java-act-" + n;
        String vm = "/subscriptions/" + sub + "/resourceGroups/" + rg + "/providers/Microsoft.Compute/virtualMachines/vm-" + n;
        String agId = "/subscriptions/" + sub + "/resourceGroups/" + rg + "/providers/microsoft.insights/actionGroups/" + ag;

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
        MonitorManager mgr = MonitorManager.authenticate(pipeline, profile);
        var agc = mgr.serviceClient().getActionGroups();
        var mac = mgr.serviceClient().getMetricAlerts();
        var alc = mgr.serviceClient().getActivityLogAlerts();

        check("ActionGroups.createOrUpdate", () -> {
            ActionGroupResourceInner g = agc.createOrUpdate(rg, ag, new ActionGroupResourceInner().withLocation("Global")
                    .withGroupShortName("javaag").withEnabled(true).withTags(Map.of("env", "conf"))
                    .withEmailReceivers(List.of(new EmailReceiver().withName("oncall").withEmailAddress("oncall@example.com")
                            .withUseCommonAlertSchema(true))));
            return ag.equals(g.name()) && g.emailReceivers().size() == 1 && g.emailReceivers().get(0).status().toString().equals("Enabled");
        });
        check("ActionGroups.getByResourceGroup", () -> "conf".equals(agc.getByResourceGroup(rg, ag).tags().get("env")));
        check("ActionGroups.get missing → 404", () -> fails(() -> agc.getByResourceGroup(rg, "no-such-ag"), 404));
        check("groupShortName over 12 characters → 400", () -> fails(() -> agc.createOrUpdate(rg, ag + "x",
                new ActionGroupResourceInner().withLocation("Global").withGroupShortName("thisiswaytoolong").withEnabled(true)), 400));
        check("ActionGroups.update (disable)", () -> !agc.update(rg, ag, new ActionGroupPatchBody().withEnabled(false)).enabled());
        check("ActionGroups.listByResourceGroup", () -> agc.listByResourceGroup(rg).stream().anyMatch(x -> ag.equals(x.name())));
        check("ActionGroups.list (subscription)", () -> agc.list().stream().anyMatch(x -> ag.equals(x.name())));

        MetricAlertSingleResourceMultipleMetricCriteria crit = new MetricAlertSingleResourceMultipleMetricCriteria()
                .withAllOf(List.of(new MetricCriteria().withName("HighCpu").withMetricName("Percentage CPU")
                        .withOperator(Operator.GREATER_THAN).withThreshold(80.0).withTimeAggregation(AggregationTypeEnum.AVERAGE)));
        check("MetricAlerts.createOrUpdate", () -> {
            MetricAlertResourceInner a = mac.createOrUpdate(rg, alert, new MetricAlertResourceInner().withLocation("global")
                    .withDescription("cpu high").withSeverity(3).withEnabled(true).withScopes(List.of(vm))
                    .withEvaluationFrequency(Duration.ofMinutes(1)).withWindowSize(Duration.ofMinutes(5)).withCriteria(crit)
                    .withActions(List.of(new MetricAlertAction().withActionGroupId(agId))));
            return alert.equals(a.name()) && a.autoMitigate() && a.lastUpdatedTime() != null && a.actions().size() == 1;
        });
        check("MetricAlerts.get returns the criteria", () -> {
            MetricAlertResourceInner a = mac.getByResourceGroup(rg, alert);
            MetricAlertSingleResourceMultipleMetricCriteria c = (MetricAlertSingleResourceMultipleMetricCriteria) a.criteria();
            return a.severity() == 3 && c.allOf().get(0).threshold() == 80.0 && a.evaluationFrequency().equals(Duration.ofMinutes(1));
        });
        check("MetricAlerts.get missing → 404", () -> fails(() -> mac.getByResourceGroup(rg, "no-such-alert"), 404));
        check("severity 9 → 400", () -> fails(() -> mac.createOrUpdate(rg, alert + "-bad", new MetricAlertResourceInner().withLocation("global")
                .withSeverity(9).withEnabled(true).withScopes(List.of(vm)).withEvaluationFrequency(Duration.ofMinutes(1))
                .withWindowSize(Duration.ofMinutes(5)).withCriteria(crit)), 400));
        check("window shorter than evaluation frequency → 400", () -> fails(() -> mac.createOrUpdate(rg, alert + "-bad",
                new MetricAlertResourceInner().withLocation("global").withSeverity(3).withEnabled(true).withScopes(List.of(vm))
                        .withEvaluationFrequency(Duration.ofMinutes(15)).withWindowSize(Duration.ofMinutes(1)).withCriteria(crit)), 400));
        check("MetricAlerts.listByResourceGroup", () -> mac.listByResourceGroup(rg).stream().anyMatch(x -> alert.equals(x.name())));
        check("MetricAlerts.listBySubscription", () -> mac.list().stream().anyMatch(x -> alert.equals(x.name())));

        check("ActivityLogAlerts.createOrUpdate", () -> {
            ActivityLogAlertResourceInner l = alc.createOrUpdate(rg, act, new ActivityLogAlertResourceInner().withLocation("Global")
                    .withScopes(List.of("/subscriptions/" + sub)).withEnabled(true)
                    .withCondition(new ActivityLogAlertAllOfCondition().withAllOf(Arrays.asList(
                            new ActivityLogAlertLeafCondition().withField("category").withEquals("Administrative"),
                            new ActivityLogAlertLeafCondition().withField("status").withEquals("Failed"))))
                    .withActions(new ActionList()));
            return act.equals(l.name()) && l.condition().allOf().size() == 2;
        });
        check("activity log alert without a category → 400", () -> fails(() -> alc.createOrUpdate(rg, act + "-bad",
                new ActivityLogAlertResourceInner().withLocation("Global").withScopes(List.of("/subscriptions/" + sub)).withEnabled(true)
                        .withCondition(new ActivityLogAlertAllOfCondition().withAllOf(List.of(
                                new ActivityLogAlertLeafCondition().withField("status").withEquals("Failed"))))
                        .withActions(new ActionList())), 400));
        check("ActivityLogAlerts.listByResourceGroup", () -> alc.listByResourceGroup(rg).stream().anyMatch(x -> act.equals(x.name())));

        check("ActivityLogAlerts.delete", () -> { alc.delete(rg, act); return fails(() -> alc.getByResourceGroup(rg, act), 404); });
        check("MetricAlerts.delete", () -> { mac.delete(rg, alert); return fails(() -> mac.getByResourceGroup(rg, alert), 404); });
        check("ActionGroups.delete", () -> { agc.delete(rg, ag); return fails(() -> agc.getByResourceGroup(rg, ag), 404); });
        System.exit(fail > 0 ? 1 : 0);
    }
}

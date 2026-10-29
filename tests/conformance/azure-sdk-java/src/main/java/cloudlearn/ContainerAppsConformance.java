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
import com.azure.resourcemanager.appcontainers.ContainerAppsApiManager;
import com.azure.resourcemanager.appcontainers.models.ActiveRevisionsMode;
import com.azure.resourcemanager.appcontainers.models.Configuration;
import com.azure.resourcemanager.appcontainers.models.Container;
import com.azure.resourcemanager.appcontainers.models.ContainerApp;
import com.azure.resourcemanager.appcontainers.models.ContainerResources;
import com.azure.resourcemanager.appcontainers.models.Ingress;
import com.azure.resourcemanager.appcontainers.models.ManagedEnvironment;
import com.azure.resourcemanager.appcontainers.models.Revision;
import com.azure.resourcemanager.appcontainers.models.Scale;
import com.azure.resourcemanager.appcontainers.models.Secret;
import com.azure.resourcemanager.appcontainers.models.Template;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Azure Container Apps (Microsoft.App) conformance: the real azure-resourcemanager-appcontainers
 * fluent SDK against Vyomi, only the ARM endpoint changed. Prints one [PASS]/[FAIL] line per
 * check and exits non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.ContainerAppsConformance
 */
public class ContainerAppsConformance {
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
        String rg = "rg-java-app-" + (System.currentTimeMillis() / 1000 % 100000);
        String envName = "cae-java", appName = "web-java";

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
        ContainerAppsApiManager mgr = ContainerAppsApiManager.authenticate(pipeline, profile);

        ManagedEnvironment[] env = new ManagedEnvironment[1];
        check("managedEnvironments.define().create() (LRO)", () -> {
            env[0] = mgr.managedEnvironments().define(envName).withRegion("eastus").withExistingResourceGroup(rg).create();
            return env[0].id() != null && env[0].defaultDomain() != null && !env[0].defaultDomain().isEmpty();
        });
        check("managedEnvironments.getByResourceGroup", () ->
                mgr.managedEnvironments().getByResourceGroup(rg, envName).name().equals(envName));

        ContainerApp[] app = new ContainerApp[1];
        check("containerApps.define().create() (LRO)", () -> {
            app[0] = mgr.containerApps().define(appName).withRegion("eastus").withExistingResourceGroup(rg)
                    .withManagedEnvironmentId(env[0].id())
                    .withConfiguration(new Configuration().withActiveRevisionsMode(ActiveRevisionsMode.MULTIPLE)
                            .withIngress(new Ingress().withExternal(true).withTargetPort(80))
                            .withSecrets(List.of(new Secret().withName("api-key").withValue("k-123"))))
                    .withTemplate(new Template()
                            .withContainers(List.of(new Container().withName("web").withImage("mcr.microsoft.com/k8se/quickstart:latest")
                                    .withResources(new ContainerResources().withCpu(0.5).withMemory("1Gi"))))
                            .withScale(new Scale().withMinReplicas(1).withMaxReplicas(3)))
                    .create();
            return app[0].latestRevisionName() != null && app[0].provisioningState() != null;
        });
        check("ingress fqdn lives under the environment default domain", () -> {
            String fqdn = app[0].configuration().ingress().fqdn();
            return fqdn.startsWith(appName + ".") && fqdn.endsWith(env[0].defaultDomain());
        });
        check("containerApps.getByResourceGroup", () ->
                mgr.containerApps().getByResourceGroup(rg, appName).latestRevisionName().equals(app[0].latestRevisionName()));
        check("containerApps.listSecrets returns the secret value", () ->
                "k-123".equals(mgr.containerApps().listSecrets(rg, appName).value().get(0).value()));
        check("containerApps.listByResourceGroup", () -> {
            int n = 0;
            for (ContainerApp ignored : mgr.containerApps().listByResourceGroup(rg)) n++;
            return n == 1;
        });
        check("containerApps.update → new revision (Multiple mode)", () -> {
            ContainerApp upd = mgr.containerApps().getByResourceGroup(rg, appName);
            upd.template().containers().get(0).withImage("mcr.microsoft.com/azuredocs/containerapps-helloworld:latest");
            upd.configuration().secrets().get(0).withValue("k-123");   // GET never returns secret values
            ContainerApp saved = mgr.containerApps().define(appName).withRegion("eastus").withExistingResourceGroup(rg)
                    .withManagedEnvironmentId(env[0].id()).withConfiguration(upd.configuration()).withTemplate(upd.template()).create();
            return !saved.latestRevisionName().equals(app[0].latestRevisionName());
        });
        check("containerAppsRevisions.listRevisions has two revisions", () -> {
            int n = 0;
            for (Revision r : mgr.containerAppsRevisions().listRevisions(rg, appName)) n++;
            return n == 2;
        });
        check("containerAppsRevisions.deactivateRevision", () -> {
            String first = app[0].latestRevisionName();
            mgr.containerAppsRevisions().deactivateRevision(rg, appName, first);
            return Boolean.FALSE.equals(mgr.containerAppsRevisions().getRevision(rg, appName, first).active());
        });
        check("containerApps.stop / start", () -> {
            mgr.containerApps().stop(rg, appName);
            mgr.containerApps().start(rg, appName);
            return true;
        });
        check("get missing app → ManagementException 404 ResourceNotFound", () -> {
            try {
                mgr.containerApps().getByResourceGroup(rg, "does-not-exist");
                return false;
            } catch (ManagementException e) {
                return e.getResponse().getStatusCode() == 404 && "ResourceNotFound".equals(e.getValue().getCode());
            }
        });
        check("invalid cpu/memory pair → 400 ContainerAppInvalidResourceTotal", () -> {
            try {
                mgr.containerApps().define("bad-cpu").withRegion("eastus").withExistingResourceGroup(rg)
                        .withManagedEnvironmentId(env[0].id())
                        .withTemplate(new Template().withContainers(List.of(new Container().withName("c").withImage("nginx")
                                .withResources(new ContainerResources().withCpu(0.5).withMemory("3Gi"))))).create();
                return false;
            } catch (ManagementException e) {
                return e.getResponse().getStatusCode() == 400 && "ContainerAppInvalidResourceTotal".equals(e.getValue().getCode());
            }
        });
        check("containerApps.deleteById then get → 404", () -> {
            mgr.containerApps().deleteById(app[0].id());
            try {
                mgr.containerApps().getByResourceGroup(rg, appName);
                return false;
            } catch (ManagementException e) {
                return e.getResponse().getStatusCode() == 404;
            }
        });
        check("managedEnvironments.deleteById", () -> {
            mgr.managedEnvironments().deleteById(env[0].id());
            return true;
        });

        if (fail > 0) {
            System.out.println(fail + " check(s) failed");
            System.exit(1);
        }
    }
}

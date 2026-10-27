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
import com.azure.resourcemanager.containerservice.ContainerServiceManager;
import com.azure.resourcemanager.containerservice.fluent.ManagedClustersClient;
import com.azure.resourcemanager.containerservice.fluent.AgentPoolsClient;
import com.azure.resourcemanager.containerservice.fluent.models.AgentPoolInner;
import com.azure.resourcemanager.containerservice.fluent.models.ManagedClusterInner;
import com.azure.resourcemanager.containerservice.fluent.models.CredentialResultsInner;
import com.azure.resourcemanager.containerservice.models.AgentPoolMode;
import com.azure.resourcemanager.containerservice.models.ManagedClusterAgentPoolProfile;
import com.azure.resourcemanager.containerservice.models.ManagedClusterSku;
import com.azure.resourcemanager.containerservice.models.ManagedClusterSkuName;
import com.azure.resourcemanager.containerservice.models.ManagedClusterSkuTier;
import com.azure.resourcemanager.containerservice.models.ResourceIdentityType;
import com.azure.resourcemanager.containerservice.models.ManagedClusterIdentity;
import com.azure.resourcemanager.containerservice.models.TagsObject;
import com.azure.resourcemanager.containerservice.models.OSType;

import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * AKS / Azure Kubernetes Service conformance: the real azure-resourcemanager-containerservice SDK
 * against Vyomi, only the ARM endpoint changed. Prints one [PASS]/[FAIL] line per check and exits
 * non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.ContainerServiceConformance
 */
public class ContainerServiceConformance {
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
        String rg = "rg-java-aks-" + n;
        String name = "javaaks" + n;

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
        ContainerServiceManager mgr = ContainerServiceManager.authenticate(pipeline, profile);
        ManagedClustersClient clusters = mgr.serviceClient().getManagedClusters();
        AgentPoolsClient pools = mgr.serviceClient().getAgentPools();

        ManagedClusterInner[] cl = new ManagedClusterInner[1];
        check("managedClusters.beginCreateOrUpdate (LRO)", () -> {
            ManagedClusterInner body = new ManagedClusterInner().withLocation("eastus")
                    .withSku(new ManagedClusterSku().withName(ManagedClusterSkuName.BASE).withTier(ManagedClusterSkuTier.FREE))
                    .withIdentity(new ManagedClusterIdentity().withType(ResourceIdentityType.SYSTEM_ASSIGNED))
                    .withDnsPrefix(name + "-dns").withKubernetesVersion("1.29.9");
            body.withAgentPoolProfiles(java.util.List.of(new ManagedClusterAgentPoolProfile().withName("nodepool1").withCount(2)
                    .withVmSize("Standard_DS2_v2").withMode(AgentPoolMode.SYSTEM).withOsType(OSType.LINUX)));
            Map<String, String> tags = new HashMap<>();
            tags.put("env", "conf");
            body.withTags(tags);
            cl[0] = clusters.beginCreateOrUpdate(rg, name, body).getFinalResult();
            return name.equals(cl[0].name());
        });
        check("cluster has FQDN, Succeeded, Running", () -> cl[0].fqdn() != null && cl[0].fqdn().contains("azmk8s.io")
                && "Succeeded".equals(cl[0].provisioningState()) && "Running".equals(cl[0].powerState().code().toString()));
        check("system-assigned identity has a principal", () -> cl[0].identity() != null && cl[0].identity().principalId() != null);
        check("get cluster", () -> {
            ManagedClusterInner g = clusters.getByResourceGroup(rg, name);
            return "conf".equals(g.tags().get("env")) && "1.29.9".equals(g.kubernetesVersion())
                    && g.agentPoolProfiles().size() == 1 && g.agentPoolProfiles().get(0).count() == 2;
        });
        check("get missing cluster → 404", () -> fails(() -> clusters.getByResourceGroup(rg, "nosuchcluster99"), 404));
        check("updateTags", () -> {
            Map<String, String> t = new HashMap<>();
            t.put("env", "updated");
            ManagedClusterInner u = clusters.beginUpdateTags(rg, name, new TagsObject().withTags(t)).getFinalResult();
            return "updated".equals(clusters.getByResourceGroup(rg, name).tags().get("env")) && u != null;
        });
        check("listByResourceGroup", () -> {
            int c = 0;
            for (ManagedClusterInner m : clusters.listByResourceGroup(rg)) {
                c++;
            }
            return c == 1;
        });
        check("list (subscription)", () -> {
            for (ManagedClusterInner m : clusters.list()) {
                if (name.equals(m.name())) {
                    return true;
                }
            }
            return false;
        });
        check("unsupported Kubernetes version → 400", () -> fails(() -> clusters.beginCreateOrUpdate(rg, "bad" + name,
                new ManagedClusterInner().withLocation("eastus").withDnsPrefix("bad-dns").withKubernetesVersion("9.9.9")
                        .withAgentPoolProfiles(java.util.List.of(new ManagedClusterAgentPoolProfile().withName("nodepool1").withCount(1)
                                .withMode(AgentPoolMode.SYSTEM))))
                .getFinalResult(), 400));

        check("listClusterAdminCredentials returns a kubeconfig", () -> {
            CredentialResultsInner c = clusters.listClusterAdminCredentials(rg, name);
            String txt = new String(c.kubeconfigs().get(0).value(), StandardCharsets.UTF_8);
            if (!txt.contains("kind: Config")) {
                txt = new String(java.util.Base64.getDecoder().decode(txt), StandardCharsets.UTF_8);
            }
            return txt.contains("kind: Config") && txt.contains("clusterAdmin_");
        });
        check("listClusterUserCredentials", () -> clusters.listClusterUserCredentials(rg, name).kubeconfigs().size() == 1);

        check("agentPools create (user pool, autoscaling)", () -> {
            AgentPoolInner ap = pools.beginCreateOrUpdate(rg, name, "userpool", new AgentPoolInner().withCount(1)
                    .withVmSize("Standard_D4s_v3").withMode(AgentPoolMode.USER).withOsType(OSType.LINUX)
                    .withEnableAutoScaling(true).withMinCount(1).withMaxCount(4)).getFinalResult();
            return "Standard_D4s_v3".equals(ap.vmSize()) && ap.mode() == AgentPoolMode.USER;
        });
        check("agentPools get", () -> pools.get(rg, name, "userpool").maxCount() == 4);
        check("agentPools list (system + user)", () -> {
            int c = 0;
            for (AgentPoolInner a : pools.list(rg, name)) {
                c++;
            }
            return c == 2;
        });
        check("invalid pool name → 400", () -> fails(() -> pools.beginCreateOrUpdate(rg, name, "BadName", new AgentPoolInner().withCount(1))
                .getFinalResult(), 400));
        check("pool upgrade profile", () -> !pools.getUpgradeProfile(rg, name, "userpool").upgrades().isEmpty());
        check("cluster upgrade profile", () -> !clusters.getUpgradeProfile(rg, name).controlPlaneProfile().upgrades().isEmpty());
        check("stop → Stopped", () -> {
            clusters.beginStop(rg, name).getFinalResult();
            return "Stopped".equals(clusters.getByResourceGroup(rg, name).powerState().code().toString());
        });
        check("start → Running", () -> {
            clusters.beginStart(rg, name).getFinalResult();
            return "Running".equals(clusters.getByResourceGroup(rg, name).powerState().code().toString());
        });
        check("agentPools delete", () -> {
            pools.beginDelete(rg, name, "userpool").getFinalResult();
            return fails(() -> pools.get(rg, name, "userpool"), 404);
        });
        check("managedClusters delete", () -> {
            clusters.beginDelete(rg, name).getFinalResult();
            return true;
        });
        check("deleted cluster → 404", () -> fails(() -> clusters.getByResourceGroup(rg, name), 404));

        if (fail > 0) {
            System.out.println(fail + " check(s) failed");
            System.exit(1);
        }
        System.out.println("all checks passed");
    }
}

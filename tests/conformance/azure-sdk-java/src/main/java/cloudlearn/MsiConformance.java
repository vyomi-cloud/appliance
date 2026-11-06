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
import com.azure.resourcemanager.msi.MsiManager;
import com.azure.resourcemanager.msi.fluent.models.FederatedIdentityCredentialInner;
import com.azure.resourcemanager.msi.fluent.models.IdentityInner;
import com.azure.resourcemanager.msi.models.Identity;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Azure Managed Identities conformance: the real azure-resourcemanager-msi fluent SDK against Vyomi, only
 * the ARM endpoint changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
 *
 *   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=cloudlearn.MsiConformance
 */
public class MsiConformance {
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
        String name = "java-id-" + n;
        String name2 = "java-id2-" + n;

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
        MsiManager mgr = MsiManager.authenticate(pipeline, profile);

        Identity[] id = new Identity[1];
        check("identities.define().create()", () -> {
            id[0] = mgr.identities().define(name).withRegion(Region.US_EAST).withExistingResourceGroup(rg).withTag("env", "conf").create();
            return name.equals(id[0].name()) && "conf".equals(id[0].tags().get("env"));
        });
        check("identity has clientId, principalId and tenantId", () ->
                id[0].clientId() != null && !id[0].clientId().isEmpty() && id[0].principalId() != null
                        && !id[0].principalId().isEmpty() && id[0].tenantId() != null && !id[0].tenantId().isEmpty());
        check("identity type", () -> "Microsoft.ManagedIdentity/userAssignedIdentities".equals(id[0].type()));
        check("getByResourceGroup returns the same clientId", () ->
                id[0].clientId().equals(mgr.identities().getByResourceGroup(rg, name).clientId()));
        check("getByResourceGroup missing → 404", () -> fails(() -> mgr.identities().getByResourceGroup(rg, "no-such-identity"), 404));
        check("invalid identity name → 400", () -> fails(() ->
                mgr.serviceClient().getUserAssignedIdentities().createOrUpdate(rg, "a!", new IdentityInner().withLocation("eastus")), 400));
        check("changing the location → 400", () -> fails(() ->
                mgr.serviceClient().getUserAssignedIdentities().createOrUpdate(rg, name, new IdentityInner().withLocation("westus")), 400));
        check("update() changes tags, keeps clientId", () -> {
            Identity u = id[0].update().withTag("env", "updated").apply();
            return "updated".equals(u.tags().get("env")) && id[0].clientId().equals(u.clientId());
        });
        check("create a second identity", () ->
                name2.equals(mgr.identities().define(name2).withRegion(Region.EUROPE_WEST).withExistingResourceGroup(rg).create().name()));
        check("listByResourceGroup contains both", () -> {
            int c = 0;
            for (Identity x : mgr.identities().listByResourceGroup(rg)) {
                if (name.equals(x.name()) || name2.equals(x.name())) c++;
            }
            return c == 2;
        });
        check("list (subscription) contains both", () -> {
            int c = 0;
            for (Identity x : mgr.identities().list()) {
                if (name.equals(x.name()) || name2.equals(x.name())) c++;
            }
            return c == 2;
        });

        var fcs = mgr.serviceClient().getFederatedIdentityCredentials();
        String gh = "https://token.actions.githubusercontent.com";
        check("federated credential createOrUpdate", () -> {
            FederatedIdentityCredentialInner f = fcs.createOrUpdate(rg, name, "github-main", new FederatedIdentityCredentialInner()
                    .withIssuer(gh).withSubject("repo:cloudlearn/demo:ref:refs/heads/main").withAudiences(Arrays.asList("api://AzureADTokenExchange")));
            return "github-main".equals(f.name()) && gh.equals(f.issuer()) && f.audiences().size() == 1
                    && f.type().endsWith("/federatedIdentityCredentials");
        });
        check("same issuer+subject under another name → 409", () -> fails(() -> fcs.createOrUpdate(rg, name, "github-dup",
                new FederatedIdentityCredentialInner().withIssuer(gh).withSubject("repo:cloudlearn/demo:ref:refs/heads/main")
                        .withAudiences(Arrays.asList("api://AzureADTokenExchange"))), 409));
        check("non-https issuer → 400", () -> fails(() -> fcs.createOrUpdate(rg, name, "bad-issuer",
                new FederatedIdentityCredentialInner().withIssuer("http://insecure.example.com").withSubject("s")
                        .withAudiences(Arrays.asList("api://AzureADTokenExchange"))), 400));
        check("second federated credential + get", () -> {
            fcs.createOrUpdate(rg, name, "k8s-prod", new FederatedIdentityCredentialInner().withIssuer("https://oidc.example.com/cluster")
                    .withSubject("system:serviceaccount:default:app").withAudiences(Arrays.asList("api://AzureADTokenExchange")));
            return "system:serviceaccount:default:app".equals(fcs.get(rg, name, "k8s-prod").subject());
        });
        check("get missing federated credential → 404", () -> fails(() -> fcs.get(rg, name, "nope"), 404));
        check("list federated credentials", () -> {
            int c = 0;
            for (FederatedIdentityCredentialInner f : fcs.list(rg, name)) c++;
            return c == 2;
        });
        check("delete federated credential → get 404", () -> {
            fcs.delete(rg, name, "github-main");
            return fails(() -> fcs.get(rg, name, "github-main"), 404);
        });

        check("identities.deleteByResourceGroup", () -> {
            mgr.identities().deleteByResourceGroup(rg, name);
            return fails(() -> mgr.identities().getByResourceGroup(rg, name), 404);
        });
        check("delete is idempotent", () -> {
            mgr.identities().deleteByResourceGroup(rg, name);
            return true;
        });
        check("delete second identity", () -> {
            mgr.identities().deleteByResourceGroup(rg, name2);
            return true;
        });

        if (fail > 0) {
            System.out.println(fail + " check(s) failed");
            System.exit(1);
        }
    }
}

// Real aws-sdk-java-v2 conformance for Amazon ECS against the Vyomi appliance — only the
// endpoint is changed. One [PASS]/[FAIL] line per check; exit 1 on any failure.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=AwsEcsConformance

import java.net.URI;
import java.util.List;
import java.util.function.Supplier;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.ecs.EcsClient;
import software.amazon.awssdk.services.ecs.model.*;

public class AwsEcsConformance {
    static int fails = 0;

    static void check(String name, boolean ok, String detail) {
        if (ok) System.out.println("[PASS] " + name);
        else { fails++; System.out.println("[FAIL] " + name + " :: " + detail); }
    }

    static <T> T call(String name, Supplier<T> op, java.util.function.Predicate<T> ok) {
        try {
            T r = op.get();
            check(name, ok.test(r), "unexpected response: " + r);
            return r;
        } catch (Throwable t) {
            fails++;
            System.out.println("[FAIL] " + name + " :: " + t.getMessage());
            return null;
        }
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        System.out.println("== aws-sdk-java-v2 ecs against " + endpoint + " ==");
        EcsClient ecs = EcsClient.builder().endpointOverride(URI.create(endpoint)).region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test"))).build();
        String sfx = Long.toString(System.nanoTime() % 1000000000L);
        String cname = "java-smoke-" + sfx, fam = "java-web-" + sfx, svc = "java-svc-" + sfx;
        NetworkConfiguration net = NetworkConfiguration.builder().awsvpcConfiguration(
                AwsVpcConfiguration.builder().subnets("subnet-0a1b2c3d4e5f60718").build()).build();

        CreateClusterResponse cc = call("CreateCluster", () -> ecs.createCluster(b -> b.clusterName(cname)
                .tags(Tag.builder().key("env").value("test").build())),
                r -> cname.equals(r.cluster().clusterName()) && "ACTIVE".equals(r.cluster().status()));
        String arn = cc == null ? "" : cc.cluster().clusterArn();
        call("DescribeClusters (with TAGS)", () -> ecs.describeClusters(b -> b.clusters(cname).include(ClusterField.TAGS)),
                r -> r.clusters().size() == 1 && r.clusters().get(0).tags().size() == 1);
        call("ListClusters", () -> ecs.listClusters(), r -> r.clusterArns().contains(arn));
        call("UpdateCluster (containerInsights)", () -> ecs.updateCluster(b -> b.cluster(cname)
                .settings(ClusterSetting.builder().name(ClusterSettingName.CONTAINER_INSIGHTS).value("enabled").build())), r -> true);

        call("RegisterTaskDefinition", () -> ecs.registerTaskDefinition(b -> b.family(fam).cpu("256").memory("512")
                .networkMode(NetworkMode.AWSVPC).requiresCompatibilities(Compatibility.FARGATE)
                .containerDefinitions(ContainerDefinition.builder().name("web").image("nginx:1.27").essential(true)
                        .portMappings(PortMapping.builder().containerPort(80).build()).build())),
                r -> r.taskDefinition().revision() == 1 && r.taskDefinition().status() == TaskDefinitionStatus.ACTIVE);
        call("DescribeTaskDefinition", () -> ecs.describeTaskDefinition(b -> b.taskDefinition(fam)),
                r -> "nginx:1.27".equals(r.taskDefinition().containerDefinitions().get(0).image()));
        call("ListTaskDefinitions", () -> ecs.listTaskDefinitions(b -> b.familyPrefix(fam)), r -> r.taskDefinitionArns().size() == 1);

        call("CreateService", () -> ecs.createService(b -> b.cluster(cname).serviceName(svc).taskDefinition(fam)
                .desiredCount(1).launchType(LaunchType.FARGATE).networkConfiguration(net)),
                r -> svc.equals(r.service().serviceName()) && r.service().desiredCount() == 1);
        call("DescribeServices", () -> ecs.describeServices(b -> b.cluster(cname).services(svc)),
                r -> r.services().size() == 1 && "ACTIVE".equals(r.services().get(0).status()));
        call("ListServices", () -> ecs.listServices(b -> b.cluster(cname)), r -> r.serviceArns().size() == 1);
        call("UpdateService (scale to 2)", () -> ecs.updateService(b -> b.cluster(cname).service(svc).desiredCount(2)),
                r -> r.service().desiredCount() == 2);

        RunTaskResponse rt = call("RunTask", () -> ecs.runTask(b -> b.cluster(cname).taskDefinition(fam)
                .launchType(LaunchType.FARGATE).networkConfiguration(net)), r -> r.tasks().size() == 1 && r.failures().isEmpty());
        String taskArn = rt == null || rt.tasks().isEmpty() ? "" : rt.tasks().get(0).taskArn();
        call("ListTasks", () -> ecs.listTasks(b -> b.cluster(cname)), r -> r.taskArns().contains(taskArn));
        call("DescribeTasks", () -> ecs.describeTasks(b -> b.cluster(cname).tasks(taskArn)),
                r -> r.tasks().size() == 1 && r.tasks().get(0).lastStatus() != null && !r.tasks().get(0).lastStatus().isEmpty());
        call("StopTask", () -> ecs.stopTask(b -> b.cluster(cname).task(taskArn).reason("smoke")),
                r -> "STOPPED".equals(r.task().desiredStatus()));

        call("TagResource", () -> ecs.tagResource(b -> b.resourceArn(arn).tags(Tag.builder().key("team").value("platform").build())), r -> true);
        call("ListTagsForResource", () -> ecs.listTagsForResource(b -> b.resourceArn(arn)), r -> r.tags().size() == 2);
        call("UntagResource", () -> ecs.untagResource(b -> b.resourceArn(arn).tagKeys("team")), r -> true);

        call("PutClusterCapacityProviders", () -> ecs.putClusterCapacityProviders(b -> b.cluster(cname)
                .capacityProviders("FARGATE", "FARGATE_SPOT")
                .defaultCapacityProviderStrategy(CapacityProviderStrategyItem.builder().capacityProvider("FARGATE").weight(1).build())),
                r -> r.cluster().capacityProviders().size() == 2);

        try {
            ecs.describeServices(b -> b.cluster("no-such-" + sfx).services("x"));
            check("missing cluster -> ClusterNotFoundException", false, "no error");
        } catch (ClusterNotFoundException e) {
            check("missing cluster -> ClusterNotFoundException", true, "");
        } catch (Throwable t) { check("missing cluster -> ClusterNotFoundException", false, t.toString()); }
        try {
            ecs.deleteCluster(b -> b.cluster(cname));
            check("DeleteCluster with active service -> ClusterContainsServicesException", false, "no error");
        } catch (ClusterContainsServicesException e) {
            check("DeleteCluster with active service -> ClusterContainsServicesException", true, "");
        } catch (Throwable t) { check("DeleteCluster with active service -> ClusterContainsServicesException", false, t.toString()); }

        call("DeleteService (force)", () -> ecs.deleteService(b -> b.cluster(cname).service(svc).force(true)), r -> true);
        call("DeregisterTaskDefinition", () -> ecs.deregisterTaskDefinition(b -> b.taskDefinition(fam + ":1")),
                r -> r.taskDefinition().status() == TaskDefinitionStatus.INACTIVE);
        call("DeleteCluster", () -> ecs.deleteCluster(b -> b.cluster(cname)), r -> "INACTIVE".equals(r.cluster().status()));
        call("cluster gone after delete", () -> ecs.listClusters(), r -> !r.clusterArns().contains(arn));

        if (fails > 0) { System.out.println(fails + " check(s) failed"); System.exit(1); }
        System.out.println("all checks passed");
    }
}

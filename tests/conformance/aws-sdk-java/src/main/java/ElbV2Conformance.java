// Real aws-sdk-java-v2 ELBv2 conformance probe against Vyomi.
//
// Unmodified software.amazon.awssdk.services.elasticloadbalancingv2 with only the
// endpoint overridden. One [PASS]/[FAIL] line per check; exit code 1 on any failure.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=ElbV2Conformance

import java.net.URI;
import java.util.function.Supplier;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.elasticloadbalancingv2.ElasticLoadBalancingV2Client;
import software.amazon.awssdk.services.elasticloadbalancingv2.model.*;

public class ElbV2Conformance {

    static int pass = 0;
    static int fail = 0;

    static void chk(String name, boolean ok, String detail) {
        if (ok) {
            pass++;
            System.out.println("[PASS] " + name);
        } else {
            fail++;
            System.out.println("[FAIL] " + name + (detail == null || detail.isEmpty() ? "" : " :: " + detail));
        }
    }

    static <T> T run(String name, Supplier<T> fn) {
        try {
            T v = fn.get();
            chk(name, true, "");
            return v;
        } catch (Exception e) {
            chk(name, false, e.toString());
            return null;
        }
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        ElasticLoadBalancingV2Client elb = ElasticLoadBalancingV2Client.builder()
                .endpointOverride(URI.create(endpoint))
                .region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
                .build();
        String sfx = Long.toString(System.currentTimeMillis() % 1000000);
        String lbName = "jlb-" + sfx, tgName = "jtg-" + sfx;

        CreateLoadBalancerResponse clb = run("CreateLoadBalancer", () -> elb.createLoadBalancer(
                CreateLoadBalancerRequest.builder().name(lbName).subnets("subnet-aaa111", "subnet-bbb222")
                        .tags(Tag.builder().key("env").value("test").build()).build()));
        LoadBalancer lb = clb == null ? null : clb.loadBalancers().get(0);
        chk("load balancer is an internet-facing application LB",
                lb != null && lb.typeAsString().equals("application") && lb.schemeAsString().equals("internet-facing"), "");
        chk("DNS name and ARN are real-shaped", lb != null && lb.dnsName().endsWith(".elb.amazonaws.com")
                && lb.loadBalancerArn().contains(":loadbalancer/app/" + lbName + "/"), "");
        chk("two availability zones", lb != null && lb.availabilityZones().size() == 2, "");
        String lbArn = lb == null ? "" : lb.loadBalancerArn();

        DescribeLoadBalancersResponse dlb = run("DescribeLoadBalancers by name", () -> elb.describeLoadBalancers(
                DescribeLoadBalancersRequest.builder().names(lbName).build()));
        chk("describe returns the load balancer", dlb != null && dlb.loadBalancers().size() == 1, "");
        run("DescribeLoadBalancers waiter (load_balancer_available)", () -> elb.waiter().waitUntilLoadBalancerAvailable(
                DescribeLoadBalancersRequest.builder().loadBalancerArns(lbArn).build()));
        try {
            elb.describeLoadBalancers(DescribeLoadBalancersRequest.builder().names("no-such-lb-" + sfx).build());
            chk("unknown LB raises LoadBalancerNotFound", false, "no error");
        } catch (LoadBalancerNotFoundException e) {
            chk("unknown LB raises LoadBalancerNotFound", true, "");
        } catch (Exception e) {
            chk("unknown LB raises LoadBalancerNotFound", false, e.toString());
        }

        run("ModifyLoadBalancerAttributes", () -> elb.modifyLoadBalancerAttributes(
                ModifyLoadBalancerAttributesRequest.builder().loadBalancerArn(lbArn)
                        .attributes(LoadBalancerAttribute.builder().key("idle_timeout.timeout_seconds").value("120").build()).build()));
        DescribeLoadBalancerAttributesResponse attrs = run("DescribeLoadBalancerAttributes", () ->
                elb.describeLoadBalancerAttributes(DescribeLoadBalancerAttributesRequest.builder().loadBalancerArn(lbArn).build()));
        chk("idle timeout reads back", attrs != null && attrs.attributes().stream().anyMatch(
                a -> a.key().equals("idle_timeout.timeout_seconds") && a.value().equals("120")), "");

        CreateTargetGroupResponse ctg = run("CreateTargetGroup", () -> elb.createTargetGroup(
                CreateTargetGroupRequest.builder().name(tgName).protocol(ProtocolEnum.HTTP).port(8080)
                        .vpcId(lb == null ? "vpc-1" : lb.vpcId()).healthCheckPath("/health").build()));
        TargetGroup tg = ctg == null ? null : ctg.targetGroups().get(0);
        chk("target group defaults (instance, /health, 30s)", tg != null && tg.targetTypeAsString().equals("instance")
                && "/health".equals(tg.healthCheckPath()) && tg.healthCheckIntervalSeconds() == 30, "");
        String tgArn = tg == null ? "" : tg.targetGroupArn();
        run("ModifyTargetGroup", () -> elb.modifyTargetGroup(ModifyTargetGroupRequest.builder()
                .targetGroupArn(tgArn).healthCheckIntervalSeconds(15).build()));
        DescribeTargetGroupsResponse dtg = run("DescribeTargetGroups", () -> elb.describeTargetGroups(
                DescribeTargetGroupsRequest.builder().targetGroupArns(tgArn).build()));
        chk("modified health check interval reads back", dtg != null && dtg.targetGroups().get(0).healthCheckIntervalSeconds() == 15, "");

        run("RegisterTargets", () -> elb.registerTargets(RegisterTargetsRequest.builder().targetGroupArn(tgArn)
                .targets(TargetDescription.builder().id("i-0123456789abcdef0").build()).build()));
        DescribeTargetHealthResponse unused = run("DescribeTargetHealth (not attached)", () -> elb.describeTargetHealth(
                DescribeTargetHealthRequest.builder().targetGroupArn(tgArn).build()));
        chk("target is unused before a listener forwards to it", unused != null && unused.targetHealthDescriptions().size() == 1
                && unused.targetHealthDescriptions().get(0).targetHealth().stateAsString().equals("unused"), "");

        CreateListenerResponse cl = run("CreateListener", () -> elb.createListener(CreateListenerRequest.builder()
                .loadBalancerArn(lbArn).protocol(ProtocolEnum.HTTP).port(80)
                .defaultActions(Action.builder().type(ActionTypeEnum.FORWARD).targetGroupArn(tgArn).build()).build()));
        String lsArn = cl == null ? "" : cl.listeners().get(0).listenerArn();
        chk("listener forwards to the target group", cl != null && cl.listeners().get(0).defaultActions().get(0)
                .targetGroupArn().equals(tgArn), "");
        DescribeTargetHealthResponse healthy = run("DescribeTargetHealth (attached)", () -> elb.describeTargetHealth(
                DescribeTargetHealthRequest.builder().targetGroupArn(tgArn).build()));
        chk("target is healthy once attached", healthy != null
                && healthy.targetHealthDescriptions().get(0).targetHealth().stateAsString().equals("healthy"), "");
        try {
            elb.deleteTargetGroup(DeleteTargetGroupRequest.builder().targetGroupArn(tgArn).build());
            chk("deleting an in-use target group raises ResourceInUse", false, "no error");
        } catch (ResourceInUseException e) {
            chk("deleting an in-use target group raises ResourceInUse", true, "");
        } catch (Exception e) {
            chk("deleting an in-use target group raises ResourceInUse", false, e.toString());
        }

        CreateRuleResponse cr = run("CreateRule", () -> elb.createRule(CreateRuleRequest.builder().listenerArn(lsArn).priority(10)
                .conditions(RuleCondition.builder().field("path-pattern").values("/api/*").build())
                .actions(Action.builder().type(ActionTypeEnum.FIXED_RESPONSE).fixedResponseConfig(
                        FixedResponseActionConfig.builder().statusCode("200").contentType("text/plain").messageBody("ok").build()).build())
                .build()));
        String ruleArn = cr == null ? "" : cr.rules().get(0).ruleArn();
        DescribeRulesResponse rules = run("DescribeRules", () -> elb.describeRules(DescribeRulesRequest.builder().listenerArn(lsArn).build()));
        chk("custom rule plus the default rule", rules != null && rules.rules().size() == 2
                && rules.rules().get(1).isDefault(), "");
        run("SetRulePriorities", () -> elb.setRulePriorities(SetRulePrioritiesRequest.builder()
                .rulePriorities(RulePriorityPair.builder().ruleArn(ruleArn).priority(20).build()).build()));
        run("ModifyRule", () -> elb.modifyRule(ModifyRuleRequest.builder().ruleArn(ruleArn)
                .conditions(RuleCondition.builder().field("host-header").values("example.com").build()).build()));
        run("DeleteRule", () -> elb.deleteRule(DeleteRuleRequest.builder().ruleArn(ruleArn).build()));

        run("AddTags", () -> elb.addTags(AddTagsRequest.builder().resourceArns(lbArn)
                .tags(Tag.builder().key("team").value("platform").build()).build()));
        DescribeTagsResponse tags = run("DescribeTags", () -> elb.describeTags(DescribeTagsRequest.builder().resourceArns(lbArn).build()));
        chk("both tags present", tags != null && tags.tagDescriptions().get(0).tags().size() == 2, "");
        run("RemoveTags", () -> elb.removeTags(RemoveTagsRequest.builder().resourceArns(lbArn).tagKeys("team").build()));

        run("DescribeSSLPolicies", () -> elb.describeSSLPolicies(DescribeSslPoliciesRequest.builder().build()));
        run("DescribeAccountLimits", () -> elb.describeAccountLimits(DescribeAccountLimitsRequest.builder().build()));

        run("DeregisterTargets", () -> elb.deregisterTargets(DeregisterTargetsRequest.builder().targetGroupArn(tgArn)
                .targets(TargetDescription.builder().id("i-0123456789abcdef0").build()).build()));
        run("DeleteListener", () -> elb.deleteListener(DeleteListenerRequest.builder().listenerArn(lsArn).build()));
        run("DeleteTargetGroup", () -> elb.deleteTargetGroup(DeleteTargetGroupRequest.builder().targetGroupArn(tgArn).build()));
        run("DeleteLoadBalancer", () -> elb.deleteLoadBalancer(DeleteLoadBalancerRequest.builder().loadBalancerArn(lbArn).build()));
        try {
            elb.describeLoadBalancers(DescribeLoadBalancersRequest.builder().loadBalancerArns(lbArn).build());
            chk("deleted LB is gone", false, "still described");
        } catch (LoadBalancerNotFoundException e) {
            chk("deleted LB is gone", true, "");
        } catch (Exception e) {
            chk("deleted LB is gone", false, e.toString());
        }

        System.out.println("pass=" + pass + " fail=" + fail);
        System.exit(fail == 0 ? 0 : 1);
    }
}

// Real aws-sdk-go-v2 ELBv2 conformance probe against Vyomi.
//
// Unmodified github.com/aws/aws-sdk-go-v2/service/elasticloadbalancingv2 with only
// BaseEndpoint overridden. One [PASS]/[FAIL] line per check; exit 1 on failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	elb "github.com/aws/aws-sdk-go-v2/service/elasticloadbalancingv2"
	"github.com/aws/aws-sdk-go-v2/service/elasticloadbalancingv2/types"
)

var pass, fail int

func chk(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fail++
	if detail != "" {
		fmt.Printf("[FAIL] %s :: %s\n", name, detail)
	} else {
		fmt.Printf("[FAIL] %s\n", name)
	}
}

func step(name string, err error) bool {
	if err != nil {
		chk(name, false, err.Error())
		return false
	}
	chk(name, true, "")
	return true
}

func main() {
	endpoint := os.Getenv("ENDPOINT")
	if endpoint == "" {
		endpoint = "http://127.0.0.1:9000"
	}
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx,
		config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Println("[FAIL] load config ::", err)
		os.Exit(1)
	}
	c := elb.NewFromConfig(cfg, func(o *elb.Options) { o.BaseEndpoint = aws.String(endpoint) })
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000)
	lbName, tgName := "glb-"+sfx, "gtg-"+sfx

	// Network load balancer (one subnet is enough) + an application one.
	nlb, err := c.CreateLoadBalancer(ctx, &elb.CreateLoadBalancerInput{
		Name: aws.String("gnlb-" + sfx), Type: types.LoadBalancerTypeEnumNetwork, Subnets: []string{"subnet-aaa111"}})
	if step("CreateLoadBalancer (network)", err) {
		chk("network LB arn is loadbalancer/net/", strings.Contains(*nlb.LoadBalancers[0].LoadBalancerArn, ":loadbalancer/net/"), "")
		_, err = c.DeleteLoadBalancer(ctx, &elb.DeleteLoadBalancerInput{LoadBalancerArn: nlb.LoadBalancers[0].LoadBalancerArn})
		step("DeleteLoadBalancer (network)", err)
	}
	_, err = c.CreateLoadBalancer(ctx, &elb.CreateLoadBalancerInput{Name: aws.String("one-subnet-" + sfx), Subnets: []string{"subnet-aaa111"}})
	chk("application LB needs two subnets (ValidationError)", err != nil && strings.Contains(err.Error(), "ValidationError"), fmt.Sprint(err))

	clb, err := c.CreateLoadBalancer(ctx, &elb.CreateLoadBalancerInput{
		Name: &lbName, Subnets: []string{"subnet-aaa111", "subnet-bbb222"}, Scheme: types.LoadBalancerSchemeEnumInternal,
		Tags: []types.Tag{{Key: aws.String("env"), Value: aws.String("test")}}})
	if !step("CreateLoadBalancer", err) {
		os.Exit(1)
	}
	lb := clb.LoadBalancers[0]
	chk("internal scheme has the internal- DNS prefix", strings.HasPrefix(*lb.DNSName, "internal-"+lbName), *lb.DNSName)
	lbArn := *lb.LoadBalancerArn
	_, err = c.CreateLoadBalancer(ctx, &elb.CreateLoadBalancerInput{
		Name: &lbName, Subnets: []string{"subnet-aaa111", "subnet-bbb222"}, Scheme: types.LoadBalancerSchemeEnumInternetFacing})
	var dup *types.DuplicateLoadBalancerNameException
	chk("same name, different settings -> DuplicateLoadBalancerName", errors.As(err, &dup), fmt.Sprint(err))

	d, err := c.DescribeLoadBalancers(ctx, &elb.DescribeLoadBalancersInput{LoadBalancerArns: []string{lbArn}})
	if step("DescribeLoadBalancers", err) {
		chk("state is active", d.LoadBalancers[0].State.Code == types.LoadBalancerStateEnumActive, string(d.LoadBalancers[0].State.Code))
	}
	_, err = c.SetSecurityGroups(ctx, &elb.SetSecurityGroupsInput{LoadBalancerArn: &lbArn, SecurityGroups: []string{"sg-0123abcd"}})
	step("SetSecurityGroups", err)
	_, err = c.SetIpAddressType(ctx, &elb.SetIpAddressTypeInput{LoadBalancerArn: &lbArn, IpAddressType: types.IpAddressTypeDualstack})
	step("SetIpAddressType", err)
	_, err = c.SetSubnets(ctx, &elb.SetSubnetsInput{LoadBalancerArn: &lbArn, Subnets: []string{"subnet-aaa111", "subnet-bbb222", "subnet-ccc333"}})
	step("SetSubnets", err)
	d, err = c.DescribeLoadBalancers(ctx, &elb.DescribeLoadBalancersInput{Names: []string{lbName}})
	if step("DescribeLoadBalancers (after updates)", err) {
		x := d.LoadBalancers[0]
		chk("security group, dualstack and 3 AZs read back", len(x.SecurityGroups) == 1 && x.IpAddressType == types.IpAddressTypeDualstack && len(x.AvailabilityZones) == 3, "")
	}

	tg, err := c.CreateTargetGroup(ctx, &elb.CreateTargetGroupInput{Name: &tgName, Protocol: types.ProtocolEnumHttp,
		Port: aws.Int32(9000), VpcId: lb.VpcId, TargetType: types.TargetTypeEnumIp})
	if !step("CreateTargetGroup (ip)", err) {
		os.Exit(1)
	}
	tgArn := *tg.TargetGroups[0].TargetGroupArn
	chk("default matcher 200 and path /", tg.TargetGroups[0].Matcher != nil && *tg.TargetGroups[0].Matcher.HttpCode == "200" && *tg.TargetGroups[0].HealthCheckPath == "/", "")
	_, err = c.RegisterTargets(ctx, &elb.RegisterTargetsInput{TargetGroupArn: &tgArn, Targets: []types.TargetDescription{{Id: aws.String("not-an-ip")}}})
	chk("invalid IP target -> ValidationError", err != nil, "")
	_, err = c.RegisterTargets(ctx, &elb.RegisterTargetsInput{TargetGroupArn: &tgArn, Targets: []types.TargetDescription{
		{Id: aws.String("10.0.1.10"), Port: aws.Int32(9000)}, {Id: aws.String("10.0.1.11"), Port: aws.Int32(9001)}}})
	step("RegisterTargets (2 IPs)", err)
	h, err := c.DescribeTargetHealth(ctx, &elb.DescribeTargetHealthInput{TargetGroupArn: &tgArn,
		Targets: []types.TargetDescription{{Id: aws.String("10.0.1.11"), Port: aws.Int32(9001)}}})
	if step("DescribeTargetHealth (one target)", err) {
		chk("filtered to the requested target", len(h.TargetHealthDescriptions) == 1 && *h.TargetHealthDescriptions[0].Target.Port == 9001, "")
		chk("reason Target.NotInUse while unattached", h.TargetHealthDescriptions[0].TargetHealth.Reason == types.TargetHealthReasonEnumNotInUse, "")
	}

	ls, err := c.CreateListener(ctx, &elb.CreateListenerInput{LoadBalancerArn: &lbArn, Protocol: types.ProtocolEnumHttp, Port: aws.Int32(80),
		DefaultActions: []types.Action{{Type: types.ActionTypeEnumRedirect, RedirectConfig: &types.RedirectActionConfig{
			Protocol: aws.String("HTTPS"), Port: aws.String("443"), StatusCode: types.RedirectActionStatusCodeEnumHttp301}}}})
	if !step("CreateListener (redirect)", err) {
		os.Exit(1)
	}
	lsArn := *ls.Listeners[0].ListenerArn
	_, err = c.CreateListener(ctx, &elb.CreateListenerInput{LoadBalancerArn: &lbArn, Protocol: types.ProtocolEnumHttp, Port: aws.Int32(80),
		DefaultActions: []types.Action{{Type: types.ActionTypeEnumForward, TargetGroupArn: &tgArn}}})
	var dl *types.DuplicateListenerException
	chk("same port -> DuplicateListener", errors.As(err, &dl), fmt.Sprint(err))
	_, err = c.CreateListener(ctx, &elb.CreateListenerInput{LoadBalancerArn: &lbArn, Protocol: types.ProtocolEnumHttps, Port: aws.Int32(443),
		DefaultActions: []types.Action{{Type: types.ActionTypeEnumForward, TargetGroupArn: &tgArn}}})
	chk("HTTPS without a certificate -> error", err != nil, "")
	_, err = c.ModifyListener(ctx, &elb.ModifyListenerInput{ListenerArn: &lsArn, Port: aws.Int32(8080),
		DefaultActions: []types.Action{{Type: types.ActionTypeEnumForward, TargetGroupArn: &tgArn}}})
	step("ModifyListener (port + forward)", err)
	ds, err := c.DescribeListeners(ctx, &elb.DescribeListenersInput{LoadBalancerArn: &lbArn})
	if step("DescribeListeners", err) {
		chk("listener now on 8080 forwarding to the target group", len(ds.Listeners) == 1 && *ds.Listeners[0].Port == 8080 &&
			*ds.Listeners[0].DefaultActions[0].TargetGroupArn == tgArn, "")
	}
	h, err = c.DescribeTargetHealth(ctx, &elb.DescribeTargetHealthInput{TargetGroupArn: &tgArn})
	if step("DescribeTargetHealth (attached)", err) {
		chk("both targets healthy", len(h.TargetHealthDescriptions) == 2 && h.TargetHealthDescriptions[0].TargetHealth.State == types.TargetHealthStateEnumHealthy, "")
	}
	tgd, err := c.DescribeTargetGroups(ctx, &elb.DescribeTargetGroupsInput{LoadBalancerArn: &lbArn})
	if step("DescribeTargetGroups by load balancer", err) {
		chk("target group lists its load balancer", len(tgd.TargetGroups) == 1 && len(tgd.TargetGroups[0].LoadBalancerArns) == 1, "")
	}

	_, err = c.ModifyTargetGroupAttributes(ctx, &elb.ModifyTargetGroupAttributesInput{TargetGroupArn: &tgArn,
		Attributes: []types.TargetGroupAttribute{{Key: aws.String("deregistration_delay.timeout_seconds"), Value: aws.String("30")}}})
	step("ModifyTargetGroupAttributes", err)
	at, err := c.DescribeTargetGroupAttributes(ctx, &elb.DescribeTargetGroupAttributesInput{TargetGroupArn: &tgArn})
	if step("DescribeTargetGroupAttributes", err) {
		ok := false
		for _, a := range at.Attributes {
			if *a.Key == "deregistration_delay.timeout_seconds" && *a.Value == "30" {
				ok = true
			}
		}
		chk("deregistration delay reads back", ok, "")
	}

	r1, err := c.CreateRule(ctx, &elb.CreateRuleInput{ListenerArn: &lsArn, Priority: aws.Int32(1), Conditions: []types.RuleCondition{
		{Field: aws.String("http-header"), HttpHeaderConfig: &types.HttpHeaderConditionConfig{HttpHeaderName: aws.String("X-Env"), Values: []string{"canary"}}}},
		Actions: []types.Action{{Type: types.ActionTypeEnumForward, ForwardConfig: &types.ForwardActionConfig{TargetGroups: []types.TargetGroupTuple{
			{TargetGroupArn: &tgArn, Weight: aws.Int32(5)}}}}}})
	step("CreateRule (http-header + weighted forward)", err)
	_, err = c.CreateRule(ctx, &elb.CreateRuleInput{ListenerArn: &lsArn, Priority: aws.Int32(1), Conditions: []types.RuleCondition{
		{Field: aws.String("path-pattern"), Values: []string{"/x"}}},
		Actions: []types.Action{{Type: types.ActionTypeEnumFixedResponse, FixedResponseConfig: &types.FixedResponseActionConfig{StatusCode: aws.String("404")}}}})
	var pu *types.PriorityInUseException
	chk("duplicate priority -> PriorityInUse", errors.As(err, &pu), fmt.Sprint(err))
	if r1 != nil {
		_, err = c.DeleteRule(ctx, &elb.DeleteRuleInput{RuleArn: r1.Rules[0].RuleArn})
		step("DeleteRule", err)
	}
	rs, err := c.DescribeRules(ctx, &elb.DescribeRulesInput{ListenerArn: &lsArn})
	if step("DescribeRules", err) {
		chk("only the default rule remains", len(rs.Rules) == 1 && *rs.Rules[0].IsDefault, "")
		_, err = c.DeleteRule(ctx, &elb.DeleteRuleInput{RuleArn: rs.Rules[0].RuleArn})
		chk("the default rule cannot be deleted", err != nil, "")
	}

	tags, err := c.DescribeTags(ctx, &elb.DescribeTagsInput{ResourceArns: []string{lbArn, tgArn}})
	if step("DescribeTags", err) {
		chk("LB carries its tag, target group none", len(tags.TagDescriptions) == 2 && len(tags.TagDescriptions[0].Tags) == 1 && len(tags.TagDescriptions[1].Tags) == 0, "")
	}

	pol, err := c.DescribeSSLPolicies(ctx, &elb.DescribeSSLPoliciesInput{Names: []string{"ELBSecurityPolicy-TLS13-1-2-2021-06"}})
	if step("DescribeSSLPolicies", err) {
		chk("TLS 1.3 policy lists TLSv1.3", len(pol.SslPolicies) == 1 && len(pol.SslPolicies[0].SslProtocols) == 2, "")
	}

	_, err = c.ModifyLoadBalancerAttributes(ctx, &elb.ModifyLoadBalancerAttributesInput{LoadBalancerArn: &lbArn,
		Attributes: []types.LoadBalancerAttribute{{Key: aws.String("deletion_protection.enabled"), Value: aws.String("true")}}})
	step("ModifyLoadBalancerAttributes (deletion protection)", err)
	_, err = c.DeleteLoadBalancer(ctx, &elb.DeleteLoadBalancerInput{LoadBalancerArn: &lbArn})
	var np *types.OperationNotPermittedException
	chk("deletion protection blocks delete (OperationNotPermitted)", errors.As(err, &np), fmt.Sprint(err))
	_, err = c.ModifyLoadBalancerAttributes(ctx, &elb.ModifyLoadBalancerAttributesInput{LoadBalancerArn: &lbArn,
		Attributes: []types.LoadBalancerAttribute{{Key: aws.String("deletion_protection.enabled"), Value: aws.String("false")}}})
	step("ModifyLoadBalancerAttributes (protection off)", err)

	_, err = c.DeregisterTargets(ctx, &elb.DeregisterTargetsInput{TargetGroupArn: &tgArn, Targets: []types.TargetDescription{
		{Id: aws.String("10.0.1.10"), Port: aws.Int32(9000)}}})
	step("DeregisterTargets", err)
	h, err = c.DescribeTargetHealth(ctx, &elb.DescribeTargetHealthInput{TargetGroupArn: &tgArn})
	if step("DescribeTargetHealth (after deregister)", err) {
		chk("one target left", len(h.TargetHealthDescriptions) == 1, "")
	}
	_, err = c.DeleteLoadBalancer(ctx, &elb.DeleteLoadBalancerInput{LoadBalancerArn: &lbArn})
	step("DeleteLoadBalancer (cascades listeners)", err)
	_, err = c.DeleteTargetGroup(ctx, &elb.DeleteTargetGroupInput{TargetGroupArn: &tgArn})
	step("DeleteTargetGroup (free after the LB is gone)", err)
	_, err = c.DescribeListeners(ctx, &elb.DescribeListenersInput{ListenerArns: []string{lsArn}})
	var lnf *types.ListenerNotFoundException
	chk("listener is gone with its load balancer", errors.As(err, &lnf), fmt.Sprint(err))

	fmt.Printf("pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}

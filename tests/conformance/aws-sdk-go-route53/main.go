// Real aws-sdk-go-v2 Route 53 conformance probe against Vyomi.
//
// Unmodified github.com/aws/aws-sdk-go-v2/service/route53 with only BaseEndpoint
// overridden. One [PASS]/[FAIL] line per check; exit 1 on failure.
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
	"github.com/aws/aws-sdk-go-v2/service/route53"
	"github.com/aws/aws-sdk-go-v2/service/route53/types"
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

func rrset(name string, t types.RRType, ttl int64, vals ...string) *types.ResourceRecordSet {
	rs := &types.ResourceRecordSet{Name: aws.String(name), Type: t, TTL: aws.Int64(ttl)}
	for _, v := range vals {
		rs.ResourceRecords = append(rs.ResourceRecords, types.ResourceRecord{Value: aws.String(v)})
	}
	return rs
}

func change(a types.ChangeAction, rs *types.ResourceRecordSet) types.Change {
	return types.Change{Action: a, ResourceRecordSet: rs}
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
	r := route53.NewFromConfig(cfg, func(o *route53.Options) { o.BaseEndpoint = aws.String(endpoint) })

	sfx := fmt.Sprintf("%d", time.Now().UnixNano()/1e6%1000000)
	zone := "go-" + sfx + ".example.com"

	cz, err := r.CreateHostedZone(ctx, &route53.CreateHostedZoneInput{
		Name: aws.String(zone), CallerReference: aws.String("go-" + sfx),
		HostedZoneConfig: &types.HostedZoneConfig{Comment: aws.String("go sdk")},
	})
	if !step("CreateHostedZone", err) {
		os.Exit(1)
	}
	zid := strings.TrimPrefix(aws.ToString(cz.HostedZone.Id), "/hostedzone/")
	chk("zone id is real-shaped and name is absolute", strings.HasPrefix(aws.ToString(cz.HostedZone.Id), "/hostedzone/Z") && aws.ToString(cz.HostedZone.Name) == zone+".", aws.ToString(cz.HostedZone.Name))
	chk("CreateHostedZone returns 4 name servers and a PENDING change", cz.DelegationSet != nil && len(cz.DelegationSet.NameServers) == 4 && cz.ChangeInfo.Status == types.ChangeStatusPending, "")

	gz, err := r.GetHostedZone(ctx, &route53.GetHostedZoneInput{Id: aws.String(zid)})
	if step("GetHostedZone", err) {
		chk("GetHostedZone has SOA+NS and the comment", aws.ToInt64(gz.HostedZone.ResourceRecordSetCount) == 2 && aws.ToString(gz.HostedZone.Config.Comment) == "go sdk", "")
	}
	_, err = r.CreateHostedZone(ctx, &route53.CreateHostedZoneInput{Name: aws.String(zone), CallerReference: aws.String("go-" + sfx)})
	var exists *types.HostedZoneAlreadyExists
	chk("duplicate caller reference -> HostedZoneAlreadyExists", errors.As(err, &exists), fmt.Sprint(err))
	_, err = r.GetHostedZone(ctx, &route53.GetHostedZoneInput{Id: aws.String("ZNOSUCHZONE")})
	var nsz *types.NoSuchHostedZone
	chk("unknown zone -> NoSuchHostedZone", errors.As(err, &nsz), fmt.Sprint(err))

	lz, err := r.ListHostedZones(ctx, &route53.ListHostedZonesInput{})
	if step("ListHostedZones", err) {
		found := false
		for _, z := range lz.HostedZones {
			if aws.ToString(z.Name) == zone+"." {
				found = true
			}
		}
		chk("ListHostedZones contains the zone", found, "")
	}
	lbn, err := r.ListHostedZonesByName(ctx, &route53.ListHostedZonesByNameInput{DNSName: aws.String(zone)})
	if step("ListHostedZonesByName", err) {
		chk("ListHostedZonesByName starts at the zone", len(lbn.HostedZones) > 0 && aws.ToString(lbn.HostedZones[0].Name) == zone+".", "")
	}
	cnt, err := r.GetHostedZoneCount(ctx, &route53.GetHostedZoneCountInput{})
	if step("GetHostedZoneCount", err) {
		chk("GetHostedZoneCount >= 1", aws.ToInt64(cnt.HostedZoneCount) >= 1, "")
	}

	// Records
	crr, err := r.ChangeResourceRecordSets(ctx, &route53.ChangeResourceRecordSetsInput{
		HostedZoneId: aws.String(zid),
		ChangeBatch: &types.ChangeBatch{Comment: aws.String("go"), Changes: []types.Change{
			change(types.ChangeActionCreate, rrset("www."+zone, types.RRTypeA, 300, "192.0.2.10", "192.0.2.11")),
			change(types.ChangeActionCreate, rrset("*."+zone, types.RRTypeTxt, 60, "\"wild\"")),
			change(types.ChangeActionCreate, rrset("mail."+zone, types.RRTypeMx, 300, "10 mx."+zone)),
		}},
	})
	if step("ChangeResourceRecordSets (CREATE x3)", err) {
		chk("change is PENDING with a /change/ id", crr.ChangeInfo.Status == types.ChangeStatusPending && strings.HasPrefix(aws.ToString(crr.ChangeInfo.Id), "/change/"), "")
		gc, err := r.GetChange(ctx, &route53.GetChangeInput{Id: crr.ChangeInfo.Id})
		if step("GetChange", err) {
			chk("GetChange is INSYNC", gc.ChangeInfo.Status == types.ChangeStatusInsync, "")
		}
		w := route53.NewResourceRecordSetsChangedWaiter(r)
		step("ResourceRecordSetsChanged waiter", w.Wait(ctx, &route53.GetChangeInput{Id: crr.ChangeInfo.Id}, 20*time.Second))
	}
	lr, err := r.ListResourceRecordSets(ctx, &route53.ListResourceRecordSetsInput{HostedZoneId: aws.String(zid)})
	if step("ListResourceRecordSets", err) {
		var gotA, wild bool
		for _, rs := range lr.ResourceRecordSets {
			if aws.ToString(rs.Name) == "www."+zone+"." && rs.Type == types.RRTypeA && len(rs.ResourceRecords) == 2 && aws.ToInt64(rs.TTL) == 300 {
				gotA = true
			}
			if strings.HasPrefix(aws.ToString(rs.Name), "\\052.") {
				wild = true
			}
		}
		chk("A record round-trips (2 values, TTL 300)", gotA, "")
		chk("wildcard name uses the \\052 escape", wild, "")
		chk("5 record sets incl. SOA and NS", len(lr.ResourceRecordSets) == 5, fmt.Sprint(len(lr.ResourceRecordSets)))
	}
	one, err := r.ListResourceRecordSets(ctx, &route53.ListResourceRecordSetsInput{HostedZoneId: aws.String(zid), MaxItems: aws.Int32(2)})
	if step("ListResourceRecordSets (MaxItems=2)", err) {
		chk("pagination is truncated with a next record", one.IsTruncated && one.NextRecordName != nil, "")
	}
	_, err = r.ChangeResourceRecordSets(ctx, &route53.ChangeResourceRecordSetsInput{
		HostedZoneId: aws.String(zid),
		ChangeBatch:  &types.ChangeBatch{Changes: []types.Change{change(types.ChangeActionCreate, rrset("www."+zone, types.RRTypeA, 300, "1.1.1.1"))}},
	})
	var icb *types.InvalidChangeBatch
	chk("CREATE of an existing record -> InvalidChangeBatch", errors.As(err, &icb), fmt.Sprint(err))
	_, err = r.ChangeResourceRecordSets(ctx, &route53.ChangeResourceRecordSetsInput{
		HostedZoneId: aws.String(zid),
		ChangeBatch:  &types.ChangeBatch{Changes: []types.Change{change(types.ChangeActionUpsert, rrset("www."+zone, types.RRTypeA, 120, "192.0.2.99"))}},
	})
	step("UPSERT", err)
	ans, err := r.TestDNSAnswer(ctx, &route53.TestDNSAnswerInput{HostedZoneId: aws.String(zid), RecordName: aws.String("www." + zone), RecordType: types.RRTypeA})
	if step("TestDNSAnswer", err) {
		chk("TestDNSAnswer returns the upserted value", len(ans.RecordData) == 1 && ans.RecordData[0] == "192.0.2.99" && aws.ToString(ans.ResponseCode) == "NOERROR", fmt.Sprint(ans.RecordData))
	}
	_, err = r.DeleteHostedZone(ctx, &route53.DeleteHostedZoneInput{Id: aws.String(zid)})
	var hne *types.HostedZoneNotEmpty
	chk("non-empty zone -> HostedZoneNotEmpty", errors.As(err, &hne), fmt.Sprint(err))

	// Tags
	_, err = r.ChangeTagsForResource(ctx, &route53.ChangeTagsForResourceInput{ResourceType: types.TagResourceTypeHostedzone, ResourceId: aws.String(zid),
		AddTags: []types.Tag{{Key: aws.String("env"), Value: aws.String("go")}}})
	step("ChangeTagsForResource", err)
	lt, err := r.ListTagsForResource(ctx, &route53.ListTagsForResourceInput{ResourceType: types.TagResourceTypeHostedzone, ResourceId: aws.String(zid)})
	if step("ListTagsForResource", err) {
		chk("tag round-trips", len(lt.ResourceTagSet.Tags) == 1 && aws.ToString(lt.ResourceTagSet.Tags[0].Value) == "go", "")
	}
	_, err = r.UpdateHostedZoneComment(ctx, &route53.UpdateHostedZoneCommentInput{Id: aws.String(zid), Comment: aws.String("updated")})
	step("UpdateHostedZoneComment", err)

	// Health checks
	hc, err := r.CreateHealthCheck(ctx, &route53.CreateHealthCheckInput{CallerReference: aws.String("hc-" + sfx), HealthCheckConfig: &types.HealthCheckConfig{
		Type: types.HealthCheckTypeHttps, FullyQualifiedDomainName: aws.String("www." + zone), ResourcePath: aws.String("/health")}})
	if step("CreateHealthCheck", err) {
		c := hc.HealthCheck.HealthCheckConfig
		chk("health check defaults (port 443, interval 30, threshold 3)", aws.ToInt32(c.Port) == 443 && aws.ToInt32(c.RequestInterval) == 30 && aws.ToInt32(c.FailureThreshold) == 3, "")
		hid := aws.ToString(hc.HealthCheck.Id)
		_, err = r.UpdateHealthCheck(ctx, &route53.UpdateHealthCheckInput{HealthCheckId: aws.String(hid), FailureThreshold: aws.Int32(5)})
		step("UpdateHealthCheck", err)
		g, err := r.GetHealthCheck(ctx, &route53.GetHealthCheckInput{HealthCheckId: aws.String(hid)})
		if step("GetHealthCheck", err) {
			chk("update bumped threshold and version", aws.ToInt32(g.HealthCheck.HealthCheckConfig.FailureThreshold) == 5 && aws.ToInt64(g.HealthCheck.HealthCheckVersion) == 2, "")
		}
		st, err := r.GetHealthCheckStatus(ctx, &route53.GetHealthCheckStatusInput{HealthCheckId: aws.String(hid)})
		if step("GetHealthCheckStatus", err) {
			chk("status has observations", len(st.HealthCheckObservations) > 0, "")
		}
		lh, err := r.ListHealthChecks(ctx, &route53.ListHealthChecksInput{})
		if step("ListHealthChecks", err) {
			chk("ListHealthChecks contains it", len(lh.HealthChecks) >= 1, "")
		}
		_, err = r.DeleteHealthCheck(ctx, &route53.DeleteHealthCheckInput{HealthCheckId: aws.String(hid)})
		step("DeleteHealthCheck", err)
		_, err = r.GetHealthCheck(ctx, &route53.GetHealthCheckInput{HealthCheckId: aws.String(hid)})
		var nhc *types.NoSuchHealthCheck
		chk("deleted health check -> NoSuchHealthCheck", errors.As(err, &nhc), fmt.Sprint(err))
	}

	// Delegation set + limits
	ds, err := r.CreateReusableDelegationSet(ctx, &route53.CreateReusableDelegationSetInput{CallerReference: aws.String("ds-" + sfx)})
	if step("CreateReusableDelegationSet", err) {
		_, err = r.GetReusableDelegationSet(ctx, &route53.GetReusableDelegationSetInput{Id: ds.DelegationSet.Id})
		step("GetReusableDelegationSet", err)
		_, err = r.DeleteReusableDelegationSet(ctx, &route53.DeleteReusableDelegationSetInput{Id: ds.DelegationSet.Id})
		step("DeleteReusableDelegationSet", err)
	}
	lim, err := r.GetAccountLimit(ctx, &route53.GetAccountLimitInput{Type: types.AccountLimitTypeMaxHostedZonesByOwner})
	if step("GetAccountLimit", err) {
		chk("hosted zone limit is 500", aws.ToInt64(lim.Limit.Value) == 500, "")
	}

	// Cleanup
	_, err = r.ChangeResourceRecordSets(ctx, &route53.ChangeResourceRecordSetsInput{
		HostedZoneId: aws.String(zid),
		ChangeBatch: &types.ChangeBatch{Changes: []types.Change{
			change(types.ChangeActionDelete, rrset("www."+zone, types.RRTypeA, 120, "192.0.2.99")),
			change(types.ChangeActionDelete, rrset("*."+zone, types.RRTypeTxt, 60, "\"wild\"")),
			change(types.ChangeActionDelete, rrset("mail."+zone, types.RRTypeMx, 300, "10 mx."+zone)),
		}},
	})
	step("ChangeResourceRecordSets (DELETE x3)", err)
	_, err = r.DeleteHostedZone(ctx, &route53.DeleteHostedZoneInput{Id: aws.String(zid)})
	step("DeleteHostedZone", err)
	_, err = r.GetHostedZone(ctx, &route53.GetHostedZoneInput{Id: aws.String(zid)})
	chk("deleted zone -> NoSuchHostedZone", errors.As(err, &nsz), fmt.Sprint(err))

	fmt.Printf("== %d passed, %d failed ==\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}

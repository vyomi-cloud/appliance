// Azure Cache for Redis conformance: the real azure-sdk-for-go armredis client against Vyomi — only the
// ARM endpoint changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/arm"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/cloud"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	redis "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/redis/armredis/v2"
)

type fakeCred struct{}

func (fakeCred) GetToken(_ context.Context, _ policy.TokenRequestOptions) (azcore.AccessToken, error) {
	return azcore.AccessToken{Token: "fake-token", ExpiresOn: time.Now().Add(time.Hour)}, nil
}

var failed int

var poll = runtime.PollUntilDoneOptions{Frequency: time.Second}

func check(name string, ok bool, detail string) {
	if ok {
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	failed++
	fmt.Printf("[FAIL] %s %s\n", name, detail)
}

func status(err error) int {
	var re *azcore.ResponseError
	if errors.As(err, &re) {
		return re.StatusCode
	}
	return 0
}

func main() {
	ep := os.Getenv("ENDPOINT")
	if ep == "" {
		ep = "http://127.0.0.1:9000"
	}
	sub := os.Getenv("SUB")
	if sub == "" {
		sub = "00000000-0000-0000-0000-cloudlearn01"
	}
	suffix := time.Now().Unix() % 1000000
	rg := "cloudlearn-rg"
	name := fmt.Sprintf("go-cache-%d", suffix)
	prem := fmt.Sprintf("go-prem-%d", suffix)
	prem2 := fmt.Sprintf("go-prem2-%d", suffix)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	cred := fakeCred{}
	client, err := redis.NewClient(sub, cred, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	fw, _ := redis.NewFirewallRulesClient(sub, cred, opts)
	ps, _ := redis.NewPatchSchedulesClient(sub, cred, opts)
	ls, _ := redis.NewLinkedServerClient(sub, cred, opts)

	defer func() {
		for _, n := range []string{name, prem, prem2} {
			if p, e := client.BeginDelete(ctx, rg, n, nil); e == nil {
				_, _ = p.PollUntilDone(ctx, &poll)
			}
		}
	}()

	// ── create ─────────────────────────────────────────────
	avail, err := client.CheckNameAvailability(ctx, redis.CheckNameAvailabilityParameters{Name: to.Ptr(name), Type: to.Ptr("Microsoft.Cache/Redis")}, nil)
	_ = avail
	check("CheckNameAvailability: free name → 200", err == nil, fmt.Sprint(err))

	cp, err := client.BeginCreate(ctx, rg, name, redis.CreateParameters{
		Location: to.Ptr("eastus"), Tags: map[string]*string{"env": to.Ptr("conf")},
		Properties: &redis.CreateProperties{
			SKU:                &redis.SKU{Name: to.Ptr(redis.SKUNameBasic), Family: to.Ptr(redis.SKUFamilyC), Capacity: to.Ptr[int32](0)},
			EnableNonSSLPort:   to.Ptr(false),
			MinimumTLSVersion:  to.Ptr(redis.TLSVersionOne2),
			RedisConfiguration: &redis.CommonPropertiesRedisConfiguration{MaxmemoryPolicy: to.Ptr("allkeys-lru")},
		},
	}, nil)
	var cache redis.ResourceInfo
	if err == nil {
		var res redis.ClientCreateResponse
		res, err = cp.PollUntilDone(ctx, &poll)
		cache = res.ResourceInfo
	}
	check("BeginCreate Basic C0 → Succeeded", err == nil && cache.Properties != nil && *cache.Properties.ProvisioningState == redis.ProvisioningStateSucceeded, fmt.Sprint(err))
	if err != nil {
		os.Exit(1)
	}
	hn := *cache.Properties.HostName
	check("host name, ports and Redis type", hn == name+".redis.cache.windows.net" && *cache.Properties.SSLPort == 6380 && *cache.Properties.Port == 6379 &&
		*cache.Type == "Microsoft.Cache/Redis", hn)
	check("redisConfiguration: policy kept, maxclients computed", *cache.Properties.RedisConfiguration.MaxmemoryPolicy == "allkeys-lru" &&
		*cache.Properties.RedisConfiguration.Maxclients == "256", "")

	_, err = client.CheckNameAvailability(ctx, redis.CheckNameAvailabilityParameters{Name: to.Ptr(name), Type: to.Ptr("Microsoft.Cache/Redis")}, nil)
	check("CheckNameAvailability: taken name → 409", status(err) == 409, fmt.Sprint(err))

	got, err := client.Get(ctx, rg, name, nil)
	check("Get returns the cache without keys", err == nil && *got.Name == name && *got.Tags["env"] == "conf", fmt.Sprint(err))
	_, err = client.Get(ctx, rg, "go-missing-"+fmt.Sprint(suffix), nil)
	check("Get missing → 404", status(err) == 404, fmt.Sprint(err))

	found := false
	pg := client.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		page, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, c := range page.Value {
			if c.Name != nil && *c.Name == name {
				found = true
			}
		}
	}
	check("ListByResourceGroup contains the cache", found, fmt.Sprint(err))
	found = false
	sp := client.NewListBySubscriptionPager(nil)
	for sp.More() {
		page, e := sp.NextPage(ctx)
		if e != nil {
			break
		}
		for _, c := range page.Value {
			if c.Name != nil && *c.Name == name {
				found = true
			}
		}
	}
	check("ListBySubscription contains the cache", found, "")

	// ── update (scale + config) ────────────────────────────
	up, err := client.BeginUpdate(ctx, rg, name, redis.UpdateParameters{
		Tags: map[string]*string{"env": to.Ptr("updated")},
		Properties: &redis.UpdateProperties{
			SKU:              &redis.SKU{Name: to.Ptr(redis.SKUNameStandard), Family: to.Ptr(redis.SKUFamilyC), Capacity: to.Ptr[int32](1)},
			EnableNonSSLPort: to.Ptr(true),
		},
	}, nil)
	var upd redis.ResourceInfo
	if err == nil {
		var res redis.ClientUpdateResponse
		res, err = up.PollUntilDone(ctx, &poll)
		upd = res.ResourceInfo
	}
	check("BeginUpdate scales Basic C0 → Standard C1", err == nil && *upd.Properties.SKU.Name == redis.SKUNameStandard && *upd.Properties.SKU.Capacity == 1 &&
		*upd.Properties.EnableNonSSLPort && *upd.Tags["env"] == "updated", fmt.Sprint(err))
	_, err = client.BeginUpdate(ctx, rg, name, redis.UpdateParameters{Properties: &redis.UpdateProperties{
		SKU: &redis.SKU{Name: to.Ptr(redis.SKUNameBasic), Family: to.Ptr(redis.SKUFamilyC), Capacity: to.Ptr[int32](1)}}}, nil)
	check("scaling down the tier → 400", status(err) == 400, fmt.Sprint(err))

	// ── keys + reboot ──────────────────────────────────────
	k0, err := client.ListKeys(ctx, rg, name, nil)
	check("ListKeys returns two keys", err == nil && len(*k0.PrimaryKey) == 44 && len(*k0.SecondaryKey) == 44, fmt.Sprint(err))
	k1, err := client.RegenerateKey(ctx, rg, name, redis.RegenerateKeyParameters{KeyType: to.Ptr(redis.RedisKeyTypePrimary)}, nil)
	check("RegenerateKey rotates only the primary", err == nil && *k1.PrimaryKey != *k0.PrimaryKey && *k1.SecondaryKey == *k0.SecondaryKey, fmt.Sprint(err))
	rb, err := client.ForceReboot(ctx, rg, name, redis.RebootParameters{RebootType: to.Ptr(redis.RebootTypeAllNodes)}, nil)
	check("ForceReboot AllNodes → message", err == nil && rb.Message != nil && *rb.Message != "", fmt.Sprint(err))

	// ── firewall rules ─────────────────────────────────────
	_, err = fw.CreateOrUpdate(ctx, rg, name, "office", redis.FirewallRule{Properties: &redis.FirewallRuleProperties{StartIP: to.Ptr("10.0.0.1"), EndIP: to.Ptr("10.0.0.20")}}, nil)
	check("FirewallRules.CreateOrUpdate", err == nil, fmt.Sprint(err))
	fr, err := fw.Get(ctx, rg, name, "office", nil)
	check("FirewallRules.Get", err == nil && *fr.Properties.EndIP == "10.0.0.20", fmt.Sprint(err))
	n := 0
	fp := fw.NewListPager(rg, name, nil)
	for fp.More() {
		page, e := fp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(page.Value)
	}
	check("FirewallRules.List", n == 1, fmt.Sprint(err))
	_, err = fw.CreateOrUpdate(ctx, rg, name, "bad", redis.FirewallRule{Properties: &redis.FirewallRuleProperties{StartIP: to.Ptr("nope"), EndIP: to.Ptr("10.0.0.20")}}, nil)
	check("FirewallRules: invalid IP → 400", status(err) == 400, fmt.Sprint(err))
	_, err = fw.Delete(ctx, rg, name, "office", nil)
	_, err2 := fw.Get(ctx, rg, name, "office", nil)
	check("FirewallRules.Delete then Get → 404", err == nil && status(err2) == 404, fmt.Sprint(err, err2))

	// ── premium: patch schedules, linked servers, export ───
	mk := func(n, loc string) error {
		p, e := client.BeginCreate(ctx, rg, n, redis.CreateParameters{Location: to.Ptr(loc), Properties: &redis.CreateProperties{
			SKU: &redis.SKU{Name: to.Ptr(redis.SKUNamePremium), Family: to.Ptr(redis.SKUFamilyP), Capacity: to.Ptr[int32](1)}}}, nil)
		if e != nil {
			return e
		}
		_, e = p.PollUntilDone(ctx, &poll)
		return e
	}
	check("BeginCreate Premium P1", mk(prem, "eastus") == nil, "")
	check("BeginCreate second Premium (westus)", mk(prem2, "westus") == nil, "")

	_, err = ps.CreateOrUpdate(ctx, rg, name, redis.DefaultNameDefault, redis.PatchSchedule{Properties: &redis.ScheduleEntries{
		ScheduleEntries: []*redis.ScheduleEntry{{DayOfWeek: to.Ptr(redis.DayOfWeekMonday), StartHourUTC: to.Ptr[int32](3)}}}}, nil)
	check("PatchSchedules on a Standard cache → 400", status(err) == 400, fmt.Sprint(err))
	_, err = ps.CreateOrUpdate(ctx, rg, prem, redis.DefaultNameDefault, redis.PatchSchedule{Properties: &redis.ScheduleEntries{
		ScheduleEntries: []*redis.ScheduleEntry{{DayOfWeek: to.Ptr(redis.DayOfWeekSunday), StartHourUTC: to.Ptr[int32](2), MaintenanceWindow: to.Ptr("PT5H")}}}}, nil)
	check("PatchSchedules.CreateOrUpdate (Premium)", err == nil, fmt.Sprint(err))
	pgot, err := ps.Get(ctx, rg, prem, redis.DefaultNameDefault, nil)
	check("PatchSchedules.Get", err == nil && len(pgot.Properties.ScheduleEntries) == 1 && *pgot.Properties.ScheduleEntries[0].DayOfWeek == redis.DayOfWeekSunday, fmt.Sprint(err))
	_, err = ps.Delete(ctx, rg, prem, redis.DefaultNameDefault, nil)
	_, err2 = ps.Get(ctx, rg, prem, redis.DefaultNameDefault, nil)
	check("PatchSchedules.Delete then Get → 404", err == nil && status(err2) == 404, fmt.Sprint(err, err2))

	id2 := fmt.Sprintf("/subscriptions/%s/resourceGroups/%s/providers/Microsoft.Cache/Redis/%s", sub, rg, prem2)
	lp, err := ls.BeginCreate(ctx, rg, prem, prem2, redis.LinkedServerCreateParameters{Properties: &redis.LinkedServerCreateProperties{
		LinkedRedisCacheID: to.Ptr(id2), LinkedRedisCacheLocation: to.Ptr("westus"), ServerRole: to.Ptr(redis.ReplicationRoleSecondary)}}, nil)
	if err == nil {
		_, err = lp.PollUntilDone(ctx, &poll)
	}
	check("LinkedServer.BeginCreate (geo-replication)", err == nil, fmt.Sprint(err))
	lg, err := ls.Get(ctx, rg, prem, prem2, nil)
	check("LinkedServer.Get", err == nil && *lg.Properties.ServerRole == redis.ReplicationRoleSecondary, fmt.Sprint(err))
	pc, err := client.Get(ctx, rg, prem, nil)
	check("cache lists the linked server", err == nil && len(pc.Properties.LinkedServers) == 1 && *pc.Properties.LinkedServers[0].ID == id2, fmt.Sprint(err))
	ln := 0
	lp2 := ls.NewListPager(rg, prem, nil)
	for lp2.More() {
		page, e := lp2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		ln += len(page.Value)
	}
	check("LinkedServer.List", ln == 1, fmt.Sprint(err))

	ex, err := client.BeginExportData(ctx, rg, prem, redis.ExportRDBParameters{Container: to.Ptr("https://cloudlearn.blob.core.windows.net/backups"), Prefix: to.Ptr("bk"), Format: to.Ptr("RDB")}, nil)
	if err == nil {
		_, err = ex.PollUntilDone(ctx, &poll)
	}
	check("BeginExportData (Premium)", err == nil, fmt.Sprint(err))
	_, err = client.BeginExportData(ctx, rg, name, redis.ExportRDBParameters{Container: to.Ptr("https://x/y"), Prefix: to.Ptr("bk")}, nil)
	check("ExportData on a Standard cache → 400", status(err) == 400, fmt.Sprint(err))

	// ── delete ─────────────────────────────────────────────
	dp, err := client.BeginDelete(ctx, rg, name, nil)
	if err == nil {
		_, err = dp.PollUntilDone(ctx, &poll)
	}
	check("BeginDelete", err == nil, fmt.Sprint(err))
	_, err = client.Get(ctx, rg, name, nil)
	check("Get after delete → 404", status(err) == 404, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
}

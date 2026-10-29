// Azure App Configuration conformance: the real azure-sdk-for-go armappconfiguration (control plane)
// and azappconfig (data plane) clients against Vyomi — only the endpoints changed.
// Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
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

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/arm"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/cloud"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	"github.com/Azure/azure-sdk-for-go/sdk/data/azappconfig"
	appcfg "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/appconfiguration/armappconfiguration/v2"
)

type fakeCred struct{}

func (fakeCred) GetToken(_ context.Context, _ policy.TokenRequestOptions) (azcore.AccessToken, error) {
	return azcore.AccessToken{Token: "fake-token", ExpiresOn: time.Now().Add(time.Hour)}, nil
}

var failed int

var runtimePoll = runtime.PollUntilDoneOptions{Frequency: time.Second}

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
	rg := fmt.Sprintf("rg-go-appcfg-%d", suffix)
	name := fmt.Sprintf("goappcfg%d", suffix)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	stores, err := appcfg.NewConfigurationStoresClient(sub, fakeCred{}, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	kvArm, _ := appcfg.NewKeyValuesClient(sub, fakeCred{}, opts)

	// ── control plane ──
	poller, err := stores.BeginCreate(ctx, rg, name, appcfg.ConfigurationStore{
		Location: to.Ptr("eastus"), SKU: &appcfg.SKU{Name: to.Ptr("Standard")}, Tags: map[string]*string{"env": to.Ptr("conf")},
	}, nil)
	var store appcfg.ConfigurationStoresClientCreateResponse
	if err == nil {
		store, err = poller.PollUntilDone(ctx, &runtimePoll)
	}
	check("BeginCreate store (LRO)", err == nil && store.Name != nil && *store.Name == name, fmt.Sprint(err))
	endpoint := ""
	if store.Properties != nil && store.Properties.Endpoint != nil {
		endpoint = *store.Properties.Endpoint
	}
	check("store has endpoint, Standard sku, Succeeded", endpoint != "" && store.SKU != nil && *store.SKU.Name == "Standard" &&
		store.Properties.ProvisioningState != nil && *store.Properties.ProvisioningState == appcfg.ProvisioningStateSucceeded, endpoint)
	got, err := stores.Get(ctx, rg, name, nil)
	check("Get store", err == nil && got.Tags["env"] != nil && *got.Tags["env"] == "conf", fmt.Sprint(err))
	_, err = stores.Get(ctx, rg, "nosuchstore99", nil)
	check("Get missing store → 404", status(err) == 404, fmt.Sprint(err))
	upd, err := stores.BeginUpdate(ctx, rg, name, appcfg.ConfigurationStoreUpdateParameters{Tags: map[string]*string{"env": to.Ptr("updated")}}, nil)
	if err == nil {
		_, err = upd.PollUntilDone(ctx, &runtimePoll)
	}
	check("BeginUpdate (tags)", err == nil, fmt.Sprint(err))
	err = nil
	n := 0
	pg := stores.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		p, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(p.Value)
	}
	check("ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))
	err = nil
	n = 0
	pg2 := stores.NewListPager(nil)
	for pg2.More() {
		p, e := pg2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, s := range p.Value {
			if s.Name != nil && *s.Name == name {
				n++
			}
		}
	}
	check("List (subscription)", n == 1, fmt.Sprint(n, err))
	err = nil
	keys := stores.NewListKeysPager(rg, name, nil)
	var all []*appcfg.APIKey
	for keys.More() {
		p, e := keys.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		all = append(all, p.Value...)
	}
	check("ListKeys returns 4 keys with connection strings", len(all) == 4 && all[0].ConnectionString != nil &&
		strings.HasPrefix(*all[0].ConnectionString, "Endpoint="), fmt.Sprint(len(all), err))
	reg, err := stores.RegenerateKey(ctx, rg, name, appcfg.RegenerateKeyParameters{ID: all[0].ID}, nil)
	check("RegenerateKey rotates the secret", err == nil && reg.Value != nil && *reg.Value != *all[0].Value, fmt.Sprint(err))
	cs := *all[0].ConnectionString
	if reg.ConnectionString != nil {
		cs = *reg.ConnectionString
	}
	ops, _ := appcfg.NewOperationsClient(sub, fakeCred{}, opts)
	av, err := ops.CheckNameAvailability(ctx, appcfg.CheckNameAvailabilityParameters{Name: to.Ptr(name), Type: to.Ptr(appcfg.ConfigurationResourceTypeMicrosoftAppConfigurationConfigurationStores)}, nil)
	check("CheckNameAvailability reports the name taken", err == nil && av.NameAvailable != nil && !*av.NameAvailable, fmt.Sprint(err))

	// ── data plane (azappconfig, HMAC connection string over plain HTTP) ──
	dp, err := azappconfig.NewClientFromConnectionString(cs, nil)
	if err != nil {
		check("azappconfig client", false, err.Error())
		os.Exit(1)
	}
	set, err := dp.SetSetting(ctx, "app:color", to.Ptr("blue"), &azappconfig.SetSettingOptions{Label: to.Ptr("dev"), ContentType: to.Ptr("text/plain")})
	check("SetSetting", err == nil && set.Value != nil && *set.Value == "blue" && set.ETag != nil, fmt.Sprint(err))
	g, err := dp.GetSetting(ctx, "app:color", &azappconfig.GetSettingOptions{Label: to.Ptr("dev")})
	check("GetSetting", err == nil && *g.Value == "blue" && *g.Label == "dev" && *g.ContentType == "text/plain", fmt.Sprint(err))
	_, err = dp.GetSetting(ctx, "nope", nil)
	check("GetSetting missing → 404", status(err) == 404, fmt.Sprint(err))
	_, err = dp.AddSetting(ctx, "app:color", to.Ptr("x"), &azappconfig.AddSettingOptions{Label: to.Ptr("dev")})
	check("AddSetting on existing key → 412", status(err) == 412, fmt.Sprint(err))
	_, err = dp.AddSetting(ctx, "app:size", to.Ptr("L"), &azappconfig.AddSettingOptions{Label: to.Ptr("dev")})
	check("AddSetting new key", err == nil, fmt.Sprint(err))
	_, err = dp.SetSetting(ctx, "other", to.Ptr("v1"), nil)
	check("SetSetting without label", err == nil, fmt.Sprint(err))
	_, err = dp.SetSetting(ctx, "app:color", to.Ptr("red"), &azappconfig.SetSettingOptions{Label: to.Ptr("dev"), OnlyIfUnchanged: set.ETag})
	check("SetSetting with matching ETag", err == nil, fmt.Sprint(err))
	_, err = dp.SetSetting(ctx, "app:color", to.Ptr("green"), &azappconfig.SetSettingOptions{Label: to.Ptr("dev"), OnlyIfUnchanged: set.ETag})
	check("SetSetting with stale ETag → 412", status(err) == 412, fmt.Sprint(err))
	err = nil
	var keysSeen []string
	lp := dp.NewListSettingsPager(azappconfig.SettingSelector{KeyFilter: to.Ptr("app:*"), LabelFilter: to.Ptr("dev")}, nil)
	for lp.More() {
		p, e := lp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, s := range p.Settings {
			keysSeen = append(keysSeen, *s.Key)
		}
	}
	check("ListSettings key/label filter", err == nil && strings.Join(keysSeen, ",") == "app:color,app:size", fmt.Sprint(keysSeen, err))
	ro, err := dp.SetReadOnly(ctx, "other", true, nil)
	check("SetReadOnly (lock)", err == nil && ro.IsReadOnly != nil && *ro.IsReadOnly, fmt.Sprint(err))
	_, err = dp.SetSetting(ctx, "other", to.Ptr("v2"), nil)
	check("write to a locked key → 409", status(err) == 409, fmt.Sprint(err))
	_, err = dp.SetReadOnly(ctx, "other", false, nil)
	check("unlock", err == nil, fmt.Sprint(err))
	_, err = dp.SetSetting(ctx, "other", to.Ptr("v2"), nil)
	check("write after unlock", err == nil, fmt.Sprint(err))
	err = nil
	revs := 0
	rp := dp.NewListRevisionsPager(azappconfig.SettingSelector{KeyFilter: to.Ptr("other")}, nil)
	for rp.More() {
		p, e := rp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		revs += len(p.Settings)
	}
	check("ListRevisions keeps history", err == nil && revs >= 2, fmt.Sprint(revs, err))
	del, err := dp.DeleteSetting(ctx, "other", nil)
	check("DeleteSetting", err == nil && del.Value != nil, fmt.Sprint(err))
	_, err = dp.GetSetting(ctx, "other", nil)
	check("deleted key is gone", status(err) == 404, fmt.Sprint(err))
	snapPoller, err := dp.BeginCreateSnapshot(ctx, "snap-go", []azappconfig.SettingFilter{{KeyFilter: to.Ptr("app:*")}}, nil)
	var snap azappconfig.CreateSnapshotResponse
	if err == nil {
		snap, err = snapPoller.PollUntilDone(ctx, nil)
	}
	check("BeginCreateSnapshot", err == nil && snap.Name != nil && *snap.Name == "snap-go", fmt.Sprint(err))
	sn, err := dp.GetSnapshot(ctx, "snap-go", nil)
	check("GetSnapshot is ready with 2 items", err == nil && sn.Status != nil && *sn.Status == azappconfig.SnapshotStatusReady && sn.ItemsCount != nil && *sn.ItemsCount == 2, fmt.Sprint(err))
	err = nil
	cnt := 0
	sp := dp.NewListSettingsForSnapshotPager("snap-go", nil)
	for sp.More() {
		p, e := sp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		cnt += len(p.Settings)
	}
	check("ListSettingsForSnapshot", err == nil && cnt == 2, fmt.Sprint(cnt, err))

	// ── ARM keyValues view of the same data ──
	kv, err := kvArm.CreateOrUpdate(ctx, rg, name, "arm:key", &appcfg.KeyValuesClientCreateOrUpdateOptions{KeyValueParameters: &appcfg.KeyValue{Properties: &appcfg.KeyValueProperties{Value: to.Ptr("from-arm")}}})
	check("ARM KeyValues.CreateOrUpdate", err == nil && kv.Properties != nil && *kv.Properties.Value == "from-arm", fmt.Sprint(err))
	g, err = dp.GetSetting(ctx, "arm:key", nil)
	check("key written through ARM is readable on the data plane", err == nil && *g.Value == "from-arm", fmt.Sprint(err))

	// ── delete → soft delete → purge ──
	dpoll, err := stores.BeginDelete(ctx, rg, name, nil)
	if err == nil {
		_, err = dpoll.PollUntilDone(ctx, &runtimePoll)
	}
	check("BeginDelete store", err == nil, fmt.Sprint(err))
	_, err = stores.Get(ctx, rg, name, nil)
	check("deleted store → 404", status(err) == 404, fmt.Sprint(err))
	ppoll, err := stores.BeginPurgeDeleted(ctx, "eastus", name, nil)
	if err == nil {
		_, err = ppoll.PollUntilDone(ctx, &runtimePoll)
	}
	check("BeginPurgeDeleted", err == nil, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}

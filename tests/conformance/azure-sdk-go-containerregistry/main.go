// Azure Container Registry conformance: the real azure-sdk-for-go armcontainerregistry client against
// Vyomi — only the endpoint changed. One [PASS]/[FAIL] line per check; non-zero exit on failure.
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
	acr "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/containerregistry/armcontainerregistry"
	"github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/resources/armresources"
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
	rg := fmt.Sprintf("rg-go-acr-%d", suffix)
	name := fmt.Sprintf("goacr%d", suffix)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	rgc, err := armresources.NewResourceGroupsClient(sub, fakeCred{}, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	_, err = rgc.CreateOrUpdate(ctx, rg, armresources.ResourceGroup{Location: to.Ptr("eastus")}, nil)
	check("create resource group", err == nil, fmt.Sprint(err))

	f, _ := acr.NewClientFactory(sub, fakeCred{}, opts)
	regs := f.NewRegistriesClient()
	whs := f.NewWebhooksClient()
	reps := f.NewReplicationsClient()
	sms := f.NewScopeMapsClient()
	toks := f.NewTokensClient()

	// ── registries ──
	p, err := regs.BeginCreate(ctx, rg, name, acr.Registry{
		Location: to.Ptr("eastus"), SKU: &acr.SKU{Name: to.Ptr(acr.SKUNameStandard)},
		Tags:       map[string]*string{"env": to.Ptr("conf")},
		Properties: &acr.RegistryProperties{AdminUserEnabled: to.Ptr(true)},
	}, nil)
	var created acr.RegistriesClientCreateResponse
	if err == nil {
		created, err = p.PollUntilDone(ctx, &poll)
	}
	check("BeginCreate registry (LRO)", err == nil && created.Name != nil && *created.Name == name, fmt.Sprint(err))
	want := name + ".azurecr.io"
	check("registry has loginServer and Succeeded", created.Properties != nil && created.Properties.LoginServer != nil &&
		*created.Properties.LoginServer == want && created.Properties.ProvisioningState != nil &&
		*created.Properties.ProvisioningState == acr.ProvisioningStateSucceeded, fmt.Sprintf("%+v", created.Properties))

	g, err := regs.Get(ctx, rg, name, nil)
	check("Get registry", err == nil && g.SKU != nil && *g.SKU.Name == acr.SKUNameStandard && g.Tags["env"] != nil &&
		g.Properties.AdminUserEnabled != nil && *g.Properties.AdminUserEnabled, fmt.Sprint(err))

	found := false
	lp := regs.NewListByResourceGroupPager(rg, nil)
	for lp.More() {
		pg, e := lp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, r := range pg.Value {
			found = found || (r.Name != nil && *r.Name == name)
		}
	}
	check("ListByResourceGroup contains registry", found, fmt.Sprint(err))
	found = false
	lp2 := regs.NewListPager(nil)
	for lp2.More() {
		pg, e := lp2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, r := range pg.Value {
			found = found || (r.Name != nil && *r.Name == name)
		}
	}
	check("List (subscription) contains registry", found, fmt.Sprint(err))

	up, err := regs.BeginUpdate(ctx, rg, name, acr.RegistryUpdateParameters{
		Tags: map[string]*string{"env": to.Ptr("updated")}, Properties: &acr.RegistryPropertiesUpdateParameters{AdminUserEnabled: to.Ptr(false)},
	}, nil)
	var ur acr.RegistriesClientUpdateResponse
	if err == nil {
		ur, err = up.PollUntilDone(ctx, &poll)
	}
	check("BeginUpdate registry (tags, admin user off)", err == nil && ur.Tags["env"] != nil && *ur.Tags["env"] == "updated" &&
		ur.Properties.AdminUserEnabled != nil && !*ur.Properties.AdminUserEnabled, fmt.Sprint(err))

	en, err := regs.BeginUpdate(ctx, rg, name, acr.RegistryUpdateParameters{Properties: &acr.RegistryPropertiesUpdateParameters{AdminUserEnabled: to.Ptr(true)}}, nil)
	if err == nil {
		_, err = en.PollUntilDone(ctx, &poll)
	}
	check("BeginUpdate re-enables admin user", err == nil, fmt.Sprint(err))
	cr, err := regs.ListCredentials(ctx, rg, name, nil)
	check("ListCredentials returns username + 2 passwords", err == nil && cr.Username != nil && *cr.Username == name && len(cr.Passwords) == 2, fmt.Sprint(err))
	var oldPw string
	if len(cr.Passwords) > 0 && cr.Passwords[0].Value != nil {
		oldPw = *cr.Passwords[0].Value
	}
	rc, err := regs.RegenerateCredential(ctx, rg, name, acr.RegenerateCredentialParameters{Name: to.Ptr(acr.PasswordNamePassword)}, nil)
	check("RegenerateCredential rotates password", err == nil && len(rc.Passwords) > 0 && rc.Passwords[0].Value != nil &&
		*rc.Passwords[0].Value != "" && *rc.Passwords[0].Value != oldPw, fmt.Sprint(err))

	na, err := regs.CheckNameAvailability(ctx, acr.RegistryNameCheckRequest{Name: to.Ptr(name), Type: to.Ptr("Microsoft.ContainerRegistry/registries")}, nil)
	check("CheckNameAvailability: taken", err == nil && na.NameAvailable != nil && !*na.NameAvailable && na.Reason != nil && *na.Reason == "AlreadyExists", fmt.Sprint(err))
	na, err = regs.CheckNameAvailability(ctx, acr.RegistryNameCheckRequest{Name: to.Ptr("a-b"), Type: to.Ptr("Microsoft.ContainerRegistry/registries")}, nil)
	check("CheckNameAvailability: invalid", err == nil && na.NameAvailable != nil && !*na.NameAvailable && na.Reason != nil && *na.Reason == "Invalid", fmt.Sprint(err))
	na, err = regs.CheckNameAvailability(ctx, acr.RegistryNameCheckRequest{Name: to.Ptr("free" + name), Type: to.Ptr("Microsoft.ContainerRegistry/registries")}, nil)
	check("CheckNameAvailability: free", err == nil && na.NameAvailable != nil && *na.NameAvailable, fmt.Sprint(err))

	us, err := regs.ListUsages(ctx, rg, name, nil)
	hasSize := false
	for _, u := range us.Value {
		hasSize = hasSize || (u.Name != nil && *u.Name == "Size")
	}
	check("ListUsages reports Size", err == nil && hasSize, fmt.Sprint(err))

	// ── webhooks ──
	wp, err := whs.BeginCreate(ctx, rg, name, "hookgo", acr.WebhookCreateParameters{
		Location: to.Ptr("eastus"),
		Properties: &acr.WebhookPropertiesCreateParameters{ServiceURI: to.Ptr("https://example.com/hook"),
			Actions: []*acr.WebhookAction{to.Ptr(acr.WebhookActionPush)}},
	}, nil)
	var wh acr.WebhooksClientCreateResponse
	if err == nil {
		wh, err = wp.PollUntilDone(ctx, &poll)
	}
	check("Webhooks BeginCreate", err == nil && wh.Properties != nil && wh.Properties.ProvisioningState != nil, fmt.Sprint(err))
	wg, err := whs.Get(ctx, rg, name, "hookgo", nil)
	check("Webhooks Get", err == nil && wg.Properties != nil && wg.Properties.Status != nil && *wg.Properties.Status == acr.WebhookStatusEnabled, fmt.Sprint(err))
	n := 0
	wl := whs.NewListPager(rg, name, nil)
	for wl.More() {
		pg, e := wl.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(pg.Value)
	}
	check("Webhooks List", err == nil && n == 1, fmt.Sprint(err, n))
	wd, err := whs.BeginDelete(ctx, rg, name, "hookgo", nil)
	if err == nil {
		_, err = wd.PollUntilDone(ctx, &poll)
	}
	check("Webhooks BeginDelete", err == nil, fmt.Sprint(err))
	_, err = whs.Get(ctx, rg, name, "hookgo", nil)
	check("deleted webhook -> 404", status(err) == 404, fmt.Sprint(err))

	// ── replications: Basic/Standard rejected, Premium allowed ──
	_, err = reps.BeginCreate(ctx, rg, name, "westus", acr.Replication{Location: to.Ptr("westus")}, nil)
	check("Replication on Standard registry is rejected", err != nil && status(err) == 400, fmt.Sprint(err))
	pu, err := regs.BeginUpdate(ctx, rg, name, acr.RegistryUpdateParameters{SKU: &acr.SKU{Name: to.Ptr(acr.SKUNamePremium)}}, nil)
	if err == nil {
		_, err = pu.PollUntilDone(ctx, &poll)
	}
	check("upgrade to Premium", err == nil, fmt.Sprint(err))
	rp, err := reps.BeginCreate(ctx, rg, name, "westus", acr.Replication{Location: to.Ptr("westus")}, nil)
	var rep acr.ReplicationsClientCreateResponse
	if err == nil {
		rep, err = rp.PollUntilDone(ctx, &poll)
	}
	check("Replications BeginCreate on Premium", err == nil && rep.Properties != nil && rep.Properties.ProvisioningState != nil &&
		*rep.Properties.ProvisioningState == acr.ProvisioningStateSucceeded, fmt.Sprint(err))
	n = 0
	rl := reps.NewListPager(rg, name, nil)
	for rl.More() {
		pg, e := rl.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(pg.Value)
	}
	check("Replications List", err == nil && n == 1, fmt.Sprint(err, n))
	rd, err := reps.BeginDelete(ctx, rg, name, "westus", nil)
	if err == nil {
		_, err = rd.PollUntilDone(ctx, &poll)
	}
	check("Replications BeginDelete", err == nil, fmt.Sprint(err))

	// ── scope maps + tokens ──
	sp, err := sms.BeginCreate(ctx, rg, name, "gomap", acr.ScopeMap{Properties: &acr.ScopeMapProperties{
		Actions: []*string{to.Ptr("repositories/*/content/read")}}}, nil)
	var sm acr.ScopeMapsClientCreateResponse
	if err == nil {
		sm, err = sp.PollUntilDone(ctx, &poll)
	}
	check("ScopeMaps BeginCreate", err == nil && sm.ID != nil, fmt.Sprint(err))
	sysFound := false
	sl := sms.NewListPager(rg, name, nil)
	for sl.More() {
		pg, e := sl.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, s := range pg.Value {
			sysFound = sysFound || (s.Name != nil && *s.Name == "_repositories_pull")
		}
	}
	check("ScopeMaps List includes system scope maps", err == nil && sysFound, fmt.Sprint(err))
	smID := ""
	if sm.ID != nil {
		smID = *sm.ID
	}
	tp, err := toks.BeginCreate(ctx, rg, name, "gotok", acr.Token{Properties: &acr.TokenProperties{ScopeMapID: to.Ptr(smID), Status: to.Ptr(acr.TokenStatusEnabled)}}, nil)
	var tk acr.TokensClientCreateResponse
	if err == nil {
		tk, err = tp.PollUntilDone(ctx, &poll)
	}
	check("Tokens BeginCreate bound to scope map", err == nil && tk.Properties != nil && tk.Properties.ScopeMapID != nil, fmt.Sprint(err))
	_, err = sms.BeginDelete(ctx, rg, name, "gomap", nil)
	check("deleting an in-use scope map is rejected", err != nil && status(err) == 409, fmt.Sprint(err))
	td, err := toks.BeginDelete(ctx, rg, name, "gotok", nil)
	if err == nil {
		_, err = td.PollUntilDone(ctx, &poll)
	}
	check("Tokens BeginDelete", err == nil, fmt.Sprint(err))
	sd, err := sms.BeginDelete(ctx, rg, name, "gomap", nil)
	if err == nil {
		_, err = sd.PollUntilDone(ctx, &poll)
	}
	check("ScopeMaps BeginDelete", err == nil, fmt.Sprint(err))

	// ── delete ──
	dp, err := regs.BeginDelete(ctx, rg, name, nil)
	if err == nil {
		_, err = dp.PollUntilDone(ctx, &poll)
	}
	check("BeginDelete registry (LRO)", err == nil, fmt.Sprint(err))
	_, err = regs.Get(ctx, rg, name, nil)
	check("deleted registry -> 404", status(err) == 404, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}

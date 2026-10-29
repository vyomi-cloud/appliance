// Azure AI services / Cognitive Services conformance: the real azure-sdk-for-go armcognitiveservices
// client against Vyomi — only the ARM endpoint changed.
// Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
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
	cs "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/cognitiveservices/armcognitiveservices"
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

func errCode(err error) string {
	var re *azcore.ResponseError
	if errors.As(err, &re) {
		return re.ErrorCode
	}
	return ""
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
	rg := fmt.Sprintf("rg-go-ai-%d", suffix)
	name := fmt.Sprintf("goai%d", suffix)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	accounts, err := cs.NewAccountsClient(sub, fakeCred{}, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	deployments, _ := cs.NewDeploymentsClient(sub, fakeCred{}, opts)
	plans, _ := cs.NewCommitmentPlansClient(sub, fakeCred{}, opts)
	deleted, _ := cs.NewDeletedAccountsClient(sub, fakeCred{}, opts)
	models, _ := cs.NewModelsClient(sub, fakeCred{}, opts)
	skus, _ := cs.NewResourceSKUsClient(sub, fakeCred{}, opts)
	usages, _ := cs.NewUsagesClient(sub, fakeCred{}, opts)

	// ── accounts ──
	p, err := accounts.BeginCreate(ctx, rg, name, cs.Account{
		Kind: to.Ptr("OpenAI"), Location: to.Ptr("eastus"), SKU: &cs.SKU{Name: to.Ptr("S0")},
		Properties: &cs.AccountProperties{CustomSubDomainName: to.Ptr(name)},
		Tags:       map[string]*string{"env": to.Ptr("conf")},
	}, nil)
	var acct cs.AccountsClientCreateResponse
	if err == nil {
		acct, err = p.PollUntilDone(ctx, &poll)
	}
	check("BeginCreate account (LRO)", err == nil && acct.Name != nil && *acct.Name == name, fmt.Sprint(err))
	endpoint := ""
	if acct.Properties != nil && acct.Properties.Endpoint != nil {
		endpoint = *acct.Properties.Endpoint
	}
	check("account has endpoint, S0 sku, Succeeded", endpoint != "" && acct.SKU != nil && *acct.SKU.Name == "S0" &&
		acct.Properties.ProvisioningState != nil && *acct.Properties.ProvisioningState == cs.ProvisioningStateSucceeded, endpoint)
	got, err := accounts.Get(ctx, rg, name, nil)
	check("Get account", err == nil && got.Tags["env"] != nil && *got.Tags["env"] == "conf" && *got.Kind == "OpenAI", fmt.Sprint(err))
	_, err = accounts.Get(ctx, rg, "nosuchaccount99", nil)
	check("Get missing account → 404", status(err) == 404, fmt.Sprint(err))
	up, err := accounts.BeginUpdate(ctx, rg, name, cs.Account{Tags: map[string]*string{"env": to.Ptr("updated")}}, nil)
	if err == nil {
		_, err = up.PollUntilDone(ctx, &poll)
	}
	check("BeginUpdate (tags)", err == nil, fmt.Sprint(err))
	got, err = accounts.Get(ctx, rg, name, nil)
	check("update persisted", err == nil && got.Tags["env"] != nil && *got.Tags["env"] == "updated", fmt.Sprint(err))
	err = nil
	n := 0
	pg := accounts.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		pp, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(pp.Value)
	}
	check("ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))
	err = nil
	n = 0
	pg2 := accounts.NewListPager(nil)
	for pg2.More() {
		pp, e := pg2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, a := range pp.Value {
			if a.Name != nil && *a.Name == name {
				n++
			}
		}
	}
	check("List (subscription)", n == 1, fmt.Sprint(n, err))
	_, err = accounts.BeginCreate(ctx, rg, "other"+name, cs.Account{Kind: to.Ptr("OpenAI"), Location: to.Ptr("eastus"),
		SKU: &cs.SKU{Name: to.Ptr("S0")}, Properties: &cs.AccountProperties{CustomSubDomainName: to.Ptr(name)}}, nil)
	check("duplicate custom subdomain → 409", status(err) == 409, fmt.Sprint(err))
	_, err = accounts.BeginCreate(ctx, rg, "bad"+name, cs.Account{Kind: to.Ptr("NoSuchKind"), Location: to.Ptr("eastus"),
		SKU: &cs.SKU{Name: to.Ptr("S0")}}, nil)
	check("unknown kind → 400", status(err) == 400, fmt.Sprint(err))

	// ── keys ──
	k1, err := accounts.ListKeys(ctx, rg, name, nil)
	check("ListKeys returns two keys", err == nil && k1.Key1 != nil && k1.Key2 != nil && *k1.Key1 != *k1.Key2, fmt.Sprint(err))
	k2, err := accounts.RegenerateKey(ctx, rg, name, cs.RegenerateKeyParameters{KeyName: to.Ptr(cs.KeyNameKey1)}, nil)
	check("RegenerateKey rotates key1 only", err == nil && k2.Key1 != nil && *k2.Key1 != *k1.Key1 && *k2.Key2 == *k1.Key2, fmt.Sprint(err))
	sk, err := accounts.ListSKUs(ctx, rg, name, nil)
	check("account ListSKUs", err == nil && len(sk.Value) > 0, fmt.Sprint(err))
	au, err := accounts.ListUsages(ctx, rg, name, nil)
	check("account ListUsages", err == nil && len(au.Value) > 0, fmt.Sprint(err))
	us := usages.NewListPager("eastus", nil)
	err = nil
	un := 0
	for us.More() {
		pp, e := us.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		un += len(pp.Value)
	}
	check("Usages.List (location)", err == nil && un > 0, fmt.Sprint(un, err))
	mp := models.NewListPager("eastus", nil)
	err = nil
	mn := 0
	for mp.More() {
		pp, e := mp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		mn += len(pp.Value)
	}
	check("Models.List (location) has OpenAI models", err == nil && mn > 5, fmt.Sprint(mn, err))
	rp := skus.NewListPager(nil)
	err = nil
	rn := 0
	for rp.More() {
		pp, e := rp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		rn += len(pp.Value)
	}
	check("ResourceSKUs.List", err == nil && rn > 5, fmt.Sprint(rn, err))
	cd, err := cs.NewManagementClient(sub, fakeCred{}, opts)
	if err == nil {
		var r cs.ManagementClientCheckDomainAvailabilityResponse
		r, err = cd.CheckDomainAvailability(ctx, cs.CheckDomainAvailabilityParameter{SubdomainName: to.Ptr(name), Type: to.Ptr("Microsoft.CognitiveServices/accounts")}, nil)
		check("CheckDomainAvailability: taken", err == nil && r.IsSubdomainAvailable != nil && !*r.IsSubdomainAvailable, fmt.Sprint(err))
		r, err = cd.CheckDomainAvailability(ctx, cs.CheckDomainAvailabilityParameter{SubdomainName: to.Ptr("free-" + name), Type: to.Ptr("Microsoft.CognitiveServices/accounts")}, nil)
		check("CheckDomainAvailability: free", err == nil && r.IsSubdomainAvailable != nil && *r.IsSubdomainAvailable, fmt.Sprint(err))
	} else {
		check("management client", false, fmt.Sprint(err))
	}

	// ── deployments ──
	dp, err := deployments.BeginCreateOrUpdate(ctx, rg, name, "chat", cs.Deployment{
		SKU: &cs.SKU{Name: to.Ptr("Standard"), Capacity: to.Ptr[int32](10)},
		Properties: &cs.DeploymentProperties{Model: &cs.DeploymentModel{
			Format: to.Ptr("OpenAI"), Name: to.Ptr("gpt-4o"), Version: to.Ptr("2024-08-06")}},
	}, nil)
	var dep cs.DeploymentsClientCreateOrUpdateResponse
	if err == nil {
		dep, err = dp.PollUntilDone(ctx, &poll)
	}
	check("BeginCreateOrUpdate deployment", err == nil && dep.Name != nil && *dep.Name == "chat" &&
		*dep.Properties.Model.Name == "gpt-4o" && *dep.SKU.Capacity == 10, fmt.Sprint(err))
	gd, err := deployments.Get(ctx, rg, name, "chat", nil)
	check("Get deployment", err == nil && *gd.Properties.ProvisioningState == cs.DeploymentProvisioningStateSucceeded, fmt.Sprint(err))
	_, err = deployments.BeginCreateOrUpdate(ctx, rg, name, "bad", cs.Deployment{
		SKU:        &cs.SKU{Name: to.Ptr("Standard"), Capacity: to.Ptr[int32](10)},
		Properties: &cs.DeploymentProperties{Model: &cs.DeploymentModel{Format: to.Ptr("OpenAI"), Name: to.Ptr("no-such-model"), Version: to.Ptr("1")}},
	}, nil)
	check("deployment with unknown model → 400", status(err) == 400, fmt.Sprint(err))
	_, err = deployments.BeginCreateOrUpdate(ctx, rg, name, "huge", cs.Deployment{
		SKU:        &cs.SKU{Name: to.Ptr("Standard"), Capacity: to.Ptr[int32](100000)},
		Properties: &cs.DeploymentProperties{Model: &cs.DeploymentModel{Format: to.Ptr("OpenAI"), Name: to.Ptr("gpt-4o"), Version: to.Ptr("2024-08-06")}},
	}, nil)
	check("deployment over quota → InsufficientQuota", status(err) == 400 && errCode(err) == "InsufficientQuota", fmt.Sprint(status(err), errCode(err), err))
	err = nil
	dn := 0
	dl := deployments.NewListPager(rg, name, nil)
	for dl.More() {
		pp, e := dl.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		dn += len(pp.Value)
	}
	check("List deployments", err == nil && dn == 1, fmt.Sprint(dn, err))
	ad := accounts.NewListModelsPager(rg, name, nil)
	err = nil
	an := 0
	for ad.More() {
		pp, e := ad.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		an += len(pp.Value)
	}
	check("account ListModels", err == nil && an > 5, fmt.Sprint(an, err))
	dd, err := deployments.BeginDelete(ctx, rg, name, "chat", nil)
	if err == nil {
		_, err = dd.PollUntilDone(ctx, &poll)
	}
	check("BeginDelete deployment", err == nil, fmt.Sprint(err))
	_, err = deployments.Get(ctx, rg, name, "chat", nil)
	check("deleted deployment → 404", status(err) == 404, fmt.Sprint(err))

	// ── commitment plans (Language account) ──
	lang := "golang" + name
	lp, err := accounts.BeginCreate(ctx, rg, lang, cs.Account{Kind: to.Ptr("TextAnalytics"), Location: to.Ptr("eastus"),
		SKU: &cs.SKU{Name: to.Ptr("S")}, Properties: &cs.AccountProperties{CustomSubDomainName: to.Ptr(lang)}}, nil)
	if err == nil {
		_, err = lp.PollUntilDone(ctx, &poll)
	}
	check("create TextAnalytics account", err == nil, fmt.Sprint(err))
	_, err = plans.CreateOrUpdate(ctx, rg, lang, "plan1", cs.CommitmentPlan{Properties: &cs.CommitmentPlanProperties{
		HostingModel: to.Ptr(cs.HostingModelWeb), PlanType: to.Ptr("TA"), AutoRenew: to.Ptr(true),
		Current: &cs.CommitmentPeriod{Tier: to.Ptr("T1")}}}, nil)
	check("CommitmentPlans.CreateOrUpdate", err == nil, fmt.Sprint(err))
	gp, err := plans.Get(ctx, rg, lang, "plan1", nil)
	check("CommitmentPlans.Get", err == nil && *gp.Properties.AutoRenew, fmt.Sprint(err))
	_, err = deployments.BeginCreateOrUpdate(ctx, rg, lang, "x", cs.Deployment{SKU: &cs.SKU{Name: to.Ptr("Standard")},
		Properties: &cs.DeploymentProperties{Model: &cs.DeploymentModel{Format: to.Ptr("OpenAI"), Name: to.Ptr("gpt-4o"), Version: to.Ptr("2024-08-06")}}}, nil)
	check("deployments rejected on a non-OpenAI account → 400", status(err) == 400, fmt.Sprint(err))
	for _, a := range []string{lang} {
		d, e := accounts.BeginDelete(ctx, rg, a, nil)
		if e == nil {
			_, e = d.PollUntilDone(ctx, &poll)
		}
		check("delete "+a, e == nil, fmt.Sprint(e))
	}

	// ── delete, soft-delete, restore, purge ──
	d, err := accounts.BeginDelete(ctx, rg, name, nil)
	if err == nil {
		_, err = d.PollUntilDone(ctx, &poll)
	}
	check("BeginDelete account", err == nil, fmt.Sprint(err))
	_, err = accounts.Get(ctx, rg, name, nil)
	check("deleted account → 404", status(err) == 404, fmt.Sprint(err))
	gone, err := deleted.Get(ctx, "eastus", rg, name, nil)
	check("DeletedAccounts.Get shows the soft-deleted account", err == nil && gone.Name != nil && *gone.Name == name, fmt.Sprint(err))
	_, err = accounts.BeginCreate(ctx, rg, name, cs.Account{Kind: to.Ptr("OpenAI"), Location: to.Ptr("eastus"),
		SKU: &cs.SKU{Name: to.Ptr("S0")}, Properties: &cs.AccountProperties{CustomSubDomainName: to.Ptr(name)}}, nil)
	check("re-create while soft-deleted → 409", status(err) == 409, fmt.Sprint(err))
	rp2, err := accounts.BeginCreate(ctx, rg, name, cs.Account{Kind: to.Ptr("OpenAI"), Location: to.Ptr("eastus"),
		SKU: &cs.SKU{Name: to.Ptr("S0")}, Properties: &cs.AccountProperties{CustomSubDomainName: to.Ptr(name), Restore: to.Ptr(true)}}, nil)
	if err == nil {
		_, err = rp2.PollUntilDone(ctx, &poll)
	}
	check("restore soft-deleted account (restore=true)", err == nil, fmt.Sprint(err))
	d, err = accounts.BeginDelete(ctx, rg, name, nil)
	if err == nil {
		_, err = d.PollUntilDone(ctx, &poll)
	}
	pu, err := deleted.BeginPurge(ctx, "eastus", rg, name, nil)
	if err == nil {
		_, err = pu.PollUntilDone(ctx, &poll)
	}
	check("DeletedAccounts.BeginPurge", err == nil, fmt.Sprint(err))
	_, err = deleted.Get(ctx, "eastus", rg, name, nil)
	check("purged account → 404", status(err) == 404, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}

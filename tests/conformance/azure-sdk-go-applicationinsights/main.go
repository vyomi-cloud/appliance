// Azure Application Insights (Microsoft.Insights) conformance: the real azure-sdk-for-go
// armapplicationinsights client against Vyomi, only the ARM endpoint changed.
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
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	ai "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/applicationinsights/armapplicationinsights"
)

type fakeCred struct{}

func (fakeCred) GetToken(_ context.Context, _ policy.TokenRequestOptions) (azcore.AccessToken, error) {
	return azcore.AccessToken{Token: "fake-token", ExpiresOn: time.Now().Add(time.Hour)}, nil
}

var failed int

func check(name string, ok bool, detail string) {
	if ok {
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	failed++
	fmt.Printf("[FAIL] %s %s\n", name, detail)
}

func errCode(err error) (int, string) {
	var re *azcore.ResponseError
	if errors.As(err, &re) {
		return re.StatusCode, re.ErrorCode
	}
	return 0, ""
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
	rg := fmt.Sprintf("rg-go-ai-%d", time.Now().Unix()%100000)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services: map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	cred := fakeCred{}
	comps, _ := ai.NewComponentsClient(sub, cred, opts)
	keys, _ := ai.NewAPIKeysClient(sub, cred, opts)
	feats, _ := ai.NewComponentCurrentBillingFeaturesClient(sub, cred, opts)
	tests, _ := ai.NewWebTestsClient(sub, cred, opts)

	name, loc := "appi-go", "eastus"

	c, err := comps.CreateOrUpdate(ctx, rg, name, ai.Component{Location: &loc, Kind: to.Ptr("web"),
		Tags: map[string]*string{"env": to.Ptr("test")},
		Properties: &ai.ComponentProperties{ApplicationType: to.Ptr(ai.ApplicationTypeWeb), RetentionInDays: to.Ptr(int32(30)),
			RequestSource: to.Ptr(ai.RequestSourceRest), FlowType: to.Ptr(ai.FlowTypeBluefield)}}, nil)
	check("Components.CreateOrUpdate", err == nil && c.Properties != nil && c.Properties.InstrumentationKey != nil && *c.Properties.InstrumentationKey != "", fmt.Sprint(err))
	ikey := ""
	if err == nil {
		ikey = *c.Properties.InstrumentationKey
	}
	check("connection string embeds the instrumentation key", err == nil && c.Properties.ConnectionString != nil &&
		strings.Contains(*c.Properties.ConnectionString, "InstrumentationKey="+ikey) && strings.Contains(*c.Properties.ConnectionString, "IngestionEndpoint="), "")
	check("component defaults (retention 30 as requested, provisioning Succeeded, app id)", err == nil && *c.Properties.RetentionInDays == 30 &&
		*c.Properties.ProvisioningState == "Succeeded" && c.Properties.AppID != nil, "")
	g, err := comps.Get(ctx, rg, name, nil)
	check("Components.Get", err == nil && *g.Name == name && *g.Kind == "web" && *g.Properties.InstrumentationKey == ikey, fmt.Sprint(err))
	t, err := comps.UpdateTags(ctx, rg, name, ai.TagsResource{Tags: map[string]*string{"env": to.Ptr("prod"), "team": to.Ptr("obs")}}, nil)
	check("Components.UpdateTags", err == nil && len(t.Tags) == 2 && *t.Tags["env"] == "prod", fmt.Sprint(err))

	n := 0
	pg := comps.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		page, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(page.Value)
	}
	check("Components.ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))
	n = 0
	lp := comps.NewListPager(nil)
	for lp.More() {
		page, e := lp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, v := range page.Value {
			if *v.Name == name {
				n++
			}
		}
	}
	check("Components.List (subscription)", err == nil && n == 1, fmt.Sprint(n, err))

	// API keys
	k, err := keys.Create(ctx, rg, name, ai.APIKeyRequest{Name: to.Ptr("reader"),
		LinkedReadProperties:  []*string{to.Ptr(*g.ID + "/api"), to.Ptr(*g.ID + "/agentconfig")},
		LinkedWriteProperties: []*string{to.Ptr(*g.ID + "/annotations")}}, nil)
	check("APIKeys.Create returns the key value", err == nil && k.APIKey != nil && *k.APIKey != "" && *k.Name == "reader", fmt.Sprint(err))
	keyID := ""
	if err == nil {
		keyID = (*k.ID)[strings.LastIndex(*k.ID, "/")+1:]
	}
	kg, err := keys.Get(ctx, rg, name, keyID, nil)
	check("APIKeys.Get hides the key value", err == nil && kg.APIKey == nil && len(kg.LinkedReadProperties) == 2, fmt.Sprint(err))
	n = 0
	kp := keys.NewListPager(rg, name, nil)
	for kp.More() {
		page, e := kp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(page.Value)
	}
	check("APIKeys.List", err == nil && n == 1, fmt.Sprint(n, err))
	_, err = keys.Delete(ctx, rg, name, keyID, nil)
	check("APIKeys.Delete", err == nil, fmt.Sprint(err))
	_, err = keys.Get(ctx, rg, name, keyID, nil)
	st, _ := errCode(err)
	check("APIKeys.Get after delete → 404", st == 404, fmt.Sprint(err))

	// billing features / daily cap
	f, err := feats.Update(ctx, rg, name, ai.ComponentBillingFeatures{DataVolumeCap: &ai.ComponentDataVolumeCap{Cap: to.Ptr(float32(5))}}, nil)
	check("ComponentCurrentBillingFeatures.Update (daily cap)", err == nil && f.DataVolumeCap != nil && *f.DataVolumeCap.Cap == 5.0, fmt.Sprint(err))
	fg, err := feats.Get(ctx, rg, name, nil)
	check("ComponentCurrentBillingFeatures.Get", err == nil && len(fg.CurrentBillingFeatures) == 1 && *fg.CurrentBillingFeatures[0] == "Basic" && *fg.DataVolumeCap.Cap == 5.0, fmt.Sprint(err))

	// availability web test linked to the component
	wtName := "wt-go"
	w, err := tests.CreateOrUpdate(ctx, rg, wtName, ai.WebTest{Location: &loc, Kind: to.Ptr(ai.WebTestKindPing),
		Tags: map[string]*string{"hidden-link:" + *g.ID: to.Ptr("Resource")},
		Properties: &ai.WebTestProperties{SyntheticMonitorID: &wtName, WebTestName: &wtName, WebTestKind: to.Ptr(ai.WebTestKindPing),
			Enabled: to.Ptr(true), Frequency: to.Ptr(int32(300)), Timeout: to.Ptr(int32(30)), RetryEnabled: to.Ptr(true),
			Locations:     []*ai.WebTestGeolocation{{Location: to.Ptr("us-fl-mia-edge")}},
			Configuration: &ai.WebTestPropertiesConfiguration{WebTest: to.Ptr("<WebTest Name=\"wt-go\" Url=\"https://example.com\"/>")}}}, nil)
	check("WebTests.CreateOrUpdate", err == nil && *w.Name == wtName && *w.Properties.Frequency == 300, fmt.Sprint(err))
	n = 0
	wp := tests.NewListByComponentPager(name, rg, nil)
	for wp.More() {
		page, e := wp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(page.Value)
	}
	check("WebTests.ListByComponent", err == nil && n == 1, fmt.Sprint(n, err))
	_, err = tests.CreateOrUpdate(ctx, rg, "wt-bad", ai.WebTest{Location: &loc,
		Properties: &ai.WebTestProperties{WebTestName: to.Ptr("wt-bad"), Frequency: to.Ptr(int32(42)),
			Locations: []*ai.WebTestGeolocation{{Location: to.Ptr("us-fl-mia-edge")}}}}, nil)
	st, _ = errCode(err)
	check("WebTests invalid frequency → 400", st == 400, fmt.Sprint(err))
	_, err = tests.Delete(ctx, rg, wtName, nil)
	check("WebTests.Delete", err == nil, fmt.Sprint(err))

	// purge + errors
	pr, err := comps.Purge(ctx, rg, name, ai.ComponentPurgeBody{Table: to.Ptr("Heartbeat"),
		Filters: []*ai.ComponentPurgeBodyFilters{{Column: to.Ptr("TimeGenerated"), Operator: to.Ptr(">"), Value: "2020-01-01"}}}, nil)
	check("Components.Purge returns an operation id", err == nil && pr.OperationID != nil, fmt.Sprint(err))
	_, err = comps.CreateOrUpdate(ctx, rg, "appi-bad", ai.Component{Location: &loc, Kind: to.Ptr("web"),
		Properties: &ai.ComponentProperties{ApplicationType: to.Ptr(ai.ApplicationTypeWeb), RetentionInDays: to.Ptr(int32(31))}}, nil)
	st, _ = errCode(err)
	check("invalid retention → 400", st == 400, fmt.Sprint(err))
	_, err = comps.Get(ctx, rg, "does-not-exist", nil)
	st, code := errCode(err)
	check("Components.Get missing → 404 ResourceNotFound", st == 404 && code == "ResourceNotFound", fmt.Sprint(st, code))

	_, err = comps.Delete(ctx, rg, name, nil)
	check("Components.Delete", err == nil, fmt.Sprint(err))
	_, err = comps.Get(ctx, rg, name, nil)
	st, _ = errCode(err)
	check("Components.Get after delete → 404", st == 404, fmt.Sprint(err))

	if failed > 0 {
		os.Exit(1)
	}
}

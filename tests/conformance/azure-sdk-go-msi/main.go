// Azure Managed Identities conformance: the real azure-sdk-for-go armmsi client against Vyomi — only the
// ARM endpoint changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
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
	"github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/msi/armmsi"
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
	name := fmt.Sprintf("go-id-%d", suffix)
	name2 := fmt.Sprintf("go-id2-%d", suffix)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	ids, err := armmsi.NewUserAssignedIdentitiesClient(sub, fakeCred{}, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	fcs, _ := armmsi.NewFederatedIdentityCredentialsClient(sub, fakeCred{}, opts)

	// ── identities ──
	id, err := ids.CreateOrUpdate(ctx, rg, name, armmsi.Identity{Location: to.Ptr("eastus"),
		Tags: map[string]*string{"env": to.Ptr("conf")}}, nil)
	check("CreateOrUpdate identity", err == nil && id.Name != nil && *id.Name == name, fmt.Sprint(err))
	p := id.Properties
	check("identity has clientId, principalId and tenantId", err == nil && p != nil && p.ClientID != nil && *p.ClientID != "" &&
		p.PrincipalID != nil && *p.PrincipalID != "" && p.TenantID != nil && *p.TenantID != "", fmt.Sprint(p))
	check("identity type is Microsoft.ManagedIdentity/userAssignedIdentities", err == nil && id.Type != nil &&
		*id.Type == "Microsoft.ManagedIdentity/userAssignedIdentities", fmt.Sprint(id.Type))
	got, err := ids.Get(ctx, rg, name, nil)
	check("Get identity", err == nil && got.Tags["env"] != nil && *got.Tags["env"] == "conf" &&
		got.Properties != nil && p != nil && *got.Properties.ClientID == *p.ClientID, fmt.Sprint(err))
	_, err = ids.Get(ctx, rg, "no-such-identity", nil)
	check("Get missing identity → 404", status(err) == 404, fmt.Sprint(err))
	_, err = ids.CreateOrUpdate(ctx, rg, "a!", armmsi.Identity{Location: to.Ptr("eastus")}, nil)
	check("invalid identity name → 400", status(err) == 400, fmt.Sprint(err))
	_, err = ids.CreateOrUpdate(ctx, rg, name, armmsi.Identity{Location: to.Ptr("westus")}, nil)
	check("changing the location of an identity → 400", status(err) == 400, fmt.Sprint(err))
	upd, err := ids.Update(ctx, rg, name, armmsi.IdentityUpdate{Tags: map[string]*string{"env": to.Ptr("updated")}}, nil)
	check("Update identity tags", err == nil && upd.Tags["env"] != nil && *upd.Tags["env"] == "updated", fmt.Sprint(err))
	check("Update keeps the same clientId", err == nil && p != nil && upd.Properties != nil && *upd.Properties.ClientID == *p.ClientID, "")
	_, err = ids.CreateOrUpdate(ctx, rg, name2, armmsi.Identity{Location: to.Ptr("westeurope")}, nil)
	check("CreateOrUpdate second identity", err == nil, fmt.Sprint(err))

	found := map[string]bool{}
	pg := ids.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		page, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range page.Value {
			found[*x.Name] = true
		}
	}
	check("ListByResourceGroup contains both identities", err == nil && found[name] && found[name2], fmt.Sprint(err, found))
	found = map[string]bool{}
	ps := ids.NewListBySubscriptionPager(nil)
	for ps.More() {
		page, e := ps.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range page.Value {
			found[*x.Name] = true
		}
	}
	check("ListBySubscription contains both identities", err == nil && found[name] && found[name2], fmt.Sprint(err, found))

	// ── federated identity credentials ──
	gh := "https://token.actions.githubusercontent.com"
	fc, err := fcs.CreateOrUpdate(ctx, rg, name, "github-main", armmsi.FederatedIdentityCredential{Properties: &armmsi.FederatedIdentityCredentialProperties{
		Issuer: to.Ptr(gh), Subject: to.Ptr("repo:cloudlearn/demo:ref:refs/heads/main"), Audiences: []*string{to.Ptr("api://AzureADTokenExchange")}}}, nil)
	check("CreateOrUpdate federated credential", err == nil && fc.Name != nil && *fc.Name == "github-main" && fc.Properties != nil &&
		*fc.Properties.Issuer == gh && len(fc.Properties.Audiences) == 1, fmt.Sprint(err))
	check("federated credential type and id", err == nil && fc.Type != nil && strings.HasSuffix(*fc.Type, "/federatedIdentityCredentials") &&
		fc.ID != nil && strings.HasSuffix(*fc.ID, "/userAssignedIdentities/"+name+"/federatedIdentityCredentials/github-main"), fmt.Sprint(fc.ID, fc.Type))
	_, err = fcs.CreateOrUpdate(ctx, rg, name, "github-dup", armmsi.FederatedIdentityCredential{Properties: &armmsi.FederatedIdentityCredentialProperties{
		Issuer: to.Ptr(gh), Subject: to.Ptr("repo:cloudlearn/demo:ref:refs/heads/main"), Audiences: []*string{to.Ptr("api://AzureADTokenExchange")}}}, nil)
	check("same issuer+subject under another name → 409", status(err) == 409, fmt.Sprint(err))
	_, err = fcs.CreateOrUpdate(ctx, rg, name, "bad-issuer", armmsi.FederatedIdentityCredential{Properties: &armmsi.FederatedIdentityCredentialProperties{
		Issuer: to.Ptr("http://insecure.example.com"), Subject: to.Ptr("s"), Audiences: []*string{to.Ptr("api://AzureADTokenExchange")}}}, nil)
	check("non-https issuer → 400", status(err) == 400, fmt.Sprint(err))
	_, err = fcs.CreateOrUpdate(ctx, rg, name, "k8s-prod", armmsi.FederatedIdentityCredential{Properties: &armmsi.FederatedIdentityCredentialProperties{
		Issuer: to.Ptr("https://oidc.example.com/cluster"), Subject: to.Ptr("system:serviceaccount:default:app"), Audiences: []*string{to.Ptr("api://AzureADTokenExchange")}}}, nil)
	check("CreateOrUpdate second federated credential", err == nil, fmt.Sprint(err))
	gf, err := fcs.Get(ctx, rg, name, "k8s-prod", nil)
	check("Get federated credential", err == nil && gf.Properties != nil && *gf.Properties.Subject == "system:serviceaccount:default:app", fmt.Sprint(err))
	_, err = fcs.Get(ctx, rg, name, "nope", nil)
	check("Get missing federated credential → 404", status(err) == 404, fmt.Sprint(err))
	n := 0
	err = nil
	pf := fcs.NewListPager(rg, name, nil)
	for pf.More() {
		page, e := pf.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(page.Value)
	}
	check("List federated credentials", err == nil && n == 2, fmt.Sprint(err, n))
	_, err = fcs.Delete(ctx, rg, name, "github-main", nil)
	check("Delete federated credential", err == nil, fmt.Sprint(err))
	_, err = fcs.Get(ctx, rg, name, "github-main", nil)
	check("deleted federated credential → 404", status(err) == 404, fmt.Sprint(err))

	// ── delete ──
	_, err = ids.Delete(ctx, rg, name, nil)
	check("Delete identity", err == nil, fmt.Sprint(err))
	_, err = ids.Get(ctx, rg, name, nil)
	check("deleted identity → 404", status(err) == 404, fmt.Sprint(err))
	_, err = ids.Delete(ctx, rg, name, nil)
	check("Delete is idempotent", err == nil, fmt.Sprint(err))
	_, err = ids.Delete(ctx, rg, name2, nil)
	check("Delete second identity", err == nil, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
}

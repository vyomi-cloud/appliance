// Azure Event Hubs conformance: the real azure-sdk-for-go armeventhub client against Vyomi — only the ARM
// endpoint changed — plus the Event Hubs REST send API (the AMQP/Kafka wires are not exposed) read back through
// the ARM-path events extension. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/arm"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/cloud"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	eh "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/eventhub/armeventhub"
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
	rg := fmt.Sprintf("rg-go-eh-%d", suffix)
	ns := fmt.Sprintf("goeh%d", suffix)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	namespaces, err := eh.NewNamespacesClient(sub, fakeCred{}, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	hubs, _ := eh.NewEventHubsClient(sub, fakeCred{}, opts)
	groups, _ := eh.NewConsumerGroupsClient(sub, fakeCred{}, opts)

	// ── namespace ──
	p, err := namespaces.BeginCreateOrUpdate(ctx, rg, ns, eh.EHNamespace{
		Location: to.Ptr("eastus"),
		SKU:      &eh.SKU{Name: to.Ptr(eh.SKUNameStandard), Tier: to.Ptr(eh.SKUTierStandard), Capacity: to.Ptr[int32](2)},
		Tags:     map[string]*string{"env": to.Ptr("conf")},
	}, nil)
	var got eh.NamespacesClientCreateOrUpdateResponse
	if err == nil {
		got, err = p.PollUntilDone(ctx, &poll)
	}
	check("BeginCreateOrUpdate namespace (LRO)", err == nil && got.Name != nil && *got.Name == ns, fmt.Sprint(err))
	endpoint := ""
	if got.Properties != nil && got.Properties.ServiceBusEndpoint != nil {
		endpoint = *got.Properties.ServiceBusEndpoint
	}
	check("namespace has endpoint, Standard sku with 2 TUs, Kafka on", endpoint != "" && *got.SKU.Capacity == 2 && *got.Properties.KafkaEnabled &&
		*got.Properties.ProvisioningState == "Succeeded", endpoint)
	g, err := namespaces.Get(ctx, rg, ns, nil)
	check("Get namespace", err == nil && g.Tags["env"] != nil && *g.Tags["env"] == "conf", fmt.Sprint(err))
	_, err = namespaces.Get(ctx, rg, "nosuchns99", nil)
	check("Get missing namespace → 404", status(err) == 404, fmt.Sprint(err))
	up, err := namespaces.Update(ctx, rg, ns, eh.EHNamespace{Tags: map[string]*string{"env": to.Ptr("updated")}}, nil)
	check("Update (tags)", err == nil && *up.Tags["env"] == "updated", fmt.Sprint(err))
	n := 0
	err = nil
	pg := namespaces.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		pp, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(pp.Value)
	}
	check("ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))
	err, n = nil, 0
	pg2 := namespaces.NewListPager(nil)
	for pg2.More() {
		pp, e := pg2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, a := range pp.Value {
			if a.Name != nil && *a.Name == ns {
				n++
			}
		}
	}
	check("List (subscription)", err == nil && n == 1, fmt.Sprint(n, err))
	_, err = namespaces.BeginCreateOrUpdate(ctx, rg+"b", ns, eh.EHNamespace{Location: to.Ptr("eastus")}, nil)
	check("duplicate namespace name → 409", status(err) == 409, fmt.Sprint(err))
	_, err = namespaces.BeginCreateOrUpdate(ctx, rg, "ab", eh.EHNamespace{Location: to.Ptr("eastus")}, nil)
	check("invalid namespace name → 400", status(err) == 400, fmt.Sprint(err))
	ca, err := namespaces.CheckNameAvailability(ctx, eh.CheckNameAvailabilityParameter{Name: to.Ptr(ns)}, nil)
	check("CheckNameAvailability: taken", err == nil && !*ca.NameAvailable, fmt.Sprint(err))
	ca, err = namespaces.CheckNameAvailability(ctx, eh.CheckNameAvailabilityParameter{Name: to.Ptr("free-" + ns)}, nil)
	check("CheckNameAvailability: free", err == nil && *ca.NameAvailable, fmt.Sprint(err))

	// ── namespace authorization rules ──
	keys, err := namespaces.ListKeys(ctx, rg, ns, "RootManageSharedAccessKey", nil)
	check("ListKeys on RootManageSharedAccessKey", err == nil && strings.HasPrefix(*keys.PrimaryConnectionString, "Endpoint=sb://"+ns+".servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;"), fmt.Sprint(err))
	rk, err := namespaces.RegenerateKeys(ctx, rg, ns, "RootManageSharedAccessKey", eh.RegenerateAccessKeyParameters{KeyType: to.Ptr(eh.KeyTypePrimaryKey)}, nil)
	check("RegenerateKeys rotates the primary key only", err == nil && *rk.PrimaryKey != *keys.PrimaryKey && *rk.SecondaryKey == *keys.SecondaryKey, fmt.Sprint(err))
	rule, err := namespaces.CreateOrUpdateAuthorizationRule(ctx, rg, ns, "send-only", eh.AuthorizationRule{
		Properties: &eh.AuthorizationRuleProperties{Rights: []*eh.AccessRights{to.Ptr(eh.AccessRightsSend)}}}, nil)
	check("CreateOrUpdateAuthorizationRule", err == nil && len(rule.Properties.Rights) == 1 && *rule.Properties.Rights[0] == eh.AccessRightsSend, fmt.Sprint(err))
	_, err = namespaces.CreateOrUpdateAuthorizationRule(ctx, rg, ns, "bad", eh.AuthorizationRule{
		Properties: &eh.AuthorizationRuleProperties{Rights: []*eh.AccessRights{to.Ptr(eh.AccessRightsManage)}}}, nil)
	check("Manage without Listen+Send → 400", status(err) == 400, fmt.Sprint(err))

	// ── event hubs ──
	h, err := hubs.CreateOrUpdate(ctx, rg, ns, "orders", eh.Eventhub{Properties: &eh.Properties{
		PartitionCount: to.Ptr[int64](4), MessageRetentionInDays: to.Ptr[int64](3)}}, nil)
	check("EventHubs.CreateOrUpdate", err == nil && *h.Name == "orders" && len(h.Properties.PartitionIDs) == 4 &&
		*h.Properties.MessageRetentionInDays == 3 && *h.Properties.Status == eh.EntityStatusActive, fmt.Sprint(err))
	_, err = hubs.CreateOrUpdate(ctx, rg, ns, "toomany", eh.Eventhub{Properties: &eh.Properties{PartitionCount: to.Ptr[int64](500)}}, nil)
	check("partitionCount over the limit → 400", status(err) == 400, fmt.Sprint(err))
	_, err = hubs.CreateOrUpdate(ctx, rg, ns, "orders", eh.Eventhub{Properties: &eh.Properties{PartitionCount: to.Ptr[int64](8)}}, nil)
	check("partitionCount can't change on Standard → 400", status(err) == 400, fmt.Sprint(err))
	hg, err := hubs.Get(ctx, rg, ns, "orders", nil)
	check("EventHubs.Get", err == nil && *hg.Properties.PartitionCount == 4, fmt.Sprint(err))
	_, err = hubs.Get(ctx, rg, ns, "nohub", nil)
	check("EventHubs.Get missing → 404", status(err) == 404, fmt.Sprint(err))
	err, n = nil, 0
	hp := hubs.NewListByNamespacePager(rg, ns, nil)
	for hp.More() {
		pp, e := hp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(pp.Value)
	}
	check("EventHubs.ListByNamespace", err == nil && n == 1, fmt.Sprint(n, err))
	hr, err := hubs.CreateOrUpdateAuthorizationRule(ctx, rg, ns, "orders", "listen", eh.AuthorizationRule{
		Properties: &eh.AuthorizationRuleProperties{Rights: []*eh.AccessRights{to.Ptr(eh.AccessRightsListen)}}}, nil)
	check("event hub authorization rule", err == nil && *hr.Name == "listen", fmt.Sprint(err))
	hk, err := hubs.ListKeys(ctx, rg, ns, "orders", "listen", nil)
	check("event hub ListKeys has EntityPath", err == nil && strings.HasSuffix(*hk.PrimaryConnectionString, ";EntityPath=orders"), fmt.Sprint(err))

	// ── consumer groups ──
	err = nil
	cgs := groups.NewListByEventHubPager(rg, ns, "orders", nil)
	names := []string{}
	for cgs.More() {
		pp, e := cgs.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, c := range pp.Value {
			names = append(names, *c.Name)
		}
	}
	check("$Default consumer group exists", err == nil && len(names) == 1 && names[0] == "$Default", fmt.Sprint(names, err))
	cg, err := groups.CreateOrUpdate(ctx, rg, ns, "orders", "analytics", eh.ConsumerGroup{Properties: &eh.ConsumerGroupProperties{UserMetadata: to.Ptr("reporting")}}, nil)
	check("ConsumerGroups.CreateOrUpdate", err == nil && *cg.Properties.UserMetadata == "reporting", fmt.Sprint(err))
	_, err = groups.Delete(ctx, rg, ns, "orders", "$Default", nil)
	check("deleting $Default → 400", status(err) == 400, fmt.Sprint(err))
	_, err = groups.Delete(ctx, rg, ns, "orders", "analytics", nil)
	check("ConsumerGroups.Delete", err == nil, fmt.Sprint(err))

	// ── data plane: REST send, read back via the console extension ──
	data := strings.TrimRight(endpoint, "/")
	if !strings.Contains(data, "/azure-data/eventhub/") { // not the simulator endpoint (real-shaped URL): route via the appliance
		data = ep + "/azure-data/eventhub/" + ns
	}
	post := func(path, ctype, body string, hdr map[string]string) int {
		req, _ := http.NewRequest("POST", data+path, strings.NewReader(body))
		req.Header.Set("Content-Type", ctype)
		for k, v := range hdr {
			req.Header.Set(k, v)
		}
		resp, e := http.DefaultClient.Do(req)
		if e != nil {
			return -1
		}
		defer resp.Body.Close()
		io.Copy(io.Discard, resp.Body)
		return resp.StatusCode
	}
	check("REST send single event → 201", post("/orders/messages", "application/atom+xml;type=entry;charset=utf-8", "hello-go",
		map[string]string{"BrokerProperties": `{"PartitionKey":"k1"}`}) == 201, "")
	check("REST send batch → 201", post("/orders/messages", "application/vnd.microsoft.servicebus.json",
		`[{"Body":"b1"},{"Body":"b2","BrokerProperties":{"PartitionKey":"k1"}}]`, nil) == 201, "")
	check("REST send to partition 3 → 201", post("/orders/partitions/3/messages", "text/plain", "to-p3", nil) == 201, "")
	check("REST send to unknown hub → 404", post("/nohub/messages", "text/plain", "x", nil) == 404, "")
	resp, err := http.Get(fmt.Sprintf("%s/subscriptions/%s/resourceGroups/%s/providers/Microsoft.EventHub/namespaces/%s/eventhubs/orders/events?api-version=2024-01-01&maxCount=50", ep, sub, rg, ns))
	var evs struct {
		Count int `json:"count"`
		Value []struct {
			Body        string `json:"body"`
			PartitionID string `json:"partitionId"`
		} `json:"value"`
	}
	if err == nil {
		json.NewDecoder(resp.Body).Decode(&evs)
		resp.Body.Close()
	}
	bodies := map[string]string{}
	for _, e := range evs.Value {
		bodies[e.Body] = e.PartitionID
	}
	check("sent events are readable per partition", err == nil && evs.Count == 4 && bodies["hello-go"] != "" && bodies["to-p3"] == "3", fmt.Sprint(evs.Count, bodies, err))
	check("same partition key → same partition", bodies["hello-go"] == bodies["b2"], fmt.Sprint(bodies))

	// ── cleanup ──
	_, err = hubs.Delete(ctx, rg, ns, "orders", nil)
	check("EventHubs.Delete", err == nil, fmt.Sprint(err))
	d, err := namespaces.BeginDelete(ctx, rg, ns, nil)
	if err == nil {
		_, err = d.PollUntilDone(ctx, &poll)
	}
	check("BeginDelete namespace", err == nil, fmt.Sprint(err))
	_, err = namespaces.Get(ctx, rg, ns, nil)
	check("deleted namespace → 404", status(err) == 404, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}

// Azure DNS conformance: the real azure-sdk-for-go armdns client against Vyomi — only the ARM
// endpoint changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
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
	dns "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/dns/armdns"
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
	zone := fmt.Sprintf("go%d.example.com", suffix)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	zones, err := dns.NewZonesClient(sub, fakeCred{}, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	rsets, _ := dns.NewRecordSetsClient(sub, fakeCred{}, opts)

	// ── zones ──
	z, err := zones.CreateOrUpdate(ctx, rg, zone, dns.Zone{Location: to.Ptr("global"),
		Tags: map[string]*string{"env": to.Ptr("conf")}}, nil)
	check("CreateOrUpdate zone", err == nil && z.Name != nil && *z.Name == zone, fmt.Sprint(err))
	check("zone has 4 name servers, maxNumberOfRecordSets and SOA+NS", err == nil && z.Properties != nil && len(z.Properties.NameServers) == 4 &&
		z.Properties.MaxNumberOfRecordSets != nil && *z.Properties.MaxNumberOfRecordSets == 10000 &&
		z.Properties.NumberOfRecordSets != nil && *z.Properties.NumberOfRecordSets == 2, fmt.Sprint(z.Properties))
	got, err := zones.Get(ctx, rg, zone, nil)
	check("Get zone", err == nil && got.Tags["env"] != nil && *got.Tags["env"] == "conf" && strings.HasSuffix(*got.Type, "dnszones"), fmt.Sprint(err))
	_, err = zones.Get(ctx, rg, "nosuch.example.com", nil)
	check("Get missing zone → 404", status(err) == 404, fmt.Sprint(err))
	_, err = zones.CreateOrUpdate(ctx, rg, "nodots", dns.Zone{Location: to.Ptr("global")}, nil)
	check("invalid zone name → 400", status(err) == 400, fmt.Sprint(err))
	up, err := zones.Update(ctx, rg, zone, dns.ZoneUpdate{Tags: map[string]*string{"env": to.Ptr("updated")}}, nil)
	check("Update zone (tags)", err == nil && up.Tags["env"] != nil && *up.Tags["env"] == "updated", fmt.Sprint(err))
	n := 0
	pg := zones.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		pp, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range pp.Value {
			if *x.Name == zone {
				n++
			}
		}
	}
	check("ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))
	n = 0
	pg2 := zones.NewListPager(nil)
	for pg2.More() {
		pp, e := pg2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range pp.Value {
			if *x.Name == zone {
				n++
			}
		}
	}
	check("List (subscription)", n == 1, fmt.Sprint(n, err))

	// ── record sets ──
	rs, err := rsets.CreateOrUpdate(ctx, rg, zone, "www", dns.RecordTypeA, dns.RecordSet{Properties: &dns.RecordSetProperties{
		TTL: to.Ptr[int64](300), ARecords: []*dns.ARecord{{IPv4Address: to.Ptr("10.0.0.4")}, {IPv4Address: to.Ptr("10.0.0.5")}}}}, nil)
	check("CreateOrUpdate A record set", err == nil && rs.Properties != nil && len(rs.Properties.ARecords) == 2 && *rs.Properties.TTL == 300 &&
		strings.HasPrefix(*rs.Properties.Fqdn, "www."+zone), fmt.Sprint(err))
	check("record set has etag + type", err == nil && rs.Etag != nil && *rs.Etag != "" && strings.HasSuffix(*rs.Type, "dnszones/A"), fmt.Sprint(rs.Type))
	_, err = rsets.CreateOrUpdate(ctx, rg, zone, "v6", dns.RecordTypeAAAA, dns.RecordSet{Properties: &dns.RecordSetProperties{
		TTL: to.Ptr[int64](60), AaaaRecords: []*dns.AaaaRecord{{IPv6Address: to.Ptr("2001:db8::1")}}}}, nil)
	check("AAAA record set", err == nil, fmt.Sprint(err))
	_, err = rsets.CreateOrUpdate(ctx, rg, zone, "alias", dns.RecordTypeCNAME, dns.RecordSet{Properties: &dns.RecordSetProperties{
		TTL: to.Ptr[int64](3600), CnameRecord: &dns.CnameRecord{Cname: to.Ptr("www." + zone)}}}, nil)
	check("CNAME record set", err == nil, fmt.Sprint(err))
	_, err = rsets.CreateOrUpdate(ctx, rg, zone, "@", dns.RecordTypeMX, dns.RecordSet{Properties: &dns.RecordSetProperties{
		TTL: to.Ptr[int64](3600), MxRecords: []*dns.MxRecord{{Preference: to.Ptr[int32](10), Exchange: to.Ptr("mail." + zone)}}}}, nil)
	check("MX record set at the apex", err == nil, fmt.Sprint(err))
	_, err = rsets.CreateOrUpdate(ctx, rg, zone, "@", dns.RecordTypeTXT, dns.RecordSet{Properties: &dns.RecordSetProperties{
		TTL: to.Ptr[int64](3600), TxtRecords: []*dns.TxtRecord{{Value: []*string{to.Ptr("v=spf1 -all")}}}}}, nil)
	check("TXT record set", err == nil, fmt.Sprint(err))
	_, err = rsets.CreateOrUpdate(ctx, rg, zone, "_sip._tcp", dns.RecordTypeSRV, dns.RecordSet{Properties: &dns.RecordSetProperties{
		TTL: to.Ptr[int64](3600), SrvRecords: []*dns.SrvRecord{{Priority: to.Ptr[int32](1), Weight: to.Ptr[int32](5), Port: to.Ptr[int32](5060), Target: to.Ptr("sip." + zone)}}}}, nil)
	check("SRV record set", err == nil, fmt.Sprint(err))
	_, err = rsets.CreateOrUpdate(ctx, rg, zone, "@", dns.RecordTypeCAA, dns.RecordSet{Properties: &dns.RecordSetProperties{
		TTL: to.Ptr[int64](3600), CaaRecords: []*dns.CaaRecord{{Flags: to.Ptr[int32](0), Tag: to.Ptr("issue"), Value: to.Ptr("letsencrypt.org")}}}}, nil)
	check("CAA record set", err == nil, fmt.Sprint(err))
	_, err = rsets.CreateOrUpdate(ctx, rg, zone, "alias", dns.RecordTypeA, dns.RecordSet{Properties: &dns.RecordSetProperties{
		ARecords: []*dns.ARecord{{IPv4Address: to.Ptr("10.0.0.9")}}}}, nil)
	check("A next to a CNAME of the same name → 409", status(err) == 409, fmt.Sprint(err))
	_, err = rsets.CreateOrUpdate(ctx, rg, zone, "@", dns.RecordTypeCNAME, dns.RecordSet{Properties: &dns.RecordSetProperties{
		CnameRecord: &dns.CnameRecord{Cname: to.Ptr("x.example.org")}}}, nil)
	check("CNAME at the apex → 400", status(err) == 400, fmt.Sprint(err))
	_, err = rsets.CreateOrUpdate(ctx, rg, zone, "bad", dns.RecordTypeA, dns.RecordSet{Properties: &dns.RecordSetProperties{
		ARecords: []*dns.ARecord{{IPv4Address: to.Ptr("999.1.1.1")}}}}, nil)
	check("invalid IPv4 → 400", status(err) == 400, fmt.Sprint(err))
	g, err := rsets.Get(ctx, rg, zone, "www", dns.RecordTypeA, nil)
	check("Get record set", err == nil && len(g.Properties.ARecords) == 2, fmt.Sprint(err))
	_, err = rsets.Get(ctx, rg, zone, "nosuch", dns.RecordTypeA, nil)
	check("Get missing record set → 404", status(err) == 404, fmt.Sprint(err))
	u, err := rsets.Update(ctx, rg, zone, "www", dns.RecordTypeA, dns.RecordSet{Properties: &dns.RecordSetProperties{
		TTL: to.Ptr[int64](120), Metadata: map[string]*string{"owner": to.Ptr("conf")}}}, nil)
	check("Update record set (TTL + metadata keep records)", err == nil && *u.Properties.TTL == 120 && len(u.Properties.ARecords) == 2 &&
		u.Properties.Metadata["owner"] != nil, fmt.Sprint(err))
	cnt := 0
	tp := rsets.NewListByTypePager(rg, zone, dns.RecordTypeA, nil)
	for tp.More() {
		pp, e := tp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		cnt += len(pp.Value)
	}
	check("ListByType A", err == nil && cnt == 1, fmt.Sprint(cnt, err))
	cnt = 0
	ap := rsets.NewListAllByDNSZonePager(rg, zone, &dns.RecordSetsClientListAllByDNSZoneOptions{Top: to.Ptr[int32](3)})
	for ap.More() {
		pp, e := ap.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		cnt += len(pp.Value)
	}
	check("ListAllByDNSZone pages through every record set (top=3)", err == nil && cnt == 9, fmt.Sprint(cnt, err))
	cnt = 0
	dp := rsets.NewListByDNSZonePager(rg, zone, &dns.RecordSetsClientListByDNSZoneOptions{Recordsetnamesuffix: to.Ptr("_tcp")})
	for dp.More() {
		pp, e := dp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		cnt += len(pp.Value)
	}
	check("ListByDNSZone with recordsetnamesuffix", err == nil && cnt == 1, fmt.Sprint(cnt, err))
	z2, _ := zones.Get(ctx, rg, zone, nil)
	check("numberOfRecordSets reflects the record sets", *z2.Properties.NumberOfRecordSets == 9, fmt.Sprint(*z2.Properties.NumberOfRecordSets))
	_, err = rsets.Delete(ctx, rg, zone, "@", dns.RecordTypeSOA, nil)
	check("deleting the SOA record set → 400", status(err) == 400, fmt.Sprint(err))
	_, err = rsets.Delete(ctx, rg, zone, "v6", dns.RecordTypeAAAA, nil)
	check("Delete record set", err == nil, fmt.Sprint(err))
	_, err = rsets.Get(ctx, rg, zone, "v6", dns.RecordTypeAAAA, nil)
	check("deleted record set → 404", status(err) == 404, fmt.Sprint(err))

	// ── zone delete ──
	d, err := zones.BeginDelete(ctx, rg, zone, nil)
	if err == nil {
		_, err = d.PollUntilDone(ctx, &poll)
	}
	check("BeginDelete zone (LRO)", err == nil, fmt.Sprint(err))
	_, err = zones.Get(ctx, rg, zone, nil)
	check("deleted zone → 404", status(err) == 404, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}

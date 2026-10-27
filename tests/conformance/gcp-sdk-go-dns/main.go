// Real google.golang.org/api/dns/v1 conformance against Vyomi's Cloud DNS API.
// ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check;
// exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	dns "google.golang.org/api/dns/v1"
	"google.golang.org/api/googleapi"
	"google.golang.org/api/option"
)

var pass, fail int

func check(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
	} else {
		fail++
		fmt.Printf("[FAIL] %s :: %s\n", name, detail)
	}
}

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func httpCode(err error) int {
	var ge *googleapi.Error
	if errors.As(err, &ge) {
		return ge.Code
	}
	return 0
}

func reason(err error) string {
	var ge *googleapi.Error
	if errors.As(err, &ge) && len(ge.Errors) > 0 {
		return ge.Errors[0].Reason
	}
	return ""
}

func main() {
	endpoint := strings.TrimRight(env("ENDPOINT", "http://127.0.0.1:9000"), "/") + "/"
	project := env("PROJECT", "go-dns-proj")
	fmt.Printf("== google.golang.org/api/dns/v1 (Go) against %s project=%s ==\n", endpoint, project)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	svc, err := dns.NewService(ctx, option.WithEndpoint(endpoint), option.WithoutAuthentication())
	if err != nil {
		fmt.Printf("[FAIL] client :: %v\n", err)
		os.Exit(1)
	}
	zoneName := fmt.Sprintf("go-zone-%d", time.Now().UnixNano()%1000000)
	domain := zoneName + ".example.net."

	z, err := svc.ManagedZones.Create(project, &dns.ManagedZone{Name: zoneName, DnsName: domain, Description: "created by the Go SDK",
		Labels: map[string]string{"env": "test"}}).Context(ctx).Do()
	check("ManagedZones.Create", err == nil && z.Name == zoneName && z.DnsName == domain && len(z.NameServers) == 4 &&
		z.Visibility == "public" && z.Id != 0, fmt.Sprintf("%v %+v", err, z))

	_, err = svc.ManagedZones.Create(project, &dns.ManagedZone{Name: zoneName, DnsName: domain}).Context(ctx).Do()
	check("duplicate zone → 409 alreadyExists", httpCode(err) == 409 && reason(err) == "alreadyExists", fmt.Sprint(err))

	_, err = svc.ManagedZones.Create(project, &dns.ManagedZone{Name: zoneName + "-bad", DnsName: "no-trailing-dot.com"}).Context(ctx).Do()
	check("dnsName without trailing dot → 400", httpCode(err) == 400, fmt.Sprint(err))

	g, err := svc.ManagedZones.Get(project, zoneName).Context(ctx).Do()
	check("ManagedZones.Get", err == nil && g.Description == "created by the Go SDK" && g.Labels["env"] == "test", fmt.Sprintf("%v %+v", err, g))

	_, err = svc.ManagedZones.Get(project, "no-such-zone").Context(ctx).Do()
	check("Get missing zone → 404 notFound", httpCode(err) == 404 && reason(err) == "notFound", fmt.Sprint(err))

	l, err := svc.ManagedZones.List(project).Context(ctx).Do()
	found := false
	if err == nil {
		for _, mz := range l.ManagedZones {
			if mz.Name == zoneName {
				found = true
			}
		}
	}
	check("ManagedZones.List contains the zone", found, fmt.Sprint(err))

	op, err := svc.ManagedZones.Patch(project, zoneName, &dns.ManagedZone{Description: "patched by the Go SDK"}).Context(ctx).Do()
	g, _ = svc.ManagedZones.Get(project, zoneName).Context(ctx).Do()
	check("ManagedZones.Patch", err == nil && op != nil && g != nil && g.Description == "patched by the Go SDK", fmt.Sprint(err))

	rs, err := svc.ResourceRecordSets.List(project, zoneName).Context(ctx).Do()
	types := []string{}
	if err == nil {
		for _, r := range rs.Rrsets {
			types = append(types, r.Type)
		}
	}
	check("new zone has default NS + SOA", err == nil && strings.Join(types, ",") == "NS,SOA", fmt.Sprint(err, types))

	www := "www." + domain
	ch, err := svc.Changes.Create(project, zoneName, &dns.Change{Additions: []*dns.ResourceRecordSet{
		{Name: www, Type: "A", Ttl: 120, Rrdatas: []string{"192.0.2.10", "192.0.2.11"}},
		{Name: domain, Type: "MX", Ttl: 300, Rrdatas: []string{"10 mail." + domain}},
		{Name: "txt." + domain, Type: "TXT", Ttl: 60, Rrdatas: []string{"\"v=spf1 -all\""}},
	}}).Context(ctx).Do()
	check("Changes.Create (additions)", err == nil && ch.Status == "done" && len(ch.Additions) == 3 && ch.Id != "", fmt.Sprintf("%v %+v", err, ch))

	r, err := svc.ResourceRecordSets.Get(project, zoneName, www, "A").Context(ctx).Do()
	check("ResourceRecordSets.Get", err == nil && r.Ttl == 120 && len(r.Rrdatas) == 2, fmt.Sprintf("%v %+v", err, r))

	rs, err = svc.ResourceRecordSets.List(project, zoneName).Name(www).Type("A").Context(ctx).Do()
	check("ResourceRecordSets.List name+type filter", err == nil && len(rs.Rrsets) == 1, fmt.Sprint(err))

	rs, err = svc.ResourceRecordSets.List(project, zoneName).MaxResults(2).Context(ctx).Do()
	check("ResourceRecordSets.List pagination", err == nil && len(rs.Rrsets) == 2 && rs.NextPageToken != "", fmt.Sprintf("%v %+v", err, rs))
	if err == nil && rs.NextPageToken != "" {
		rs2, err2 := svc.ResourceRecordSets.List(project, zoneName).MaxResults(2).PageToken(rs.NextPageToken).Context(ctx).Do()
		check("ResourceRecordSets.List next page", err2 == nil && len(rs2.Rrsets) >= 1 && rs2.Rrsets[0].Name+rs2.Rrsets[0].Type != rs.Rrsets[0].Name+rs.Rrsets[0].Type, fmt.Sprint(err2))
	}

	_, err = svc.Changes.Create(project, zoneName, &dns.Change{Additions: []*dns.ResourceRecordSet{
		{Name: www, Type: "A", Ttl: 120, Rrdatas: []string{"192.0.2.99"}}}}).Context(ctx).Do()
	check("adding an existing rrset → 409", httpCode(err) == 409, fmt.Sprint(err))

	_, err = svc.Changes.Create(project, zoneName, &dns.Change{Additions: []*dns.ResourceRecordSet{
		{Name: "bad." + domain, Type: "A", Ttl: 120, Rrdatas: []string{"not-an-ip"}}}}).Context(ctx).Do()
	check("invalid A rrdata → 400", httpCode(err) == 400, fmt.Sprint(err))

	_, err = svc.Changes.Create(project, zoneName, &dns.Change{Deletions: []*dns.ResourceRecordSet{
		{Name: www, Type: "A", Ttl: 5, Rrdatas: []string{"192.0.2.10", "192.0.2.11"}}}}).Context(ctx).Do()
	check("delete with mismatched TTL → 412 conditionNotMet", httpCode(err) == 412 && reason(err) == "conditionNotMet", fmt.Sprint(err))

	ch, err = svc.Changes.Create(project, zoneName, &dns.Change{
		Deletions: []*dns.ResourceRecordSet{{Name: www, Type: "A", Ttl: 120, Rrdatas: []string{"192.0.2.10", "192.0.2.11"}}},
		Additions: []*dns.ResourceRecordSet{{Name: www, Type: "A", Ttl: 30, Rrdatas: []string{"198.51.100.7"}}}}).Context(ctx).Do()
	r, _ = svc.ResourceRecordSets.Get(project, zoneName, www, "A").Context(ctx).Do()
	check("atomic replace in one change", err == nil && r != nil && r.Ttl == 30 && r.Rrdatas[0] == "198.51.100.7", fmt.Sprint(err))

	r, err = svc.ResourceRecordSets.Patch(project, zoneName, www, "A", &dns.ResourceRecordSet{Ttl: 45, Rrdatas: []string{"198.51.100.8"}}).Context(ctx).Do()
	check("ResourceRecordSets.Patch", err == nil && r.Ttl == 45 && r.Rrdatas[0] == "198.51.100.8", fmt.Sprintf("%v %+v", err, r))

	_, err = svc.ResourceRecordSets.Create(project, zoneName, &dns.ResourceRecordSet{Name: "api." + domain, Type: "CNAME", Ttl: 300, Rrdatas: []string{www}}).Context(ctx).Do()
	check("ResourceRecordSets.Create (CNAME)", err == nil, fmt.Sprint(err))

	_, err = svc.ResourceRecordSets.Delete(project, zoneName, "api."+domain, "CNAME").Context(ctx).Do()
	_, gerr := svc.ResourceRecordSets.Get(project, zoneName, "api."+domain, "CNAME").Context(ctx).Do()
	check("ResourceRecordSets.Delete", err == nil && httpCode(gerr) == 404, fmt.Sprint(err, gerr))

	cl, err := svc.Changes.List(project, zoneName).SortOrder("descending").Context(ctx).Do()
	check("Changes.List (descending)", err == nil && len(cl.Changes) >= 4 && cl.Changes[0].Id > "", fmt.Sprint(err))
	if err == nil && len(cl.Changes) > 0 {
		c1, err := svc.Changes.Get(project, zoneName, cl.Changes[len(cl.Changes)-1].Id).Context(ctx).Do()
		check("Changes.Get", err == nil && c1.Status == "done", fmt.Sprint(err))
	}

	pr, err := svc.Projects.Get(project).Context(ctx).Do()
	check("Projects.Get quota", err == nil && pr.Quota != nil && pr.Quota.ManagedZones > 0, fmt.Sprint(err))

	pol, err := svc.Policies.Create(project, &dns.Policy{Name: zoneName + "-pol", Description: "go policy", EnableInboundForwarding: true}).Context(ctx).Do()
	check("Policies.Create", err == nil && pol.EnableInboundForwarding, fmt.Sprint(err))
	pl, err := svc.Policies.List(project).Context(ctx).Do()
	check("Policies.List", err == nil && len(pl.Policies) >= 1, fmt.Sprint(err))
	err = svc.Policies.Delete(project, zoneName+"-pol").Context(ctx).Do()
	check("Policies.Delete", err == nil, fmt.Sprint(err))

	err = svc.ManagedZones.Delete(project, zoneName).Context(ctx).Do()
	check("delete non-empty zone → 400 containerNotEmpty", httpCode(err) == 400 && reason(err) == "containerNotEmpty", fmt.Sprint(err))

	cur, _ := svc.ResourceRecordSets.List(project, zoneName).Context(ctx).Do()
	var del []*dns.ResourceRecordSet
	for _, rr := range cur.Rrsets {
		if rr.Type != "NS" && rr.Type != "SOA" {
			del = append(del, rr)
		}
	}
	_, err = svc.Changes.Create(project, zoneName, &dns.Change{Deletions: del}).Context(ctx).Do()
	check("delete all custom records", err == nil, fmt.Sprint(err))
	err = svc.ManagedZones.Delete(project, zoneName).Context(ctx).Do()
	check("ManagedZones.Delete", err == nil, fmt.Sprint(err))
	_, err = svc.ManagedZones.Get(project, zoneName).Context(ctx).Do()
	check("deleted zone is gone (404)", httpCode(err) == 404, fmt.Sprint(err))

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}

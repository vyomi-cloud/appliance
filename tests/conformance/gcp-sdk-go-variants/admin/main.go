// Real google.golang.org/api (Apiary REST) conformance probe for the admin/REST
// GCP services: Compute Engine, Cloud SQL Admin, Cloud Functions, IAM. Proves the
// official Google REST clients can list resources from the simulator with an
// endpoint override + no credentials. ENDPOINT default http://127.0.0.1:9000,
// PROJECT default gcp-dev.
package main

import (
	"context"
	"fmt"
	"os"

	cloudfunctions "google.golang.org/api/cloudfunctions/v1"
	compute "google.golang.org/api/compute/v1"
	iam "google.golang.org/api/iam/v1"
	"google.golang.org/api/option"
	sqladmin "google.golang.org/api/sqladmin/v1beta4"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

var pass, fail int

func chk(name string, ok bool, detail string) {
	if ok {
		fmt.Println("PASS", name)
		pass++
	} else {
		fmt.Println("FAIL", name, "::", detail)
		fail++
	}
}

func main() {
	endpoint := env("ENDPOINT", "http://127.0.0.1:9000")
	project := env("PROJECT", "gcp-dev")
	zone := "us-central1-a"
	location := "us-central1"
	ctx := context.Background()
	noauth := option.WithoutAuthentication()
	fmt.Printf("== google.golang.org/api (REST) against %s project=%s ==\n", endpoint, project)

	// Compute
	if csvc, err := compute.NewService(ctx, noauth, option.WithEndpoint(endpoint+"/compute/v1/")); err != nil {
		chk("compute NewService", false, err.Error())
	} else {
		il, e := csvc.Instances.List(project, zone).Do()
		chk("compute instances.list", e == nil, fmt.Sprint(e))
		if e == nil {
			fmt.Printf("   (instances=%d)\n", len(il.Items))
		}
		nl, e2 := csvc.Networks.List(project).Do()
		chk("compute networks.list", e2 == nil, fmt.Sprint(e2))
		_ = nl
	}

	// Cloud SQL Admin
	if ssvc, err := sqladmin.NewService(ctx, noauth, option.WithEndpoint(endpoint+"/")); err != nil {
		chk("sqladmin NewService", false, err.Error())
	} else {
		l, e := ssvc.Instances.List(project).Do()
		chk("sqladmin instances.list", e == nil, fmt.Sprint(e))
		if e == nil {
			fmt.Printf("   (sql instances=%d)\n", len(l.Items))
		}
	}

	// Cloud Functions
	if fsvc, err := cloudfunctions.NewService(ctx, noauth, option.WithEndpoint(endpoint+"/")); err != nil {
		chk("functions NewService", false, err.Error())
	} else {
		parent := fmt.Sprintf("projects/%s/locations/%s", project, location)
		l, e := fsvc.Projects.Locations.Functions.List(parent).Do()
		chk("functions list", e == nil, fmt.Sprint(e))
		if e == nil {
			fmt.Printf("   (functions=%d)\n", len(l.Functions))
		}
	}

	// IAM
	if isvc, err := iam.NewService(ctx, noauth, option.WithEndpoint(endpoint+"/")); err != nil {
		chk("iam NewService", false, err.Error())
	} else {
		l, e := isvc.Projects.ServiceAccounts.List("projects/" + project).Do()
		chk("iam serviceAccounts.list", e == nil, fmt.Sprint(e))
		if e == nil {
			fmt.Printf("   (service accounts=%d)\n", len(l.Accounts))
		}
	}

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}

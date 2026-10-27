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
	"time"

	cloudfunctions "google.golang.org/api/cloudfunctions/v1"
	compute "google.golang.org/api/compute/v1"
	iam "google.golang.org/api/iam/v1"
	"google.golang.org/api/option"
	pubsubapi "google.golang.org/api/pubsub/v1"
	secretmanager "google.golang.org/api/secretmanager/v1"
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
		chk("sqladmin instances.list (ListInstances, ListInstancesResp)", e == nil, fmt.Sprint(e))
		if e == nil {
			fmt.Printf("   (sql instances=%d)\n", len(l.Items))
		}
		// Instance lifecycle: insert, get, database insert, delete.
		name := fmt.Sprintf("conf-sql-%d", time.Now().Unix())
		_, e = ssvc.Instances.Insert(project, &sqladmin.DatabaseInstance{
			Name: name, DatabaseVersion: "POSTGRES_15", Region: location,
			Settings: &sqladmin.Settings{Tier: "db-f1-micro"},
		}).Do()
		chk("sqladmin instances.insert (InsertInstance)", e == nil, fmt.Sprint(e))
		if e == nil {
			g, e := ssvc.Instances.Get(project, name).Do()
			chk("sqladmin instances.get (GetInstanceResp)", e == nil && g.Name == name, fmt.Sprint(e))
			l2, e := ssvc.Instances.List(project).Do()
			found := false
			if e == nil {
				for _, it := range l2.Items {
					found = found || it.Name == name
				}
			}
			chk("sqladmin instances.list contains new instance", found, fmt.Sprint(e))
			_, e = ssvc.Databases.Insert(project, name, &sqladmin.Database{Name: "appdb"}).Do()
			chk("sqladmin databases.insert (InsertDatabase)", e == nil, fmt.Sprint(e))
			_, e = ssvc.Instances.Delete(project, name).Do()
			chk("sqladmin instances.delete (DeleteInstance)", e == nil, fmt.Sprint(e))
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
		chk("iam serviceAccounts.list (ListServiceAccounts)", e == nil, fmt.Sprint(e))
		if e == nil {
			fmt.Printf("   (service accounts=%d)\n", len(l.Accounts))
		}
		// Service account lifecycle: create, get, list, delete.
		acct := fmt.Sprintf("conf-sa-%d", time.Now().Unix()%100000000)
		sa, e := isvc.Projects.ServiceAccounts.Create("projects/"+project, &iam.CreateServiceAccountRequest{
			AccountId: acct, ServiceAccount: &iam.ServiceAccount{DisplayName: "Conformance"},
		}).Do()
		chk("iam serviceAccounts.create (CreateServiceAccount)", e == nil && sa != nil && sa.Email != "", fmt.Sprint(e))
		if e == nil && sa != nil {
			g, e := isvc.Projects.ServiceAccounts.Get(sa.Name).Do()
			chk("iam serviceAccounts.get (GetServiceAccount)", e == nil && g.Email == sa.Email, fmt.Sprint(e))
			l3, e := isvc.Projects.ServiceAccounts.List("projects/" + project).Do()
			found := false
			if e == nil {
				for _, a := range l3.Accounts {
					found = found || a.Email == sa.Email
				}
			}
			chk("iam serviceAccounts.list contains new account", found, fmt.Sprint(e))
			_, e = isvc.Projects.ServiceAccounts.Delete(sa.Name).Do()
			chk("iam serviceAccounts.delete (DeleteServiceAccount)", e == nil, fmt.Sprint(e))
		}
	}

	// Secret Manager: version state transitions.
	if msvc, err := secretmanager.NewService(ctx, noauth, option.WithEndpoint(endpoint+"/")); err != nil {
		chk("secretmanager NewService", false, err.Error())
	} else {
		sid := fmt.Sprintf("conf-sec-%d", time.Now().Unix())
		parent := "projects/" + project
		sec, e := msvc.Projects.Secrets.Create(parent, &secretmanager.Secret{
			Replication: &secretmanager.Replication{Automatic: &secretmanager.Automatic{}},
		}).SecretId(sid).Do()
		chk("secretmanager secrets.create", e == nil, fmt.Sprint(e))
		if e == nil {
			v, e := msvc.Projects.Secrets.AddVersion(sec.Name, &secretmanager.AddSecretVersionRequest{
				Payload: &secretmanager.SecretPayload{Data: "c2VjcmV0"},
			}).Do()
			chk("secretmanager addVersion", e == nil && v != nil && v.State == "ENABLED", fmt.Sprint(e))
			if e == nil {
				d, e := msvc.Projects.Secrets.Versions.Disable(v.Name, &secretmanager.DisableSecretVersionRequest{}).Do()
				chk("secretmanager versions.disable (SetVersionState)", e == nil && d.State == "DISABLED", fmt.Sprint(e))
				_, e = msvc.Projects.Secrets.Versions.Access(v.Name).Do()
				chk("secretmanager access of disabled version fails", e != nil, "expected error")
				en, e := msvc.Projects.Secrets.Versions.Enable(v.Name, &secretmanager.EnableSecretVersionRequest{}).Do()
				chk("secretmanager versions.enable", e == nil && en.State == "ENABLED", fmt.Sprint(e))
				x, e := msvc.Projects.Secrets.Versions.Destroy(v.Name, &secretmanager.DestroySecretVersionRequest{}).Do()
				chk("secretmanager versions.destroy", e == nil && x.State == "DESTROYED", fmt.Sprint(e))
			}
			_, e = msvc.Projects.Secrets.Delete(sec.Name).Do()
			chk("secretmanager secrets.delete", e == nil, fmt.Sprint(e))
		}
	}

	// Pub/Sub (REST): subscription get.
	if psvc, err := pubsubapi.NewService(ctx, noauth, option.WithEndpoint(endpoint+"/")); err != nil {
		chk("pubsub NewService", false, err.Error())
	} else {
		tn := fmt.Sprintf("projects/%s/topics/conf-t-%d", project, time.Now().Unix())
		sn := fmt.Sprintf("projects/%s/subscriptions/conf-s-%d", project, time.Now().Unix())
		_, e := psvc.Projects.Topics.Create(tn, &pubsubapi.Topic{}).Do()
		chk("pubsub topics.create", e == nil, fmt.Sprint(e))
		_, e = psvc.Projects.Subscriptions.Create(sn, &pubsubapi.Subscription{Topic: tn, AckDeadlineSeconds: 30}).Do()
		chk("pubsub subscriptions.create", e == nil, fmt.Sprint(e))
		g, e := psvc.Projects.Subscriptions.Get(sn).Do()
		chk("pubsub subscriptions.get (GetSubscription)", e == nil && g.Name == sn && g.Topic == tn, fmt.Sprint(e))
		_, e = psvc.Projects.Subscriptions.Delete(sn).Do()
		chk("pubsub subscriptions.delete", e == nil, fmt.Sprint(e))
		_, e = psvc.Projects.Topics.Delete(tn).Do()
		chk("pubsub topics.delete", e == nil, fmt.Sprint(e))
	}

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}

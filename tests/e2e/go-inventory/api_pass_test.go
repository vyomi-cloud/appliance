// api_pass_test.go — Go counterpart to the Playwright console-pass spec.
//
// Uses unmodified cloud.google.com/go SDKs to provision the GCP resources
// directly against the simulator, then HTTP-pokes the running go-inventory
// app's endpoints and asserts correctness.
//
// Run with the app + simulator both reachable:
//
//	ENDPOINT=http://192.168.252.7:9000 APP_BASE=http://192.168.252.7:8081 \
//	  go test -v -run TestApiPass
//
// The test creates a Postgres DB via the Azure SQL path (same approach as the
// Playwright spec) since the simulator's Cloud SQL real-Postgres provisioning
// path returns connection strings the same way.
package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"
)

const (
	envEndpoint = "ENDPOINT"
	envAppBase  = "APP_BASE"

	tProject      = "inventory-app"
	tSecret       = "inventory-db-creds"
	tBucket       = "inventory-images"
	tTopic        = "inventory-events"
	tSub          = "inventory-worker"
	tKeyring      = "inventory-keyring"
	tKey          = "sku-key"
)

func endpoint() string { return envOr(envEndpoint, "http://192.168.252.7:9000") }
func appBase() string  { return envOr(envAppBase, "http://192.168.252.7:8081") }

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

// ----------------------------------------------------------------------------
// TestApiPass: the whole flow as a single subtests-driven Go test.
// ----------------------------------------------------------------------------
func TestApiPass(t *testing.T) {
	ep := endpoint()
	t.Logf("simulator: %s", ep)
	t.Logf("app:       %s", appBase())

	var dbConn map[string]any

	t.Run("provision Postgres via Azure SQL path", func(t *testing.T) {
		if err := switchSpace(ep, "azure"); err != nil { t.Fatal(err) }

		api := "api-version=2023-08-01"
		base := ep + "/subscriptions/sub-e2e/resourceGroups/rg-e2e/providers/Microsoft.Sql/servers/inv-sql"

		mustHttp(t, "PUT", base+"?"+api,
			`{"location":"eastus","properties":{"administratorLogin":"azureadmin","administratorLoginPassword":"Password123!"}}`)
		mustHttp(t, "PUT", base+"/databases/inventory?"+api,
			`{"location":"eastus","properties":{}}`)

		body := mustHttp(t, "GET", base+"/databases/inventory?"+api, "")
		var resp struct {
			Properties struct {
				ConnectionInfo map[string]any `json:"connectionInfo"`
			} `json:"properties"`
		}
		if err := json.Unmarshal([]byte(body), &resp); err != nil { t.Fatal(err) }
		dbConn = resp.Properties.ConnectionInfo
		if dbConn == nil || !strings.Contains(fmt.Sprint(dbConn["engine"]), "PostgreSQL") {
			t.Fatalf("expected real Postgres connectionInfo, got: %s", body)
		}
		t.Logf("real Postgres DB ready: %v", dbConn["database"])
	})

	t.Run("provision GCP resources", func(t *testing.T) {
		if err := switchSpace(ep, "gcp"); err != nil { t.Fatal(err) }

		// 1. Secret Manager — create + addVersion.
		mustHttp(t, "POST", fmt.Sprintf("%s/v1/projects/%s/secrets?secretId=%s", ep, tProject, tSecret),
			`{"replication":{"automatic":{}}}`)

		secretBody := mustJSON(map[string]any{
			"url":      fmt.Sprintf("postgresql://%v:%v@%v:%v/%v",
				dbConn["user"], dbConn["password"], dbConn["host"], dbConn["port"], dbConn["database"]),
			"user":     dbConn["user"],
			"password": dbConn["password"],
		})
		dataB64 := base64.StdEncoding.EncodeToString([]byte(secretBody))
		mustHttp(t, "POST",
			fmt.Sprintf("%s/v1/projects/%s/secrets/%s:addVersion", ep, tProject, tSecret),
			fmt.Sprintf(`{"payload":{"data":"%s"}}`, dataB64))

		// 2. Storage bucket.
		mustHttp(t, "POST", fmt.Sprintf("%s/storage/v1/b?project=%s", ep, tProject),
			fmt.Sprintf(`{"name":"%s","location":"us-central1"}`, tBucket))

		// 3. Pub/Sub topic + subscription.
		mustHttp(t, "PUT", fmt.Sprintf("%s/v1/projects/%s/topics/%s", ep, tProject, tTopic), `{}`)
		mustHttp(t, "PUT", fmt.Sprintf("%s/v1/projects/%s/subscriptions/%s", ep, tProject, tSub),
			fmt.Sprintf(`{"topic":"projects/%s/topics/%s"}`, tProject, tTopic))

		// 4. KMS encrypt is implicit-on-use; nothing to provision.
		t.Logf("provisioned: secret + bucket + topic + subscription")
	})

	t.Run("app health=UP", func(t *testing.T) {
		deadline := time.Now().Add(90 * time.Second)
		var last string
		for time.Now().Before(deadline) {
			body, code, err := tryHttp("GET", appBase()+"/health", "")
			if err == nil && code == 200 {
				var h map[string]any
				if jerr := json.Unmarshal([]byte(body), &h); jerr == nil {
					last = body
					if fmt.Sprint(h["status"]) == "UP" {
						for _, svc := range []string{"db", "storage", "pubsub", "kms", "secret_manager"} {
							if v, _ := h[svc].(map[string]any); v == nil || v["ok"] != true {
								t.Fatalf("svc %s not OK in health: %s", svc, body)
							}
						}
						return
					}
				}
			}
			time.Sleep(2 * time.Second)
		}
		t.Fatalf("app /health never became UP; last=%s", last)
	})

	t.Run("POST /items round-trip", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		_ = ctx
		body := mustHttp(t, "POST", appBase()+"/items",
			`{"name":"widget","sku":"W-001","stock":5}`)
		var item struct {
			ID int64 `json:"id"`
		}
		if err := json.Unmarshal([]byte(body), &item); err != nil { t.Fatal(err) }
		if item.ID <= 0 { t.Fatalf("expected id>0, got %d", item.ID) }

		listBody := mustHttp(t, "GET", appBase()+"/items", "")
		if !strings.Contains(listBody, "widget") {
			t.Fatalf("GET /items doesn't contain created item: %s", listBody)
		}

		// GET image → upload to bucket.
		imgBody := mustHttp(t, "GET", fmt.Sprintf("%s/items/%d/image", appBase(), item.ID), "")
		if !strings.Contains(imgBody, tBucket) {
			t.Fatalf("expected bucket %s in image URL: %s", tBucket, imgBody)
		}
	})
}

// ----------------------------------------------------------------------------
// helpers
// ----------------------------------------------------------------------------
func switchSpace(ep, provider string) error {
	body, _, err := tryHttp("GET", ep+"/api/spaces", "")
	if err != nil { return err }
	var resp struct {
		Spaces []struct {
			SpaceID  string `json:"space_id"`
			Provider string `json:"provider"`
		} `json:"spaces"`
	}
	if err := json.Unmarshal([]byte(body), &resp); err != nil { return err }
	for _, s := range resp.Spaces {
		if s.Provider == provider {
			_, _, err := tryHttp("POST", ep+"/api/spaces/"+s.SpaceID+"/switch", "")
			return err
		}
	}
	// create one
	created, _, err := tryHttp("POST", ep+"/api/spaces",
		fmt.Sprintf(`{"name":"e2e-%s","provider":"%s"}`, provider, provider))
	if err != nil { return err }
	var c struct{ SpaceID string `json:"space_id"` }
	if err := json.Unmarshal([]byte(created), &c); err != nil { return err }
	_, _, err = tryHttp("POST", ep+"/api/spaces/"+c.SpaceID+"/switch", "")
	return err
}

func mustHttp(t *testing.T, method, url, body string) string {
	t.Helper()
	out, code, err := tryHttp(method, url, body)
	if err != nil { t.Fatalf("%s %s: %v", method, url, err) }
	if code >= 500 { t.Fatalf("%s %s → HTTP %d: %s", method, url, code, out) }
	return out
}

func tryHttp(method, url, body string) (string, int, error) {
	var reader io.Reader
	if body != "" { reader = bytes.NewBufferString(body) }
	req, err := http.NewRequest(method, url, reader)
	if err != nil { return "", 0, err }
	if body != "" { req.Header.Set("Content-Type", "application/json") }
	resp, err := http.DefaultClient.Do(req)
	if err != nil { return "", 0, err }
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return string(b), resp.StatusCode, nil
}

func mustJSON(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

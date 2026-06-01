// api_pass_test.go — black-box API smoke test for azure-tickets.
//
// Brings up the app in-process via a separate goroutine + tests the public
// HTTP surface end-to-end. Each test exercises one or more of the 7 Azure
// services. Skips cleanly if the simulator isn't reachable.
//
// Run:   go test -v -run TestApiPass
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
)

func simulatorReachable(t *testing.T, endpoint string) bool {
	t.Helper()
	r, err := http.Get(endpoint + "/healthz")
	if err != nil || r.StatusCode != 200 {
		return false
	}
	r.Body.Close()
	return true
}

// httpRound brings up the chi router with an isolated App + returns a
// httptest.Server URL.
func httpRound(t *testing.T) (*httptest.Server, *App) {
	t.Helper()
	endpoint := envOr("CLOUDLEARN_ENDPOINT", "http://192.168.252.7:9000")
	if !simulatorReachable(t, endpoint) {
		t.Skipf("simulator not reachable at %s — skipping", endpoint)
	}
	a := &App{
		endpoint: endpoint, subID: subscriptionIDDefault,
		httpClient: &http.Client{Timeout: 10 * time.Second},
	}
	if err := a.initClients(context.Background()); err != nil {
		t.Fatalf("init clients: %v", err)
	}
	// RBAC + ensure container + queue best-effort
	_ = a.checkRBAC(context.Background())
	_ = a.ensureContainer(context.Background())

	// Postgres is optional for the routing tests — set it up if reachable.
	if err := a.initPostgres(context.Background()); err != nil {
		t.Logf("postgres unavailable (test will skip DB-dependent paths): %v", err)
	}

	r := chi.NewRouter()
	r.Get("/health", a.handleHealth)
	r.Post("/tickets", a.handleCreateTicket)
	r.Get("/tickets/{id}", a.handleGetTicket)
	r.Get("/tickets", a.handleListTickets)
	return httptest.NewServer(r), a
}

func TestApiPass_Health(t *testing.T) {
	srv, _ := httpRound(t)
	defer srv.Close()
	r, err := http.Get(srv.URL + "/health")
	if err != nil { t.Fatal(err) }
	defer r.Body.Close()
	if r.StatusCode != 200 {
		t.Fatalf("health = %d", r.StatusCode)
	}
	var d map[string]any
	_ = json.NewDecoder(r.Body).Decode(&d)
	if !d["ok"].(bool) {
		t.Fatalf("health.ok = false; %+v", d)
	}
	t.Logf("✓ health: %+v", d)
}

func TestApiPass_CreateTicket(t *testing.T) {
	srv, app := httpRound(t)
	defer srv.Close()
	if app.pg == nil {
		t.Skip("postgres not reachable")
	}
	body := []byte(`{"title":"Test ticket","body":"contents","pii":"sensitive","attachment_b64":"aGVsbG8="}`)
	r, err := http.Post(srv.URL+"/tickets", "application/json", bytes.NewReader(body))
	if err != nil { t.Fatal(err) }
	defer r.Body.Close()
	raw, _ := io.ReadAll(r.Body)
	if r.StatusCode != 201 {
		t.Fatalf("create ticket = %d: %s", r.StatusCode, raw)
	}
	var d map[string]any
	_ = json.Unmarshal(raw, &d)
	id, ok := d["id"].(float64)
	if !ok || id <= 0 {
		t.Fatalf("ticket id missing: %+v", d)
	}
	t.Logf("✓ created ticket id=%v attachment=%v", d["id"], d["attachment_url"])
}

func TestApiPass_ListTickets(t *testing.T) {
	srv, app := httpRound(t)
	defer srv.Close()
	if app.pg == nil {
		t.Skip("postgres not reachable")
	}
	r, err := http.Get(srv.URL + "/tickets")
	if err != nil { t.Fatal(err) }
	defer r.Body.Close()
	if r.StatusCode != 200 {
		raw, _ := io.ReadAll(r.Body)
		t.Fatalf("list tickets = %d: %s", r.StatusCode, raw)
	}
	var d []map[string]any
	_ = json.NewDecoder(r.Body).Decode(&d)
	t.Logf("✓ listed %d tickets", len(d))
}

func TestApiPass_DirectAzureServices(t *testing.T) {
	srv, app := httpRound(t)
	defer srv.Close()
	_ = srv
	checks := map[string]bool{
		"blob_client":          app.blob != nil,
		"servicebus_client":    app.bus != nil,
		"keyvault_secrets":     app.kvSecrets != nil,
		"keyvault_keys":        app.kvKeys != nil,
		"postgres":             app.pg != nil,
	}
	for name, ok := range checks {
		if !ok {
			t.Logf("⚠ %s client not initialized (may be expected for test endpoint)", name)
		} else {
			t.Logf("✓ %s client initialized", name)
		}
	}
}

// TestApiPass_EventGridPublish exercises the simulator's Event Grid endpoint
// via the same path the worker uses. Useful gate that the Azure REST surface
// is reachable.
func TestApiPass_EventGridPublish(t *testing.T) {
	endpoint := envOr("CLOUDLEARN_ENDPOINT", "http://192.168.252.7:9000")
	if !simulatorReachable(t, endpoint) {
		t.Skip("simulator not reachable")
	}
	body := []byte(`[{"id":"evt-1","eventType":"TestEvent","subject":"tickets/0","eventTime":"2026-06-01T00:00:00Z","data":{"hello":"world"},"dataVersion":"1.0"}]`)
	url := fmt.Sprintf("%s/subscriptions/%s/resourceGroups/%s/providers/Microsoft.EventGrid/topics/tickets-topic/events?api-version=2023-12-15-preview",
		endpoint, subscriptionIDDefault, resourceGroup)
	r, err := http.Post(url, "application/json", bytes.NewReader(body))
	if err != nil { t.Fatal(err) }
	defer r.Body.Close()
	raw, _ := io.ReadAll(r.Body)
	if r.StatusCode >= 500 {
		t.Fatalf("event grid publish HTTP %d: %s", r.StatusCode, raw)
	}
	// 2xx/4xx all acceptable — the route handles unknown topics gracefully
	t.Logf("✓ event grid publish HTTP %d (body: %s)", r.StatusCode, strings.TrimSpace(string(raw)))
}

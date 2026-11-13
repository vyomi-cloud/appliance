//go:build !windows

package main

import (
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func portOf(t *testing.T, srv *httptest.Server) string {
	t.Helper()
	_, p, _ := net.SplitHostPort(strings.TrimPrefix(srv.URL, "http://"))
	return p
}

func jsonHandler(routes map[string]string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		body, ok := routes[r.URL.Path]
		if !ok {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(body))
	}
}

func fakeNano(t *testing.T, tab bool) *httptest.Server {
	srv := httptest.NewServer(jsonHandler(map[string]string{"/health": `{"ok":true,"relay":"vyomi-local","version":"1.2.0","tab":` + strconv.FormatBool(tab) +
		`,"tabs":1,"features":["http","vm-tcp","db-tcp","amqp"],"mesh_sessions":3,"vms":[{"vm":"web-1","port":22,"host_port":22000,"secret":"x"}],"dbs":[{"db":"appdb","engine":"postgres","host_port":22001}]}`}))
	t.Cleanup(srv.Close)
	t.Setenv("RELAY_PORT", portOf(t, srv))
	return srv
}

const meshStatusBody = `{"mesh":true,"mesh_id":"m-123","headless":true,"version":"4.0.0","tier":"pro","locked":%LOCKED%,"trial":true,"trial_days_left":9,
 "sub_days_left":9,"reminder":false,"hostname":"rohiths-mac","resources":{"memory_cap_mb":8192,"memory_split_mb":{"compute":6144,"ai":2048},"usage_mb":{"compute":10,"ai":0},"free_mb":{"compute":6134,"ai":2048}},
 "health":{"ok":true,"state":"ok"},"tunnel":{"pairing_code":"PAIR-SECRET"},"relay_url":"https://relay.vyomi.cloud/s?token=TOKEN-SECRET","local_url":"http://127.0.0.1:9000",
 "code":"CODE-SECRET","ai":{"state":"ready","ledger":[{"token":"LEDGER-SECRET"}]},"llm":"llm: local (mesh)"}`

func fakeMesh(t *testing.T, locked bool) *httptest.Server {
	srv := httptest.NewServer(jsonHandler(map[string]string{
		"/mesh/status": strings.ReplaceAll(meshStatusBody, "%LOCKED%", strconv.FormatBool(locked)),
		"/healthz":     `{"status":"ok"}`,
	}))
	t.Cleanup(srv.Close)
	t.Setenv("VYOMI_MESH_URL", srv.URL)
	t.Setenv("VYOMI_SIMULATOR_PORT", portOf(t, srv))
	return srv
}

func fakeOffline(t *testing.T) *httptest.Server {
	srv := httptest.NewServer(jsonHandler(map[string]string{
		"/healthz":               `{"status":"ok","tier":"pro"}`,
		"/api/license/status":    `{"active_tier":"pro","license":{"jwt":"SECRET"}}`,
		"/api/runtime/readiness": `{"ready_count":1,"total_count":1,"overall_pct":100,"services":[]}`,
		"/api/spaces/active":     `{"active_space_id":"sp-1","space":{"name":"dev"}}`,
	}))
	t.Cleanup(srv.Close)
	t.Setenv("VYOMI_MESH_URL", srv.URL)
	t.Setenv("VYOMI_SIMULATOR_PORT", portOf(t, srv))
	return srv
}

// fakeTunnel installs a VYOMI_TUNNEL_BIN shell script with the given body and makes credentials "exist".
func fakeTunnel(t *testing.T, body string) string {
	t.Helper()
	dir := t.TempDir()
	bin := filepath.Join(dir, "vyomi-tunnel")
	if err := os.WriteFile(bin, []byte("#!/bin/sh\n"+body+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("VYOMI_TUNNEL_BIN", bin)
	t.Setenv("VYOMI_ACCESS_KEY_ID", "AKTEST") // Q5: probe only when credentials exist
	return dir
}

func statusOf(t *testing.T, s *mcpServer) (map[string]any, map[string]map[string]any) {
	t.Helper()
	s.homeCache = homeCache{}
	res, isErr := callTool(t, s, "vyomi_status", map[string]any{})
	if isErr {
		t.Fatal(res["error"])
	}
	byID := map[string]map[string]any{}
	for _, h := range res["homes"].([]any) {
		m := h.(map[string]any)
		byID[m["id"].(string)] = m
	}
	return res, byID
}

// L1-10: only the Nano tunnel answers, with a tab.
func TestMCPHomesNanoOnly(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeNano(t, true)
	res, homes := statusOf(t, s)
	if res["selected"] != homeNanoLocal {
		t.Fatalf("selected=%v why=%v", res["selected"], res["why"])
	}
	if !strings.Contains(res["why"].(string), "/health") {
		t.Errorf("why must name the probe: %v", res["why"])
	}
	n := homes[homeNanoLocal]
	if n["reachable"] != true || n["endpoint"] != "http://127.0.0.1:"+os.Getenv("RELAY_PORT") {
		t.Errorf("nano home: %v", n)
	}
	d := n["detail"].(map[string]any)
	if d["tab"] != true || len(d["vms"].([]any)) != 1 || d["mesh_sessions"] != nil {
		t.Errorf("nano detail must be the tunnel whitelist: %v", d)
	}
	if raw, _ := json.Marshal(res); strings.Contains(string(raw), `"secret"`) {
		t.Errorf("non-whitelisted VM field leaked: %s", raw)
	}
}

// L1-11: only /mesh/status with mesh:true.
func TestMCPHomesMeshOnly(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeMesh(t, false)
	res, homes := statusOf(t, s)
	if res["selected"] != homeMeshLocal {
		t.Fatalf("selected=%v why=%v", res["selected"], res["why"])
	}
	if homes[homeOffline]["reachable"] != false {
		t.Errorf("a mesh must not also be reported as an offline appliance: %v", homes[homeOffline])
	}
	d := homes[homeMeshLocal]["detail"].(map[string]any)
	if d["tier"] != "pro" || d["trial_days_left"] != float64(9) || d["health"].(map[string]any)["state"] != "ok" {
		t.Errorf("mesh detail: %v", d)
	}
}

// L1-12: /healthz OK and /mesh/status 404 -> the offline appliance, with the 3.0.46-era fields.
func TestMCPHomesOffline(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeOffline(t)
	res, homes := statusOf(t, s)
	if res["selected"] != homeOffline || homes[homeOffline]["reachable"] != true {
		t.Fatalf("selected=%v why=%v homes=%v", res["selected"], res["why"], homes)
	}
	for _, k := range []string{"running", "health", "license", "readiness", "active_space", "endpoint", "tls_endpoint", "substrate"} {
		if _, ok := res[k]; !ok {
			t.Errorf("legacy field %q missing for the offline home", k)
		}
	}
	if res["running"] != true {
		t.Errorf("running=%v", res["running"])
	}
}

// L1-13: Nano and a mesh both up -> nothing selected, both listed.
func TestMCPHomesAmbiguous(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeNano(t, true)
	fakeMesh(t, false)
	res, homes := statusOf(t, s)
	if res["selected"] != nil {
		t.Fatalf("must not auto-pick with two homes, got %v", res["selected"])
	}
	if homes[homeNanoLocal]["reachable"] != true || homes[homeMeshLocal]["reachable"] != true {
		t.Errorf("both homes must be listed reachable: %v", homes)
	}
	if !strings.Contains(res["why"].(string), "several") {
		t.Errorf("why: %v", res["why"])
	}
	// An explicit choice still wins.
	t.Setenv("VYOMI_TARGET", "nano")
	res, _ = statusOf(t, s)
	if res["selected"] != homeNanoLocal || res["why"] != "VYOMI_TARGET=nano" {
		t.Errorf("VYOMI_TARGET must win: %v / %v", res["selected"], res["why"])
	}
	// auto tools fall back to the offline default and warn.
	t.Setenv("VYOMI_TARGET", "")
	s.homeCache = homeCache{}
	if sel := s.autoHome(); sel.Warning == "" {
		t.Errorf("auto home with several homes must warn: %+v", sel)
	}
}

// D0 item 3 shape (vyomi-tunnel <= 1.2.x: "targets", no schema) plus a mesh service row and a live API forward.
const listMeshJSON = `{"targets":[
 {"where":"mesh","name":"host","type":"host","address":"10.0.0.2","connect":"ssh host.vyomi"},
 {"where":"mesh","name":"vyomi-appliance","type":"service","address":"10.0.0.3:9000","connect":"vyomi-tunnel forward vyomi-appliance 9000:9000"},
 {"where":"mesh","name":"vyomi-k3s-ab12","type":"k3s","address":"10.0.0.4:6443","connect":"vyomi-tunnel forward vyomi-k3s-ab12 6443:6443"}
],"notes":[]}`

// L1-14: the Codespace probe parses `list mesh --json`; an unknown schema makes it unreachable with a note.
func TestMCPHomesCodespace(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeTunnel(t, "cat <<'EOF'\n"+listMeshJSON+"\nEOF")
	res, homes := statusOf(t, s)
	cs := homes[homeMeshCodespace]
	if cs["reachable"] != true || cs["serving"] != false {
		t.Fatalf("codespace: %v", cs)
	}
	d := cs["detail"].(map[string]any)
	if len(d["targets"].([]any)) != 3 || d["api_target"] != "vyomi-appliance" {
		t.Errorf("rows not parsed: %v", d)
	}
	if res["selected"] != homeMeshCodespace || !strings.Contains(res["why"].(string), "no forward") {
		t.Errorf("selected=%v why=%v", res["selected"], res["why"])
	}
	// schema 1 under "rows" (the T1 contract) with a forward to the API: serving at the forward's local port.
	fakeTunnel(t, `cat <<'EOF'
{"schema":1,"rows":[{"where":"mesh","name":"vyomi-appliance","type":"service","address":"10.0.0.3:9000","connect":"vyomi-tunnel forward vyomi-appliance 9000:9000"},
 {"where":"local","name":"vyomi-appliance","type":"forward","address":"127.0.0.1:19000","connect":"-> vyomi-appliance:9000 (pid 4242)"}],"notes":[]}
EOF`)
	res, homes = statusOf(t, s)
	cs = homes[homeMeshCodespace]
	if cs["serving"] != true || cs["endpoint"] != "http://127.0.0.1:19000" || res["selected"] != homeMeshCodespace {
		t.Errorf("forwarded codespace: %v (selected %v)", cs, res["selected"])
	}
	// Any other schema: not reachable, with a note.
	fakeTunnel(t, `echo '{"schema":2,"rows":[{"where":"mesh","name":"x","type":"host"}],"notes":[]}'`)
	_, homes = statusOf(t, s)
	cs = homes[homeMeshCodespace]
	if cs["reachable"] != false || !strings.Contains(cs["detail"].(map[string]any)["note"].(string), "schema 2") {
		t.Errorf("schema 2 must be refused with a note: %v", cs)
	}
	// Auth failures print no JSON: the stderr line becomes the note.
	fakeTunnel(t, `echo 'vyomi-tunnel: your Mesh session has ended. Start Mesh again in the console.' >&2; exit 1`)
	_, homes = statusOf(t, s)
	if n := homes[homeMeshCodespace]["detail"].(map[string]any)["note"]; n != "your Mesh session has ended. Start Mesh again in the console." {
		t.Errorf("note: %v", n)
	}
	// Without credentials the Codespace is not probed at all (spec Q5).
	t.Setenv("VYOMI_ACCESS_KEY_ID", "")
	_, homes = statusOf(t, s)
	if n := homes[homeMeshCodespace]["detail"].(map[string]any)["note"]; !strings.Contains(n.(string), "no Vyomi credentials") {
		t.Errorf("no-credentials note: %v", n)
	}
}

// L1-15: a hanging tunnel costs at most the 8 s cap, and its whole process group is gone afterwards.
func TestMCPHomesCodespaceTimeout(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	dir := fakeTunnel(t, "")
	pidFile := filepath.Join(dir, "pids")
	_ = os.WriteFile(os.Getenv("VYOMI_TUNNEL_BIN"), []byte("#!/bin/sh\necho $$ > "+pidFile+"\nsleep 20 &\necho $! >> "+pidFile+"\nwait\n"), 0o755)
	start := time.Now()
	_, homes := statusOf(t, s)
	if el := time.Since(start); el > 9*time.Second {
		t.Errorf("status took %v (> 9 s)", el)
	}
	cs := homes[homeMeshCodespace]
	if cs["reachable"] != false || cs["detail"].(map[string]any)["note"] != "timeout" {
		t.Errorf("codespace after timeout: %v", cs)
	}
	time.Sleep(200 * time.Millisecond)
	raw, _ := os.ReadFile(pidFile)
	for _, f := range strings.Fields(string(raw)) {
		pid, _ := strconv.Atoi(f)
		if pid > 0 && syscall.Kill(pid, 0) == nil {
			t.Errorf("probe child %d still alive after the timeout", pid)
			_ = syscall.Kill(pid, syscall.SIGKILL)
		}
	}
}

// L1-16: extra /mesh/status fields (relay_url with a token, code, tunnel pairing, hostname, the AI ledger) never reach the model.
func TestMCPHomesMeshWhitelist(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeMesh(t, false)
	res, _ := statusOf(t, s)
	raw, _ := json.Marshal(res)
	for _, secret := range []string{"TOKEN-SECRET", "CODE-SECRET", "PAIR-SECRET", "LEDGER-SECRET", "relay_url", "rohiths-mac", "local_url", "memory_split_mb"} {
		if strings.Contains(string(raw), secret) {
			t.Errorf("%s leaked into vyomi_status", secret)
		}
	}
	if !strings.Contains(string(raw), `"ai":{"state":"ready"}`) {
		t.Errorf("ai.state should be kept: %s", raw)
	}
}

// Probes are cached for 10 s: status then env back to back probe once.
func TestMCPHomesCache(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	hits := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true,"relay":"vyomi-local","tab":true}`))
	}))
	defer srv.Close()
	t.Setenv("RELAY_PORT", portOf(t, srv))
	s.homes()
	s.homes()
	if hits != 1 {
		t.Errorf("want one probe within the cache window, got %d", hits)
	}
}

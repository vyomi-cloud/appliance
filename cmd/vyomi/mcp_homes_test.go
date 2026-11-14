//go:build !windows

package main

import (
	"encoding/json"
	"fmt"
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
		if pid > 0 && stillRunning(pid) {
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

// L1-17: Nano tunnel without a tab: the open-tab hint, and `vyomi up` nowhere in the output.
func TestMCPStatusNanoNoTab(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeNano(t, false)
	res, _ := statusOf(t, s)
	if res["selected"] != homeNanoLocal || res["hint"] != hintNanoOpenTab {
		t.Errorf("selected=%v hint=%v", res["selected"], res["hint"])
	}
	if raw, _ := json.Marshal(res); strings.Contains(string(raw), "vyomi up") {
		t.Errorf("a Nano status must never say `vyomi up`: %s", raw)
	}
	if res["running"] != false || res["nano"] == nil {
		t.Errorf("running/nano: %v %v", res["running"], res["nano"])
	}
	// With the tab: no hint, running, the tunnel endpoint.
	fakeNano(t, true)
	res, _ = statusOf(t, s)
	if res["hint"] != nil || res["running"] != true || res["endpoint"] != "http://127.0.0.1:"+os.Getenv("RELAY_PORT") {
		t.Errorf("nano with tab: %v", res)
	}
}

// L1-18: a locked mesh is still selected and gets the locked text.
func TestMCPStatusMeshLocked(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeMesh(t, true)
	res, _ := statusOf(t, s)
	if res["selected"] != homeMeshLocal || res["hint"] != hintMeshLocked {
		t.Errorf("selected=%v hint=%v why=%v", res["selected"], res["hint"], res["why"])
	}
	if res["mesh"].(map[string]any)["locked"] != true {
		t.Errorf("mesh detail: %v", res["mesh"])
	}
}

// L1-19: nothing reachable and no tunnel on PATH: the Nano onboarding hint.
func TestMCPStatusNothingReachable(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	res, _ := statusOf(t, s)
	if res["selected"] != nil || res["hint"] != hintNanoOnboard {
		t.Errorf("selected=%v hint=%v", res["selected"], res["hint"])
	}
	if raw, _ := json.Marshal(res); strings.Contains(string(raw), "vyomi up") {
		t.Errorf("onboarding must not send the user to `vyomi up`: %s", raw)
	}
	// The tunnel installed but not running: run it.
	fakeTunnel(t, "exit 2")
	t.Setenv("VYOMI_ACCESS_KEY_ID", "")
	res, _ = statusOf(t, s)
	if res["hint"] != hintNanoTunnelOff {
		t.Errorf("tunnel installed: hint=%v", res["hint"])
	}
	// An explicit offline endpoint that is down keeps the 3.0.46 behaviour (running=false, `vyomi up`).
	t.Setenv("VYOMI_ENDPOINT", "http://127.0.0.1:"+strconv.Itoa(deadPort(t)))
	res, _ = statusOf(t, s)
	if res["selected"] != homeOffline || res["running"] != false || !strings.Contains(res["hint"].(string), "vyomi up") {
		t.Errorf("offline down: %v", res)
	}
}

// Ambiguous homes get the "which space" hint; a Codespace without a forward gets the forward command;
// a dead relay URL gets the relay hint; a multi-space mesh warns which space SDK calls land in (spec Q4).
func TestMCPStatusOtherHints(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeNano(t, true)
	fakeMesh(t, false)
	res, _ := statusOf(t, s)
	if res["hint"] != hintAmbiguous {
		t.Errorf("ambiguous hint: %v", res["hint"])
	}

	deadHomes(t)
	fakeTunnel(t, "cat <<'EOF'\n"+listMeshJSON+"\nEOF")
	res, _ = statusOf(t, s)
	if h := fmt_(res["hint"]); !strings.Contains(h, "vyomi-tunnel forward vyomi-appliance 9000:9000") || !strings.Contains(h, "do not run it yourself") {
		t.Errorf("codespace hint: %v", res["hint"])
	}

	deadHomes(t)
	t.Setenv("VYOMI_TUNNEL_BIN", "")
	t.Setenv("VYOMI_ACCESS_KEY_ID", "")
	t.Setenv("VYOMI_ENDPOINT", "http://10.255.255.1:1/sess-abc") // non-routable: the relay does not answer
	res, _ = statusOf(t, s)
	if res["selected"] != homeNanoCloud || res["hint"] != hintRelayDown {
		t.Errorf("relay down: selected=%v hint=%v", res["selected"], res["hint"])
	}

	deadHomes(t)
	srv := httptest.NewServer(jsonHandler(map[string]string{
		"/mesh/status":       strings.ReplaceAll(meshStatusBody, "%LOCKED%", "false"),
		"/healthz":           `{"status":"ok"}`,
		"/api/spaces":        `{"spaces":[{"space_id":"a"},{"space_id":"b"}],"active_space_id":"a"}`,
		"/api/spaces/active": `{"active_space_id":"a","space":{"name":"web"}}`,
	}))
	defer srv.Close()
	t.Setenv("VYOMI_MESH_URL", srv.URL)
	res, _ = statusOf(t, s)
	if !strings.Contains(fmt_(res["spaces_warning"]), "2 spaces") || res["active_space"] == nil || res["running"] != true {
		t.Errorf("multi-space mesh: %v", res)
	}
}

func fmt_(v any) string { s, _ := v.(string); return s }

// D0 item 4 (run 3, a real v4 mesh): a fresh mesh has one default space per cloud, so a call has exactly one place to land and
// there is no warning. With several spaces of one cloud the warning names where each cloud's calls land (the active space for its
// cloud, otherwise that cloud's first space) and says the Nano console's switch does not reach the mesh. Bodies as /api/spaces answered.
func TestMCPStatusMeshSpacesWarning(t *testing.T) {
	s, _ := testMCPServer(t)
	defaults := `{"space_id":"space-legacy","name":"aws-default","provider":"aws"},{"space_id":"space-azure-default","name":"azure-default","provider":"azure"},` +
		`{"space_id":"space-gcp-default","name":"gcp-default","provider":"gcp"}`
	extra := `,{"space_id":"space-df5afd24f69c","name":"run3-one","provider":"aws"},{"space_id":"space-2eaf506b27fd","name":"run3-two","provider":"aws"}`
	cases := []struct {
		name, spaces, active string
		want, not            []string
	}{
		{"fresh mesh, one space per cloud", defaults, "space-legacy", nil, nil},
		{"three aws spaces, run3-two active", defaults + extra, "space-2eaf506b27fd",
			[]string{"5 spaces (3 aws)", "aws -> run3-two (the active space)", "gcp -> gcp-default", "azure -> azure-default",
				"Nano console does not change", "/api/spaces/<space_id>/switch"}, []string{"aws -> aws-default"}},
		{"three aws spaces, a gcp space active", defaults + extra, "space-gcp-default",
			[]string{"aws -> aws-default;", "gcp -> gcp-default (the active space)"}, []string{"run3-two"}},
	}
	for _, c := range cases {
		deadHomes(t)
		srv := httptest.NewServer(jsonHandler(map[string]string{
			"/mesh/status":       strings.ReplaceAll(meshStatusBody, "%LOCKED%", "false"),
			"/healthz":           `{"status":"ok"}`,
			"/api/spaces":        `{"spaces":[` + c.spaces + `],"active_space_id":"` + c.active + `"}`,
			"/api/spaces/active": `{"active_space_id":"` + c.active + `","space":{"name":"x"}}`,
		}))
		t.Setenv("VYOMI_MESH_URL", srv.URL)
		res, _ := statusOf(t, s)
		srv.Close()
		w, has := res["spaces_warning"].(string)
		if res["selected"] != homeMeshLocal {
			t.Fatalf("%s: selected=%v", c.name, res["selected"])
		}
		if c.want == nil {
			if has {
				t.Errorf("%s: no warning expected, got %q", c.name, w)
			}
			continue
		}
		for _, x := range c.want {
			if !strings.Contains(w, x) {
				t.Errorf("%s: warning lacks %q: %q", c.name, x, w)
			}
		}
		for _, x := range c.not {
			if strings.Contains(w, x) {
				t.Errorf("%s: warning must not contain %q: %q", c.name, x, w)
			}
		}
	}
}

// L1-20: vyomi_reach merges the tunnel's /health rows with `list --json` rows and leaves no process behind.
func TestMCPReach(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeNano(t, true)
	dir := fakeTunnel(t, "")
	pidFile := filepath.Join(dir, "pids")
	_ = os.WriteFile(os.Getenv("VYOMI_TUNNEL_BIN"), []byte("#!/bin/sh\nsleep 30 &\necho $! > "+pidFile+"\ncat <<'EOF'\n"+listMeshJSON+"\nEOF\n"), 0o755)
	s.homeCache = homeCache{}
	res, isErr := callTool(t, s, "vyomi_reach", map[string]any{"scope": "all"})
	if isErr {
		t.Fatal(res["error"])
	}
	types := map[string]bool{}
	for _, r := range res["rows"].([]any) {
		m := r.(map[string]any)
		types[m["where"].(string)+"/"+m["type"].(string)] = true
		for _, k := range []string{"where", "name", "type", "address", "connect"} {
			if _, ok := m[k]; !ok {
				t.Errorf("row without %s: %v", k, m)
			}
		}
	}
	for _, want := range []string{"local/api", "local/amqp", "browser/vm", "browser/db", "mesh/host", "mesh/service", "mesh/k3s"} {
		if !types[want] {
			t.Errorf("missing %s row (have %v)", want, types)
		}
	}
	time.Sleep(200 * time.Millisecond)
	raw, _ := os.ReadFile(pidFile)
	if pid, _ := strconv.Atoi(strings.TrimSpace(string(raw))); pid > 0 && stillRunning(pid) {
		t.Errorf("vyomi_reach left process %d running", pid)
		_ = syscall.Kill(pid, syscall.SIGKILL)
	}
	nano, _ := callTool(t, s, "vyomi_reach", map[string]any{"scope": "nano"})
	for _, r := range nano["rows"].([]any) {
		if r.(map[string]any)["where"] == "mesh" {
			t.Errorf("scope nano returned a mesh row: %v", r)
		}
	}
	if _, isErr := callTool(t, s, "vyomi_reach", map[string]any{"scope": "galaxy"}); !isErr {
		t.Error("bad scope must be a tool error")
	}
}

// stillRunning reports whether pid is a live (non-zombie) process, waiting up to 2 s for it to go away.
// A killed child whose parent has already exited is a zombie until init reaps it: kill(pid, 0) still
// succeeds on a zombie, and on Linux (CI runners, containers) the reap can lag. macOS reaps at once.
func stillRunning(pid int) bool {
	deadline := time.Now().Add(2 * time.Second)
	for {
		if syscall.Kill(pid, 0) != nil {
			return false
		}
		if b, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat"); err == nil {
			// Fields after the "(comm)" field; the first is the state. comm may contain spaces.
			if i := strings.LastIndexByte(string(b), ')'); i >= 0 {
				if f := strings.Fields(string(b)[i+1:]); len(f) > 0 && f[0] == "Z" {
					return false
				}
			}
		}
		if time.Now().After(deadline) {
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
}

// Prerelease eval A06: a suggested forward must use a free local port (an offline appliance often holds :9000
// and :9443 on the user's machine).
// realPortFree is the host check, captured before any test stubs portFree (isolateHomes does).
var realPortFree = portFree

// On macOS a socket on *:9000 (Docker Desktop publishing the offline appliance) does not stop a bind to 127.0.0.1:9000,
// so a bind-only check suggested `forward ... 9000:9000` next to a running appliance (seen live on the owner's Mac).
// The check must also see a port that merely answers.
func TestMCPPortFreeSeesAWildcardListener(t *testing.T) {
	l, err := net.Listen("tcp", ":0")
	if err != nil {
		t.Fatal(err)
	}
	port := l.Addr().(*net.TCPAddr).Port
	if realPortFree(port) {
		t.Fatalf("port %d has a listener on all addresses but portFree says free", port)
	}
	_ = l.Close()
	if !realPortFree(port) {
		t.Fatalf("port %d is closed again but portFree says busy", port)
	}
}

func TestMCPForwardPortSkipsBusyPorts(t *testing.T) {
	isolateHomes(t)
	busy := map[int]bool{9000: true, 9100: true, 9443: true}
	portFree = func(p int) bool { return !busy[p] }
	if got := forwardPort(9000, 9100); got != 9101 {
		t.Errorf("forwardPort(9000) with 9000+9100 busy = %d, want 9101", got)
	}
	if got := forwardPort(9443, 9543); got != 9543 {
		t.Errorf("forwardPort(9443) with 9443 busy = %d, want 9543", got)
	}
	s, _ := testMCPServer(t)
	deadHomes(t)
	portFree = func(p int) bool { return !busy[p] }
	fakeTunnel(t, "cat <<'EOF'\n"+listMeshJSON+"\nEOF")
	res, _ := statusOf(t, s)
	if h := fmt_(res["hint"]); !strings.Contains(h, "vyomi-tunnel forward vyomi-appliance 9101:9000") {
		t.Errorf("hint must suggest the free port 9101: %v", h)
	}
}

// Prerelease eval A06: home=mesh is the Codespace mesh when that is the only mesh. Before, vyomi_env used the
// local-mesh URL (VYOMI_MESH_URL) and labelled the home mesh-local.
func TestMCPEnvMeshIsCodespace(t *testing.T) {
	s, _ := testMCPServer(t)
	deadHomes(t)
	fakeTunnel(t, "cat <<'EOF'\n"+listMeshJSON+"\nEOF")
	res, isErr := callTool(t, s, "vyomi_env", map[string]any{"cloud": "aws", "lang": "python", "home": "mesh"})
	if isErr {
		t.Fatalf("vyomi_env error: %v", res)
	}
	js := fmt.Sprint(res)
	if !strings.Contains(js, "127.0.0.1:9000") || !strings.Contains(js, homeMeshCodespace) || strings.Contains(js, homeMeshLocal) {
		t.Errorf("no forward: want the suggested forward port, labelled %s: %s", homeMeshCodespace, js)
	}
	if !strings.Contains(js, "vyomi-tunnel forward vyomi-appliance 9000:9000") || !strings.Contains(js, "never starts forwards") {
		t.Errorf("no forward: want a warning naming the forward to start: %s", js)
	}
	// With a live forward the env uses the forward's local port.
	fakeTunnel(t, `cat <<'EOF'
{"schema":1,"rows":[{"where":"mesh","name":"vyomi-appliance","type":"service","address":"10.0.0.3:9000","connect":"vyomi-tunnel forward vyomi-appliance 9000:9000"},
 {"where":"local","name":"vyomi-appliance","type":"forward","address":"127.0.0.1:19000","connect":"-> vyomi-appliance:9000 (pid 4242)"}],"notes":[]}
EOF`)
	s.homeCache = homeCache{}
	res, _ = callTool(t, s, "vyomi_env", map[string]any{"cloud": "aws", "lang": "python", "home": "mesh"})
	if js := fmt.Sprint(res); !strings.Contains(js, "127.0.0.1:19000") || !strings.Contains(js, homeMeshCodespace) {
		t.Errorf("live forward: want 127.0.0.1:19000 labelled %s: %s", homeMeshCodespace, js)
	}
}

package main

// Homes: where the simulator lives in v4 (spec §2). A Nano browser tab (reached through the local tunnel on
// :8090 or the cloud relay URL), a local mesh (the headless Pro/Max appliance on :9000), the v3 / v4.0.0
// offline appliance (:9000), or a mesh in the user's Codespace (reached through `vyomi-tunnel forward`).
//
// The resolver (plan H1) probes the local homes in parallel, classifies them, and picks one only when the
// choice is unambiguous. It never starts anything (spec decision 6) and passes only whitelisted fields to the
// model (decision 7).

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	homeNanoLocal     = "nano-local"
	homeNanoCloud     = "nano-cloud"
	homeMeshLocal     = "mesh-local"
	homeMeshCodespace = "mesh-codespace"
	homeOffline       = "offline"
)

var (
	homeProbeTimeout   = 1500 * time.Millisecond // each HTTP probe (spec §2)
	tunnelProbeTimeout = 8 * time.Second         // `vyomi-tunnel list mesh --json` (spec Q5)
	homeCacheTTL       = 10 * time.Second        // agents call status then env back to back (plan H1.6)
)

const tunnelProbeMaxStdout = 1 << 20

// wiringHome maps a home id to the homes.<x> block of the knowledge (scripts/mcp_wiring.json).
func wiringHome(id string) string {
	switch id {
	case homeNanoLocal, homeNanoCloud:
		return "nano"
	case homeMeshLocal, homeMeshCodespace:
		return "mesh"
	}
	return "offline"
}

// wiringHomeArg is the `home` tool argument that selects this home id.
func wiringHomeArg(id string) string { return wiringHome(id) }

// home is one place the simulator may live, as probed.
type home struct {
	ID          string         `json:"id"`
	Reachable   bool           `json:"reachable"`
	Serving     bool           `json:"serving"` // reachable AND able to answer cloud API calls now
	Endpoint    string         `json:"endpoint,omitempty"`
	TLSEndpoint string         `json:"tls_endpoint,omitempty"`
	Detail      map[string]any `json:"detail,omitempty"`
	target      mcpTarget
}

type homeProbe struct {
	Homes    []*home
	Selected *home
	Why      string
}

func (p *homeProbe) find(id string) *home {
	for _, h := range p.Homes {
		if h.ID == id {
			return h
		}
	}
	return nil
}

// homeSel is the home a tool works against: its id, the endpoint target, and why it was chosen.
type homeSel struct {
	ID      string
	Why     string
	Warning string
	target  mcpTarget
}

// homeCache holds the last probe for homeCacheTTL.
type homeCache struct {
	mu  sync.Mutex
	at  time.Time
	val *homeProbe
}

func relayPort() int {
	if p, err := strconv.Atoi(envAny("", "RELAY_PORT")); err == nil && p > 0 {
		return p
	}
	return 8090
}

func meshURL() string {
	if u := strings.TrimRight(envAny("", "VYOMI_MESH_URL"), "/"); u != "" {
		return u
	}
	return "http://127.0.0.1:9000"
}

func isLoopback(h string) bool {
	return h == "127.0.0.1" || h == "localhost" || h == "::1" || strings.HasPrefix(h, "127.")
}

// relayEndpoint reports whether VYOMI_ENDPOINT is the Nano cloud relay (https://relay.vyomi.cloud/<session>):
// a relay host, or a non-local URL with a path (the session). A bare host[:port] is an appliance (e.g. a
// Multipass VM IP), exactly as before v4.
func relayEndpoint() (*url.URL, bool) {
	ep := envAny("", "VYOMI_ENDPOINT")
	if ep == "" {
		return nil, false
	}
	u, err := url.Parse(ep)
	if err != nil || u.Hostname() == "" {
		return nil, false
	}
	if strings.HasSuffix(u.Hostname(), "relay.vyomi.cloud") || (!isLoopback(u.Hostname()) && strings.Trim(u.Path, "/") != "") {
		return u, true
	}
	return u, false
}

// endpointTarget turns a base URL (scheme, host, optional port, optional path such as the relay session)
// into a target, keeping the defaults it does not override.
func endpointTarget(u *url.URL, t mcpTarget) mcpTarget {
	if u.Scheme != "" {
		t.Scheme = u.Scheme
	}
	t.Host = u.Hostname()
	t.SimPort = 0
	if p, err := strconv.Atoi(u.Port()); err == nil {
		t.SimPort = p
	}
	t.Path = strings.TrimRight(u.EscapedPath(), "/")
	return t
}

// nanoTarget is the Nano endpoint: the cloud relay when VYOMI_ENDPOINT names one (or any non-local URL with
// home=nano), else the local tunnel. Nano is plain HTTP: no TLS port.
func (s *mcpServer) nanoTarget() (mcpTarget, string) {
	t := mcpTarget{Scheme: "http", Host: "127.0.0.1", SimPort: relayPort(), Account: s.matrix.Defaults.AzureAccount}
	if ep := envAny("", "VYOMI_ENDPOINT"); ep != "" {
		if u, err := url.Parse(ep); err == nil && u.Hostname() != "" && !isLoopback(u.Hostname()) {
			return endpointTarget(u, t), homeNanoCloud
		}
	}
	return t, homeNanoLocal
}

func (s *mcpServer) meshTarget() mcpTarget {
	t := s.target(nil)
	if u, err := url.Parse(meshURL()); err == nil && u.Hostname() != "" {
		t.Scheme, t.Host = "http", u.Hostname()
		if p, err := strconv.Atoi(u.Port()); err == nil {
			t.SimPort = p
		}
	}
	return t
}

func (t mcpTarget) tlsURL() string {
	if t.TLSPort == 0 {
		return ""
	}
	return fmt.Sprintf("https://%s:%d", t.Host, t.TLSPort)
}

// ── whitelists (spec decision 7) ─────────────────────────────────────────────

// Only these /mesh/status fields reach the model. relay_url / local_url / tunnel can carry pairing codes and
// session tokens; ai carries the session ledger; hostname identifies the machine.
var meshFields = []string{"mesh", "mesh_id", "version", "tier", "locked", "trial", "trial_days_left", "reminder", "llm"}

func pickMesh(m map[string]any) map[string]any {
	out := pick(m, meshFields)
	if h, ok := m["health"].(map[string]any); ok {
		out["health"] = pick(h, []string{"state"})
	}
	if r, ok := m["resources"].(map[string]any); ok {
		out["resources"] = pick(r, []string{"memory_cap_mb", "usage_mb", "free_mb"})
	}
	if a, ok := m["ai"].(map[string]any); ok {
		out["ai"] = pick(a, []string{"state"})
	}
	return out
}

// Only these local-tunnel /health fields reach the model (tunnelFields in plan H1.3).
func pickTunnel(m map[string]any) map[string]any {
	out := pick(m, []string{"version", "tab", "tabs", "features"})
	pickRows := func(key string, keys []string) {
		list, _ := m[key].([]any)
		rows := []map[string]any{}
		for _, x := range list {
			if r, ok := x.(map[string]any); ok {
				rows = append(rows, pick(r, keys))
			}
		}
		out[key] = rows
	}
	pickRows("vms", []string{"vm", "host_port"})
	pickRows("dbs", []string{"db", "engine", "host_port"})
	return out
}

// ── probes ───────────────────────────────────────────────────────────────────

type probeAnswer struct {
	ok     bool
	status int
	body   map[string]any
	err    string
}

func (s *mcpServer) probeGET(ctx context.Context, rawURL string) probeAnswer {
	ctx, cancel := context.WithTimeout(ctx, homeProbeTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return probeAnswer{err: err.Error()}
	}
	resp, err := s.probeClient.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return probeAnswer{err: "timeout"}
		}
		return probeAnswer{err: "not reachable"}
	}
	defer resp.Body.Close()
	a := probeAnswer{status: resp.StatusCode, ok: resp.StatusCode < 400}
	if a.ok {
		_ = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&a.body)
	} else {
		a.err = fmt.Sprintf("HTTP %d", resp.StatusCode)
	}
	return a
}

// tunnelBin is the vyomi-tunnel to call back: VYOMI_TUNNEL_BIN (set by `vyomi-tunnel mcp`), else PATH.
func tunnelBin() string {
	if b := envAny("", "VYOMI_TUNNEL_BIN"); b != "" {
		return b
	}
	if p, err := exec.LookPath("vyomi-tunnel"); err == nil {
		return p
	}
	return ""
}

// tunnelCredentialsExist: spec Q5 probes the Codespace only when credentials exist. The MCP never reads
// them (decision 3): an env key, or the file's existence (stat only), is enough.
func tunnelCredentialsExist() bool {
	if envAny("", "VYOMI_ACCESS_KEY_ID") != "" {
		return true
	}
	f := envAny("", "VYOMI_CREDENTIALS_FILE")
	if f == "" {
		dir := envAny("", "VYOMI_HOME")
		if dir == "" {
			dir = filepath.Join(homeDir(), ".vyomi")
		}
		f = filepath.Join(dir, "credentials")
	}
	st, err := os.Stat(f)
	return err == nil && st.Mode().IsRegular()
}

type limitedBuffer struct {
	buf   bytes.Buffer
	limit int
	over  bool
}

func (l *limitedBuffer) Write(p []byte) (int, error) {
	if room := l.limit - l.buf.Len(); room < len(p) {
		l.over = true
		if room > 0 {
			l.buf.Write(p[:room])
		}
		return len(p), nil
	}
	return l.buf.Write(p)
}

type tunnelRow struct {
	Where   string `json:"where"`
	Name    string `json:"name"`
	Type    string `json:"type"`
	Address string `json:"address"`
	Connect string `json:"connect"`
}

type tunnelList struct {
	Schema  *int        `json:"schema"`
	Rows    []tunnelRow `json:"rows"`
	Targets []tunnelRow `json:"targets"` // vyomi-tunnel <= 1.2.x (D0 item 3): same rows under "targets"
	Notes   []string    `json:"notes"`
}

// runTunnelList runs `vyomi-tunnel list <scope> --json` with a hard timeout and a 1 MB stdout cap. The
// result is parsed even on exit 1 (no rows, JSON still printed); without JSON the first stderr line is the note.
func runTunnelList(ctx context.Context, bin, scope string) (*tunnelList, string) {
	ctx, cancel := context.WithTimeout(ctx, tunnelProbeTimeout)
	defer cancel()
	args := []string{"list", scope, "--json"}
	var cmd *exec.Cmd
	if strings.HasSuffix(bin, ".mjs") || strings.HasSuffix(bin, ".js") {
		cmd = exec.CommandContext(ctx, "node", append([]string{bin}, args...)...)
	} else {
		cmd = exec.CommandContext(ctx, bin, args...)
	}
	probeProcGroup(cmd)
	cmd.WaitDelay = 500 * time.Millisecond
	cmd.Stdin = nil
	stdout := &limitedBuffer{limit: tunnelProbeMaxStdout}
	stderr := &limitedBuffer{limit: 4096}
	cmd.Stdout, cmd.Stderr = stdout, stderr
	err := cmd.Run()
	probeReap(cmd)
	if ctx.Err() == context.DeadlineExceeded {
		return nil, "timeout"
	}
	if stdout.over {
		return nil, "vyomi-tunnel list output exceeded 1 MB"
	}
	var l tunnelList
	if jerr := json.Unmarshal(bytes.TrimSpace(stdout.buf.Bytes()), &l); jerr != nil {
		note := strings.TrimSpace(strings.SplitN(stderr.buf.String(), "\n", 2)[0])
		if note == "" && err != nil {
			note = err.Error()
		}
		if note == "" {
			note = "vyomi-tunnel list printed no JSON"
		}
		return nil, clip(strings.TrimPrefix(note, "vyomi-tunnel: "))
	}
	if l.Rows == nil {
		l.Rows = l.Targets
	}
	return &l, ""
}

var forwardTo9000 = regexp.MustCompile(`->\s*(\S+):9000\b`)

// portFree reports whether 127.0.0.1:p can be bound right now (a variable so tests are independent of the host).
var portFree = func(p int) bool {
	l, err := net.Listen("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(p)))
	if err != nil {
		return false
	}
	_ = l.Close()
	return true
}

// forwardPort suggests the local port for a Codespace forward: the remote port itself when it is free here,
// else the first free port in [alt, alt+100). An offline appliance or another stack often holds :9000 / :9443.
func forwardPort(remote, alt int) int {
	if portFree(remote) {
		return remote
	}
	for p := alt; p < alt+100; p++ {
		if portFree(p) {
			return p
		}
	}
	return remote
}

// codespaceHome classifies `vyomi-tunnel list mesh --json`. Reachable: the Codespace answered with mesh rows.
// Serving: a live `vyomi-tunnel forward <api> <local>:9000` exists, so 127.0.0.1:<local> is the mesh API.
func (s *mcpServer) codespaceHome(l *tunnelList, note string) *home {
	h := &home{ID: homeMeshCodespace, Detail: map[string]any{}}
	if l == nil {
		h.Detail["note"] = note
		return h
	}
	if l.Schema != nil && *l.Schema != 1 {
		h.Detail["note"] = fmt.Sprintf("vyomi-tunnel list --json schema %d is not supported (this MCP reads schema 1); update vyomi-tunnel or the MCP", *l.Schema)
		return h
	}
	var rows []map[string]any
	apiTarget := ""
	for _, r := range l.Rows {
		rows = append(rows, map[string]any{"where": r.Where, "name": r.Name, "type": r.Type, "address": r.Address, "connect": r.Connect})
		if r.Where == "mesh" {
			h.Reachable = true
			if apiTarget == "" && r.Type == "service" && strings.HasSuffix(r.Address, ":9000") {
				apiTarget = r.Name
			}
		}
	}
	for _, r := range l.Rows {
		if r.Type != "forward" {
			continue
		}
		if m := forwardTo9000.FindStringSubmatch(r.Connect); m != nil && strings.HasPrefix(r.Address, "127.0.0.1:") {
			if u, err := url.Parse("http://" + r.Address); err == nil {
				t := s.meshTarget()
				t.Host = u.Hostname()
				if p, err := strconv.Atoi(u.Port()); err == nil {
					t.SimPort = p
				}
				h.target, h.Endpoint, h.Serving, h.Reachable = t, t.simURL(), true, true
				apiTarget = m[1]
			}
		}
	}
	if rows == nil {
		rows = []map[string]any{}
	}
	h.Detail["targets"] = rows
	if len(l.Notes) > 0 {
		notes := make([]string, 0, len(l.Notes))
		for _, n := range l.Notes {
			notes = append(notes, clip(n))
		}
		h.Detail["notes"] = notes
	}
	if apiTarget != "" {
		h.Detail["api_target"] = apiTarget
	} else if h.Reachable {
		h.Detail["api_target"] = "unknown: no service row on port 9000 in `vyomi-tunnel list mesh` (on a Codespace it is vyomi-mesh-simulator-1)"
	}
	if h.Reachable && !h.Serving {
		target := apiTarget
		if target == "" {
			target = "<the service row on port 9000 from vyomi_reach mesh>"
		}
		api, tls := forwardPort(9000, 9100), forwardPort(9443, 9543)
		h.Detail["forward_command"] = fmt.Sprintf("vyomi-tunnel forward %s %d:9000", target, api)
		h.Detail["forward_tls_command"] = fmt.Sprintf("vyomi-tunnel forward %s %d:9443", target, tls)
		t := s.meshTarget()
		t.Scheme, t.Host, t.SimPort, t.TLSPort = "http", "127.0.0.1", api, tls
		h.target = t
	}
	return h
}

// probeHomes runs every probe in parallel and classifies the answers (spec §2).
func (s *mcpServer) probeHomes(ctx context.Context) *homeProbe {
	legacy := s.target(nil)
	relayURL, isRelay := relayEndpoint()
	meshBase := meshURL()
	applianceBase := legacy.simURL()
	if isRelay {
		applianceBase = meshBase // VYOMI_ENDPOINT is the relay, not an appliance
	}
	bases := []string{meshBase}
	if applianceBase != meshBase {
		bases = append(bases, applianceBase)
	}
	nanoBase := fmt.Sprintf("http://127.0.0.1:%d", relayPort())

	var wg sync.WaitGroup
	var mu sync.Mutex
	answers := map[string]probeAnswer{}
	get := func(key, u string) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			a := s.probeGET(ctx, u)
			mu.Lock()
			answers[key] = a
			mu.Unlock()
		}()
	}
	for _, b := range bases {
		get(b+"|mesh", b+"/mesh/status")
		get(b+"|healthz", b+"/healthz")
	}
	get("nano", nanoBase+"/health")
	if isRelay {
		get("relay", strings.TrimRight(relayURL.String(), "/")+"/")
	}
	var list *tunnelList
	listNote, probedCodespace := "", false
	bin := tunnelBin()
	switch {
	case bin == "":
		listNote = "vyomi-tunnel is not installed"
	case !tunnelCredentialsExist():
		listNote = "no Vyomi credentials for vyomi-tunnel (skipped the Codespace probe)"
	default:
		probedCodespace = true
		wg.Add(1)
		go func() {
			defer wg.Done()
			l, n := runTunnelList(ctx, bin, "mesh")
			mu.Lock()
			list, listNote = l, n
			mu.Unlock()
		}()
	}
	wg.Wait()

	p := &homeProbe{}
	// Nano through the local tunnel.
	nano := &home{ID: homeNanoLocal, Endpoint: nanoBase, Detail: map[string]any{"probe": "GET " + nanoBase + "/health"}}
	nano.target, _ = s.nanoTarget()
	nano.target.Path, nano.target.Scheme, nano.target.Host, nano.target.SimPort = "", "http", "127.0.0.1", relayPort()
	if a := answers["nano"]; a.ok && a.body != nil && (a.body["relay"] == "vyomi-local" || a.body["ok"] == true) {
		nano.Reachable = true
		for k, v := range pickTunnel(a.body) {
			nano.Detail[k] = v
		}
		nano.Serving = a.body["tab"] == true
	} else {
		nano.Detail["error"] = firstNonEmpty(a.err, "no vyomi-tunnel answer")
	}
	p.Homes = append(p.Homes, nano)
	// Nano through the cloud relay (only when VYOMI_ENDPOINT names it).
	if isRelay {
		t, _ := s.nanoTarget()
		rh := &home{ID: homeNanoCloud, Endpoint: t.simURL(), target: t, Detail: map[string]any{"probe": "GET <VYOMI_ENDPOINT>/"}}
		if a := answers["relay"]; a.status > 0 && a.status < 500 {
			rh.Reachable, rh.Serving = true, true
		} else {
			rh.Detail["error"] = firstNonEmpty(a.err, "no answer")
		}
		p.Homes = append(p.Homes, rh)
	}
	// :9000-style appliances: a mesh (/mesh/status mesh:true) or the offline appliance (/healthz only).
	for i, b := range bases {
		m, hz := answers[b+"|mesh"], answers[b+"|healthz"]
		t := s.meshTarget()
		if u, err := url.Parse(b); err == nil {
			t = endpointTarget(u, t)
			if t.SimPort == 0 {
				t.SimPort = 80
			}
			t.Path = ""
		}
		isMesh := m.ok && m.body != nil && m.body["mesh"] == true
		if i == 0 || isMesh {
			mh := &home{ID: homeMeshLocal, Endpoint: t.simURL(), TLSEndpoint: t.tlsURL(), target: t, Detail: map[string]any{"probe": "GET " + b + "/mesh/status"}}
			if isMesh {
				mh.Reachable, mh.Serving = true, true
				for k, v := range pickMesh(m.body) {
					mh.Detail[k] = v
				}
				if mh.Detail["locked"] == true {
					mh.Serving = false
				}
			} else if m.ok {
				mh.Detail["error"] = "answered, but mesh is not on (mesh:false)"
			} else {
				mh.Detail["error"] = firstNonEmpty(m.err, "no answer")
			}
			if p.find(homeMeshLocal) == nil {
				p.Homes = append(p.Homes, mh)
			} else if isMesh {
				*p.find(homeMeshLocal) = *mh
			}
		}
		if b == applianceBase || i == len(bases)-1 {
			oh := &home{ID: homeOffline, Endpoint: t.simURL(), TLSEndpoint: t.tlsURL(), target: t, Detail: map[string]any{"probe": "GET " + b + "/healthz"}}
			switch {
			case isMesh:
				oh.Detail["error"] = "this endpoint is a mesh (see mesh-local)"
			case hz.ok:
				oh.Reachable, oh.Serving = true, true
				if v, ok := hz.body["status"]; ok {
					oh.Detail["health"] = v
				}
			default:
				oh.Detail["error"] = firstNonEmpty(hz.err, "no answer")
			}
			if p.find(homeOffline) == nil {
				p.Homes = append(p.Homes, oh)
			}
		}
	}
	// The user's Codespace mesh, through vyomi-tunnel.
	cs := s.codespaceHome(list, listNote)
	if !probedCodespace {
		cs.Detail = map[string]any{"note": listNote}
	}
	if ml := p.find(homeMeshLocal); cs.Serving && ml != nil && ml.Reachable && ml.target.Host == cs.target.Host && ml.target.SimPort == cs.target.SimPort {
		// A Codespace forward on the mesh port answers /mesh/status too: it is the Codespace, not a local mesh.
		cs.Detail = mergeDetail(cs.Detail, ml.Detail)
		ml.Reachable, ml.Serving = false, false
		ml.Detail = map[string]any{"probe": ml.Detail["probe"], "error": "this port is the Codespace forward (see mesh-codespace)"}
	}
	p.Homes = append(p.Homes, cs)
	s.selectHome(p)
	return p
}

func mergeDetail(a, b map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range b {
		out[k] = v
	}
	for k, v := range a {
		out[k] = v
	}
	return out
}

func firstNonEmpty(xs ...string) string {
	for _, x := range xs {
		if x != "" {
			return x
		}
	}
	return ""
}

// selectHome applies the spec §2 rule: an explicit choice (VYOMI_TARGET, then VYOMI_ENDPOINT) wins; otherwise
// exactly one serving home is used (or exactly one reachable one, e.g. the tunnel without a tab); several ->
// none selected (the agent asks which space); none -> none selected.
func (s *mcpServer) selectHome(p *homeProbe) {
	switch v := strings.ToLower(envAny("", "VYOMI_TARGET")); v {
	case "nano", "mesh", "offline":
		var h *home
		switch v {
		case "nano":
			if _, relay := relayEndpoint(); relay {
				h = p.find(homeNanoCloud)
			} else {
				h = p.find(homeNanoLocal)
			}
		case "mesh":
			if cs := p.find(homeMeshCodespace); cs != nil && cs.Serving {
				h = cs
			} else {
				h = p.find(homeMeshLocal)
			}
		case "offline":
			h = p.find(homeOffline)
		}
		p.Selected, p.Why = h, "VYOMI_TARGET="+v
		return
	}
	if ep := envAny("", "VYOMI_ENDPOINT"); ep != "" {
		if _, relay := relayEndpoint(); relay {
			p.Selected = p.find(homeNanoCloud)
		} else if ml := p.find(homeMeshLocal); ml != nil && ml.Reachable && ml.Endpoint == s.target(nil).simURL() {
			p.Selected = ml
		} else {
			p.Selected = p.find(homeOffline)
		}
		p.Why = "VYOMI_ENDPOINT is set"
		return
	}
	var serving, reachable []*home
	for _, h := range p.Homes {
		if h.Serving {
			serving = append(serving, h)
		}
		if h.Reachable {
			reachable = append(reachable, h)
		}
	}
	switch {
	case len(serving) == 1:
		p.Selected = serving[0]
		p.Why = "the only home that answers: " + fmt.Sprint(serving[0].Detail["probe"])
		if serving[0].ID == homeMeshCodespace {
			p.Why = "the only home that answers: the Codespace mesh through a vyomi-tunnel forward"
		}
	case len(serving) > 1:
		ids := make([]string, 0, len(serving))
		for _, h := range serving {
			ids = append(ids, h.ID)
		}
		p.Why = "several homes answer (" + strings.Join(ids, ", ") + "); only the user knows which space they work in"
	case len(reachable) == 1:
		p.Selected = reachable[0]
		p.Why = "the only reachable home (" + fmt.Sprint(reachable[0].Detail["probe"]) + "), but it cannot serve API calls yet"
		if reachable[0].ID == homeMeshCodespace {
			p.Why = "the only reachable home: the Codespace mesh, but no forward to its API yet"
		}
	case len(reachable) > 1:
		p.Why = "several homes are reachable but none can serve API calls yet"
	default:
		p.Why = "no home answered the probes"
	}
}

// homes returns the probe result, cached for homeCacheTTL.
func (s *mcpServer) homes() *homeProbe {
	s.homeCache.mu.Lock()
	defer s.homeCache.mu.Unlock()
	if s.homeCache.val != nil && time.Since(s.homeCache.at) < homeCacheTTL {
		return s.homeCache.val
	}
	s.homeCache.val = s.probeHomes(context.Background())
	s.homeCache.at = time.Now()
	return s.homeCache.val
}

// resolveHome turns a tool's `home` argument into a target. Explicit values never probe; "" / "auto" use the
// resolver, and fall back to the legacy target (VYOMI_ENDPOINT / :9000) when it selects nothing.
func (s *mcpServer) resolveHome(arg string) (homeSel, error) {
	switch strings.ToLower(strings.TrimSpace(arg)) {
	case "nano":
		t, id := s.nanoTarget()
		return homeSel{ID: id, Why: "home=nano requested", target: t}, nil
	case "mesh":
		return s.meshHome(), nil
	case "offline":
		return homeSel{ID: homeOffline, Why: "home=offline requested", target: s.target(nil)}, nil
	case "", "auto":
		return s.autoHome(), nil
	}
	return homeSel{}, fmt.Errorf("home must be one of auto, nano, mesh, offline (got %q)", arg)
}

// meshHome resolves home=mesh. A local mesh that answers wins; otherwise a reachable Codespace mesh is the mesh:
// through its live forward, or (no forward yet) at the suggested forward's local ports with a warning to start it.
func (s *mcpServer) meshHome() homeSel {
	p := s.homes()
	ml, cs := p.find(homeMeshLocal), p.find(homeMeshCodespace)
	if ml != nil && ml.Reachable {
		return homeSel{ID: homeMeshLocal, Why: "home=mesh requested", target: s.meshTarget()}
	}
	if cs != nil && cs.Serving {
		return homeSel{ID: homeMeshCodespace, Why: "home=mesh requested: the Codespace mesh through its vyomi-tunnel forward", target: cs.target}
	}
	if cs != nil && cs.Reachable {
		fwd, _ := cs.Detail["forward_command"].(string)
		tls, _ := cs.Detail["forward_tls_command"].(string)
		return homeSel{ID: homeMeshCodespace, Why: "home=mesh requested: the Codespace mesh (no forward yet)", target: cs.target,
			Warning: "No forward to the Codespace mesh API yet. These values assume the user runs `" + fwd + "` in another terminal and keeps it open" +
				" (TLS services such as Cosmos DB and Key Vault also need `" + tls + "`). The MCP never starts forwards."}
	}
	return homeSel{ID: homeMeshLocal, Why: "home=mesh requested", target: s.meshTarget()}
}

func (s *mcpServer) autoHome() homeSel {
	p := s.homes()
	if h := p.Selected; h != nil && (h.Endpoint != "" || h.ID == homeOffline) {
		t := h.target
		if h.ID == homeOffline || (h.ID == homeMeshLocal && envAny("", "VYOMI_ENDPOINT") != "") {
			t = s.target(nil) // keep the legacy target (and its TLS port) exactly
		}
		return homeSel{ID: h.ID, Why: p.Why, target: t}
	}
	sel := homeSel{ID: homeOffline, Why: "default endpoint (VYOMI_ENDPOINT or 127.0.0.1:9000): " + p.Why, target: s.target(nil)}
	if p.Selected == nil && strings.HasPrefix(p.Why, "several") {
		sel.Warning = "Several Vyomi homes are reachable; this used the offline default. Ask the user which space they work in and pass home=nano or home=mesh."
	}
	return sel
}

// homeTarget resolves a tool's `home` and applies its host / account overrides. The offline home keeps the
// legacy target exactly (VYOMI_ENDPOINT / VYOMI_SIMULATOR_PORT / host arg), so 3.0.46-era output is unchanged.
func (s *mcpServer) homeTarget(arg string, a *mcpTargetArgs) (homeSel, mcpTarget, error) {
	sel, err := s.resolveHome(arg)
	if err != nil {
		return sel, mcpTarget{}, err
	}
	if sel.ID == homeOffline {
		return sel, s.target(a), nil
	}
	t := sel.target
	if a != nil {
		if h := strings.TrimSpace(a.Host); h != "" {
			if hh, pp, ok := strings.Cut(h, ":"); ok {
				h = hh
				if p, err := strconv.Atoi(pp); err == nil {
					t.SimPort = p
				}
			}
			t.Host = h
		}
		if acc := strings.TrimSpace(a.Account); acc != "" {
			t.Account = acc
		}
	}
	return sel, t, nil
}

package main

// Guardrails for the hosted MCP surface (HOSTED-MCP-IMPLEMENTATION-PLAN.md §4): the hosted server is read-only,
// has no writer, reaches no network, touches no file, and takes no file path. The local surface is pinned
// separately in mcp_guardrails_test.go and is not affected by anything here.

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"testing"
)

// hostedPin is the hosted tool surface: eight read-only tools, no writer. Changing this list is a contract
// change: directories re-review the tool set (plan §7).
var hostedPin = []string{"check_capability", "get_code_snippet", "get_scan_rules", "get_sdk_settings",
	"list_services", "propose_agents_md_section", "propose_env_file", "summarize_scan_hits"}

func testHostedServer(t *testing.T) *mcpServer {
	t.Helper()
	s, err := newHostedMCPServer()
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// hostedCalls covers every hosted tool over every home, so the no-outbound and no-file-access tests exercise the
// whole surface rather than one happy path.
type hostedCall struct {
	tool string
	args map[string]any
}

func hostedCalls() []hostedCall {
	type call = hostedCall
	var calls []call
	for _, home := range []string{"", "nano", "mesh", "offline"} {
		for _, cloud := range mcpClouds {
			calls = append(calls,
				call{"list_services", map[string]any{"cloud": cloud, "home": home}},
				call{"get_sdk_settings", map[string]any{"cloud": cloud, "home": home}},
			)
		}
		calls = append(calls,
			call{"get_code_snippet", map[string]any{"cloud": "aws", "service": "s3", "home": home}},
			call{"get_code_snippet", map[string]any{"cloud": "gcp", "service": "storage", "lang": "python", "home": home}},
			call{"get_sdk_settings", map[string]any{"cloud": "azure", "home": home, "host": "192.168.64.5:9100", "account": "devstoreaccount1"}},
		)
	}
	for _, home := range []string{"", "nano", "mesh", "offline"} {
		calls = append(calls,
			call{"summarize_scan_hits", map[string]any{"home": home, "hits": []map[string]any{
				{"rule": "aws-python-1", "file": "src/app.py", "line": 12, "token": "s3"},
				{"rule": "gcp-nodejs-1", "file": "web/index.js", "line": 3, "token": "pubsub"},
				{"rule": "azure-terraform-1", "file": "infra/main.tf", "line": 40, "token": "cosmosdb"},
				{"rule": scanWiredRuleID, "file": "src/app.py", "line": 9},
			}}},
			call{"propose_env_file", map[string]any{"clouds": []string{"aws", "gcp", "azure"}, "home": home}},
		)
	}
	calls = append(calls,
		call{"get_scan_rules", map[string]any{}},
		call{"get_scan_rules", map[string]any{"languages": []string{"python", "terraform"}}},
		call{"propose_env_file", map[string]any{"clouds": []string{"aws"}, "filename": ".env.vyomi.local", "home": "nano"}},
		call{"propose_agents_md_section", map[string]any{"clouds": []string{"aws"}}},
		call{"propose_agents_md_section", map[string]any{"clouds": []string{"aws", "gcp"}, "agents_md": "# Agents\n", "claude_md": "# notes\n", "env_file": ".env.vyomi.local"}},
		call{"check_capability", map[string]any{"query": "bucket versioning"}},
		call{"check_capability", map[string]any{"query": "aks.cluster", "cloud": "azure"}},
		call{"list_services", map[string]any{}},
		// The Nano cloud relay: no URL is ever sent, and the answer carries the placeholder (plan §4 rule 4).
		call{"get_sdk_settings", map[string]any{"cloud": "aws", "home": "nano", "nano_access": "relay"}},
		call{"get_code_snippet", map[string]any{"cloud": "aws", "service": "s3", "home": "nano", "nano_access": "relay"}},
		call{"propose_env_file", map[string]any{"clouds": []string{"aws", "azure"}, "home": "nano", "nano_access": "relay"}},
	)
	return calls
}

// Rule 3: exactly these tools, every one read-only and non-destructive, no writer.
func TestHostedToolSurfaceIsPinned(t *testing.T) {
	s := testHostedServer(t)
	var got, writers []string
	for _, tool := range s.tools {
		got = append(got, tool.Name)
		if !tool.ReadOnly || tool.Destructive {
			writers = append(writers, tool.Name)
		}
		if tool.OpenWorld {
			t.Errorf("%s: openWorldHint must be false (the hosted server answers from embedded knowledge)", tool.Name)
		}
		if tool.Title == "" {
			t.Errorf("%s has no title (every hosted tool needs one)", tool.Name)
		}
	}
	sort.Strings(got)
	if strings.Join(got, ",") != strings.Join(hostedPin, ",") {
		t.Errorf("hosted tool surface changed: got %v want %v (a contract change: directories re-review the tool set)", got, hostedPin)
	}
	if len(writers) > 0 {
		t.Errorf("the hosted server must have 0 writers, got %v", writers)
	}
}

// Rule 3 on the wire: the annotations a client reads.
func TestHostedToolAnnotationsOnTheWire(t *testing.T) {
	s := testHostedServer(t)
	for _, tool := range s.tools {
		d := tool.describe()
		a, ok := d["annotations"].(map[string]any)
		if !ok {
			t.Fatalf("%s has no annotations", tool.Name)
		}
		for key, want := range map[string]bool{"readOnlyHint": true, "destructiveHint": false, "idempotentHint": true, "openWorldHint": false} {
			if a[key] != want {
				t.Errorf("%s: %s = %v, want %v", tool.Name, key, a[key], want)
			}
		}
		if a["title"] == "" || d["title"] == "" {
			t.Errorf("%s: title is empty on the wire", tool.Name)
		}
		if len(tool.Name) > 64 {
			t.Errorf("%s: tool names must be at most 64 characters (directory policy 5C)", tool.Name)
		}
	}
}

// Every hosted description has to say what the tool is for, when to use it, what it takes and that it has no
// side effects, and must carry no pricing or upgrade wording (O-D2, O-D4).
func TestHostedDescriptionsAreComplete(t *testing.T) {
	s := testHostedServer(t)
	for _, tool := range s.tools {
		d := tool.Description
		if len(d) < 200 {
			t.Errorf("%s: description is too thin to state purpose, use, inputs and side effects: %q", tool.Name, d)
		}
		if !strings.Contains(strings.ToLower(d), "side effects") {
			t.Errorf("%s: description must state that the tool has no side effects", tool.Name)
		}
		if !strings.Contains(strings.ToLower(d), "input") {
			t.Errorf("%s: description must state its inputs", tool.Name)
		}
		if !strings.Contains(strings.ToLower(d), "use it") {
			t.Errorf("%s: description must say when to use the tool", tool.Name)
		}
		if !strings.Contains(strings.ToLower(d), "return") {
			t.Errorf("%s: description must say what the tool returns", tool.Name)
		}
	}
}

// No tier pricing and no upgrade wording anywhere a client reads: the instructions, the titles, the descriptions
// and the schema text. "available on a Vyomi mesh" is the most that may be said about a mesh-only feature.
func TestHostedTextHasNoPricingOrUpgradeWording(t *testing.T) {
	s := testHostedServer(t)
	banned := []string{"upgrade", "pricing", "price", "paid", "purchase", "subscribe", "subscription",
		"free plan", "pro tier", "pro plan", "pro licence", "pro license", "pro/max", "trial", "billing"}
	// An amount of money, rather than a bare "$": the scan token pattern anchors with one and the Nano relay
	// placeholder is ${VYOMI_RELAY_URL}.
	currency := regexp.MustCompile(`[$€£₹]\s*\d|\d\s*(usd|eur|inr|/month|per month|a month)`)
	check := func(what, text string) {
		low := strings.ToLower(text)
		for _, b := range banned {
			if strings.Contains(low, b) {
				t.Errorf("%s mentions %q; the hosted surface carries no tier pricing or upgrade wording", what, b)
			}
		}
		if m := currency.FindString(low); m != "" {
			t.Errorf("%s mentions a price (%q); the hosted surface carries no pricing", what, m)
		}
	}
	check("the hosted instructions", mcpHostedInstructions)
	for _, tool := range s.tools {
		check(tool.Name+" title", tool.Title)
		check(tool.Name+" description", tool.Description)
		schema, _ := json.Marshal(tool.Schema)
		check(tool.Name+" schema", string(schema))
	}
}

// Rule 2, first half: no hosted input names a place on the caller's disk, at any depth of any schema.
//
// Some inputs do carry file NAMES, which is deliberate and disclosed (design §4 and §8): a scan hit's `file` and
// `line` are how the report shows the user where a service is used, and `filename` / `env_file` are the name of
// the file the agent will write after a yes. None of them is ever opened — the hosted server has no file access
// at all (TestHostedToolsTouchNoFiles). They are pinned here so a new file-ish input needs a deliberate review.
func TestHostedSchemasHaveNoPath(t *testing.T) {
	s := testHostedServer(t)
	banned := map[string]bool{"path": true, "file_path": true, "filepath": true, "dir": true, "directory": true,
		"cwd": true, "root": true, "project": true, "project_path": true, "workspace": true, "paths": true, "files": true}
	// A hosted input never carries a URL, a token, a key or a secret: the server must not be able to receive a
	// bearer capability (the Nano cloud relay URL is one) or a credential, by accident or by a prompt injection.
	credentialish := []string{"url", "uri", "token", "key", "secret", "password", "credential", "auth", "session"}
	// The one exception, reviewed: a scan hit's `token` is the service identifier a rule captured (`s3`,
	// `storage-blob`), validated against scanTokenPattern, never a credential (D-I1).
	allowedSensitiveNames := map[string]bool{"summarize_scan_hits.hits[].token": true}
	allowedFileNames := map[string]bool{
		"summarize_scan_hits.hits[].file":          true, // where a hit was found: shown to the user, never opened
		"propose_env_file.filename":                true, // the name of the proposed .env.vyomi
		"propose_agents_md_section.env_file":       true, // the env file name the section refers to
		"propose_agents_md_section.claude_md_file": true, // which memory file claude_md came from (a fixed enum)
	}
	var walk func(tool, where string, v any)
	walk = func(tool, where string, v any) {
		m, ok := v.(map[string]any)
		if !ok {
			return
		}
		if props, ok := m["properties"].(map[string]any); ok {
			for name, sub := range props {
				at := where + "." + name
				low := strings.ToLower(name)
				if banned[low] {
					t.Errorf("%s: schema %s is a path input; the hosted server never sees a file system", tool, at)
				}
				if (strings.Contains(low, "file") || strings.Contains(low, "path")) && !allowedFileNames[tool+strings.TrimPrefix(at, "root")] {
					t.Errorf("%s: schema %s looks like a file input and is not in the reviewed list", tool, at)
				}
				for _, c := range credentialish {
					if strings.Contains(low, c) && !allowedSensitiveNames[tool+strings.TrimPrefix(at, "root")] {
						t.Errorf("%s: schema %s contains %q; a hosted input must never be able to carry a URL, token, key or secret", tool, at, c)
					}
				}
				walk(tool, at, sub)
			}
		}
		if items, ok := m["items"]; ok {
			walk(tool, where+"[]", items)
		}
	}
	for _, tool := range s.tools {
		walk(tool.Name, "root", map[string]any(tool.Schema))
	}
}

// recordingTransport fails the test if a hosted handler ever dials.
type recordingTransport struct {
	mu   sync.Mutex
	dial []string
}

func (rt *recordingTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	rt.mu.Lock()
	rt.dial = append(rt.dial, r.Method+" "+r.URL.String())
	rt.mu.Unlock()
	return nil, http.ErrUseLastResponse
}

// Rule 1 and rule 4: no hosted handler reaches the network, not even for a URL the caller supplied.
func TestHostedToolsMakeNoOutboundRequests(t *testing.T) {
	s := testHostedServer(t)
	rt := &recordingTransport{}
	s.client = &http.Client{Transport: rt}
	s.probeClient = &http.Client{Transport: rt}
	for _, c := range hostedCalls() {
		res, isErr := callTool(t, s, c.tool, c.args)
		if isErr {
			t.Fatalf("%s %v: %v", c.tool, c.args, res["error"])
		}
	}
	if len(rt.dial) > 0 {
		t.Fatalf("hosted handlers dialled out %d time(s): %v", len(rt.dial), rt.dial)
	}
	// There is no input that could carry a URL to fetch: the relay is a placeholder (see
	// TestHostedNanoRelayIsAPlaceholderNeverAnInput).
	if res, isErr := callTool(t, s, "get_sdk_settings", map[string]any{"cloud": "aws", "home": "nano", "relay_url": "https://relay.vyomi.cloud/abc123"}); !isErr {
		t.Errorf("relay_url must not be an input any more: %v", res)
	}
}

// Belt and braces behind rule 1: the transport the hosted server is built with cannot dial at all.
func TestHostedServerCannotDial(t *testing.T) {
	s := testHostedServer(t)
	for _, c := range []*http.Client{s.client, s.probeClient} {
		if _, err := c.Get("http://127.0.0.1:9000/healthz"); err == nil {
			t.Fatal("the hosted server's HTTP client dialled; it must always error")
		}
	}
	if _, err := s.getJSON("http://127.0.0.1:9000", "/healthz"); err == nil {
		t.Fatal("getJSON succeeded on the hosted server; outbound HTTP must be disabled")
	}
}

// Rule 2, second half: run every hosted tool from an empty working directory and prove nothing was created.
func TestHostedToolsTouchNoFiles(t *testing.T) {
	dir := t.TempDir()
	t.Chdir(dir)
	s := testHostedServer(t)
	before := snapshot(t, dir)
	for _, c := range hostedCalls() {
		if res, isErr := callTool(t, s, c.tool, c.args); isErr {
			t.Fatalf("%s %v: %v", c.tool, c.args, res["error"])
		}
	}
	sameTree(t, before, snapshot(t, dir))
	if entries, err := os.ReadDir(dir); err != nil || len(entries) != 0 {
		t.Fatalf("the working directory is no longer empty: %v (%v)", entries, err)
	}
	// A path argument is refused outright by every hosted tool: none of them has one.
	for _, tool := range hostedPin {
		if res, isErr := callTool(t, s, tool, map[string]any{"path": filepath.Join(dir, "x")}); !isErr {
			t.Errorf("%s accepted a path argument: %v", tool, res)
		}
	}
}

// Hosted initialize and resources (D-I2), and the local server's own answers, which must not change.
func TestHostedInitializeAndNoResources(t *testing.T) {
	s := testHostedServer(t)
	res, rerr := s.dispatch("initialize", json.RawMessage(`{"protocolVersion":"2025-06-18"}`))
	if rerr != nil {
		t.Fatal(rerr.Message)
	}
	m := res.(map[string]any)
	info := m["serverInfo"].(map[string]any)
	if info["title"] != "Vyomi" {
		t.Errorf("hosted serverInfo.title = %v, want Vyomi", info["title"])
	}
	if info["name"] != mcpServerName {
		t.Errorf("hosted serverInfo.name = %v, want %s", info["name"], mcpServerName)
	}
	if m["instructions"] != mcpHostedInstructions {
		t.Error("hosted initialize must carry mcpHostedInstructions")
	}
	if caps := m["capabilities"].(map[string]any); caps["resources"] != nil {
		t.Errorf("hosted capabilities must not advertise resources (D-I2): %v", caps)
	}
	list, _ := s.dispatch("resources/list", nil)
	if r := list.(map[string]any)["resources"].([]any); len(r) != 0 {
		t.Errorf("hosted resources/list must be empty, got %v", r)
	}
	if _, rerr := s.dispatch("resources/read", json.RawMessage(`{"uri":"vyomi://settings"}`)); rerr == nil {
		t.Error("hosted resources/read must fail: there are no resources")
	}

	// Rule 8: local mode is untouched.
	l, _ := testMCPServer(t)
	lres, _ := l.dispatch("initialize", json.RawMessage(`{"protocolVersion":"2025-06-18"}`))
	lm := lres.(map[string]any)
	if lm["instructions"] != mcpInstructions {
		t.Error("local initialize must still carry mcpInstructions")
	}
	if lm["serverInfo"].(map[string]any)["title"] != "Vyomi local cloud" {
		t.Error("local serverInfo.title changed")
	}
	if lm["capabilities"].(map[string]any)["resources"] == nil {
		t.Error("local mode must still advertise resources")
	}
	llist, _ := l.dispatch("resources/list", nil)
	if r := llist.(map[string]any)["resources"].([]map[string]any); len(r) == 0 {
		t.Error("local resources/list must still list resources")
	}
}

// namedHome is the hosted resolver: three homes, standard endpoints, no probing, no environment.
func TestNamedHomeNeverProbesOrReadsEnv(t *testing.T) {
	t.Setenv("VYOMI_ENDPOINT", "http://192.0.2.9:1234")
	t.Setenv("VYOMI_SIMULATOR_PORT", "1234")
	t.Setenv("VYOMI_MESH_URL", "http://192.0.2.9:1234")
	t.Setenv("RELAY_PORT", "1234")
	t.Setenv("VYOMI_TARGET", "offline")
	s := testHostedServer(t)
	for arg, want := range map[string]struct{ id, endpoint string }{
		"":        {homeNanoLocal, "http://127.0.0.1:8090"},
		"nano":    {homeNanoLocal, "http://127.0.0.1:8090"},
		"mesh":    {homeMeshLocal, "http://127.0.0.1:9000"},
		"offline": {homeOffline, "http://127.0.0.1:9000"},
	} {
		sel, err := s.namedHome(arg)
		if err != nil {
			t.Fatalf("namedHome(%q): %v", arg, err)
		}
		if sel.ID != want.id || sel.target.simURL() != want.endpoint {
			t.Errorf("namedHome(%q) = %s %s, want %s %s (the caller's machine, not ours; env must be ignored)",
				arg, sel.ID, sel.target.simURL(), want.id, want.endpoint)
		}
	}
	if _, err := s.namedHome("auto"); err == nil {
		t.Error("home=auto must be refused in hosted mode: nothing can be detected from here")
	}
	if _, err := s.namedHome("codespace"); err == nil {
		t.Error("an unknown home must be refused")
	}
	// The hosted server routes every knowledge handler through namedHome.
	sel, err := s.homeForArg("mesh")
	if err != nil || sel.ID != homeMeshLocal {
		t.Errorf("homeForArg on the hosted server must use namedHome: %v %v", sel.ID, err)
	}
}

// A hosted answer is the local answer for the same home with live state off (the PR 2 parity tests extend this
// to the scan and the proposals).
func TestHostedKnowledgeMatchesLocal(t *testing.T) {
	// The hosted server names the caller's standard endpoints; the local one reads this machine's settings. For
	// the two to be comparable the environment has to be the default one (which is what CI has).
	for _, k := range []string{"RELAY_PORT", "VYOMI_ENDPOINT", "VYOMI_SIMULATOR_PORT", "VYOMI_MESH_URL", "VYOMI_TARGET"} {
		t.Setenv(k, "")
	}
	hosted := testHostedServer(t)
	local, _ := testMCPServer(t)
	for _, home := range []string{"nano", "mesh", "offline"} {
		for _, cloud := range mcpClouds {
			h, isErr := callTool(t, hosted, "list_services", map[string]any{"cloud": cloud, "home": home})
			if isErr {
				t.Fatalf("hosted list_services: %v", h["error"])
			}
			l, isErr := callTool(t, local, "vyomi_services", map[string]any{"cloud": cloud, "home": home, "live": false})
			if isErr {
				t.Fatalf("local vyomi_services: %v", l["error"])
			}
			sameJSON(t, "list_services vs vyomi_services ("+cloud+", "+home+")", l, h)

			h, isErr = callTool(t, hosted, "get_sdk_settings", map[string]any{"cloud": cloud, "home": home})
			if isErr {
				t.Fatalf("hosted get_sdk_settings: %v", h["error"])
			}
			l, isErr = callTool(t, local, "vyomi_env", map[string]any{"cloud": cloud, "home": home})
			if isErr {
				t.Fatalf("local vyomi_env: %v", l["error"])
			}
			sameJSON(t, "get_sdk_settings vs vyomi_env ("+cloud+", "+home+")", l, h)
		}
		h, isErr := callTool(t, hosted, "get_code_snippet", map[string]any{"cloud": "aws", "service": "s3", "home": home})
		if isErr {
			t.Fatalf("hosted get_code_snippet: %v", h["error"])
		}
		l, isErr := callTool(t, local, "vyomi_snippet", map[string]any{"cloud": "aws", "service": "s3", "home": home})
		if isErr {
			t.Fatalf("local vyomi_snippet: %v", l["error"])
		}
		sameJSON(t, "get_code_snippet vs vyomi_snippet ("+home+")", l, h)
	}
	h, _ := callTool(t, hosted, "check_capability", map[string]any{"query": "bucket versioning"})
	l, _ := callTool(t, local, "vyomi_capability", map[string]any{"query": "bucket versioning"})
	sameJSON(t, "check_capability vs vyomi_capability", l, h)
}

func sameJSON(t *testing.T, what string, want, got any) {
	t.Helper()
	w, _ := json.MarshalIndent(want, "", "  ")
	g, _ := json.MarshalIndent(got, "", "  ")
	if string(w) != string(g) {
		t.Errorf("%s differ:\nlocal:  %s\nhosted: %s", what, w, g)
	}
}

// The Nano cloud relay URL is a bearer capability for the user's tab: the hosted server has no input that can
// carry it, and renders the placeholder instead, with instructions to substitute it locally.
func TestHostedNanoRelayIsAPlaceholderNeverAnInput(t *testing.T) {
	s := testHostedServer(t)

	// No schema takes a relay URL under any name.
	for _, tool := range s.tools {
		schema, _ := json.Marshal(tool.Schema)
		for _, banned := range []string{"relay_url", "relayUrl", "endpoint_url", "vyomi_endpoint"} {
			if strings.Contains(string(schema), banned) {
				t.Errorf("%s: schema takes %q; the relay URL must never be an input", tool.Name, banned)
			}
		}
	}
	if res, isErr := callTool(t, s, "get_sdk_settings", map[string]any{"cloud": "aws", "home": "nano", "relay_url": "https://relay.vyomi.cloud/abc"}); !isErr {
		t.Errorf("an unknown relay_url argument must be refused: %v", res)
	}
	// A URL cannot be smuggled through host either.
	for _, host := range []string{"https://relay.vyomi.cloud/abc", "relay.vyomi.cloud/abc"} {
		if res, isErr := callTool(t, s, "get_sdk_settings", map[string]any{"cloud": "aws", "home": "nano", "host": host}); !isErr {
			t.Errorf("host %q must be refused: %v", host, res)
		}
	}

	// nano_access=relay renders the placeholder, selects the nano-cloud home, and says what to do with it.
	for _, c := range []struct {
		tool string
		args map[string]any
		key  string // where the endpoint appears
	}{
		{"get_sdk_settings", map[string]any{"cloud": "aws", "home": "nano", "nano_access": "relay"}, "endpoint"},
		{"get_code_snippet", map[string]any{"cloud": "aws", "service": "s3", "home": "nano", "nano_access": "relay"}, "endpoint"},
		{"propose_env_file", map[string]any{"clouds": []string{"aws"}, "home": "nano", "nano_access": "relay"}, "endpoint"},
	} {
		res, isErr := callTool(t, s, c.tool, c.args)
		if isErr {
			t.Fatalf("%s: %v", c.tool, res["error"])
		}
		if ep, _ := res[c.key].(string); ep != nanoRelayPlaceholder {
			t.Errorf("%s: %s = %q, want the literal %s", c.tool, c.key, ep, nanoRelayPlaceholder)
		}
		if home, _ := res["home"].(string); home != homeNanoCloud {
			t.Errorf("%s: home = %q, want %s", c.tool, home, homeNanoCloud)
		}
		sub, _ := res["substitute"].(string)
		if !strings.Contains(sub, nanoRelayPlaceholder) || !strings.Contains(strings.ToLower(sub), "footer") {
			t.Errorf("%s: the answer must tell the agent to substitute the placeholder from the Nano footer, got %q", c.tool, sub)
		}
		if strings.Contains(strings.ToLower(sub), "send") && !strings.Contains(strings.ToLower(sub), "do not send") {
			t.Errorf("%s: the note must not invite sending the URL: %q", c.tool, sub)
		}
		// Whatever the answer renders, it never names a concrete session URL (only the generic form, in the note).
		raw, _ := json.Marshal(res)
		body := strings.NewReplacer(`\u003c`, "<", `\u003e`, ">").Replace(string(raw))
		for _, part := range strings.Split(body, "relay.vyomi.cloud/")[1:] {
			if !strings.HasPrefix(part, "<session>") {
				t.Errorf("%s: the answer contains a concrete relay URL (relay.vyomi.cloud/%.20s...)", c.tool, part)
			}
		}
	}

	// The generated settings and the snippet carry the placeholder, so the agent substitutes one value.
	res, isErr := callTool(t, s, "get_sdk_settings", map[string]any{"cloud": "aws", "home": "nano", "nano_access": "relay", "format": "dotenv"})
	if isErr {
		t.Fatal(res["error"])
	}
	if txt, _ := res["env_text"].(string); !strings.Contains(txt, "AWS_ENDPOINT_URL="+nanoRelayPlaceholder) {
		t.Errorf("env_text should point AWS_ENDPOINT_URL at the placeholder:\n%s", txt)
	}
	res, isErr = callTool(t, s, "get_code_snippet", map[string]any{"cloud": "aws", "service": "s3", "home": "nano", "nano_access": "relay"})
	if isErr {
		t.Fatal(res["error"])
	}
	if sn, _ := res["snippet"].(string); !strings.Contains(sn, nanoRelayPlaceholder) {
		t.Errorf("the snippet should aim at the placeholder:\n%s", sn)
	}
	res, isErr = callTool(t, s, "propose_env_file", map[string]any{"clouds": []string{"aws", "gcp"}, "home": "nano", "nano_access": "relay"})
	if isErr {
		t.Fatal(res["error"])
	}
	if content, _ := res["content"].(string); !strings.Contains(content, nanoRelayPlaceholder) || strings.Contains(content, "127.0.0.1:8090") {
		t.Errorf("the proposed file should use the placeholder and no local tunnel endpoint:\n%s", content)
	}

	// nano_access only applies to nano, and only takes the two documented values.
	for _, bad := range []map[string]any{
		{"cloud": "aws", "home": "mesh", "nano_access": "relay"},
		{"cloud": "aws", "home": "offline", "nano_access": "relay"},
		{"cloud": "aws", "home": "nano", "nano_access": "https://relay.vyomi.cloud/abc"},
		{"cloud": "aws", "home": "nano", "nano_access": "relay", "host": "192.168.64.5"},
	} {
		if res, isErr := callTool(t, s, "get_sdk_settings", bad); !isErr {
			t.Errorf("should refuse %v: %v", bad, res)
		}
	}
	// The default is the local tunnel, which is the common case.
	res, isErr = callTool(t, s, "get_sdk_settings", map[string]any{"cloud": "aws", "home": "nano"})
	if isErr {
		t.Fatal(res["error"])
	}
	if ep, _ := res["endpoint"].(string); ep != "http://127.0.0.1:8090" {
		t.Errorf("home=nano without nano_access should be the local tunnel, got %q", ep)
	}
	if res["substitute"] != nil {
		t.Errorf("the tunnel answer needs no substitution note: %v", res["substitute"])
	}
	// The instructions tell the agent the rule.
	low := strings.ToLower(mcpHostedInstructions)
	for _, want := range []string{"nano_access=relay", strings.ToLower(nanoRelayPlaceholder), "never"} {
		if !strings.Contains(low, want) {
			t.Errorf("the hosted instructions should mention %q", want)
		}
	}
}

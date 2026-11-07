package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testMCPServer(t *testing.T) (*mcpServer, *bytes.Buffer) {
	t.Helper()
	t.Setenv("VYOMI_SUBSTRATE", "docker") // never shell out to multipass in tests
	out := &bytes.Buffer{}
	s, err := newMCPServer(&Config{VyomiHome: t.TempDir()}, out)
	if err != nil {
		t.Fatal(err)
	}
	return s, out
}

func rpcLines(t *testing.T, out *bytes.Buffer) []map[string]any {
	t.Helper()
	var msgs []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "[") { // batch reply
			var batch []map[string]any
			if err := json.Unmarshal([]byte(line), &batch); err != nil {
				t.Fatalf("stdout carried a bad batch %q: %v", line, err)
			}
			msgs = append(msgs, map[string]any{"batch": batch})
			continue
		}
		var m map[string]any
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Fatalf("stdout carried a non-JSON line %q: %v", line, err)
		}
		msgs = append(msgs, m)
	}
	return msgs
}

func callTool(t *testing.T, s *mcpServer, name string, args any) (map[string]any, bool) {
	t.Helper()
	raw, _ := json.Marshal(args)
	res, rerr := s.dispatch("tools/call", json.RawMessage(`{"name":"`+name+`","arguments":`+string(raw)+`}`))
	if rerr != nil {
		t.Fatalf("%s: rpc error %v", name, rerr.Message)
	}
	r := res.(map[string]any)
	text := r["content"].([]map[string]any)[0]["text"].(string)
	if r["isError"] == true {
		return map[string]any{"error": text}, true
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(text), &out); err != nil {
		t.Fatalf("%s: result is not JSON: %v\n%s", name, err, text)
	}
	return out, false
}

func TestMCPMatrixEmbedded(t *testing.T) {
	m, err := loadMCPMatrix()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range mcpClouds {
		cl := m.Clouds[c]
		if len(cl.Services) == 0 || len(cl.Wiring.Env) == 0 {
			t.Errorf("%s: empty services or env wiring", c)
		}
		for _, svc := range cl.Services {
			if svc.Status == "" {
				t.Errorf("%s/%s: no status (services/registry.json)", c, svc.ID)
			}
		}
	}
	s := &mcpServer{matrix: m}
	if _, _, err := s.compileScanRules(); err != nil {
		t.Fatalf("scan rules must compile: %v", err)
	}
	// Every alias target must be a real service (or a deliberate skip marker), so
	// the scanner never reports a renamed service as "not emulated".
	for cloud, aliases := range m.Scan.Aliases {
		for tok, svc := range aliases {
			if svc == "_core" || svc == "_ignore" || m.service(cloud, svc) != nil {
				continue
			}
			t.Logf("note: %s alias %q -> %q is not in the matrix (reported as not_emulated)", cloud, tok, svc)
		}
	}
}

func TestMCPProtocolRoundTrip(t *testing.T) {
	s, out := testMCPServer(t)
	in := strings.Join([]string{
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}`,
		`{"jsonrpc":"2.0","method":"notifications/initialized"}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/list"}`,
		`{"jsonrpc":"2.0","id":"three","method":"resources/list"}`,
		`{"jsonrpc":"2.0","id":4,"method":"resources/read","params":{"uri":"vyomi://env/aws"}}`,
		`{"jsonrpc":"2.0","id":5,"method":"no/such"}`,
		`not json`,
		`[{"jsonrpc":"2.0","id":6,"method":"ping"},{"jsonrpc":"2.0","method":"notifications/cancelled"}]`,
	}, "\n") + "\n"
	if err := s.serve(strings.NewReader(in)); err != nil {
		t.Fatal(err)
	}
	msgs := rpcLines(t, out)
	if len(msgs) != 7 { // 5 requests + parse error + batch (notifications get no reply)
		t.Fatalf("want 7 replies, got %d: %s", len(msgs), out.String())
	}
	init := msgs[0]["result"].(map[string]any)
	if init["protocolVersion"] != "2025-03-26" {
		t.Errorf("should echo a supported client protocol version, got %v", init["protocolVersion"])
	}
	tools := msgs[1]["result"].(map[string]any)["tools"].([]any)
	want := map[string]bool{"vyomi_status": true, "vyomi_services": true, "vyomi_env": true, "vyomi_scan_repo": true, "vyomi_write_env": true}
	for _, tl := range tools {
		delete(want, tl.(map[string]any)["name"].(string))
	}
	if len(want) != 0 {
		t.Errorf("missing tools: %v", want)
	}
	if msgs[2]["id"] != "three" {
		t.Errorf("string ids must round-trip, got %v", msgs[2]["id"])
	}
	env := msgs[3]["result"].(map[string]any)["contents"].([]any)[0].(map[string]any)["text"].(string)
	if !strings.Contains(env, "AWS_ENDPOINT_URL=http://127.0.0.1:9000") {
		t.Errorf("aws env resource missing endpoint:\n%s", env)
	}
	if code := msgs[4]["error"].(map[string]any)["code"].(float64); code != rpcMethodNotFound {
		t.Errorf("unknown method code %v", code)
	}
	if code := msgs[5]["error"].(map[string]any)["code"].(float64); code != rpcParseError {
		t.Errorf("parse error code %v", code)
	}
	if batch := msgs[6]["batch"].([]map[string]any); len(batch) != 1 || batch[0]["id"].(float64) != 6 {
		t.Errorf("batch should get one reply (the ping), got %v", batch)
	}
}

func TestMCPEnvRendersTargetAndWarnings(t *testing.T) {
	s, _ := testMCPServer(t)
	res, isErr := callTool(t, s, "vyomi_env", map[string]any{"cloud": "gcp", "host": "192.168.64.5", "format": "shell"})
	if isErr {
		t.Fatal(res["error"])
	}
	txt := res["env_text"].(string)
	for _, want := range []string{"export STORAGE_EMULATOR_HOST=http://192.168.64.5:9000", "export PUBSUB_EMULATOR_HOST=192.168.64.5:8085"} {
		if !strings.Contains(txt, want) {
			t.Errorf("missing %q in:\n%s", want, txt)
		}
	}
	sdk, _ := json.Marshal(res["sdk"])
	if strings.Contains(string(sdk), "127.0.0.1:9000") {
		t.Errorf("tool_response endpoints must be re-targeted: %s", sdk)
	}
	az, _ := callTool(t, s, "vyomi_env", map[string]any{"cloud": "azure", "lang": "python"})
	notes, _ := json.Marshal(az["notes"])
	if !strings.Contains(string(notes), "AMQP") {
		t.Errorf("azure notes must warn about Service Bus AMQP: %s", notes)
	}
	if _, isErr := callTool(t, s, "vyomi_env", map[string]any{"cloud": "mars"}); !isErr {
		t.Error("unknown cloud must be a tool error")
	}
	if _, isErr := callTool(t, s, "vyomi_env", map[string]any{"cloud": "aws", "bogus": 1}); !isErr {
		t.Error("unknown arguments must be rejected")
	}
}

func writeFile(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestMCPScanRepo(t *testing.T) {
	s, _ := testMCPServer(t)
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "app", "store.py"), "import boto3\ns3 = boto3.client('s3')\nsns = boto3.client(\"sns\")\nbq = boto3.client('appflow')\n")
	writeFile(t, filepath.Join(root, "app", "worker.py"), "from azure.servicebus import ServiceBusClient\nfrom google.cloud import pubsub_v1\n")
	// Siftly-shaped: Azure OpenAI via the openai package, AI Search, SES, identity noise.
	writeFile(t, filepath.Join(root, "app", "llm.py"), "from openai import AzureOpenAI\nfrom azure.identity import DefaultAzureCredential\nfrom azure.search.documents import SearchClient\nfrom azure.communication.email import EmailClient\nses = boto3.client('ses')\n")
	writeFile(t, filepath.Join(root, "infra", "main.tf"), "resource \"aws_sqs_queue\" \"jobs\" {}\nresource \"azurerm_storage_account\" \"sa\" {}\n")
	writeFile(t, filepath.Join(root, "web", "package.json"), `{"dependencies":{"@aws-sdk/client-dynamodb":"^3"}}`)
	writeFile(t, filepath.Join(root, "node_modules", "x", "index.js"), "require('@aws-sdk/client-kinesis')\n")
	writeFile(t, filepath.Join(root, ".env.local"), "AWS_ENDPOINT_URL=http://localhost:9000\n")

	res, isErr := callTool(t, s, "vyomi_scan_repo", map[string]any{"path": root})
	if isErr {
		t.Fatal(res["error"])
	}
	status := map[string]string{}
	warn := map[string]string{}
	for cloud, list := range res["clouds"].(map[string]any) {
		for _, e := range list.([]any) {
			m := e.(map[string]any)
			key := cloud + "/" + m["service"].(string)
			status[key] = m["status"].(string)
			if w, ok := m["warning"].(string); ok {
				warn[key] = w
			}
		}
	}
	for key, want := range map[string]string{
		"aws/s3": "released", "aws/sqs": "released", "aws/dynamodb": "released", "aws/sns": "released",
		"azure/servicebus": "released", "azure/storage": "released", "gcp/pubsub": "released",
		"azure/cognitiveservices": "released", "azure/search": "not_emulated", "aws/ses": "not_emulated", "azure/communication": "not_emulated",
	} {
		if status[key] != want {
			t.Errorf("%s: status %q, want %q (all: %v)", key, status[key], want, status)
		}
	}
	if _, ok := status["aws/kinesis"]; ok {
		t.Error("node_modules must be skipped")
	}
	if !strings.Contains(warn["azure/servicebus"], "AMQP") || !strings.Contains(warn["gcp/pubsub"], "8085") {
		t.Errorf("expected Service Bus + Pub/Sub warnings, got %v", warn)
	}
	if !strings.Contains(warn["azure/cognitiveservices"], "SIMULATED") {
		t.Errorf("Azure OpenAI must carry the simulated-model warning, got %v", warn)
	}
	if _, ok := status["azure/identity"]; ok {
		t.Error("azure.identity is plumbing, not a service")
	}
	un, _ := json.Marshal(res["unrecognized"])
	if !strings.Contains(string(un), "appflow") {
		t.Errorf("unknown services should be listed as unrecognized, got %s", un)
	}
	if strings.Contains(string(un), "identity") {
		t.Errorf("azure.identity must be ignored, not unrecognized: %s", un)
	}
	if wired := res["already_wired"].([]any); len(wired) == 0 {
		t.Error("existing AWS_ENDPOINT_URL override should be detected")
	}
	if _, isErr := callTool(t, s, "vyomi_scan_repo", map[string]any{"path": "relative/dir"}); !isErr {
		t.Error("relative paths must be rejected")
	}
}

func TestMCPWriteEnv(t *testing.T) {
	s, _ := testMCPServer(t)
	dir := t.TempDir()
	res, isErr := callTool(t, s, "vyomi_write_env", map[string]any{"path": dir, "clouds": []string{"aws", "azure", "aws"}})
	if isErr {
		t.Fatal(res["error"])
	}
	b, err := os.ReadFile(filepath.Join(dir, ".env.vyomi"))
	if err != nil {
		t.Fatal(err)
	}
	body := string(b)
	if strings.Count(body, "# Vyomi: AWS") != 1 || !strings.Contains(body, "AZURE_STORAGE_CONNECTION_STRING=") {
		t.Errorf("unexpected .env.vyomi:\n%s", body)
	}
	if _, isErr := callTool(t, s, "vyomi_write_env", map[string]any{"path": dir, "clouds": []string{"aws"}}); !isErr {
		t.Error("must refuse to overwrite without overwrite=true")
	}
	if _, isErr := callTool(t, s, "vyomi_write_env", map[string]any{"path": dir, "clouds": []string{"aws"}, "filename": "../escape"}); !isErr {
		t.Error("filename must not contain directories")
	}
	if _, isErr := callTool(t, s, "vyomi_write_env", map[string]any{"path": dir, "clouds": []string{"aws"}, "overwrite": true}); isErr {
		t.Error("overwrite=true should succeed")
	}
}

func TestMCPStatus(t *testing.T) {
	s, _ := testMCPServer(t)

	t.Setenv("VYOMI_ENDPOINT", "http://127.0.0.1:1") // nothing listens on port 1
	down, _ := callTool(t, s, "vyomi_status", map[string]any{})
	if down["running"] != false || down["hint"] == nil {
		t.Errorf("down simulator should report running=false with a hint: %v", down)
	}

	sim := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/healthz":
			_, _ = w.Write([]byte(`{"status":"ok","tier":"pro","packs_active":3}`))
		case "/api/license/status":
			_, _ = w.Write([]byte(`{"active_tier":"pro","trial":{"active":true},"license":{"jwt":"SECRET"}}`))
		case "/api/spaces/active":
			_, _ = w.Write([]byte(`{"active_space_id":"sp-1","space":{"name":"dev","provider":"aws","service_states":{"s3":{"buckets":{}}},
				"cloudsim":{"summary":{"s3_bucket_count":2,"sqs_count":0,"total_resource_count":2}}}}`))
		case "/api/runtime/readiness":
			_, _ = w.Write([]byte(`{"ready_count":2,"total_count":12,"overall_pct":18,"backends":[]}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer sim.Close()
	t.Setenv("VYOMI_ENDPOINT", sim.URL)
	up, _ := callTool(t, s, "vyomi_status", map[string]any{})
	if up["running"] != true {
		t.Fatalf("expected running=true: %v", up)
	}
	raw, _ := json.Marshal(up)
	if strings.Contains(string(raw), "SECRET") {
		t.Error("raw license block (tokens) must never reach the model")
	}
	if up["license"].(map[string]any)["active_tier"] != "pro" || up["active_space"].(map[string]any)["space_id"] != "sp-1" {
		t.Errorf("license / space not surfaced: %s", raw)
	}
	if strings.Contains(string(raw), "service_states") || strings.Contains(string(raw), "sqs") {
		t.Errorf("active_space must be summarised (no raw state, no zero counts): %s", raw)
	}
	if res := up["active_space"].(map[string]any)["resources"].(map[string]any); res["s3_bucket"] != float64(2) {
		t.Errorf("non-zero resource counts should be kept: %v", res)
	}
	if !strings.Contains(string(raw), "NOT a tier limit") {
		t.Error("readiness must explain what it measures")
	}
}

func TestMCPAliasName(t *testing.T) {
	for name, want := range map[string]bool{
		"/usr/share/vyomi-docker/mcp/linux-arm64/vyomi-mcp": true,
		`C:\Program Files\Vyomi\bin\vyomi-mcp.exe`:          true,
		"./vyomi-mcp-darwin-arm64":                          true,
		"/opt/homebrew/bin/vyomi":                           false,
		"vyomi.exe":                                         false,
	} {
		if got := isMCPAlias(name); got != want {
			t.Errorf("isMCPAlias(%q) = %v, want %v", name, got, want)
		}
	}
}

func TestMCPInstructionsSteerAwayFromRealCloud(t *testing.T) {
	if !strings.Contains(mcpInstructions, "aws-mcp") || !strings.Contains(mcpInstructions, "real cloud") {
		t.Error("server instructions must steer local-dev work away from real-cloud MCP servers")
	}
}

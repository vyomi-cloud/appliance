package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"runtime"
	"strings"
	"testing"
)

func envJSON(t *testing.T, s *mcpServer, args map[string]any) (map[string]any, string) {
	t.Helper()
	res, isErr := callTool(t, s, "vyomi_env", args)
	if isErr {
		t.Fatal(res["error"])
	}
	raw, _ := json.Marshal(res)
	return res, string(raw)
}

func envValue(res map[string]any, name string) (string, bool) {
	for _, v := range res["variables"].([]any) {
		m := v.(map[string]any)
		if m["name"] == name {
			return m["value"].(string), true
		}
	}
	return "", false
}

// L1-21: AWS on Nano points at the local tunnel; nothing mentions :9000 or :9443.
func TestMCPEnvNanoAWS(t *testing.T) {
	s, _ := testMCPServer(t)
	clearHomeEnv(t)
	res, raw := envJSON(t, s, map[string]any{"cloud": "aws", "home": "nano"})
	if v, _ := envValue(res, "AWS_ENDPOINT_URL"); v != "http://127.0.0.1:8090" {
		t.Errorf("AWS_ENDPOINT_URL=%q", v)
	}
	if res["home"] != homeNanoLocal || !strings.Contains(res["env_text"].(string), "AWS_ENDPOINT_URL=http://127.0.0.1:8090") {
		t.Errorf("home/env_text: %v", res)
	}
	if strings.Contains(raw, ":9000") || strings.Contains(raw, ":9443") {
		t.Errorf("Nano env must not mention the offline ports: %s", raw)
	}
}

// L1-22: Azure on Nano hands out no TLS value; Key Vault carries the D0 warning; Cosmos is plain HTTP at the root.
func TestMCPEnvNanoAzure(t *testing.T) {
	s, _ := testMCPServer(t)
	clearHomeEnv(t)
	res, _ := envJSON(t, s, map[string]any{"cloud": "azure", "home": "nano"})
	// Values only: the Key Vault warning may (rightly) point at a mesh's https :9443.
	vals, _ := json.Marshal([]any{res["variables"], res["env_text"], res["sdk"]})
	if regexp.MustCompile(`https://|:9443|127\.0\.0\.1:0\b`).Match(vals) {
		t.Errorf("Nano Azure env must not hand out TLS values: %s", vals)
	}
	if _, ok := envValue(res, "AZURE_KEYVAULT_URL"); ok {
		t.Error("AZURE_KEYVAULT_URL must not be handed out on Nano")
	}
	warns, _ := json.Marshal(res["warnings"])
	if !strings.Contains(string(warns), "AZURE_KEYVAULT_URL") || !strings.Contains(string(warns), "Key Vault needs TLS; not available through the Nano tunnel") {
		t.Errorf("Key Vault warning missing: %s", warns)
	}
	if v, _ := envValue(res, "AZURE_COSMOS_ENDPOINT"); v != "http://127.0.0.1:8090" {
		t.Errorf("AZURE_COSMOS_ENDPOINT=%q (D0: root endpoint over HTTP)", v)
	}
	if v, _ := envValue(res, "AZURE_SERVICEBUS_CONNECTION_STRING"); !strings.Contains(v, "Endpoint=sb://127.0.0.1;") {
		t.Errorf("Service Bus AMQP connection string: %q", v)
	}
	// GCP on Nano: vyomi-project, no gRPC emulator hosts, the REST alternative in the warnings.
	g, graw := envJSON(t, s, map[string]any{"cloud": "gcp", "home": "nano"})
	if v, _ := envValue(g, "GOOGLE_CLOUD_PROJECT"); v != "vyomi-project" {
		t.Errorf("GOOGLE_CLOUD_PROJECT=%q", v)
	}
	if _, ok := envValue(g, "PUBSUB_EMULATOR_HOST"); ok || !strings.Contains(graw, "/v1/projects/vyomi-project") {
		t.Errorf("Pub/Sub on Nano: no emulator host, REST hint expected: %s", graw)
	}
	// Every Nano value says whether D0 verified it.
	for _, v := range res["variables"].([]any) {
		if _, ok := v.(map[string]any)["verified"]; !ok {
			t.Errorf("Nano variable without verified: %v", v)
		}
	}
}

// The cloud relay (Nano without the tunnel): one HTTPS URL, so no localtest.me host routing and no AMQP.
func TestMCPEnvNanoCloudRelay(t *testing.T) {
	s, _ := testMCPServer(t)
	clearHomeEnv(t)
	t.Setenv("VYOMI_ENDPOINT", "https://relay.vyomi.cloud/sess-123")
	res, _ := envJSON(t, s, map[string]any{"cloud": "azure", "home": "nano"})
	if res["home"] != homeNanoCloud || res["endpoint"] != "https://relay.vyomi.cloud/sess-123" {
		t.Errorf("home/endpoint: %v %v", res["home"], res["endpoint"])
	}
	conn, _ := envValue(res, "AZURE_STORAGE_CONNECTION_STRING")
	if !strings.Contains(conn, "BlobEndpoint=https://relay.vyomi.cloud/sess-123/devstoreaccount1;") || !strings.Contains(conn, "QueueEndpoint=https://relay.vyomi.cloud/sess-123/devstoreaccount1;") {
		t.Errorf("relay storage connection string: %s", conn)
	}
	if vals, _ := json.Marshal([]any{res["variables"], res["env_text"]}); strings.Contains(string(vals), ".localtest.me:") || strings.Contains(string(vals), ":0") {
		t.Errorf("relay env must not use host routing or a :0 port: %s", vals)
	}
	if _, ok := envValue(res, "AZURE_SERVICEBUS_CONNECTION_STRING"); ok {
		t.Error("no AMQP through the cloud relay")
	}
}

// L1-23: the offline home is byte-for-byte today's output (golden files from 42d870e), plus the `home` stamp.
func TestMCPEnvOfflineGolden(t *testing.T) {
	s, _ := testMCPServer(t)
	clearHomeEnv(t)
	for _, cloud := range mcpClouds {
		b, err := os.ReadFile(filepath.Join("testdata", "mcp_env_"+cloud+"_offline_42d870e.golden.json"))
		if err != nil {
			t.Fatal(err)
		}
		var want map[string]any
		if err := json.Unmarshal(b, &want); err != nil {
			t.Fatal(err)
		}
		got, _ := envJSON(t, s, map[string]any{"cloud": cloud, "home": "offline"})
		if got["home"] != homeOffline {
			t.Errorf("%s: home=%v", cloud, got["home"])
		}
		delete(got, "home")
		if !reflect.DeepEqual(got, want) {
			gj, _ := json.MarshalIndent(got, "", "  ")
			t.Errorf("%s offline env differs from 42d870e:\n%s", cloud, gj)
		}
	}
}

// L1-24: AKS on a Nano home is flagged mesh-only with "needs a Pro/Max mesh"; S3 carries its Nano level;
// Nano warnings replace the offline ones (no :9443 advice).
func TestMCPScanNanoHome(t *testing.T) {
	s, _ := testMCPServer(t)
	clearHomeEnv(t)
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "app.py"), "import boto3\nfrom azure.mgmt.containerservice import ContainerServiceClient\nfrom azure.cosmos import CosmosClient\ns3 = boto3.client('s3')\n")
	writeFile(t, filepath.Join(root, "main.tf"), "resource \"azurerm_kubernetes_cluster\" \"k\" {}\n")
	res, isErr := callTool(t, s, "vyomi_scan_repo", map[string]any{"path": root, "home": "nano"})
	if isErr {
		t.Fatal(res["error"])
	}
	if res["home"] != homeNanoLocal {
		t.Errorf("home=%v", res["home"])
	}
	find := func(cloud, svc string) map[string]any {
		for _, e := range res["clouds"].(map[string]any)[cloud].([]any) {
			if m := e.(map[string]any); m["service"] == svc {
				return m
			}
		}
		t.Fatalf("%s/%s not found in %v", cloud, svc, res["clouds"])
		return nil
	}
	aks := find("azure", "aks")
	if aks["mesh"] != true || !strings.Contains(aks["warning"].(string), "needs a Pro/Max mesh") || aks["status"] != "v4" {
		t.Errorf("aks finding: %v", aks)
	}
	if s3 := find("aws", "s3"); s3["level"] != "full" && s3["level"] != "limited" {
		t.Errorf("s3 level: %v", s3)
	}
	cos := find("azure", "cosmos")
	if w := cos["warning"].(string); strings.Contains(w, "9443") || !strings.Contains(w, "http://127.0.0.1:8090") {
		t.Errorf("cosmos on Nano must get the Nano warning: %q", w)
	}
	sum, _ := json.Marshal(res["summary"])
	if !strings.Contains(string(sum), "needs a Pro/Max mesh: aks") {
		t.Errorf("summary: %s", sum)
	}
	next, _ := json.Marshal(res["next_steps"])
	if !strings.Contains(string(next), "home=nano") {
		t.Errorf("next steps should carry the home: %s", next)
	}
	// The same repo against a mesh: AKS is fine there.
	m, _ := callTool(t, s, "vyomi_scan_repo", map[string]any{"path": root, "home": "mesh"})
	for _, e := range m["clouds"].(map[string]any)["azure"].([]any) {
		if x := e.(map[string]any); x["service"] == "aks" && strings.Contains(fmt.Sprint(x["warning"]), "needs a Pro/Max mesh") {
			t.Errorf("a mesh home must not warn that AKS needs a mesh: %v", x)
		}
	}
}

// Regression: a service whose level in the selected home is not_simulated (EKS on Nano) is reported as
// not emulated there, not as emulated.
func TestMCPScanNotSimulatedInHome(t *testing.T) {
	s, _ := testMCPServer(t)
	clearHomeEnv(t)
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "k.py"), "import boto3\neks = boto3.client('eks')\n")
	for home, wantGap := range map[string]bool{"nano": true, "offline": false} {
		res, isErr := callTool(t, s, "vyomi_scan_repo", map[string]any{"path": root, "home": home})
		if isErr {
			t.Fatal(res["error"])
		}
		sum, _ := json.Marshal(res["summary"])
		gap := strings.Contains(string(sum), "NOT emulated: eks (not simulated on")
		if gap != wantGap {
			t.Errorf("home %s: summary %s", home, sum)
		}
	}
}

// L1-25: write_env refuses paths outside the project and anything but .env.vyomi*; a valid write has the home header.
func TestMCPWriteEnvHome(t *testing.T) {
	s, _ := testMCPServer(t)
	clearHomeEnv(t)
	dir := t.TempDir()
	for _, name := range []string{"../outside/.env.vyomi", ".env", "config.py", ".envrc"} {
		if r, isErr := callTool(t, s, "vyomi_write_env", map[string]any{"path": dir, "clouds": []string{"aws"}, "filename": name, "home": "nano"}); !isErr {
			t.Errorf("filename %q must be refused, got %v", name, r)
		}
	}
	res, isErr := callTool(t, s, "vyomi_write_env", map[string]any{"path": dir, "clouds": []string{"aws", "azure"}, "home": "nano"})
	if isErr {
		t.Fatal(res["error"])
	}
	b, _ := os.ReadFile(filepath.Join(dir, ".env.vyomi"))
	body := string(b)
	if !regexp.MustCompile(`^# Vyomi nano-local http://127\.0\.0\.1:8090 — generated \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n`).MatchString(body) {
		t.Errorf("header:\n%s", body)
	}
	if !strings.Contains(body, "# WARNING (AZURE): AZURE_KEYVAULT_URL") || strings.Contains(body, "AZURE_KEYVAULT_URL=") {
		t.Errorf("Key Vault must be a warning comment, not a value:\n%s", body)
	}
	if res["home"] != homeNanoLocal {
		t.Errorf("home=%v", res["home"])
	}
	// .env.vyomi.local is allowed.
	if _, isErr := callTool(t, s, "vyomi_write_env", map[string]any{"path": dir, "clouds": []string{"aws"}, "filename": ".env.vyomi.local", "home": "offline"}); isErr {
		t.Error(".env.vyomi.local should be allowed")
	}
}

// Regression: overwrite=true must not write through a symlink named .env.vyomi (it could point outside the project).
func TestMCPWriteEnvRefusesSymlink(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlinks need privileges on Windows")
	}
	s, _ := testMCPServer(t)
	dir, outside := t.TempDir(), t.TempDir()
	target := filepath.Join(outside, "victim")
	writeFile(t, target, "keep me\n")
	if err := os.Symlink(target, filepath.Join(dir, ".env.vyomi")); err != nil {
		t.Fatal(err)
	}
	if _, isErr := callTool(t, s, "vyomi_write_env", map[string]any{"path": dir, "clouds": []string{"aws"}, "overwrite": true}); !isErr {
		t.Error("must refuse to write through a symlink")
	}
	if b, _ := os.ReadFile(target); string(b) != "keep me\n" {
		t.Errorf("symlink target was overwritten: %q", b)
	}
}

// vyomi_services with home says which levels key applies.
func TestMCPServicesHome(t *testing.T) {
	s, _ := testMCPServer(t)
	clearHomeEnv(t)
	res, isErr := callTool(t, s, "vyomi_services", map[string]any{"cloud": "aws", "live": false, "home": "nano"})
	if isErr {
		t.Fatal(res["error"])
	}
	if res["home"] != homeNanoLocal || !strings.Contains(res["level_key"].(string), "levels.nano") {
		t.Errorf("home/level_key: %v %v", res["home"], res["level_key"])
	}
}

package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// Knowledge v2 (plan K1): the generated capability and docs indexes next to mcp_matrix.json.

func readGzJSON(t *testing.T, name string, v any) {
	t.Helper()
	raw, err := os.ReadFile(name)
	if err != nil {
		t.Fatal(err)
	}
	zr, err := gzip.NewReader(bytes.NewReader(raw))
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	b, err := io.ReadAll(zr)
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	if err := json.Unmarshal(b, v); err != nil {
		t.Fatalf("%s: %v", name, err)
	}
}

type v2Caps struct {
	Schema int `json:"schema"`
	Clouds map[string]map[string]struct {
		File         string           `json:"file"`
		Capabilities []map[string]any `json:"capabilities"`
	} `json:"clouds"`
}

// L1-03: the capability index holds every capability of core/capabilities/{aws,gcp,azure}/*.json, with the same
// tier and mesh counts (1,444 / 86 / 16 at 42d870e; counted from the source files, so the test follows the registry).
func TestMCPCapsIndexMatchesRegistry(t *testing.T) {
	var caps v2Caps
	readGzJSON(t, "mcp_caps.json.gz", &caps)
	if caps.Schema != mcpMatrixSchema {
		t.Fatalf("caps schema %d", caps.Schema)
	}
	var wantN, wantTier, wantMesh, gotN, gotTier, gotMesh int
	for _, cloud := range mcpClouds {
		files, _ := filepath.Glob(filepath.Join("..", "..", "core", "capabilities", cloud, "*.json"))
		if len(files) == 0 {
			t.Fatalf("no capability files for %s", cloud)
		}
		for _, f := range files {
			var m map[string]json.RawMessage
			b, _ := os.ReadFile(f)
			if err := json.Unmarshal(b, &m); err != nil {
				t.Fatalf("%s: %v", f, err)
			}
			for id, raw := range m {
				if strings.HasPrefix(id, "$") {
					continue
				}
				var c struct {
					Tier string `json:"tier"`
					Mesh bool   `json:"mesh"`
				}
				_ = json.Unmarshal(raw, &c)
				wantN++
				if c.Tier != "" {
					wantTier++
				}
				if c.Mesh {
					wantMesh++
				}
			}
		}
		for stem, svc := range caps.Clouds[cloud] {
			if svc.File != "core/capabilities/"+cloud+"/"+stem+".json" {
				t.Errorf("%s/%s: file %q", cloud, stem, svc.File)
			}
			for _, c := range svc.Capabilities {
				gotN++
				if c["tier"] != nil {
					gotTier++
				}
				if c["mesh"] == true {
					gotMesh++
				}
				lv, _ := c["level"].(map[string]any)
				if lv["nano"] == nil || lv["offline"] == nil || c["title"] == nil {
					t.Errorf("%s: missing title or level.nano/offline: %v", c["id"], c)
				}
			}
		}
	}
	if gotN != wantN || gotTier != wantTier || gotMesh != wantMesh {
		t.Errorf("caps index has %d capabilities (tier %d, mesh %d); core/capabilities has %d (tier %d, mesh %d)",
			gotN, gotTier, gotMesh, wantN, wantTier, wantMesh)
	}
	if wantN < 1444 || wantTier < 86 || wantMesh < 16 {
		t.Errorf("registry shrank below the 42d870e counts: %d / %d / %d", wantN, wantTier, wantMesh)
	}
}

type v2Docs struct {
	Schema int `json:"schema"`
	Clouds map[string]map[string]struct {
		Source string `json:"source"`
		Ops    int    `json:"ops"`
		APIs   []struct {
			ID   string `json:"id"`
			Pick []int  `json:"pick"`
			Ops  []struct {
				N string            `json:"n"`
				S map[string]string `json:"s"`
			} `json:"ops"`
		} `json:"apis"`
		Data []struct {
			U string `json:"u"`
		} `json:"data"`
	} `json:"clouds"`
}

// L1-04: every snippet is aimed at the {sim} placeholder, never at a hard-coded Nano or offline endpoint.
func TestMCPDocsSnippetsUsePlaceholder(t *testing.T) {
	var docs v2Docs
	readGzJSON(t, "mcp_docs.json.gz", &docs)
	hard := regexp.MustCompile(`127\.0\.0\.1:(8090|9000|9443)|localhost:(8090|9000)|\{EP\}`)
	nSnip := 0
	for cloud, svcs := range docs.Clouds {
		for stem, svc := range svcs {
			if svc.Source != "wasm/docs/"+cloud+"/"+stem+".json" {
				t.Errorf("%s/%s: source %q", cloud, stem, svc.Source)
			}
			for _, a := range svc.APIs {
				for _, p := range a.Pick {
					if p < 0 || p >= len(a.Ops) {
						t.Errorf("%s/%s/%s: pick %d out of range", cloud, stem, a.ID, p)
					}
				}
				for _, o := range a.Ops {
					for lang, text := range o.S {
						nSnip++
						if lang != "cli" && lang != "python" && lang != "javascript" && lang != "curl" {
							t.Errorf("%s/%s %s: unknown lang %q", cloud, stem, o.N, lang)
						}
						if !strings.Contains(text, "{sim}") {
							t.Errorf("%s/%s %s [%s]: no {sim} placeholder:\n%s", cloud, stem, o.N, lang, text)
						}
						if hard.MatchString(text) {
							t.Errorf("%s/%s %s [%s]: hard-coded endpoint:\n%s", cloud, stem, o.N, lang, text)
						}
					}
				}
			}
			for _, d := range svc.Data {
				if hard.MatchString(d.U) {
					t.Errorf("%s/%s data row with a hard-coded endpoint: %s", cloud, stem, d.U)
				}
			}
		}
	}
	if nSnip < 20000 {
		t.Errorf("only %d snippets; the docs index looks truncated", nSnip)
	}
}

// The matrix carries per-service levels{nano,offline} from the capability registry (plan K1 step 3) and the
// per-home wiring (step 4): offline == the legacy wiring, mesh == offline, nano from D0.
func TestMCPMatrixV2RollupsAndHomes(t *testing.T) {
	var m map[string]any
	if err := json.Unmarshal(mcpMatrixJSON, &m); err != nil {
		t.Fatal(err)
	}
	clouds := m["clouds"].(map[string]any)
	for _, cloud := range mcpClouds {
		c := clouds[cloud].(map[string]any)
		withLevels := 0
		for _, s := range c["services"].([]any) {
			if lv, ok := s.(map[string]any)["levels"].(map[string]any); ok && lv["nano"] != "" && lv["offline"] != "" {
				withLevels++
			}
		}
		if withLevels != len(c["services"].([]any)) {
			t.Errorf("%s: only %d of %d registry services have levels (capability_aliases missing?)", cloud, withLevels, len(c["services"].([]any)))
		}
		if len(c["v4_services"].([]any)) == 0 {
			t.Errorf("%s: no v4_services", cloud)
		}
	}
	homes := m["homes"].(map[string]any)
	off, _ := json.Marshal(homes["offline"].(map[string]any)["clouds"])
	mesh, _ := json.Marshal(homes["mesh"].(map[string]any)["clouds"])
	if string(off) != string(mesh) {
		t.Error("homes.mesh must equal homes.offline (plan K1 step 4)")
	}
	for _, cloud := range mcpClouds {
		legacy, _ := json.Marshal(clouds[cloud].(map[string]any)["wiring"])
		h, _ := json.Marshal(homes["offline"].(map[string]any)["clouds"].(map[string]any)[cloud])
		if string(legacy) != string(h) {
			t.Errorf("%s: legacy wiring must be the offline home", cloud)
		}
	}
	nano, _ := json.Marshal(homes["nano"])
	if strings.Contains(string(nano), "{tls_") {
		t.Errorf("homes.nano must not hand out TLS values: %s", nano)
	}
	for _, cloud := range mcpClouds {
		for _, v := range homes["nano"].(map[string]any)["clouds"].(map[string]any)[cloud].(map[string]any)["env"].([]any) {
			if _, ok := v.(map[string]any)["verified"].(bool); !ok {
				t.Errorf("nano %s %v: every Nano value says whether D0 verified it", cloud, v)
			}
		}
	}
}

// clearHomeEnv makes a test independent of the developer's VYOMI_* / RELAY_* environment.
func clearHomeEnv(t *testing.T) {
	t.Helper()
	for _, k := range []string{"VYOMI_ENDPOINT", "VYOMI_SIMULATOR_PORT", "CLOUDLEARN_SIMULATOR_PORT", "VYOMI_MESH_URL", "RELAY_PORT", "VYOMI_TARGET", "VYOMI_TUNNEL_BIN"} {
		t.Setenv(k, "")
	}
}

// L1-05: an id prefix without the cloud prefix finds the AKS cluster capability, flagged mesh-only.
func TestMCPCapabilityIDPrefix(t *testing.T) {
	s, _ := testMCPServer(t)
	res, isErr := callTool(t, s, "vyomi_capability", map[string]any{"query": "aks.cluster"})
	if isErr {
		t.Fatal(res["error"])
	}
	ms := res["matches"].([]any)
	if len(ms) == 0 {
		t.Fatalf("no matches: %v", res)
	}
	first := ms[0].(map[string]any)
	if first["id"] != "azure.aks.cluster.crud" || first["mesh"] != true || first["cloud"] != "azure" {
		t.Errorf("want azure.aks.cluster.crud with mesh:true first, got %v", first)
	}
	if !strings.Contains(first["needs"].(string), "mesh") {
		t.Errorf("mesh-only capability must say it needs a mesh: %v", first)
	}
	if lv := first["level"].(map[string]any); lv["nano"] == nil || lv["offline"] == nil {
		t.Errorf("level{nano,offline} missing: %v", first)
	}
}

// L1-06: title words, scoped to a cloud: S3 versioning first, at most 20 results.
func TestMCPCapabilityWords(t *testing.T) {
	s, _ := testMCPServer(t)
	res, isErr := callTool(t, s, "vyomi_capability", map[string]any{"query": "bucket versioning", "cloud": "aws"})
	if isErr {
		t.Fatal(res["error"])
	}
	ms := res["matches"].([]any)
	if len(ms) == 0 || len(ms) > capabilityMaxResults {
		t.Fatalf("want 1..20 matches, got %d", len(ms))
	}
	if id := ms[0].(map[string]any)["id"]; id != "s3.bucket.versioning" {
		t.Errorf("want s3.bucket.versioning first, got %v", id)
	}
	for _, m := range ms {
		if m.(map[string]any)["cloud"] != "aws" {
			t.Errorf("cloud filter leaked: %v", m)
		}
	}
	// A broad query is capped and says so.
	broad, _ := callTool(t, s, "vyomi_capability", map[string]any{"query": "s3"})
	if n := len(broad["matches"].([]any)); n != capabilityMaxResults || broad["truncated"] != true {
		t.Errorf("broad query: %d matches, truncated=%v", n, broad["truncated"])
	}
	// full before limited within one rank.
	prev := 4
	for _, m := range broad["matches"].([]any) {
		r := levelRank[m.(map[string]any)["level"].(map[string]any)["nano"].(string)]
		if r > prev {
			t.Errorf("results not ordered full before limited: %v", broad["matches"])
			break
		}
		prev = r
	}
	if _, isErr := callTool(t, s, "vyomi_capability", map[string]any{"query": ""}); !isErr {
		t.Error("empty query must be a tool error")
	}
	none, _ := callTool(t, s, "vyomi_capability", map[string]any{"query": "zzz-no-such-thing"})
	if none["total_matches"].(float64) != 0 || none["hint"] == nil {
		t.Errorf("no-match result needs a hint: %v", none)
	}
}

// L1-07: a snippet for Nano is aimed at the local tunnel and names its source.
func TestMCPSnippetNano(t *testing.T) {
	clearHomeEnv(t)
	s, _ := testMCPServer(t)
	res, isErr := callTool(t, s, "vyomi_snippet", map[string]any{"cloud": "aws", "service": "s3", "lang": "python", "home": "nano"})
	if isErr {
		t.Fatal(res["error"])
	}
	snip := res["snippet"].(string)
	if !strings.Contains(snip, `endpoint_url="http://127.0.0.1:8090"`) {
		t.Errorf("python snippet not aimed at the Nano tunnel:\n%s", snip)
	}
	if strings.Contains(snip, "{sim}") || strings.Contains(snip, ":9000") {
		t.Errorf("placeholder or offline endpoint left in:\n%s", snip)
	}
	if res["source"] != "wasm/docs/aws/s3.json" || res["home"] != homeNanoLocal {
		t.Errorf("source/home: %v / %v", res["source"], res["home"])
	}
	if res["op"] != "CreateBucket" {
		t.Errorf("default op should be the registry's first known action (CreateBucket), got %v", res["op"])
	}
	// explicit op by any of its names, other langs, other clouds, offline home.
	for _, tc := range []struct {
		args map[string]any
		want []string
	}{
		{map[string]any{"cloud": "aws", "service": "s3", "op": "put-object", "lang": "cli", "home": "nano"}, []string{"aws --endpoint-url http://127.0.0.1:8090 s3api put-object"}},
		{map[string]any{"cloud": "aws", "service": "dynamodb", "op": "put_item", "lang": "javascript", "home": "offline"}, []string{`endpoint: "http://127.0.0.1:9000"`, "PutItemCommand"}},
		{map[string]any{"cloud": "gcp", "service": "storage", "lang": "curl", "home": "nano"}, []string{"http://127.0.0.1:8090/storage/v1/"}},
		{map[string]any{"cloud": "azure", "service": "storage", "lang": "cli", "home": "nano"}, []string{"http://127.0.0.1:8090/subscriptions/"}},
	} {
		r, isErr := callTool(t, s, "vyomi_snippet", tc.args)
		if isErr {
			t.Errorf("%v: %v", tc.args, r["error"])
			continue
		}
		for _, w := range tc.want {
			if !strings.Contains(r["snippet"].(string), w) {
				t.Errorf("%v: missing %q in\n%s", tc.args, w, r["snippet"])
			}
		}
	}
	for _, bad := range []map[string]any{
		{"cloud": "aws", "service": "nosuch", "lang": "python"},
		{"cloud": "aws", "service": "s3", "op": "NoSuchOp"},
		{"cloud": "aws", "service": "s3", "lang": "cobol"},
		{"cloud": "aws", "service": "s3", "home": "moon"},
	} {
		if r, isErr := callTool(t, s, "vyomi_snippet", bad); !isErr {
			t.Errorf("%v must be a tool error, got %v", bad, r)
		}
	}
	// The cloud relay URL (Nano without the tunnel) keeps its session path.
	t.Setenv("VYOMI_ENDPOINT", "https://relay.vyomi.cloud/abc123")
	r, _ := callTool(t, s, "vyomi_snippet", map[string]any{"cloud": "aws", "service": "s3", "lang": "cli", "home": "nano"})
	if r["home"] != homeNanoCloud || !strings.Contains(r["snippet"].(string), "--endpoint-url https://relay.vyomi.cloud/abc123 ") {
		t.Errorf("relay URL not used: %v\n%s", r["home"], r["snippet"])
	}
}

// L1-08: every service vyomi_services returns carries levels.nano and levels.offline.
func TestMCPServicesLevels(t *testing.T) {
	clearHomeEnv(t)
	t.Setenv("VYOMI_ENDPOINT", "http://127.0.0.1:1")
	s, _ := testMCPServer(t)
	res, isErr := callTool(t, s, "vyomi_services", map[string]any{"cloud": "gcp", "live": false})
	if isErr {
		t.Fatal(res["error"])
	}
	gcp := res["clouds"].(map[string]any)["gcp"].(map[string]any)
	for _, key := range []string{"services", "v4_services"} {
		list := gcp[key].([]any)
		if len(list) == 0 {
			t.Fatalf("no gcp %s", key)
		}
		for _, sv := range list {
			m := sv.(map[string]any)
			lv, _ := m["levels"].(map[string]any)
			if lv["nano"] == nil || lv["nano"] == "" || lv["offline"] == nil || lv["offline"] == "" {
				t.Errorf("gcp %s %v: missing levels.nano/offline", key, m["id"])
			}
		}
	}
	all, _ := callTool(t, s, "vyomi_services", map[string]any{"live": false})
	aks := false
	for _, sv := range all["clouds"].(map[string]any)["azure"].(map[string]any)["v4_services"].([]any) {
		if m := sv.(map[string]any); m["id"] == "aks" {
			aks = m["mesh"] == true
		}
	}
	if !aks {
		t.Error("azure aks must be listed as a v4 service with mesh:true")
	}
}

// L1-09: the server instructions never send a Nano user to `vyomi up`.
func TestMCPInstructionsNoVyomiUpForNano(t *testing.T) {
	if !strings.Contains(mcpInstructions, "Never tell a Nano user to run `vyomi up`") {
		t.Error("instructions must forbid telling Nano users to run `vyomi up`")
	}
	for _, sent := range regexp.MustCompile(`[.!?]\s`).Split(mcpInstructions, -1) {
		if strings.Contains(sent, "vyomi up") && !strings.Contains(sent, "Never") && !strings.Contains(sent, "only") {
			t.Errorf("unconditional `vyomi up` advice in the instructions: %q", sent)
		}
	}
	for _, w := range []string{"Nano", "mesh", "vyomi_capability", "vyomi_snippet", "8090"} {
		if !strings.Contains(mcpInstructions, w) {
			t.Errorf("instructions should mention %s", w)
		}
	}
}

// Regression: wasm/docs names AWS CLI commands after botocore's serviceId (secrets-manager, cloudwatch-logs, s3);
// the MCP must hand out the real command words (secretsmanager, logs, s3api).
func TestMCPSnippetAWSCLICommandNames(t *testing.T) {
	clearHomeEnv(t)
	s, _ := testMCPServer(t)
	for _, tc := range []struct{ service, op, want string }{
		{"s3", "PutObject", "aws --endpoint-url http://127.0.0.1:8090 s3api put-object"},
		{"secretsmanager", "CreateSecret", "aws --endpoint-url http://127.0.0.1:8090 secretsmanager create-secret"},
		{"cloudwatch", "CreateLogGroup", "aws --endpoint-url http://127.0.0.1:8090 logs create-log-group"},
		{"states", "CreateStateMachine", "aws --endpoint-url http://127.0.0.1:8090 stepfunctions create-state-machine"},
	} {
		r, isErr := callTool(t, s, "vyomi_snippet", map[string]any{"cloud": "aws", "service": tc.service, "op": tc.op, "lang": "cli", "home": "nano"})
		if isErr {
			t.Errorf("%s %s: %v", tc.service, tc.op, r["error"])
			continue
		}
		if !strings.Contains(r["snippet"].(string), tc.want) {
			t.Errorf("%s %s: want %q in\n%s", tc.service, tc.op, tc.want, r["snippet"])
		}
	}
	var docs v2Docs
	readGzJSON(t, "mcp_docs.json.gz", &docs)
	bad := regexp.MustCompile(`aws --endpoint-url \{sim\} (s3|secrets-manager|api-gateway|cloudwatch-logs|elastic-load-balancing(-v2)?|sfn|s3-control|dynamodb-streams|auto-scaling|eventbridge|cost-explorer|database-migration-service) `)
	for stem, svc := range docs.Clouds["aws"] {
		for _, a := range svc.APIs {
			for _, o := range a.Ops {
				if m := bad.FindString(o.S["cli"]); m != "" {
					t.Errorf("aws/%s %s: serviceId used as the CLI command: %q", stem, o.N, m)
				}
			}
		}
	}
}

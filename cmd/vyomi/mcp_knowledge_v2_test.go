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
		if withLevels < len(c["services"].([]any))-1 {
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

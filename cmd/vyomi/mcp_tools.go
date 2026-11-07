package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

type mcpTool struct {
	Name        string
	Title       string
	Description string
	Schema      map[string]any
	ReadOnly    bool
	Destructive bool
	OpenWorld   bool
	handler     func(json.RawMessage) (any, error)
}

func (t *mcpTool) describe() map[string]any {
	return map[string]any{
		"name":        t.Name,
		"title":       t.Title,
		"description": t.Description,
		"inputSchema": t.Schema,
		"annotations": map[string]any{
			"title":           t.Title,
			"readOnlyHint":    t.ReadOnly,
			"destructiveHint": t.Destructive,
			"idempotentHint":  t.ReadOnly,
			"openWorldHint":   t.OpenWorld,
		},
	}
}

func (t *mcpTool) run(args json.RawMessage) (any, error) { return t.handler(args) }

func obj(props map[string]any, required ...string) map[string]any {
	s := map[string]any{"type": "object", "properties": props, "additionalProperties": false}
	if len(required) > 0 {
		s["required"] = required
	}
	return s
}

var (
	cloudEnum  = map[string]any{"type": "string", "enum": []string{"aws", "gcp", "azure"}}
	hostProp   = map[string]any{"type": "string", "description": "Simulator host (or host:port) as seen from where the code runs, e.g. a Multipass VM IP. Defaults to VYOMI_ENDPOINT or 127.0.0.1:9000."}
	accountArg = map[string]any{"type": "string", "description": "Azure storage/Cosmos account name (default devstoreaccount1)."}
)

func (s *mcpServer) buildTools() []*mcpTool {
	return []*mcpTool{
		{
			Name:        "vyomi_status",
			Title:       "Vyomi simulator status",
			Description: "Is the local Vyomi simulator running? Returns the endpoint, license tier (trial/expiry), active space, backend readiness and substrate (docker or multipass). Call this first.",
			Schema:      obj(map[string]any{}),
			ReadOnly:    true,
			handler:     s.toolStatus,
		},
		{
			Name:        "vyomi_services",
			Title:       "Services Vyomi emulates",
			Description: "Which AWS / GCP / Azure services Vyomi emulates (released services, first version), supported API actions, data plane and per-SDK support. Works offline; adds live pack state when the simulator is running.",
			Schema: obj(map[string]any{
				"cloud": cloudEnum,
				"live":  map[string]any{"type": "boolean", "description": "Merge live state from the running simulator (default true)."},
			}),
			ReadOnly: true,
			handler:  s.toolServices,
		},
		{
			Name:        "vyomi_env",
			Title:       "Env vars and SDK config for Vyomi",
			Description: "Exact environment variables, SDK client settings and Terraform provider block that point code for one cloud at Vyomi, plus the gotchas (TLS-only data planes, separate emulators, unsupported transports).",
			Schema: obj(map[string]any{
				"cloud":   cloudEnum,
				"lang":    map[string]any{"type": "string", "enum": []string{"python", "nodejs", "java", "go", "cli", "terraform"}, "description": "Only return config for this SDK / tool."},
				"format":  map[string]any{"type": "string", "enum": []string{"dotenv", "shell", "powershell"}, "description": "Format of env_text (default dotenv)."},
				"host":    hostProp,
				"account": accountArg,
			}, "cloud"),
			ReadOnly: true,
			handler:  s.toolEnv,
		},
		{
			Name:        "vyomi_scan_repo",
			Title:       "Scan a repo for Vyomi compatibility",
			Description: "Scans a local project (SDK imports, dependency files, Terraform) for AWS / GCP / Azure usage and reports, per service, whether Vyomi emulates it, where it is used, warnings, and whether endpoint overrides already exist. Read-only.",
			Schema: obj(map[string]any{
				"path":      map[string]any{"type": "string", "description": "Absolute path of the project directory."},
				"max_files": map[string]any{"type": "integer", "minimum": 1, "maximum": 50000, "description": "Stop after this many files (default 5000)."},
			}, "path"),
			ReadOnly: true,
			handler:  s.toolScanRepo,
		},
		{
			Name:        "vyomi_write_env",
			Title:       "Write .env.vyomi",
			Description: "Writes a .env.vyomi file with the Vyomi env vars for the given clouds into a project directory. Never overwrites an existing file unless overwrite=true. Ask the user before calling.",
			Schema: obj(map[string]any{
				"path":      map[string]any{"type": "string", "description": "Absolute path of the project directory."},
				"clouds":    map[string]any{"type": "array", "items": cloudEnum, "minItems": 1, "description": "Clouds to include (e.g. from vyomi_scan_repo)."},
				"filename":  map[string]any{"type": "string", "description": "File name (default .env.vyomi). No directories."},
				"overwrite": map[string]any{"type": "boolean", "description": "Replace an existing file (default false)."},
				"host":      hostProp,
				"account":   accountArg,
			}, "path", "clouds"),
			handler: s.toolWriteEnv,
		},
	}
}

func decodeArgs(raw json.RawMessage, v any) error {
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil && !errors.Is(err, io.EOF) {
		return fmt.Errorf("invalid arguments: %v", err)
	}
	return nil
}

func validCloud(c string) bool {
	for _, x := range mcpClouds {
		if x == c {
			return true
		}
	}
	return false
}

// getJSON GETs base+path and decodes a JSON object.
func (s *mcpServer) getJSON(base, path string) (map[string]any, error) {
	resp, err := s.client.Get(strings.TrimRight(base, "/") + path)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("%s: HTTP %d", path, resp.StatusCode)
	}
	var out map[string]any
	if err := json.NewDecoder(io.LimitReader(resp.Body, 4<<20)).Decode(&out); err != nil {
		return nil, fmt.Errorf("%s: %v", path, err)
	}
	return out, nil
}

// Only these /api/license/status fields reach the model: the raw `license`
// block can carry tokens and claims, so it is never passed through.
var licenseFields = []string{
	"active_tier", "primary_cloud", "period", "seats", "expires_at", "days_until_expiry",
	"in_grace_period", "sub_expires_at", "days_until_sub_expiry", "sub_expired",
	"cancel_at_period_end", "trial",
}

func pick(m map[string]any, keys []string) map[string]any {
	out := map[string]any{}
	for _, k := range keys {
		if v, ok := m[k]; ok {
			out[k] = v
		}
	}
	return out
}

func (s *mcpServer) toolStatus(raw json.RawMessage) (any, error) {
	var a struct{}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	t := s.target(nil)
	base := t.simURL()
	out := map[string]any{
		"endpoint":                    base,
		"tls_endpoint":                fmt.Sprintf("https://%s:%d", t.Host, t.TLSPort),
		"substrate":                   s.cfg.resolveSubstrate(),
		"appliance_knowledge_version": s.version,
	}
	health, err := s.getJSON(base, "/healthz")
	if err != nil {
		out["running"] = false
		out["error"] = err.Error()
		out["hint"] = "The simulator is not reachable at " + base + ". Start it with `vyomi up`, or set VYOMI_ENDPOINT if it runs elsewhere (e.g. the Multipass VM IP on the Max tier). vyomi_services / vyomi_env / vyomi_scan_repo still work offline."
		return out, nil
	}
	out["running"] = true
	out["health"] = health
	if lic, err := s.getJSON(base, "/api/license/status"); err == nil {
		out["license"] = pick(lic, licenseFields)
	}
	if rd, err := s.getJSON(base, "/api/runtime/readiness"); err == nil {
		r := pick(rd, []string{"ready_count", "total_count", "overall_pct"})
		r["meaning"] = "Backends (databases, emulators, brokers) the simulator can reach right now, weighted by image size. Not a tier limit. Low values usually mean heavy backends that start lazily on first use (Docker tiers) or are still starting; if containers are up but stay unreachable, the stack is split across Docker networks or another stack holds the ports - suggest `docker ps` and restarting a single stack."
		out["readiness"] = r
	}
	if sp, err := s.getJSON(base, "/api/spaces/active"); err == nil {
		out["active_space"] = summarizeSpace(sp)
	}
	return out, nil
}

// summarizeSpace keeps what an agent needs from /api/spaces/active (the raw
// payload is ~150 lines of mostly-empty per-service state).
func summarizeSpace(sp map[string]any) map[string]any {
	space, _ := sp["space"].(map[string]any)
	if space == nil {
		space = sp
	}
	out := pick(space, []string{"space_id", "name", "provider", "active_region", "active_account", "status", "expires_at", "ttl_remaining_seconds"})
	if id, ok := sp["active_space_id"]; ok {
		out["space_id"] = id
	}
	if cs, ok := space["cloudsim"].(map[string]any); ok {
		if sum, ok := cs["summary"].(map[string]any); ok {
			counts := map[string]any{}
			for k, v := range sum {
				if n, ok := v.(float64); ok && n > 0 && k != "total_resource_count" {
					counts[strings.TrimSuffix(k, "_count")] = n
				}
			}
			out["total_resources"] = sum["total_resource_count"]
			out["resources"] = counts
		}
	}
	return out
}

func (s *mcpServer) toolServices(raw json.RawMessage) (any, error) {
	var a struct {
		Cloud string `json:"cloud"`
		Live  *bool  `json:"live"`
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	clouds := mcpClouds
	if a.Cloud != "" {
		if !validCloud(a.Cloud) {
			return nil, fmt.Errorf("unknown cloud %q (want aws, gcp or azure)", a.Cloud)
		}
		clouds = []string{a.Cloud}
	}
	live := a.Live == nil || *a.Live
	base := s.target(nil).simURL()
	reachable := live && func() bool { _, err := s.getJSON(base, "/healthz"); return err == nil }()

	result := map[string]any{
		"appliance_knowledge_version": s.version,
		"status_legend": map[string]string{
			"released": "Shipped and covered by the conformance suite (services/registry.json, the list vyomi.cloud publishes). released_in = first version.",
		},
		"live": reachable,
	}
	out := map[string]any{}
	for _, cloud := range clouds {
		c := s.matrix.Clouds[cloud]
		tools := map[string]any{}
		for _, lang := range sortedKeys(c.Tools) {
			var tr map[string]any
			_ = json.Unmarshal(c.Tools[lang], &tr)
			tools[lang] = pick(tr, []string{"tool", "status", "dependency", "notes"})
		}
		entry := map[string]any{
			"display_name":  c.DisplayName,
			"services":      c.Services,
			"status_counts": statusCounts(c.Services),
			"sdk_support":   tools,
		}
		if reachable {
			if lm, err := s.getJSON(base, "/api/providers/"+cloud+"/matrix"); err == nil {
				entry["live_service_counts"] = lm["service_counts"]
				var active []string
				if packs, ok := lm["packs"].(map[string]any); ok {
					for _, group := range []string{"service", "runtime"} {
						list, _ := packs[group].([]any)
						for _, p := range list {
							if pm, ok := p.(map[string]any); ok && pm["active"] == true {
								if id, ok := pm["id"].(string); ok {
									active = append(active, id)
								}
							}
						}
					}
				}
				entry["live_active_packs"] = active
			}
		}
		out[cloud] = entry
	}
	result["clouds"] = out
	return result, nil
}

func (s *mcpServer) toolEnv(raw json.RawMessage) (any, error) {
	var a struct {
		Cloud  string `json:"cloud"`
		Lang   string `json:"lang"`
		Format string `json:"format"`
		mcpTargetArgs
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	if !validCloud(a.Cloud) {
		return nil, fmt.Errorf("cloud is required: aws, gcp or azure")
	}
	t := s.target(&a.mcpTargetArgs)
	c := s.matrix.Clouds[a.Cloud]
	vars := s.envVars(a.Cloud, t)
	notes := make([]string, 0, len(c.Wiring.Notes))
	for _, n := range c.Wiring.Notes {
		notes = append(notes, t.render(n))
	}
	out := map[string]any{
		"cloud":     a.Cloud,
		"endpoint":  t.simURL(),
		"variables": vars,
		"env_text":  formatEnv(a.Cloud, vars, a.Format),
		"notes":     notes,
	}
	langs := sortedKeys(c.Tools)
	if a.Lang != "" && a.Lang != "terraform" {
		if _, ok := c.Tools[a.Lang]; !ok {
			return nil, fmt.Errorf("no %s config for %s (have %s)", a.Lang, a.Cloud, strings.Join(langs, ", "))
		}
		langs = []string{a.Lang}
	}
	if a.Lang != "terraform" {
		sdk := map[string]any{}
		for _, lang := range langs {
			var v any
			_ = json.Unmarshal([]byte(t.render(string(c.Tools[lang]))), &v)
			sdk[lang] = v
		}
		out["sdk"] = sdk
	}
	if a.Lang == "" || a.Lang == "terraform" {
		tf := map[string]any{"hcl": t.render(c.Wiring.Terraform)}
		if c.Wiring.TerraformNote != "" {
			tf["note"] = t.render(c.Wiring.TerraformNote)
		}
		out["terraform"] = tf
	}
	return out, nil
}

func (s *mcpServer) toolScanRepo(raw json.RawMessage) (any, error) {
	var a struct {
		Path     string `json:"path"`
		MaxFiles int    `json:"max_files"`
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	if a.MaxFiles <= 0 {
		a.MaxFiles = 5000
	}
	return s.scanRepo(a.Path, a.MaxFiles)
}

func (s *mcpServer) toolWriteEnv(raw json.RawMessage) (any, error) {
	var a struct {
		Path      string   `json:"path"`
		Clouds    []string `json:"clouds"`
		Filename  string   `json:"filename"`
		Overwrite bool     `json:"overwrite"`
		mcpTargetArgs
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	if a.Path == "" || !filepath.IsAbs(a.Path) {
		return nil, fmt.Errorf("path must be an absolute directory path")
	}
	if st, err := os.Stat(a.Path); err != nil || !st.IsDir() {
		return nil, fmt.Errorf("%s is not a directory", a.Path)
	}
	if len(a.Clouds) == 0 {
		return nil, fmt.Errorf("clouds is required (aws, gcp, azure)")
	}
	name := a.Filename
	if name == "" {
		name = ".env.vyomi"
	}
	if name != filepath.Base(name) || name == "." || name == ".." {
		return nil, fmt.Errorf("filename must be a plain file name, got %q", a.Filename)
	}
	dest := filepath.Join(a.Path, name)
	if _, err := os.Lstat(dest); err == nil && !a.Overwrite {
		return nil, fmt.Errorf("%s already exists; pass overwrite=true to replace it", dest)
	}
	t := s.target(&a.mcpTargetArgs)
	var b strings.Builder
	fmt.Fprintf(&b, "# Generated by `vyomi mcp` (appliance v%s). Local development only:\n", s.version)
	fmt.Fprintf(&b, "# points cloud SDKs at the Vyomi simulator (%s). Dummy credentials only.\n\n", t.simURL())
	seen := map[string]bool{}
	for _, c := range a.Clouds {
		if !validCloud(c) {
			return nil, fmt.Errorf("unknown cloud %q", c)
		}
		if seen[c] {
			continue
		}
		seen[c] = true
		b.WriteString(formatEnv(c, s.envVars(c, t), "dotenv"))
		b.WriteString("\n")
	}
	if err := os.WriteFile(dest, []byte(b.String()), 0o644); err != nil {
		return nil, err
	}
	return map[string]any{
		"written": dest,
		"content": b.String(),
		"next":    "Load it only for local runs (e.g. `set -a; . ./" + name + "; set +a`, docker compose --env-file, or your framework's dotenv loader). Keep production config untouched.",
	}, nil
}

// ── resources ────────────────────────────────────────────────────────────────

func (s *mcpServer) listResources() []map[string]any {
	res := []map[string]any{
		{"uri": "vyomi://settings", "name": "settings", "title": "Vyomi settings and ports", "mimeType": "application/json",
			"description": "VYOMI_* settings from .env.example and the host ports of the simulator and emulator containers."},
	}
	for _, c := range mcpClouds {
		dn := s.matrix.Clouds[c].DisplayName
		res = append(res,
			map[string]any{"uri": "vyomi://services/" + c, "name": "services-" + c, "title": dn + " services in Vyomi",
				"mimeType": "application/json", "description": "Emulated " + dn + " services, status, actions and data planes."},
			map[string]any{"uri": "vyomi://env/" + c, "name": "env-" + c, "title": dn + " env for Vyomi",
				"mimeType": "text/plain", "description": "dotenv block pointing " + dn + " SDKs at the local simulator."},
		)
	}
	return res
}

func (s *mcpServer) readResource(uri string) ([]map[string]any, error) {
	text := func(mime, body string) []map[string]any {
		return []map[string]any{{"uri": uri, "mimeType": mime, "text": body}}
	}
	switch {
	case uri == "vyomi://settings":
		b, _ := json.MarshalIndent(map[string]any{
			"appliance_version": s.version,
			"settings":          s.matrix.Settings,
			"host_ports":        s.matrix.HostPorts,
		}, "", "  ")
		return text("application/json", string(b)), nil
	case strings.HasPrefix(uri, "vyomi://services/"):
		c := strings.TrimPrefix(uri, "vyomi://services/")
		if !validCloud(c) {
			return nil, fmt.Errorf("unknown resource %s", uri)
		}
		b, _ := json.MarshalIndent(s.matrix.Clouds[c].Services, "", "  ")
		return text("application/json", string(b)), nil
	case strings.HasPrefix(uri, "vyomi://env/"):
		c := strings.TrimPrefix(uri, "vyomi://env/")
		if !validCloud(c) {
			return nil, fmt.Errorf("unknown resource %s", uri)
		}
		return text("text/plain", formatEnv(c, s.envVars(c, s.target(nil)), "dotenv")), nil
	}
	return nil, fmt.Errorf("unknown resource %s", uri)
}

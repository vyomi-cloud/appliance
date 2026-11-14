package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
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
	homeProp   = map[string]any{"type": "string", "enum": []string{"auto", "nano", "mesh", "offline"}, "description": "Which simulator home to target: nano (browser tab via vyomi-tunnel on 127.0.0.1:8090, or the relay URL in VYOMI_ENDPOINT), mesh (a Pro/Max mesh, VYOMI_MESH_URL), offline (the v4.0.0 / v3 appliance on :9000). Default auto: the home vyomi_status selects."}
	langProp   = map[string]any{"type": "string", "enum": snippetLangs, "description": "cli (aws / gcloud / az), python, javascript or curl. Default cli."}
	accountArg = map[string]any{"type": "string", "description": "Azure storage/Cosmos account name (default devstoreaccount1)."}
)

func (s *mcpServer) buildTools() []*mcpTool {
	return []*mcpTool{
		{
			Name:        "vyomi_status",
			Title:       "Vyomi simulator status",
			Description: "Where is the Vyomi simulator and is it running? Probes every home (Nano browser tab through vyomi-tunnel, local mesh, offline appliance, Codespace mesh) and returns homes[], the selected one and why, with its live state (tier, trial, lock, tab, forwards) and the next step when nothing usable is found. Call this first.",
			Schema:      obj(map[string]any{}),
			ReadOnly:    true,
			handler:     s.toolStatus,
		},
		{
			Name:        "vyomi_reach",
			Title:       "What can I connect to?",
			Description: "Lists what is reachable from this machine, in the shape of `vyomi-tunnel list --json`: the Nano API through the local tunnel, in-browser VMs and databases (ssh / db ports), the AMQP bridge, a local mesh API, and the Codespace mesh's hosts, instances, k3s, LLM and services with the command to connect to each. Read-only: never starts a forward.",
			Schema:      obj(map[string]any{"scope": map[string]any{"type": "string", "enum": []string{"nano", "mesh", "all"}, "description": "Default all."}}),
			ReadOnly:    true,
			handler:     s.toolReach,
		},
		{
			Name:        "vyomi_services",
			Title:       "Services Vyomi emulates",
			Description: "Which AWS / GCP / Azure services Vyomi emulates (released services, first version, plus the v4 services), with each service's level on Nano and offline/mesh (worst feature, and the spread), Pro tier and mesh-only flags, supported API actions, data plane and per-SDK support. Works offline; adds live pack state when the simulator is running. vyomi_capability answers per feature.",
			Schema: obj(map[string]any{
				"cloud": cloudEnum,
				"live":  map[string]any{"type": "boolean", "description": "Merge live state from the running simulator (default true)."},
				"home":  homeProp,
			}),
			ReadOnly: true,
			handler:  s.toolServices,
		},
		{
			Name:        "vyomi_capability",
			Title:       "Does Vyomi support a feature?",
			Description: "Searches the v4 capability registry (every console feature of AWS / GCP / Azure) by id prefix (s3.bucket, azure.aks.cluster) or title words (bucket versioning). Returns up to 20 matches with the level on Nano (browser) and offline/mesh (full, limited, config_only, not_simulated), limitations, Pro tier and mesh-only flags, and the conformance tests behind each claim. Works offline.",
			Schema: obj(map[string]any{
				"query": map[string]any{"type": "string", "description": "Capability id prefix or words from its title."},
				"cloud": cloudEnum,
			}, "query"),
			ReadOnly: true,
			handler:  s.toolCapability,
		},
		{
			Name:        "vyomi_snippet",
			Title:       "CLI / SDK example for a Vyomi operation",
			Description: "A ready-to-run CLI, Python, JavaScript or curl call for one service operation, pointed at the selected home's endpoint. Generated from the API docs the Nano console shows (only operations that really answer). Without op, picks a representative operation.",
			Schema: obj(map[string]any{
				"cloud":   cloudEnum,
				"service": map[string]any{"type": "string", "description": "Service id (e.g. s3, dynamodb, pubsub, storage, cosmos); vyomi_services lists them."},
				"op":      map[string]any{"type": "string", "description": "Operation name (PutObject, put_object, put-object, storage.buckets.insert). Default: a representative operation."},
				"lang":    langProp,
				"home":    homeProp,
			}, "cloud", "service"),
			ReadOnly: true,
			handler:  s.toolSnippet,
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
				"home":    homeProp,
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
				"home":      homeProp,
			}, "path"),
			ReadOnly: true,
			handler:  s.toolScanRepo,
		},
		{
			Name:        "vyomi_write_env",
			Title:       "Write .env.vyomi",
			Description: "Writes a .env.vyomi file with the Vyomi env vars for the given clouds into a project directory. Never overwrites an existing file unless overwrite=true. Call ONLY after the user explicitly approved this exact file: show them the path and the contents (from vyomi_env) first and wait for their yes. A general request such as 'set this project up' is not approval.",
			Schema: obj(map[string]any{
				"path":      map[string]any{"type": "string", "description": "Absolute path of the project directory."},
				"clouds":    map[string]any{"type": "array", "items": cloudEnum, "minItems": 1, "description": "Clouds to include (e.g. from vyomi_scan_repo)."},
				"filename":  map[string]any{"type": "string", "description": "File name starting with .env.vyomi (default .env.vyomi). No directories."},
				"overwrite": map[string]any{"type": "boolean", "description": "Replace an existing file (default false)."},
				"host":      hostProp,
				"account":   accountArg,
				"home":      homeProp,
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
	p := s.homes()
	var selected any
	if p.Selected != nil {
		selected = p.Selected.ID
	}
	out := map[string]any{
		"homes":                       p.Homes,
		"selected":                    selected,
		"why":                         p.Why,
		"substrate":                   s.cfg.resolveSubstrate(),
		"appliance_knowledge_version": s.version,
	}
	h := p.Selected
	if h != nil && h.Endpoint != "" {
		out["endpoint"] = h.Endpoint
		if h.TLSEndpoint != "" {
			out["tls_endpoint"] = h.TLSEndpoint
		}
	}
	if hint := s.homeHint(p); hint != "" {
		out["hint"] = hint
	}
	switch {
	case h == nil:
		return out, nil
	case h.ID == homeOffline:
		// 3.0.46-era fields, exactly as before: endpoint, tls_endpoint, running, health, license, readiness, active_space.
		t := s.target(nil)
		out["endpoint"] = t.simURL()
		out["tls_endpoint"] = fmt.Sprintf("https://%s:%d", t.Host, t.TLSPort)
		s.applianceState(out, t.simURL(), false)
	case h.ID == homeMeshLocal || (h.ID == homeMeshCodespace && h.Serving):
		out["mesh"] = h.Detail
		if h.Serving {
			s.applianceState(out, h.Endpoint, true)
		}
	case h.ID == homeNanoLocal:
		out["nano"] = h.Detail
		out["running"] = h.Serving
	case h.ID == homeNanoCloud:
		out["running"] = h.Reachable
	case h.ID == homeMeshCodespace:
		out["mesh"] = h.Detail
		out["running"] = false
	}
	return out, nil
}

// applianceState adds the live /api/* state of a :9000-style appliance (offline or mesh): health, licence,
// backend readiness, active space. On a mesh it also reads the spaces and warns when one cloud has several
// (spec Q4, see spacesWarning).
func (s *mcpServer) applianceState(out map[string]any, base string, mesh bool) {
	health, err := s.getJSON(base, "/healthz")
	if err != nil {
		out["running"] = false
		out["error"] = err.Error()
		if !mesh {
			out["hint"] = "The simulator is not reachable at " + base + ". Start it with `vyomi up`, or set VYOMI_ENDPOINT if it runs elsewhere (e.g. the Multipass VM IP on the Max tier). vyomi_services / vyomi_env / vyomi_scan_repo still work offline."
		}
		return
	}
	out["running"] = true
	out["health"] = health
	if lic, err := s.getJSON(base, "/api/license/status"); err == nil {
		out["license"] = pick(lic, licenseFields)
	}
	if rd, err := s.getJSON(base, "/api/runtime/readiness"); err == nil {
		r := pick(rd, []string{"ready_count", "total_count", "overall_pct"})
		var down []string
		if svcs, ok := rd["services"].([]any); ok {
			for _, sv := range svcs {
				if m, ok := sv.(map[string]any); ok && m["status"] != "ready" {
					if name, ok := m["name"].(string); ok {
						down = append(down, name)
					}
				}
			}
		}
		r["not_reachable"] = down
		r["meaning"] = "Backends (databases, emulators, brokers) the simulator can reach now, out of a fixed list, weighted by image size. Not a tier limit, and a low number is usually fine: project-specific stacks run only the backends they need, and on Docker tiers heavy backends start lazily on first use. It only matters if a service the user calls depends on a backend listed in not_reachable."
		out["readiness"] = r
	}
	if sp, err := s.getJSON(base, "/api/spaces/active"); err == nil {
		out["active_space"] = summarizeSpace(sp)
	}
	if mesh {
		if spaces, active := s.meshSpaces(base); len(spaces) > 1 {
			if w := spacesWarning(spaces, active, base); w != "" {
				out["spaces_warning"] = w
			}
		}
	}
}

// meshSpace is one entry of a mesh's /api/spaces, in the mesh's order (oldest first).
type meshSpace struct{ ID, Name, Cloud string }

// meshSpaces reads /api/spaces: the spaces (an absent provider is aws, as on the appliance) and the active id.
func (s *mcpServer) meshSpaces(base string) ([]meshSpace, string) {
	resp, err := s.client.Get(strings.TrimRight(base, "/") + "/api/spaces")
	if err != nil {
		return nil, ""
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return nil, ""
	}
	var v any
	if json.NewDecoder(io.LimitReader(resp.Body, 4<<20)).Decode(&v) != nil {
		return nil, ""
	}
	var list []any
	active := ""
	switch x := v.(type) {
	case []any:
		list = x
	case map[string]any:
		active, _ = x["active_space_id"].(string)
		switch sp := x["spaces"].(type) {
		case []any:
			list = sp
		case map[string]any:
			for _, e := range sp {
				list = append(list, e)
			}
		}
	}
	out := make([]meshSpace, 0, len(list))
	for _, e := range list {
		m, _ := e.(map[string]any)
		sp := meshSpace{Cloud: "aws"}
		if m != nil {
			sp.ID, _ = m["space_id"].(string)
			sp.Name, _ = m["name"].(string)
			if c, _ := m["provider"].(string); strings.TrimSpace(c) != "" {
				sp.Cloud = strings.ToLower(strings.TrimSpace(c))
			}
		}
		out = append(out, sp)
	}
	return out, active
}

// spacesWarning (spec Q4, D0 item 4 verified on a local mesh): a call for cloud X lands in the mesh's own active
// space when that space is an X space, otherwise in the first X space. Nothing in the request picks the space, and
// the Nano console's space switch does not reach the mesh. One space per cloud (a fresh mesh has aws-, gcp- and
// azure-default) is therefore unambiguous: warn only when some cloud has more than one space.
func spacesWarning(spaces []meshSpace, active string, base string) string {
	byCloud := map[string][]meshSpace{}
	var clouds []string
	activeCloud, activeName := "", ""
	for _, sp := range spaces {
		if _, ok := byCloud[sp.Cloud]; !ok {
			clouds = append(clouds, sp.Cloud)
		}
		byCloud[sp.Cloud] = append(byCloud[sp.Cloud], sp)
		if sp.ID != "" && sp.ID == active {
			activeCloud, activeName = sp.Cloud, firstNonEmpty(sp.Name, sp.ID)
		}
	}
	var shared []string
	for _, c := range clouds {
		if n := len(byCloud[c]); n > 1 {
			shared = append(shared, fmt.Sprintf("%d %s", n, c))
		}
	}
	if len(shared) == 0 {
		return ""
	}
	sort.Strings(clouds)
	var lands []string
	for _, c := range clouds {
		where := firstNonEmpty(byCloud[c][0].Name, byCloud[c][0].ID)
		if c == activeCloud {
			where = activeName + " (the active space)"
		}
		lands = append(lands, c+" -> "+where)
	}
	return fmt.Sprintf("This mesh hosts %d spaces (%s). Direct SDK and CLI calls to %s go to ONE space per cloud: the mesh's own active space for its cloud, otherwise that cloud's first space. Now: %s. "+
		"Switching spaces in the Nano console does not change this; only POST %s/api/spaces/<space_id>/switch on the mesh does. Ask the user which space they mean before creating resources.",
		len(spaces), strings.Join(shared, ", "), base, strings.Join(lands, "; "), strings.TrimRight(base, "/"))
}

// Hints by home (spec decision 8). `vyomi up` appears only for the offline appliance and a local mesh.
const (
	hintNanoOpenTab   = "Open https://vyomi.cloud/nano and keep the tab open; the tunnel is running."
	hintNanoOnboard   = "No Vyomi simulator found. For Nano (the browser simulator, Free and up): `brew install vyomi-cloud/tap/vyomi-tunnel` (or `npm i -g vyomi-tunnel`), save your access key to ~/.vyomi/credentials, run `vyomi-tunnel`, and open https://vyomi.cloud/nano; or copy the cloud relay URL from the Nano footer into VYOMI_ENDPOINT. If the simulator runs on another machine, set VYOMI_ENDPOINT to it. vyomi_services / vyomi_capability / vyomi_env / vyomi_scan_repo still work without it."
	hintNanoTunnelOff = "vyomi-tunnel is installed but not running: run `vyomi-tunnel` and open https://vyomi.cloud/nano (keep the tab open); or copy the cloud relay URL from the Nano footer into VYOMI_ENDPOINT."
	hintMeshLocked    = "Mesh is locked (trial or subscription ended). Browser-homed spaces still work. Renew, or use a Nano space."
	hintAmbiguous     = "Several Vyomi homes are reachable. Ask the user which space they are working in: the one in the browser (Nano) or the mesh / appliance. Then pass home=nano | mesh | offline to vyomi_env, vyomi_scan_repo and vyomi_write_env (or set VYOMI_TARGET)."
	hintRelayDown     = "The Nano relay URL in VYOMI_ENDPOINT did not answer. Check that the Nano tab is open and copy the current URL from the Nano footer (relay sessions are short-lived), or run `vyomi-tunnel` for the local tunnel."
)

func anyServing(p *homeProbe) bool {
	for _, h := range p.Homes {
		if h.Serving {
			return true
		}
	}
	return false
}

// codespaceLockedText says why a Codespace mesh refuses requests and what the user can do.
func codespaceLockedText(h *home) string {
	if h.Detail["session"] == "none" {
		return "The Codespace mesh refuses requests: it has no valid Mesh session (a Codespace created by hand, outside the Vyomi dashboard, gets none; a session also ends after its time limit). Ask the user to start Mesh from the Vyomi dashboard. Nano and the offline appliance are not affected."
	}
	return hintMeshLocked
}

func (s *mcpServer) homeHint(p *homeProbe) string {
	h := p.Selected
	if h == nil {
		if strings.HasPrefix(p.Why, "several") {
			return hintAmbiguous
		}
		if cs := p.find(homeMeshCodespace); cs != nil && cs.Detail["locked"] == true && !anyServing(p) {
			return codespaceLockedText(cs)
		}
		if n := p.find(homeNanoLocal); n != nil && n.Reachable { // several reachable, none serving
			return hintNanoOpenTab
		}
		if tunnelBin() != "" {
			return hintNanoTunnelOff
		}
		return hintNanoOnboard
	}
	switch h.ID {
	case homeNanoLocal:
		if !h.Reachable {
			if tunnelBin() != "" {
				return hintNanoTunnelOff
			}
			return hintNanoOnboard
		}
		if !h.Serving {
			return hintNanoOpenTab
		}
	case homeNanoCloud:
		if !h.Reachable {
			return hintRelayDown
		}
	case homeMeshLocal, homeMeshCodespace:
		if h.ID == homeMeshCodespace && h.Detail["locked"] == true {
			return codespaceLockedText(h)
		}
		if h.Detail["locked"] == true {
			return hintMeshLocked
		}
		if h.ID == homeMeshCodespace && !h.Serving {
			fwd, _ := h.Detail["forward_command"].(string)
			return "Ask the user to run `" + fwd + "` in another terminal and keep it open (do not run it yourself); then call vyomi_status again."
		}
		if h.ID == homeMeshLocal && !h.Reachable {
			return "No mesh answered at " + meshURL() + ". Start the local mesh with `vyomi up` (Pro/Max), or set VYOMI_MESH_URL if it runs elsewhere."
		}
	case homeOffline:
		// applianceState sets today's hint when the appliance does not answer.
	}
	return ""
}

// ── vyomi_reach ──────────────────────────────────────────────────────────────

// toolReach lists what the user can connect to, in the shape of `vyomi-tunnel list --json` rows
// ({where, name, type, address, connect}). Built from the (cached) home probes: it never starts a forward,
// a tunnel or anything else (spec decision 6).
func (s *mcpServer) toolReach(raw json.RawMessage) (any, error) {
	var a struct {
		Scope string `json:"scope"`
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	if a.Scope == "" {
		a.Scope = "all"
	}
	if a.Scope != "nano" && a.Scope != "mesh" && a.Scope != "all" {
		return nil, fmt.Errorf("scope must be nano, mesh or all")
	}
	p := s.homes()
	rows := []map[string]any{}
	notes := []string{}
	row := func(where, name, typ, address, connect string) {
		rows = append(rows, map[string]any{"where": where, "name": name, "type": typ, "address": address, "connect": connect})
	}
	if a.Scope != "mesh" {
		if n := p.find(homeNanoLocal); n != nil && n.Reachable {
			tab := "tab connected"
			if !n.Serving {
				tab = "tab NOT connected: open https://vyomi.cloud/nano"
			}
			row("local", "nano-api", "api", n.Endpoint, "aws --endpoint-url "+n.Endpoint+" ...   ("+tab+")")
			if feats, _ := n.Detail["features"].([]any); containsAny(feats, "amqp") {
				row("local", "nano-amqp", "amqp", "127.0.0.1:5672", "Service Bus SDK: Endpoint=sb://127.0.0.1;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true; (tunnel default port)")
			}
			for _, v := range asMaps(n.Detail["vms"]) {
				hp := fmt.Sprint(v["host_port"])
				row("browser", fmt.Sprint(v["vm"]), "vm", "127.0.0.1:"+hp, "ssh -p "+hp+" user@127.0.0.1")
			}
			for _, d := range asMaps(n.Detail["dbs"]) {
				hp := fmt.Sprint(d["host_port"])
				row("browser", fmt.Sprint(d["db"]), "db", "127.0.0.1:"+hp, fmt.Sprint(d["engine"])+" client -> 127.0.0.1:"+hp)
			}
		} else {
			notes = append(notes, fmt.Sprintf("local tunnel not running on :%d (run: vyomi-tunnel)", relayPort()))
		}
		if c := p.find(homeNanoCloud); c != nil {
			row("cloud", "nano-relay", "api", c.Endpoint, "aws --endpoint-url "+c.Endpoint+" ...")
		}
	}
	if a.Scope != "nano" {
		if m := p.find(homeMeshLocal); m != nil && m.Reachable {
			row("local", "mesh-api", "api", m.Endpoint, "aws --endpoint-url "+m.Endpoint+" ...   (TLS: "+m.TLSEndpoint+")")
		}
		cs := p.find(homeMeshCodespace)
		if cs != nil {
			for _, r := range asMaps(cs.Detail["targets"]) {
				row(fmt.Sprint(r["where"]), fmt.Sprint(r["name"]), fmt.Sprint(r["type"]), fmt.Sprint(r["address"]), fmt.Sprint(r["connect"]))
			}
			for _, n := range asStrings(cs.Detail["notes"]) {
				notes = append(notes, "mesh: "+n)
			}
			if n, _ := cs.Detail["note"].(string); n != "" {
				notes = append(notes, "mesh: "+n)
			}
			if cs.Reachable && !cs.Serving {
				fwd, _ := cs.Detail["forward_command"].(string)
				notes = append(notes, "No forward to the Codespace mesh API yet: ask the user to run `"+fwd+"` in another terminal (a free local port is chosen; never run forwards yourself).")
			}
		}
	}
	return map[string]any{"scope": a.Scope, "rows": rows, "notes": notes,
		"note": "Read-only. Commands in `connect` are for the user to run; forwards are long-running and stay in their own terminal."}, nil
}

func asMaps(v any) []map[string]any {
	var out []map[string]any
	switch x := v.(type) {
	case []map[string]any:
		return x
	case []any:
		for _, e := range x {
			if m, ok := e.(map[string]any); ok {
				out = append(out, m)
			}
		}
	}
	return out
}

func asStrings(v any) []string {
	switch x := v.(type) {
	case []string:
		return x
	case []any:
		var out []string
		for _, e := range x {
			out = append(out, fmt.Sprint(e))
		}
		return out
	}
	return nil
}

func containsAny(xs []any, want string) bool {
	for _, x := range xs {
		if x == want {
			return true
		}
	}
	return false
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
		Home  string `json:"home"`
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
			"v4":       "In the v4 capability registry (core/capabilities) but not in the v3 services list.",
		},
		"levels_legend": "levels{nano,offline}: the WORST level among the service's features (full > limited > config_only > not_simulated); level_counts shows the spread. nano = the browser tab, offline = the Docker appliance / mesh. tier/mesh describe the service's main feature: mesh=true means it needs a Pro/Max mesh; mesh_only lists single features that do. Ask vyomi_capability for one feature.",
		"live":          reachable,
	}
	if a.Home != "" {
		sel, err := s.resolveHome(a.Home)
		if err != nil {
			return nil, err
		}
		key := "offline"
		if wiringHome(sel.ID) == "nano" {
			key = "nano"
		}
		result["home"] = sel.ID
		result["level_key"] = "levels." + key + " applies to the " + sel.ID + " home"
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
			"v4_services":   c.V4Services,
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
		Home   string `json:"home"`
		mcpTargetArgs
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	if !validCloud(a.Cloud) {
		return nil, fmt.Errorf("cloud is required: aws, gcp or azure")
	}
	sel, t, err := s.homeTarget(a.Home, &a.mcpTargetArgs)
	if err != nil {
		return nil, err
	}
	c := s.matrix.Clouds[a.Cloud]
	w := s.wiring(a.Cloud, sel.ID)
	vars, warns := s.envVars(a.Cloud, sel.ID, t)
	notes := make([]string, 0, len(w.Notes))
	for _, n := range w.Notes {
		notes = append(notes, t.render(n))
	}
	out := map[string]any{
		"cloud":     a.Cloud,
		"home":      sel.ID,
		"endpoint":  t.simURL(),
		"variables": vars,
		"env_text":  formatEnv(a.Cloud, vars, a.Format),
		"notes":     notes,
	}
	if sel.Warning != "" {
		warns = append([]string{sel.Warning}, warns...)
	}
	if len(warns) > 0 {
		out["warnings"] = warns
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
		tf := map[string]any{"hcl": t.render(w.Terraform)}
		if w.TerraformNote != "" {
			tf["note"] = t.render(w.TerraformNote)
		}
		out["terraform"] = tf
	}
	return out, nil
}

func (s *mcpServer) toolScanRepo(raw json.RawMessage) (any, error) {
	var a struct {
		Path     string `json:"path"`
		MaxFiles int    `json:"max_files"`
		Home     string `json:"home"`
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	if a.MaxFiles <= 0 {
		a.MaxFiles = 5000
	}
	sel, err := s.resolveHome(a.Home)
	if err != nil {
		return nil, err
	}
	return s.scanRepo(a.Path, a.MaxFiles, sel)
}

func (s *mcpServer) toolWriteEnv(raw json.RawMessage) (any, error) {
	var a struct {
		Path      string   `json:"path"`
		Clouds    []string `json:"clouds"`
		Filename  string   `json:"filename"`
		Overwrite bool     `json:"overwrite"`
		Home      string   `json:"home"`
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
	if !strings.HasPrefix(name, ".env.vyomi") {
		return nil, fmt.Errorf("filename must start with .env.vyomi (got %q): the MCP never writes the project's own .env or other files", name)
	}
	dest := filepath.Join(a.Path, name)
	if st, err := os.Lstat(dest); err == nil {
		if !a.Overwrite {
			return nil, fmt.Errorf("%s already exists; pass overwrite=true to replace it", dest)
		}
		if !st.Mode().IsRegular() {
			return nil, fmt.Errorf("%s is not a regular file (a symlink?); refusing to write through it", dest)
		}
	}
	sel, t, err := s.homeTarget(a.Home, &a.mcpTargetArgs)
	if err != nil {
		return nil, err
	}
	var b strings.Builder
	fmt.Fprintf(&b, "# Vyomi %s %s — generated %s\n", sel.ID, t.simURL(), time.Now().UTC().Format(time.RFC3339))
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
		vars, warns := s.envVars(c, sel.ID, t)
		for _, w := range warns {
			fmt.Fprintf(&b, "# WARNING (%s): %s\n", strings.ToUpper(c), w)
		}
		b.WriteString(formatEnv(c, vars, "dotenv"))
		b.WriteString("\n")
	}
	if err := os.WriteFile(dest, []byte(b.String()), 0o644); err != nil {
		return nil, err
	}
	return map[string]any{
		"written": dest,
		"home":    sel.ID,
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
		vars, _ := s.envVars(c, homeOffline, s.target(nil))
		return text("text/plain", formatEnv(c, vars, "dotenv")), nil
	}
	return nil, fmt.Errorf("unknown resource %s", uri)
}

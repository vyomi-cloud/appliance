package main

// `vyomi mcp`: a Model Context Protocol server on stdio, so Claude Code / Claude
// Desktop / Cursor (any MCP client) can see what the simulator emulates, check
// whether it is running, and wire a user's repo to it.
//
//	claude mcp add vyomi -- vyomi mcp
//
// Stdlib only (like the rest of the launcher): MCP over stdio is newline-delimited
// JSON-RPC 2.0, small enough to implement directly instead of pulling in an SDK.
// stdout carries protocol messages ONLY; all diagnostics go to stderr.
//
// Knowledge comes from mcp_matrix.json, embedded at build time and generated from
// the appliance code by scripts/gen_mcp_matrix.py (never hand-edited). Live state
// comes from the running simulator's existing HTTP API (/healthz,
// /api/license/status, /api/spaces/active, /api/providers/{cloud}/matrix).

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

const mcpServerName = "vyomi"

// Newest first. We answer with the client's version when we support it, else ours.
var mcpProtocolVersions = []string{"2025-06-18", "2025-03-26", "2024-11-05"}

const mcpInstructions = `Vyomi is a local multi-cloud simulator (AWS, GCP, Azure) for development: real cloud SDKs, CLIs and Terraform talk to it instead of the real cloud.
In v4 the simulator lives in one of several homes: a Nano browser tab (reached through the vyomi-tunnel local tunnel on 127.0.0.1:8090, or the cloud relay URL from the Nano footer), a local Pro/Max mesh or the offline appliance (127.0.0.1:9000), or a mesh in the user's Codespace. vyomi_status lists the reachable homes and the one the other tools use; when several are reachable, ask the user which space they are working in.
Typical flow: (1) vyomi_status; (2) vyomi_scan_repo on the user's project to find which cloud services it uses and whether Vyomi emulates them (level per home, Pro tier, mesh-only); (3) vyomi_env for each cloud found to get the exact env vars / SDK config for that home; (4) show the user the exact .env.vyomi (path + contents) and call vyomi_write_env only after they explicitly approve it; a general "set this up" request is not approval; (5) optionally, with the same explicit approval, vyomi_agents_md proposes a short Vyomi section for the project's AGENTS.md (read-only; you apply it with your own edit tool) so every coding agent that opens the repo runs against Vyomi. vyomi_capability answers "does Vyomi support X" per feature; vyomi_snippet returns a ready CLI / SDK / curl call aimed at the selected endpoint.
Respect the warnings these tools return; they differ per home (on the offline appliance Cosmos and Key Vault need TLS on :9443 and GCP Pub/Sub and Firestore are separate gRPC emulators; through the Nano tunnel Key Vault and the gRPC Pub/Sub / Firestore clients are not available). Production still runs on the real cloud: never change production config, only add local/dev overrides.
Never tell a Nano user to run ` + "`vyomi up`" + `: that command only starts the offline appliance or a local mesh. For Nano the fix is the tunnel plus an open Nano tab, as the vyomi_status hint says.
For local-dev tasks, do not use MCP tools that act on a real cloud account (e.g. aws-mcp, Azure or Google Cloud MCP servers); use these Vyomi tools and the local simulator unless the user explicitly asks for the real cloud.`

// mcpHostedInstructions is the hosted server's instructions (`vyomi mcp --hosted`). It must say what this server
// knows, that it cannot see the user's machine, and which steps the agent does locally with its own tools. No tier
// pricing and no upgrade wording (OpenAI listing rules, O-D2/O-D4).
const mcpHostedInstructions = `Vyomi is a local multi-cloud simulator (AWS, GCP, Azure) for development: real cloud SDKs, CLIs and Terraform talk to it instead of the real cloud. The simulator runs on the developer's own machine, in one of three kinds of home: nano (a browser tab at https://vyomi.cloud/nano, reached through the vyomi-tunnel local tunnel on 127.0.0.1:8090), mesh (a local Vyomi mesh on 127.0.0.1:9000) or offline (the appliance on 127.0.0.1:9000, TLS 9443).
This server is hosted by Vyomi and answers knowledge questions only. It CANNOT see the user's machine, project or files: it never reaches 127.0.0.1, never reads or writes a file, and never connects to an endpoint named in a request. Every tool here is read-only and has no side effects. Pass home=nano|mesh|offline (default nano) to say which home the answer is for; ask the user when you do not know.
Never send a secret, a credential or any URL that acts as one. In particular, the Nano cloud relay URL (https://relay.vyomi.cloud/<session>) lets whoever holds it drive the user's tab: this server never asks for it and has no input that takes it. When the code reaches Nano through the relay, pass nano_access=relay and the answer comes back with the literal placeholder ${VYOMI_RELAY_URL}, which you replace on the user's machine with the URL from their Nano footer (or have them export VYOMI_RELAY_URL).
What it answers: list_services (which services Vyomi emulates, and at what level per home), check_capability (whether one feature is supported), get_code_snippet (a ready-to-run CLI / SDK / curl call aimed at that home's endpoint), get_sdk_settings (the env vars, SDK client settings and Terraform block that point code at Vyomi).
The local steps are yours, with your own tools: read the project, grep it, and write files. Show the user the exact file and contents and write only after they explicitly say yes; a general request such as "set this project up" is not approval. Production still runs on the real cloud: never change production config, deployment manifests or secrets, only add local/dev overrides.
Do not tell the user to run ` + "`vyomi up`" + `: that starts an appliance or a local mesh only. For nano the fix is the vyomi-tunnel plus an open Nano tab. For local-dev tasks, do not use MCP tools that act on a real cloud account (e.g. aws-mcp, Azure or Google Cloud MCP servers); use Vyomi and the local simulator unless the user explicitly asks for the real cloud.`

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type rpcResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Result  any             `json:"result,omitempty"`
	Error   *rpcError       `json:"error,omitempty"`
}

const (
	rpcParseError     = -32700
	rpcInvalidRequest = -32600
	rpcMethodNotFound = -32601
	rpcInvalidParams  = -32602
	rpcInternalError  = -32603
)

type mcpServer struct {
	cfg    *Config
	matrix *mcpMatrix
	tools  []*mcpTool
	byName map[string]*mcpTool
	client *http.Client
	// probeClient carries per-request timeouts (homeProbeTimeout); homeCache keeps the last probe (mcp_homes.go).
	probeClient *http.Client
	homeCache   homeCache
	out         io.Writer
	outMu       sync.Mutex
	version     string
	// hosted: this process serves the hosted surface over HTTP (`vyomi mcp --hosted`). It must never touch the
	// caller's machine, so it carries the hosted tool set, no output writer, and HTTP clients that cannot dial.
	hosted bool
}

func newMCPServer(c *Config, out io.Writer) (*mcpServer, error) {
	m, err := loadMCPMatrix()
	if err != nil {
		return nil, err
	}
	s := &mcpServer{
		cfg:         c,
		matrix:      m,
		client:      &http.Client{Timeout: 3 * time.Second},
		probeClient: &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }},
		out:         out,
		version:     m.ApplianceVersion,
	}
	s.tools = s.buildTools()
	s.index()
	return s, nil
}

func (s *mcpServer) index() {
	s.byName = map[string]*mcpTool{}
	for _, t := range s.tools {
		s.byName[t.Name] = t
	}
}

// noDialTransport is the RoundTripper the hosted server's HTTP clients carry: belt and braces behind the rule that
// no hosted handler may reach the network (plan §4 rule 1, and rule 4: never fetch a URL the caller supplies).
type noDialTransport struct{}

func (noDialTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	return nil, fmt.Errorf("hosted MCP: outbound HTTP is disabled (a handler tried to reach %s)", r.URL.Host)
}

// newHostedMCPServer builds the hosted server: the hosted tool set, no output writer (nothing writes to stdout),
// and HTTP clients that always error. It reads no VYOMI_* environment: homes are named, never probed (namedHome).
func newHostedMCPServer() (*mcpServer, error) {
	m, err := loadMCPMatrix()
	if err != nil {
		return nil, err
	}
	s := &mcpServer{
		cfg:         &Config{},
		matrix:      m,
		hosted:      true,
		client:      &http.Client{Transport: noDialTransport{}, Timeout: time.Second},
		probeClient: &http.Client{Transport: noDialTransport{}, Timeout: time.Second},
		version:     m.ApplianceVersion,
	}
	s.tools = s.buildHostedTools()
	s.index()
	return s, nil
}

// runMCP is the `vyomi mcp` entry point: the local stdio server, or with --hosted the hosted HTTP server.
func (c *Config) runMCP(args []string) int {
	hosted, listen := false, ""
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "-h" || a == "--help" || a == "help":
			fmt.Print(`vyomi mcp - Model Context Protocol server for AI coding agents

Local mode (stdio, the default). Register with Claude Code:
  claude mcp add vyomi -- vyomi mcp

Claude Desktop / Cursor (mcpServers config):
  "vyomi": { "command": "vyomi", "args": ["mcp"] }

Hosted mode (Streamable HTTP: JSON-RPC over POST, no SSE). Serves the read-only knowledge
tools and never touches the machine it runs on: no outbound network, no file access.
  vyomi mcp --hosted --listen :8080
  claude mcp add --transport http vyomi-hosted http://localhost:8080/mcp

  --hosted          Serve the hosted tool set over HTTP instead of stdio
  --listen ADDR     Address to listen on (default :$PORT, else :8080)

Paths in hosted mode: POST on "/" and "/mcp" (both with and without a trailing slash; never
redirected, a redirect would break POST), GET /healthz and GET /mcp/healthz.

Environment (local mode):
  VYOMI_ENDPOINT          Simulator base URL (default http://127.0.0.1:$VYOMI_SIMULATOR_PORT); a non-local
                          URL with home=nano is the Nano cloud relay (https://relay.vyomi.cloud/<session>)
  VYOMI_SIMULATOR_PORT    Simulator host port (default 9000)
  VYOMI_MESH_URL          Mesh control base URL (default http://127.0.0.1:9000)
  RELAY_PORT              Local Nano tunnel port (default 8090)

Environment (hosted mode):
  PORT                          Default listen port when --listen is absent
  VYOMI_MCP_ALLOWED_ORIGINS     Extra browser origins to accept, comma-separated

Tools (local): vyomi_status, vyomi_reach, vyomi_services, vyomi_capability, vyomi_snippet, vyomi_env, vyomi_scan_repo, vyomi_write_env, vyomi_agents_md
Tools (hosted): list_services, check_capability, get_code_snippet, get_sdk_settings
`)
			return 0
		case a == "--hosted":
			hosted = true
		case a == "--listen":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, "vyomi mcp: --listen needs an address, e.g. --listen :8080")
				return 2
			}
			i++
			listen = args[i]
		case strings.HasPrefix(a, "--listen="):
			listen = strings.TrimPrefix(a, "--listen=")
		default:
			// Tolerated, as before this flag existed: the npx launcher forwards whatever the user typed, and an
			// unknown argument must never stop a client's stdio server from coming up.
			fmt.Fprintf(os.Stderr, "vyomi mcp: ignoring unknown argument %q (try vyomi mcp --help)\n", a)
		}
	}
	if hosted {
		return runHostedMCP(listen)
	}
	if listen != "" {
		fmt.Fprintln(os.Stderr, "vyomi mcp: --listen needs --hosted (stdio mode does not listen on a port)")
		return 2
	}
	s, err := newMCPServer(c, os.Stdout)
	if err != nil {
		fmt.Fprintln(os.Stderr, "vyomi mcp:", err)
		return 1
	}
	fmt.Fprintf(os.Stderr, "vyomi mcp: serving on stdio (knowledge from appliance v%s; the simulator home is detected on each call: Nano tunnel 127.0.0.1:%d, mesh/appliance %s, Codespace via vyomi-tunnel; see vyomi_status)\n",
		s.version, relayPort(), meshURL())
	if err := s.serve(os.Stdin); err != nil {
		fmt.Fprintln(os.Stderr, "vyomi mcp:", err)
		return 1
	}
	return 0
}

func (s *mcpServer) serve(in io.Reader) error {
	r := bufio.NewReaderSize(in, 1<<20)
	for {
		line, err := r.ReadBytes('\n')
		if trimmed := bytes.TrimSpace(line); len(trimmed) > 0 {
			s.handleLine(trimmed)
		}
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
	}
}

func (s *mcpServer) handleLine(line []byte) {
	// JSON-RPC batches (dropped from the 2025-06-18 spec, still sent by older clients).
	if line[0] == '[' {
		var batch []json.RawMessage
		if err := json.Unmarshal(line, &batch); err != nil {
			s.write(rpcResponse{JSONRPC: "2.0", ID: json.RawMessage("null"), Error: &rpcError{rpcParseError, "parse error"}})
			return
		}
		var resps []rpcResponse
		for _, raw := range batch {
			if resp, ok := s.handleMessage(raw); ok {
				resps = append(resps, resp)
			}
		}
		if len(resps) > 0 {
			s.write(resps)
		}
		return
	}
	if resp, ok := s.handleMessage(line); ok {
		s.write(resp)
	}
}

// handleMessage returns (response, true) for requests and (_, false) for notifications.
func (s *mcpServer) handleMessage(raw []byte) (rpcResponse, bool) {
	var req rpcRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		return rpcResponse{JSONRPC: "2.0", ID: json.RawMessage("null"), Error: &rpcError{rpcParseError, "parse error"}}, true
	}
	isNotification := len(req.ID) == 0 || string(req.ID) == "null"
	if req.Method == "" {
		if isNotification {
			return rpcResponse{}, false // a response from the client (e.g. to a ping): nothing to do
		}
		return rpcResponse{JSONRPC: "2.0", ID: req.ID, Error: &rpcError{rpcInvalidRequest, "missing method"}}, true
	}
	result, rerr := s.dispatch(req.Method, req.Params)
	if isNotification {
		return rpcResponse{}, false
	}
	resp := rpcResponse{JSONRPC: "2.0", ID: req.ID}
	if rerr != nil {
		resp.Error = rerr
	} else {
		if result == nil {
			result = map[string]any{}
		}
		resp.Result = result
	}
	return resp, true
}

func (s *mcpServer) dispatch(method string, params json.RawMessage) (any, *rpcError) {
	switch method {
	case "initialize":
		var p struct {
			ProtocolVersion string `json:"protocolVersion"`
		}
		_ = json.Unmarshal(params, &p)
		version := mcpProtocolVersions[0]
		for _, v := range mcpProtocolVersions {
			if v == p.ProtocolVersion {
				version = v
			}
		}
		caps := map[string]any{
			"tools":     map[string]any{"listChanged": false},
			"resources": map[string]any{"listChanged": false, "subscribe": false},
		}
		info := map[string]any{"name": mcpServerName, "title": "Vyomi local cloud", "version": s.version}
		instructions := mcpInstructions
		if s.hosted {
			// Hosted v1 is tools only (D-I2): no resources capability, so clients never ask for one.
			delete(caps, "resources")
			info["title"] = "Vyomi"
			instructions = mcpHostedInstructions
		}
		return map[string]any{
			"protocolVersion": version,
			"capabilities":    caps,
			"serverInfo":      info,
			"instructions":    instructions,
		}, nil
	case "ping":
		return map[string]any{}, nil
	case "notifications/initialized", "notifications/cancelled", "notifications/progress", "notifications/roots/list_changed":
		return nil, nil
	case "tools/list":
		list := make([]map[string]any, 0, len(s.tools))
		for _, t := range s.tools {
			list = append(list, t.describe())
		}
		return map[string]any{"tools": list}, nil
	case "tools/call":
		var p struct {
			Name      string          `json:"name"`
			Arguments json.RawMessage `json:"arguments"`
		}
		if err := json.Unmarshal(params, &p); err != nil {
			return nil, &rpcError{rpcInvalidParams, "invalid tools/call params"}
		}
		t, ok := s.byName[p.Name]
		if !ok {
			return nil, &rpcError{rpcInvalidParams, "unknown tool: " + p.Name}
		}
		if len(bytes.TrimSpace(p.Arguments)) == 0 || string(p.Arguments) == "null" {
			p.Arguments = json.RawMessage("{}")
		}
		out, err := t.run(p.Arguments)
		if err != nil {
			// Tool failures are results (isError), not protocol errors, so the model can react.
			return map[string]any{
				"content": []map[string]any{{"type": "text", "text": err.Error()}},
				"isError": true,
			}, nil
		}
		text, _ := json.MarshalIndent(out, "", "  ")
		return map[string]any{
			"content": []map[string]any{{"type": "text", "text": string(text)}},
			"isError": false,
		}, nil
	case "resources/list":
		if s.hosted {
			return map[string]any{"resources": []any{}}, nil // D-I2: hosted v1 exposes no resources
		}
		return map[string]any{"resources": s.listResources()}, nil
	case "resources/templates/list":
		return map[string]any{"resourceTemplates": []any{}}, nil
	case "resources/read":
		if s.hosted {
			return nil, &rpcError{rpcInvalidParams, "this server exposes no resources; use tools/list"}
		}
		var p struct {
			URI string `json:"uri"`
		}
		if err := json.Unmarshal(params, &p); err != nil || p.URI == "" {
			return nil, &rpcError{rpcInvalidParams, "resources/read needs a uri"}
		}
		contents, err := s.readResource(p.URI)
		if err != nil {
			return nil, &rpcError{rpcInvalidParams, err.Error()}
		}
		return map[string]any{"contents": contents}, nil
	default:
		return nil, &rpcError{rpcMethodNotFound, "method not found: " + method}
	}
}

func (s *mcpServer) write(v any) {
	b, err := json.Marshal(v)
	if err != nil {
		fmt.Fprintln(os.Stderr, "vyomi mcp: marshal:", err)
		return
	}
	s.outMu.Lock()
	defer s.outMu.Unlock()
	_, _ = s.out.Write(append(b, '\n'))
}

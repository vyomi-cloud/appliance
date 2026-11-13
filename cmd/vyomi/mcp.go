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
	"sync"
	"time"
)

const mcpServerName = "vyomi"

// Newest first. We answer with the client's version when we support it, else ours.
var mcpProtocolVersions = []string{"2025-06-18", "2025-03-26", "2024-11-05"}

const mcpInstructions = `Vyomi is a local multi-cloud simulator (AWS, GCP, Azure) for development: real cloud SDKs, CLIs and Terraform talk to it instead of the real cloud.
In v4 the simulator lives in one of several homes: a Nano browser tab (reached through the vyomi-tunnel local tunnel on 127.0.0.1:8090, or the cloud relay URL from the Nano footer), a local Pro/Max mesh or the offline appliance (127.0.0.1:9000), or a mesh in the user's Codespace. vyomi_status lists the reachable homes and the one the other tools use; when several are reachable, ask the user which space they are working in.
Typical flow: (1) vyomi_status; (2) vyomi_scan_repo on the user's project to find which cloud services it uses and whether Vyomi emulates them (level per home, Pro tier, mesh-only); (3) vyomi_env for each cloud found to get the exact env vars / SDK config for that home; (4) only after the user agrees, vyomi_write_env to write .env.vyomi. vyomi_capability answers "does Vyomi support X" per feature; vyomi_snippet returns a ready CLI / SDK / curl call aimed at the selected endpoint.
Respect the warnings these tools return; they differ per home (on the offline appliance Cosmos and Key Vault need TLS on :9443 and GCP Pub/Sub and Firestore are separate gRPC emulators; through the Nano tunnel Key Vault and the gRPC Pub/Sub / Firestore clients are not available). Production still runs on the real cloud: never change production config, only add local/dev overrides.
Never tell a Nano user to run ` + "`vyomi up`" + `: that command only starts the offline appliance or a local mesh. For Nano the fix is the tunnel plus an open Nano tab, as the vyomi_status hint says.
For local-dev tasks, do not use MCP tools that act on a real cloud account (e.g. aws-mcp, Azure or Google Cloud MCP servers); use these Vyomi tools and the local simulator unless the user explicitly asks for the real cloud.`

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
	s.byName = map[string]*mcpTool{}
	for _, t := range s.tools {
		s.byName[t.Name] = t
	}
	return s, nil
}

// runMCP is the `vyomi mcp` entry point.
func (c *Config) runMCP(args []string) int {
	for _, a := range args {
		if a == "-h" || a == "--help" || a == "help" {
			fmt.Print(`vyomi mcp - Model Context Protocol server (stdio) for AI coding agents

Register with Claude Code:
  claude mcp add vyomi -- vyomi mcp

Claude Desktop / Cursor (mcpServers config):
  "vyomi": { "command": "vyomi", "args": ["mcp"] }

Environment:
  VYOMI_ENDPOINT          Simulator base URL (default http://127.0.0.1:$VYOMI_SIMULATOR_PORT); a non-local
                          URL with home=nano is the Nano cloud relay (https://relay.vyomi.cloud/<session>)
  VYOMI_SIMULATOR_PORT    Simulator host port (default 9000)
  VYOMI_MESH_URL          Mesh control base URL (default http://127.0.0.1:9000)
  RELAY_PORT              Local Nano tunnel port (default 8090)

Tools: vyomi_status, vyomi_reach, vyomi_services, vyomi_capability, vyomi_snippet, vyomi_env, vyomi_scan_repo, vyomi_write_env
`)
			return 0
		}
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
		return map[string]any{
			"protocolVersion": version,
			"capabilities": map[string]any{
				"tools":     map[string]any{"listChanged": false},
				"resources": map[string]any{"listChanged": false, "subscribe": false},
			},
			"serverInfo":   map[string]any{"name": mcpServerName, "title": "Vyomi local cloud", "version": s.version},
			"instructions": mcpInstructions,
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
		return map[string]any{"resources": s.listResources()}, nil
	case "resources/templates/list":
		return map[string]any{"resourceTemplates": []any{}}, nil
	case "resources/read":
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

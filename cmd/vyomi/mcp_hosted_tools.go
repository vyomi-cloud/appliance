package main

// The hosted tool set (`vyomi mcp --hosted`), served at https://vyomi.cloud/mcp.
//
// Plan: docs/architecture/v4.0/HOSTED-MCP-IMPLEMENTATION-PLAN.md §2-§4. Design: HOSTED-MCP-DESIGN.md §4.
//
// A hosted server cannot see the caller's machine: not 127.0.0.1, not their project, not their files. So it hands
// out knowledge and proposals, and the agent does the local steps with its own tools. Every tool here is
// read-only, idempotent, closed-world and has no side effects; names are plain verbs (O-D2) and no input is a
// file path. Handlers go through homeForArg -> namedHome, so they never probe a home, never call getJSON or
// runTunnelList, and never connect to an endpoint a caller names.

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
)

// hostedHomeProp: the hosted `home` argument. No "auto": nothing can be detected from here, so the agent says
// which home it means (default nano, the common case).
var hostedHomeProp = map[string]any{
	"type": "string", "enum": []string{"nano", "mesh", "offline"},
	"description": "Which kind of Vyomi home on the developer's machine the answer is for: nano (a browser tab reached through the vyomi-tunnel on 127.0.0.1:8090), mesh (a Vyomi mesh on 127.0.0.1:9000) or offline (the appliance on 127.0.0.1:9000, TLS 9443). Default nano. This server never connects to it.",
}

var hostedHostProp = map[string]any{
	"type":        "string",
	"description": "Host, or host:port, to write into the settings when the simulator is not on 127.0.0.1 as seen from where the code runs (e.g. a VM IP, or a container's host alias). Default 127.0.0.1 with the home's standard port.",
}

var hostedRelayProp = map[string]any{
	"type":        "string",
	"description": "With home=nano, the Nano cloud relay URL from the Nano footer (https://relay.vyomi.cloud/<session>) to write into the settings instead of the local tunnel. Rendered into the output only: this server never connects to it.",
}

func (s *mcpServer) buildHostedTools() []*mcpTool {
	return []*mcpTool{
		{
			Name:  "list_services",
			Title: "Services Vyomi emulates",
			Description: "Lists which AWS, GCP and Azure services the Vyomi local cloud simulator emulates, and how completely. " +
				"Use it to answer \"can I run this project against Vyomi?\" or \"does Vyomi emulate <service>?\" before wiring anything, and to pick the services worth pointing at the simulator. " +
				"Inputs: cloud (aws, gcp or azure; all three when absent) and home (nano, mesh or offline; default nano). " +
				"Returns, per cloud: every emulated service, its level in that home (full, limited, config_only, not_simulated), the API actions and data plane it serves, and which SDKs are wired. " +
				"Knowledge only, from data built into this server: it reads no project, reaches no machine, and has no side effects.",
			Schema: obj(map[string]any{
				"cloud": cloudEnum,
				"home":  hostedHomeProp,
			}),
			ReadOnly: true,
			handler:  s.hostedListServices,
		},
		{
			Name:  "check_capability",
			Title: "Does Vyomi support a feature?",
			Description: "Answers whether Vyomi emulates one specific cloud feature, by searching its capability registry (every console feature of AWS, GCP and Azure). " +
				"Use it when a question is narrower than a whole service — \"does Vyomi do S3 bucket versioning?\", \"can I create an AKS cluster?\" — or to check a feature before writing code that needs it. " +
				"Inputs: query (a capability id prefix such as s3.bucket or aks.cluster, or words from its title such as \"bucket versioning\") and optionally cloud. " +
				"Returns up to 20 matches with each one's level on a nano tab and on a mesh or appliance, its limitations, whether it is available on a Vyomi mesh only, and the conformance tests behind the claim. " +
				"Knowledge only, from data built into this server: no project access, no side effects.",
			Schema: obj(map[string]any{
				"query": map[string]any{"type": "string", "description": "Capability id prefix (s3.bucket, azure.aks.cluster) or words from its title (bucket versioning)."},
				"cloud": cloudEnum,
			}, "query"),
			ReadOnly: true,
			handler:  s.hostedCheckCapability,
		},
		{
			Name:  "get_code_snippet",
			Title: "Code example for a Vyomi operation",
			Description: "Returns one ready-to-run CLI, Python, JavaScript or curl call for a single service operation, already pointed at the chosen home's endpoint. " +
				"Use it when the user asks how to call a service against Vyomi, or when you need a correct first call to verify their setup; the snippets come from the API documentation of the operations Vyomi really answers. " +
				"Inputs: cloud, service (s3, dynamodb, pubsub, storage, cosmos...), optionally op (the operation name; a representative one is picked when absent), lang (cli, python, javascript or curl; default cli), home, host and relay_url. " +
				"Returns the snippet, the endpoint it targets, the operation's method and path, and the other languages available for it. " +
				"Generated text only: this server runs nothing, reaches no machine, and has no side effects.",
			Schema: obj(map[string]any{
				"cloud":     cloudEnum,
				"service":   map[string]any{"type": "string", "description": "Service id (e.g. s3, dynamodb, pubsub, storage, cosmos); list_services lists them."},
				"op":        map[string]any{"type": "string", "description": "Operation name (PutObject, put_object, put-object, storage.buckets.insert). Default: a representative operation for the service."},
				"lang":      langProp,
				"home":      hostedHomeProp,
				"host":      hostedHostProp,
				"relay_url": hostedRelayProp,
			}, "cloud", "service"),
			ReadOnly: true,
			handler:  s.hostedGetCodeSnippet,
		},
		{
			Name:  "get_sdk_settings",
			Title: "SDK settings for Vyomi",
			Description: "Returns the exact environment variables, SDK client settings and Terraform provider block that point one cloud's code at a Vyomi simulator, plus the gotchas for that home (data planes that need TLS, services that run as separate emulators, transports that are not available). " +
				"Use it when setting a project up to run against Vyomi, or when an SDK call fails and you need the settings the simulator expects; show the user the values and let them apply them. " +
				"Inputs: cloud, optionally lang (python, nodejs, java, go, cli or terraform), format for the env text (dotenv, shell or powershell), home, host, account and relay_url. " +
				"Returns the variables with notes, the formatted env text, per-SDK client settings, the Terraform block and any warnings. The credentials are the simulator's fixed dummy values; it never asks for or returns a real secret. " +
				"Generated text only: it writes no file, reaches no machine, and has no side effects.",
			Schema: obj(map[string]any{
				"cloud":     cloudEnum,
				"lang":      map[string]any{"type": "string", "enum": []string{"python", "nodejs", "java", "go", "cli", "terraform"}, "description": "Only return the settings for this SDK or tool."},
				"format":    map[string]any{"type": "string", "enum": []string{"dotenv", "shell", "powershell"}, "description": "Format of env_text (default dotenv)."},
				"home":      hostedHomeProp,
				"host":      hostedHostProp,
				"account":   accountArg,
				"relay_url": hostedRelayProp,
			}, "cloud"),
			ReadOnly: true,
			handler:  s.hostedGetSDKSettings,
		},
	}
}

// hostedTargetArgs are the endpoint arguments a hosted tool may carry. No `path`: the hosted server never sees a
// file system (plan §4 rule 2).
type hostedTargetArgs struct {
	Home     string `json:"home"`
	Host     string `json:"host"`
	Account  string `json:"account"`
	RelayURL string `json:"relay_url"`
}

// hostedTarget names the home (never probes it) and applies the caller's host / account / relay_url to the
// endpoint that is rendered into the answer. relay_url is parsed only to render it: nothing here dials.
func (s *mcpServer) hostedTarget(a hostedTargetArgs) (homeSel, mcpTarget, error) {
	sel, err := s.namedHome(a.Home)
	if err != nil {
		return homeSel{}, mcpTarget{}, err
	}
	t := sel.target
	if ru := strings.TrimSpace(a.RelayURL); ru != "" {
		if wiringHome(sel.ID) != "nano" {
			return homeSel{}, mcpTarget{}, fmt.Errorf("relay_url applies to home=nano only (the cloud relay serves a Nano tab); got home=%s", a.Home)
		}
		u, err := url.Parse(ru)
		if err != nil || u.Scheme != "https" || u.Hostname() == "" {
			return homeSel{}, mcpTarget{}, fmt.Errorf("relay_url must be an https URL such as https://relay.vyomi.cloud/<session> (got %q)", a.RelayURL)
		}
		if u.RawQuery != "" || u.Fragment != "" || u.User != nil {
			return homeSel{}, mcpTarget{}, fmt.Errorf("relay_url must be a plain https URL with no query, fragment or credentials")
		}
		t = endpointTarget(u, t)
		sel.ID = homeNanoCloud
		sel.Why = "home=nano with the cloud relay URL the caller gave; it is written into the settings and never contacted"
	}
	if h := strings.TrimSpace(a.Host); h != "" {
		if strings.Contains(h, "/") || strings.Contains(h, " ") {
			return homeSel{}, mcpTarget{}, fmt.Errorf("host must be a host or host:port, not a URL (got %q); for the Nano cloud relay use relay_url", a.Host)
		}
		if hh, pp, ok := strings.Cut(h, ":"); ok {
			h = hh
			if p, err := parsePort(pp); err == nil {
				t.SimPort = p
			} else {
				return homeSel{}, mcpTarget{}, fmt.Errorf("host port must be a number 1-65535 (got %q)", pp)
			}
		}
		t.Host = h
	}
	if acc := strings.TrimSpace(a.Account); acc != "" {
		t.Account = acc
	}
	return sel, t, nil
}

func parsePort(s string) (int, error) {
	n := 0
	if s == "" || len(s) > 5 {
		return 0, fmt.Errorf("not a port")
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, fmt.Errorf("not a port")
		}
		n = n*10 + int(c-'0')
	}
	if n < 1 || n > 65535 {
		return 0, fmt.Errorf("not a port")
	}
	return n, nil
}

// ── handlers ─────────────────────────────────────────────────────────────────
//
// Each one decodes its own arguments and then calls the shared knowledge code with the named home, so a hosted
// answer is the local answer for the same home with live state off.

func (s *mcpServer) hostedListServices(raw json.RawMessage) (any, error) {
	var a struct {
		Cloud string `json:"cloud"`
		Home  string `json:"home"`
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	if a.Home == "" {
		a.Home = "nano"
	}
	if _, err := s.namedHome(a.Home); err != nil {
		return nil, err
	}
	args, _ := json.Marshal(map[string]any{"cloud": a.Cloud, "home": a.Home, "live": false})
	return s.toolServices(args)
}

func (s *mcpServer) hostedCheckCapability(raw json.RawMessage) (any, error) {
	return s.toolCapability(raw) // already offline-only, and its arguments are the same
}

func (s *mcpServer) hostedGetCodeSnippet(raw json.RawMessage) (any, error) {
	var a struct {
		Cloud   string `json:"cloud"`
		Service string `json:"service"`
		Op      string `json:"op"`
		Lang    string `json:"lang"`
		hostedTargetArgs
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	sel, t, err := s.hostedTarget(a.hostedTargetArgs)
	if err != nil {
		return nil, err
	}
	sel.target = t
	return s.snippetResult(a.Cloud, a.Service, a.Op, a.Lang, sel)
}

func (s *mcpServer) hostedGetSDKSettings(raw json.RawMessage) (any, error) {
	var a struct {
		Cloud  string `json:"cloud"`
		Lang   string `json:"lang"`
		Format string `json:"format"`
		hostedTargetArgs
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	if !validCloud(a.Cloud) {
		return nil, fmt.Errorf("cloud is required: aws, gcp or azure")
	}
	sel, t, err := s.hostedTarget(a.hostedTargetArgs)
	if err != nil {
		return nil, err
	}
	return s.envResult(a.Cloud, a.Lang, a.Format, sel, t)
}

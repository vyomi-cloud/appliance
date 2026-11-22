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
	"time"
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
		{
			Name:  "get_scan_rules",
			Title: "Rules to find cloud SDK usage",
			Description: "Returns the line rules that find AWS, GCP and Azure SDK, CLI and Terraform usage in a project: for each rule an id, the cloud, the language, the file globs, a regular expression and which capture group holds the service token. " +
				"Use it as the first half of a repo scan: run these rules over the project with your own grep, then send the matches to summarize_scan_hits, which says which services Vyomi emulates. " +
				"Inputs: languages (any of python, nodejs, java, go, terraform; all of them when absent). " +
				"Returns the rules plus how to run them and what to send back. " +
				"This server never sees the project: it returns rules only, reads nothing and has no side effects.",
			Schema: obj(map[string]any{
				"languages": map[string]any{"type": "array", "items": map[string]any{"type": "string", "enum": sortedKeys(scanLangExts)},
					"minItems": 1, "description": "Only return rules for these rule languages. Default: all of them."},
			}),
			ReadOnly: true,
			handler:  s.hostedGetScanRules,
		},
		{
			Name:  "summarize_scan_hits",
			Title: "Summarize cloud usage found in a repo",
			Description: "Turns the matches of the get_scan_rules rules into a per-service report: which services the project uses, whether Vyomi emulates each one and at what level in the chosen home, how often and in which languages it is used, where (file and line), the warnings that apply, and which endpoint overrides the project already has. " +
				"Use it as the second half of a repo scan, after running the rules locally, to decide what can run against Vyomi and what has to stay on the real cloud. " +
				"Inputs: hits, an array of at most 2000 {rule, file, line, token} where token is the rule's captured service token (for example s3 from boto3.client(\"s3\")), and home. " +
				"Send identifiers only: no source lines, no file contents. Returns the report. " +
				"Reads nothing and has no side effects.",
			Schema: obj(map[string]any{
				"hits": map[string]any{
					"type": "array", "maxItems": scanMaxHitsIn,
					"description": "The rule matches, at most " + fmt.Sprint(scanMaxHitsIn) + " per call. Split a bigger scan into batches.",
					"items": obj(map[string]any{
						"rule":  map[string]any{"type": "string", "description": "The rule id from get_scan_rules (e.g. aws-python-1, or already-wired)."},
						"file":  map[string]any{"type": "string", "description": "Repo-relative file the rule matched in, e.g. src/app.py. Used only to show the user where a service is used."},
						"line":  map[string]any{"type": "integer", "minimum": 0, "description": "Line number of the match."},
						"token": map[string]any{"type": "string", "maxLength": scanMaxTokenLen, "pattern": `^[A-Za-z0-9_.\-/]{1,64}$`, "description": "The rule's captured service token (capture group 1), e.g. s3, pubsub, storage-blob. Never the matched line. Not needed for the already-wired rule."},
					}, "rule", "file", "line"),
				},
				"home": hostedHomeProp,
			}, "hits"),
			ReadOnly: true,
			handler:  s.hostedSummarizeScanHits,
		},
		{
			Name:  "propose_env_file",
			Title: "Propose a .env.vyomi file",
			Description: "Returns the exact .env.vyomi file that points a project's cloud SDKs at a Vyomi simulator: the file name and the full contents, with a header, the per-cloud warnings and the dummy credentials the simulator expects. " +
				"Use it once you know which clouds a project uses, to show the user the file before anything is written; you create the file yourself with your own edit tool, and only after they say yes. A general request such as \"set this project up\" is not approval. " +
				"Inputs: clouds (one or more of aws, gcp, azure), home, filename (a plain name starting with .env.vyomi), host and account. " +
				"Returns {filename, content} plus the home and endpoint it was rendered for. " +
				"It writes nothing, reads nothing and has no side effects.",
			Schema: obj(map[string]any{
				"clouds":    map[string]any{"type": "array", "items": cloudEnum, "minItems": 1, "description": "Clouds to include (e.g. the ones summarize_scan_hits found)."},
				"filename":  map[string]any{"type": "string", "description": "File name for the proposal, starting with .env.vyomi (default .env.vyomi). A plain name, not a path."},
				"home":      hostedHomeProp,
				"host":      hostedHostProp,
				"account":   accountArg,
				"relay_url": hostedRelayProp,
			}, "clouds"),
			ReadOnly: true,
			handler:  s.hostedProposeEnvFile,
		},
		{
			Name:  "propose_agents_md_section",
			Title: "Propose the Vyomi section for AGENTS.md",
			Description: "Returns a short, marker-delimited \"Local cloud: Vyomi\" section for a project's AGENTS.md, so every coding agent that opens the repo runs against Vyomi and keeps away from the real cloud, plus the action to take (created, appended, updated or unchanged), the old block to replace and the complete proposed file. " +
				"Use it after the project is wired, to make the setup travel with the repo; read AGENTS.md and the project's Claude memory file with your own tools, pass their text here, and apply the result with your own edit tool only after the user approves it. " +
				"Inputs: clouds, the current text of agents_md and claude_md (leave a field out when that file does not exist; at most 256 KiB each), claude_md_file (which memory file the text came from) and env_file. " +
				"Returns the section, the action, the replacement block, the proposed files and the CLAUDE.md import advice. The section names no endpoints or credentials, because AGENTS.md is committed and shared. " +
				"It writes nothing and has no side effects.",
			Schema: obj(map[string]any{
				"clouds":    map[string]any{"type": "array", "items": cloudEnum, "minItems": 1, "description": "Clouds the project uses (e.g. the ones summarize_scan_hits found)."},
				"agents_md": map[string]any{"type": "string", "maxLength": agentsMDMaxTextBytes, "description": "The current contents of the project's AGENTS.md. Leave it out when the project has none."},
				"claude_md": map[string]any{"type": "string", "maxLength": agentsMDMaxTextBytes, "description": "The current contents of the project's Claude memory file, if it has one (Claude Code ignores AGENTS.md when one exists unless it imports it). Leave it out when there is none."},
				"claude_md_file": map[string]any{"type": "string", "enum": claudeMemoryFileNames(),
					"description": "Which memory file claude_md came from, because the import line is relative to it. Default CLAUDE.md."},
				"env_file": map[string]any{"type": "string", "description": "Env file name the section refers to, starting with .env.vyomi (default .env.vyomi)."},
			}, "clouds"),
			ReadOnly: true,
			handler:  s.hostedProposeAgentsMD,
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

func (s *mcpServer) hostedGetScanRules(raw json.RawMessage) (any, error) {
	var a struct {
		Languages []string `json:"languages"`
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	table, err := s.scanRuleTable()
	if err != nil {
		return nil, err
	}
	want := map[string]bool{}
	for _, l := range a.Languages {
		if _, ok := scanLangExts[l]; !ok {
			return nil, fmt.Errorf("unknown rule language %q (have %s)", l, strings.Join(sortedKeys(scanLangExts), ", "))
		}
		want[l] = true
	}
	rules := make([]scanRule, 0, len(table))
	for _, r := range table {
		if len(want) == 0 || want[r.Lang] || r.ID == scanWiredRuleID {
			rules = append(rules, r)
		}
	}
	return map[string]any{
		"appliance_knowledge_version": s.version,
		"rules":                       rules,
		"skip_dirs":                   s.matrix.Scan.SkipDirs,
		"regex_syntax":                "RE2 (Go, RE2/J, ripgrep's default). No backreferences or lookaround is used, so the same expressions work with grep -E, ripgrep and Python re.",
		"how_to_run": []string{
			"For each rule, search the files its globs match for its regex, case-sensitively, and record one hit per match.",
			"ripgrep: rg --line-number --no-heading --only-matching --replace '$1' -e '<regex>' -g '<glob>' -- <project>   ($1 is the token; --replace keeps the matched line out of your output).",
			"grep: grep -rnE '<regex>' --include='<the glob's file name part>' <project>, then take capture group " + fmt.Sprint(1) + " of the match yourself.",
			"Skip the directories in skip_dirs (.git, node_modules, vendor, dist, build, .terraform and the rest).",
			"Send each match to summarize_scan_hits as {rule: <rule id>, file: <repo-relative path>, line: <number>, token: <capture group 1>}.",
			"The " + scanWiredRuleID + " rule finds endpoint overrides the project already has. It captures no service: send {rule, file, line} and NO token, and do not send the matched line.",
			"Never send source lines or file contents: the token and the file:line are all this server needs, and all it accepts.",
			"At most " + fmt.Sprint(scanMaxHitsIn) + " hits per call; split a large repo into batches and summarize each one.",
		},
		"token_group": "Capture group 1 of each rule's regex holds the service token (for example s3 in boto3.client(\"s3\"), or storage-blob in @azure/storage-blob). token_group is 0 for a rule that captures nothing.",
		"limits":      map[string]any{"max_hits_per_call": scanMaxHitsIn, "token_pattern": scanTokenPattern.String()},
		"next":        "Run the rules locally, then call summarize_scan_hits with the hits and the home you are targeting.",
	}, nil
}

func (s *mcpServer) hostedSummarizeScanHits(raw json.RawMessage) (any, error) {
	var a struct {
		Hits []scanHitIn `json:"hits"`
		Home string      `json:"home"`
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	sel, err := s.namedHome(a.Home)
	if err != nil {
		return nil, err
	}
	return s.summarizeHits(a.Hits, sel)
}

func (s *mcpServer) hostedProposeEnvFile(raw json.RawMessage) (any, error) {
	var a struct {
		Clouds   []string `json:"clouds"`
		Filename string   `json:"filename"`
		hostedTargetArgs
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	// The clouds keep the caller's order, de-duplicated, exactly as vyomi_write_env writes them, so the proposal
	// is byte for byte the file that gets written.
	if len(a.Clouds) == 0 {
		return nil, fmt.Errorf("clouds is required (aws, gcp, azure)")
	}
	var clouds []string
	seen := map[string]bool{}
	for _, c := range a.Clouds {
		if !validCloud(c) {
			return nil, fmt.Errorf("unknown cloud %q", c)
		}
		if !seen[c] {
			seen[c] = true
			clouds = append(clouds, c)
		}
	}
	name, err := envFileName(a.Filename)
	if err != nil {
		return nil, err
	}
	sel, t, err := s.hostedTarget(a.hostedTargetArgs)
	if err != nil {
		return nil, err
	}
	content, err := s.envFileContent(clouds, sel, t, time.Now())
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"filename": name,
		"content":  content,
		"home":     sel.ID,
		"endpoint": t.simURL(),
		"clouds":   clouds,
		"next": "Nothing was written. Show the user the file name and the contents, and create the file yourself with your own edit tool only after they explicitly approve it; a general request such as \"set this project up\" is not approval. " +
			"Load it for local runs only (e.g. `set -a; . ./" + name + "; set +a`, docker compose --env-file, or the framework's dotenv loader), and leave production config untouched.",
	}, nil
}

func (s *mcpServer) hostedProposeAgentsMD(raw json.RawMessage) (any, error) {
	var a struct {
		Clouds       []string `json:"clouds"`
		AgentsMD     *string  `json:"agents_md"`
		ClaudeMD     *string  `json:"claude_md"`
		ClaudeMDFile string   `json:"claude_md_file"`
		EnvFile      string   `json:"env_file"`
	}
	if err := decodeArgs(raw, &a); err != nil {
		return nil, err
	}
	clouds, err := normalizeClouds(a.Clouds)
	if err != nil {
		return nil, err
	}
	env, err := envFileName(a.EnvFile)
	if err != nil {
		return nil, fmt.Errorf("env_file must be a plain file name starting with .env.vyomi (got %q)", a.EnvFile)
	}
	for name, text := range map[string]*string{"agents_md": a.AgentsMD, "claude_md": a.ClaudeMD} {
		if text != nil && len(*text) > agentsMDMaxTextBytes {
			return nil, fmt.Errorf("%s is %d bytes; at most %d are accepted (send the file as it is, not a repository)", name, len(*text), agentsMDMaxTextBytes)
		}
	}
	return proposeAgentsMDFromText(a.AgentsMD, a.ClaudeMD, a.ClaudeMDFile, clouds, env)
}

package main

// PR 2 parity (HOSTED-MCP-IMPLEMENTATION-PLAN.md §6): the hosted scan split and the proposal tools must answer
// exactly what the local tools answer. The hosted server cannot walk the project, so the agent runs the rules
// from get_scan_rules with its own grep and sends back {rule, file, line, token}; this test is that agent.

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// scanParityView is a report with the fields that cannot match stripped: the local walk knows the root and how
// many files it read, the hosted summary knows how many hits it was sent, the examples' source text is never
// sent to the hosted server (D-I1), and next_steps names each mode's own tools.
func scanParityView(t *testing.T, rep *scanReport) string {
	t.Helper()
	c := *rep
	c.Root, c.FilesScanned, c.HitsReceived, c.NextSteps, c.Truncated = "", 0, 0, nil, false
	c.Clouds = map[string][]*scanService{}
	for cloud, list := range rep.Clouds {
		copied := make([]*scanService, 0, len(list))
		for _, e := range list {
			s := *e
			s.Examples = nil
			for _, ex := range e.Examples {
				ex.Text = ""
				s.Examples = append(s.Examples, ex)
			}
			copied = append(copied, &s)
		}
		c.Clouds[cloud] = copied
	}
	var wired []scanHit
	for _, w := range rep.AlreadyWired {
		w.Text = ""
		wired = append(wired, w)
	}
	c.AlreadyWired = wired
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// grepFixture is what a coding agent does with get_scan_rules: for every file a rule's globs match, run the
// regex over each line and keep capture group 1. Same walk order as the local scan, so even the examples line up.
func grepFixture(t *testing.T, root string, rules []scanRule) []scanHitIn {
	t.Helper()
	globExts := func(globs []string) map[string]bool {
		out := map[string]bool{}
		for _, g := range globs {
			out[strings.ToLower(strings.TrimPrefix(g, "**/*"))] = true
		}
		return out
	}
	compiled := make([]*regexp.Regexp, len(rules))
	exts := make([]map[string]bool, len(rules))
	for i, r := range rules {
		compiled[i] = regexp.MustCompile(r.Regex)
		exts[i] = globExts(r.Globs)
	}
	var hits []scanHitIn
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		ext := strings.ToLower(filepath.Ext(d.Name()))
		data, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(root, p)
		rel = filepath.ToSlash(rel)
		sc := bufio.NewScanner(bytes.NewReader(data))
		sc.Buffer(make([]byte, 64*1024), scanMaxFileBytes)
		line := 0
		for sc.Scan() {
			line++
			text := sc.Text()
			for i, r := range rules {
				if !exts[i][ext] {
					continue
				}
				if r.ID == scanWiredRuleID {
					if compiled[i].MatchString(text) {
						// file:line only; the matched line is never sent (D-I1).
						hits = append(hits, scanHitIn{Rule: r.ID, File: rel, Line: line})
					}
					continue
				}
				for _, m := range compiled[i].FindAllStringSubmatch(text, -1) {
					if len(m) > r.TokenGroup {
						hits = append(hits, scanHitIn{Rule: r.ID, File: rel, Line: line, Token: m[r.TokenGroup]})
					}
				}
			}
		}
		return sc.Err()
	})
	if err != nil {
		t.Fatal(err)
	}
	return hits
}

// The whole point of the split: local scanRepo == get_scan_rules + grep + summarize_scan_hits, per service.
func TestHostedScanParityWithLocalScan(t *testing.T) {
	for _, k := range []string{"RELAY_PORT", "VYOMI_ENDPOINT", "VYOMI_SIMULATOR_PORT", "VYOMI_MESH_URL", "VYOMI_TARGET"} {
		t.Setenv(k, "")
	}
	hosted := testHostedServer(t)
	local, _ := testMCPServer(t)
	root, err := filepath.Abs(filepath.Join("testdata", "scan"))
	if err != nil {
		t.Fatal(err)
	}

	// The rules an agent would be given, in the order get_scan_rules returns them.
	rulesRes, isErr := callTool(t, hosted, "get_scan_rules", map[string]any{})
	if isErr {
		t.Fatal(rulesRes["error"])
	}
	var served struct {
		Rules []scanRule `json:"rules"`
	}
	raw, _ := json.Marshal(rulesRes)
	if err := json.Unmarshal(raw, &served); err != nil {
		t.Fatal(err)
	}
	if len(served.Rules) != len(local.matrix.Scan.Rules)+1 {
		t.Fatalf("get_scan_rules returned %d rules, want %d (every rule plus %s)", len(served.Rules), len(local.matrix.Scan.Rules)+1, scanWiredRuleID)
	}
	hits := grepFixture(t, root, served.Rules)
	if len(hits) < 40 {
		t.Fatalf("the fixture produced only %d hits; it should exercise all three clouds in five languages", len(hits))
	}

	for _, home := range []string{"nano", "mesh", "offline"} {
		sel, err := local.resolveHome(home)
		if err != nil {
			t.Fatal(err)
		}
		want, err := local.scanRepo(root, 5000, sel)
		if err != nil {
			t.Fatal(err)
		}
		hostedRes, isErr := callTool(t, hosted, "summarize_scan_hits", map[string]any{"home": home, "hits": hits})
		if isErr {
			t.Fatalf("summarize_scan_hits(%s): %v", home, hostedRes["error"])
		}
		var got scanReport
		b, _ := json.Marshal(hostedRes)
		if err := json.Unmarshal(b, &got); err != nil {
			t.Fatal(err)
		}
		if scanParityView(t, want) != scanParityView(t, &got) {
			t.Errorf("home=%s: the hosted summary differs from the local scan:\nlocal:\n%s\nhosted:\n%s",
				home, scanParityView(t, want), scanParityView(t, &got))
		}
		// Sanity: the fixture really does cover all three clouds, five languages and an already-wired file.
		if len(got.Clouds) != 3 {
			t.Errorf("home=%s: the fixture should find all three clouds, got %v", home, sortedKeys(got.Clouds))
		}
		langs := map[string]bool{}
		for _, list := range got.Clouds {
			for _, e := range list {
				for _, l := range e.Langs {
					langs[l] = true
				}
			}
		}
		for _, l := range []string{"python", "nodejs", "java", "go", "terraform"} {
			if !langs[l] {
				t.Errorf("home=%s: no %s hits in the fixture", home, l)
			}
		}
		if len(got.AlreadyWired) == 0 {
			t.Errorf("home=%s: the fixture's wired file should be reported as already_wired", home)
		}
		// No source text ever comes back from the hosted summary.
		for _, w := range got.AlreadyWired {
			if w.Text != "" {
				t.Errorf("already_wired carries text %q; it must be file:line only (D-I1)", w.Text)
			}
		}
		for _, list := range got.Clouds {
			for _, e := range list {
				for _, ex := range e.Examples {
					if ex.Text != "" {
						t.Errorf("%s example carries text %q; the hosted server never receives source text", e.Service, ex.Text)
					}
				}
			}
		}
		if got.HitsReceived != len(hits) {
			t.Errorf("hits_received = %d, want %d", got.HitsReceived, len(hits))
		}
	}
}

// D-I1: the only thing a hit may carry is an identifier. Anything that looks like source text is refused.
func TestHostedScanHitsRejectSourceText(t *testing.T) {
	s := testHostedServer(t)
	ok := map[string]any{"rule": "aws-python-1", "file": "src/app.py", "line": 3, "token": "s3"}
	for _, bad := range []map[string]any{
		{"rule": "aws-python-1", "file": "src/app.py", "line": 3, "token": `boto3.client("s3")`},
		{"rule": "aws-python-1", "file": "src/app.py", "line": 3, "token": "s3 = boto3.client"},
		{"rule": "aws-python-1", "file": "src/app.py", "line": 3, "token": strings.Repeat("a", scanMaxTokenLen+1)},
		{"rule": "aws-python-1", "file": "src/app.py", "line": 3, "token": ""},
		{"rule": "aws-python-1", "file": "src/app.py", "line": 3},
		{"rule": "no-such-rule", "file": "src/app.py", "line": 3, "token": "s3"},
		{"rule": "aws-python-1", "file": "", "line": 3, "token": "s3"},
		{"rule": "aws-python-1", "file": "a file\nwith a newline", "line": 3, "token": "s3"},
		{"rule": "aws-python-1", "file": `boto3.client("s3")`, "line": 3, "token": "s3"},
		{"rule": "aws-python-1", "file": "src/app.py", "line": -1, "token": "s3"},
	} {
		res, isErr := callTool(t, s, "summarize_scan_hits", map[string]any{"hits": []map[string]any{ok, bad}})
		if !isErr {
			t.Errorf("should refuse the hit %v: %v", bad, res)
		}
	}
	// The already-wired rule needs no token, and refuses one that carries text.
	if res, isErr := callTool(t, s, "summarize_scan_hits", map[string]any{"hits": []map[string]any{
		{"rule": scanWiredRuleID, "file": "src/app.py", "line": 9},
	}}); isErr {
		t.Errorf("the already-wired rule needs no token: %v", res["error"])
	}
	// Too many hits in one call.
	many := make([]map[string]any, scanMaxHitsIn+1)
	for i := range many {
		many[i] = ok
	}
	if res, isErr := callTool(t, s, "summarize_scan_hits", map[string]any{"hits": many}); !isErr {
		t.Errorf("should refuse %d hits in one call: %v", len(many), res)
	} else if !strings.Contains(fmt.Sprint(res["error"]), "too many hits") {
		t.Errorf("the error should say the batch is too large: %v", res["error"])
	}
	// An unknown token is reported, not guessed, exactly as the local scan does.
	res, isErr := callTool(t, s, "summarize_scan_hits", map[string]any{"hits": []map[string]any{
		{"rule": "aws-python-1", "file": "src/app.py", "line": 1, "token": "nosuchservice"},
	}})
	if isErr {
		t.Fatal(res["error"])
	}
	un, _ := json.Marshal(res["unrecognized"])
	if !strings.Contains(string(un), "nosuchservice") {
		t.Errorf("an unknown token should be reported as unrecognized, got %s", un)
	}
}

// The proposed .env.vyomi is byte for byte the file vyomi_write_env writes (apart from the timestamp).
func TestHostedProposeEnvFileMatchesWriteEnv(t *testing.T) {
	for _, k := range []string{"RELAY_PORT", "VYOMI_ENDPOINT", "VYOMI_SIMULATOR_PORT", "VYOMI_MESH_URL", "VYOMI_TARGET"} {
		t.Setenv(k, "")
	}
	hosted := testHostedServer(t)
	local, _ := testMCPServer(t)
	stamp := regexp.MustCompile(`— generated \S+`)
	for _, home := range []string{"nano", "mesh", "offline"} {
		for _, clouds := range [][]string{{"aws"}, {"gcp"}, {"azure"}, {"azure", "aws", "gcp"}} {
			dir := t.TempDir()
			wrote, isErr := callTool(t, local, "vyomi_write_env", map[string]any{"path": dir, "clouds": clouds, "home": home})
			if isErr {
				t.Fatalf("vyomi_write_env: %v", wrote["error"])
			}
			proposed, isErr := callTool(t, hosted, "propose_env_file", map[string]any{"clouds": clouds, "home": home})
			if isErr {
				t.Fatalf("propose_env_file: %v", proposed["error"])
			}
			if proposed["filename"] != ".env.vyomi" {
				t.Errorf("filename = %v, want .env.vyomi", proposed["filename"])
			}
			want := stamp.ReplaceAllString(wrote["content"].(string), "")
			got := stamp.ReplaceAllString(proposed["content"].(string), "")
			if want != got {
				t.Errorf("%v home=%s: the proposal differs from what vyomi_write_env writes:\nwritten:\n%s\nproposed:\n%s", clouds, home, want, got)
			}
			// What was written is what the user was shown.
			onDisk, err := os.ReadFile(filepath.Join(dir, ".env.vyomi"))
			if err != nil {
				t.Fatal(err)
			}
			if stamp.ReplaceAllString(string(onDisk), "") != got {
				t.Errorf("%v home=%s: the file on disk differs from the proposal", clouds, home)
			}
		}
	}
	// It writes nothing itself, and refuses a name that is not an .env.vyomi* plain name.
	dir := t.TempDir()
	t.Chdir(dir)
	before := snapshot(t, dir)
	for _, name := range []string{".env", "../.env.vyomi", "sub/.env.vyomi", ".env.vyomi/x"} {
		if res, isErr := callTool(t, hosted, "propose_env_file", map[string]any{"clouds": []string{"aws"}, "filename": name}); !isErr {
			t.Errorf("should refuse filename %q: %v", name, res)
		}
	}
	if res, isErr := callTool(t, hosted, "propose_env_file", map[string]any{"clouds": []string{"aws"}, "filename": ".env.vyomi.local"}); isErr {
		t.Errorf(".env.vyomi.local should be accepted: %v", res["error"])
	} else if res["filename"] != ".env.vyomi.local" {
		t.Errorf("filename = %v", res["filename"])
	}
	sameTree(t, before, snapshot(t, dir))
}

// Every mcp_agents_md_test.go scenario gives the same action and the same content through the hosted tool.
func TestHostedProposeAgentsMDMatchesLocal(t *testing.T) {
	hosted := testHostedServer(t)
	local, _ := testMCPServer(t)
	dotClaude := filepath.Join(".claude", "CLAUDE.md")
	section := func(clouds []string, env string) string { return agentsMDSection(clouds, env) }
	_ = section

	for _, c := range []struct {
		name       string
		files      map[string]string // the project, as the local tool sees it on disk
		claudeFile string            // which memory file the hosted call reports text for ("" = none)
		clouds     []string
		envFile    string
	}{
		{"created", nil, "", []string{"azure", "aws", "aws"}, ""},
		{"appended", map[string]string{"AGENTS.md": "# Agents\n\n- Use pnpm, not npm.\n"}, "", []string{"gcp"}, ""},
		{"appended, no trailing newline", map[string]string{"AGENTS.md": "# Agents"}, "", []string{"aws"}, ""},
		{"appended, blank line at the end", map[string]string{"AGENTS.md": "# Agents\n\n"}, "", []string{"aws"}, ""},
		{"updated", map[string]string{"AGENTS.md": "# Agents\n\n" + agentsMDSection([]string{"gcp"}, ".env.vyomi") + "\n## Testing\n"}, "", []string{"aws", "gcp"}, ".env.vyomi.local"},
		{"unchanged", map[string]string{"AGENTS.md": agentsMDSection([]string{"aws"}, ".env.vyomi")}, "", []string{"aws"}, ""},
		{"CLAUDE.md without the import", map[string]string{"CLAUDE.md": "# Claude notes\n"}, "CLAUDE.md", []string{"aws"}, ""},
		{"CLAUDE.md with the import", map[string]string{"CLAUDE.md": "@AGENTS.md\n\n# Claude notes\n"}, "CLAUDE.md", []string{"aws"}, ""},
		{"only .claude/CLAUDE.md", map[string]string{dotClaude: "# team\n"}, ".claude/CLAUDE.md", []string{"aws"}, ""},
		{".claude/CLAUDE.md already imports", map[string]string{dotClaude: "@../AGENTS.md\n# team\n"}, ".claude/CLAUDE.md", []string{"aws"}, ""},
		{".claude/CLAUDE.md with a wrong-relative import", map[string]string{dotClaude: "@AGENTS.md\n"}, ".claude/CLAUDE.md", []string{"aws"}, ""},
		{"only CLAUDE.local.md", map[string]string{"CLAUDE.local.md": "# mine\n"}, "CLAUDE.local.md", []string{"aws"}, ""},
		{"CLAUDE.local.md already imports", map[string]string{"CLAUDE.local.md": "# mine\n  @AGENTS.md  \n"}, "CLAUDE.local.md", []string{"aws"}, ""},
		{"AGENTS.md and CLAUDE.md together", map[string]string{"AGENTS.md": "# Agents\n", "CLAUDE.md": "root\n"}, "CLAUDE.md", []string{"aws", "gcp", "azure"}, ".env.vyomi.local"},
	} {
		t.Run(c.name, func(t *testing.T) {
			dir := t.TempDir()
			for name, body := range c.files {
				p := filepath.Join(dir, name)
				if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
					t.Fatal(err)
				}
			}
			args := map[string]any{"path": dir, "clouds": c.clouds}
			hargs := map[string]any{"clouds": c.clouds}
			if c.envFile != "" {
				args["env_file"] = c.envFile
				hargs["env_file"] = c.envFile
			}
			if body, ok := c.files["AGENTS.md"]; ok {
				hargs["agents_md"] = body
			}
			if c.claudeFile != "" {
				hargs["claude_md"] = c.files[filepath.FromSlash(c.claudeFile)]
				hargs["claude_md_file"] = c.claudeFile
			}
			want, isErr := callTool(t, local, "vyomi_agents_md", args)
			if isErr {
				t.Fatalf("vyomi_agents_md: %v", want["error"])
			}
			got, isErr := callTool(t, hosted, "propose_agents_md_section", hargs)
			if isErr {
				t.Fatalf("propose_agents_md_section: %v", got["error"])
			}
			if want["section"] != got["section"] {
				t.Errorf("section differs:\nlocal:\n%s\nhosted:\n%s", want["section"], got["section"])
			}
			wam, gam := want["agents_md"].(map[string]any), got["agents_md"].(map[string]any)
			for _, k := range []string{"action", "proposed_content", "replace_block"} {
				if wam[k] != gam[k] {
					t.Errorf("agents_md.%s differs:\nlocal:  %q\nhosted: %q", k, wam[k], gam[k])
				}
			}
			wcm, gcm := want["claude_md"].(map[string]any), got["claude_md"].(map[string]any)
			for _, k := range []string{"action", "proposed_content"} {
				if wcm[k] != gcm[k] {
					t.Errorf("claude_md.%s differs:\nlocal:  %q\nhosted: %q", k, wcm[k], gcm[k])
				}
			}
			// The local tool reports an absolute path; the hosted one a file name, because it has no project.
			if gam["file"] != agentsMDFile {
				t.Errorf("hosted agents_md.file = %v, want %s", gam["file"], agentsMDFile)
			}
			if p, _ := wcm["path"].(string); p != "" && filepath.ToSlash(strings.TrimPrefix(p, dir+string(filepath.Separator))) != gcm["file"] {
				t.Errorf("claude_md file differs: local %q, hosted %v", p, gcm["file"])
			}
		})
	}
}

// Bounds and bad input for the text the hosted AGENTS.md tool accepts (plan §4 rule 5).
func TestHostedProposeAgentsMDLimits(t *testing.T) {
	s := testHostedServer(t)
	for _, bad := range []map[string]any{
		{"clouds": []string{}},
		{"clouds": []string{"oracle"}},
		{"clouds": []string{"aws"}, "env_file": ".env"},
		{"clouds": []string{"aws"}, "env_file": "../.env.vyomi"},
		{"clouds": []string{"aws"}, "claude_md": "x", "claude_md_file": "notes.md"},
		{"clouds": []string{"aws"}, "agents_md": strings.Repeat("x", agentsMDMaxTextBytes+1)},
		{"clouds": []string{"aws"}, "claude_md": strings.Repeat("x", agentsMDMaxTextBytes+1)},
		{"clouds": []string{"aws"}, "path": "/tmp"},
		// Malformed markers, exactly as the local tool refuses them.
		{"clouds": []string{"aws"}, "agents_md": "x\n" + agentsMDStart + "\nno end\n"},
		{"clouds": []string{"aws"}, "agents_md": "x\n" + agentsMDEnd + "\n" + agentsMDStart + "\n"},
		{"clouds": []string{"aws"}, "agents_md": agentsMDStart + "\n" + agentsMDEnd + "\n" + agentsMDStart + "\n" + agentsMDEnd + "\n"},
	} {
		if res, isErr := callTool(t, s, "propose_agents_md_section", bad); !isErr {
			t.Errorf("should refuse %v: %v", bad, res)
		}
	}
	// An AGENTS.md right at the limit is accepted.
	if res, isErr := callTool(t, s, "propose_agents_md_section", map[string]any{
		"clouds": []string{"aws"}, "agents_md": strings.Repeat("x", agentsMDMaxTextBytes),
	}); isErr {
		t.Errorf("a 256 KiB AGENTS.md should be accepted: %v", res["error"])
	}
	// The section itself never names an endpoint or a credential, whatever it is rendered for.
	for _, clouds := range [][]string{{"aws"}, {"gcp"}, {"azure"}, {"aws", "gcp", "azure"}} {
		res, isErr := callTool(t, s, "propose_agents_md_section", map[string]any{"clouds": clouds})
		if isErr {
			t.Fatal(res["error"])
		}
		sec := res["section"].(string)
		for _, leak := range []string{"127.0.0.1", ":9000", ":8090", "relay.vyomi.cloud", "AWS_ACCESS_KEY", "_KEY="} {
			if strings.Contains(sec, leak) {
				t.Errorf("%v: the section must not contain %q:\n%s", clouds, leak, sec)
			}
		}
	}
}

// get_scan_rules hands out a usable, stable table and says how to run it.
func TestHostedGetScanRules(t *testing.T) {
	s := testHostedServer(t)
	res, isErr := callTool(t, s, "get_scan_rules", map[string]any{})
	if isErr {
		t.Fatal(res["error"])
	}
	rules := res["rules"].([]any)
	ids := map[string]bool{}
	for _, r := range rules {
		m := r.(map[string]any)
		id, _ := m["id"].(string)
		if id == "" || ids[id] {
			t.Errorf("rule ids must be unique and non-empty: %v", m)
		}
		ids[id] = true
		if _, err := regexp.Compile(m["regex"].(string)); err != nil {
			t.Errorf("rule %s has an invalid regex: %v", id, err)
		}
		if len(m["globs"].([]any)) == 0 {
			t.Errorf("rule %s has no globs", id)
		}
		if id == scanWiredRuleID {
			if m["token_group"] != float64(0) {
				t.Errorf("%s captures no service, so token_group must be 0: %v", scanWiredRuleID, m["token_group"])
			}
			continue
		}
		if m["token_group"] != float64(1) {
			t.Errorf("rule %s: token_group = %v, want 1", id, m["token_group"])
		}
		if m["cloud"] == nil || m["lang"] == nil {
			t.Errorf("rule %s needs a cloud and a lang: %v", id, m)
		}
	}
	if !ids["already-wired"] || !ids["aws-python-1"] {
		t.Errorf("the table should contain aws-python-1 and already-wired: %v", sortedKeys(ids))
	}
	how := res["how_to_run"].([]any)
	if len(how) < 4 {
		t.Errorf("how_to_run should explain the grep, the batching and what not to send: %v", how)
	}
	joined := strings.ToLower(fmt.Sprint(how...) + fmt.Sprint(res["token_group"]))
	for _, want := range []string{"summarize_scan_hits", "never send source lines", "skip_dirs"} {
		if !strings.Contains(joined, strings.ToLower(want)) {
			t.Errorf("how_to_run should mention %q: %v", want, how)
		}
	}
	// languages filters, and an unknown language is refused.
	res, isErr = callTool(t, s, "get_scan_rules", map[string]any{"languages": []string{"python"}})
	if isErr {
		t.Fatal(res["error"])
	}
	for _, r := range res["rules"].([]any) {
		m := r.(map[string]any)
		if m["lang"] != "python" && m["id"] != scanWiredRuleID {
			t.Errorf("languages=[python] returned a %v rule", m["lang"])
		}
	}
	if res, isErr := callTool(t, s, "get_scan_rules", map[string]any{"languages": []string{"rust"}}); !isErr {
		t.Errorf("an unknown rule language should be refused: %v", res)
	}
}

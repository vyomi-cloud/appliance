package main

import (
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"testing"
)

// snapshot records every file under dir (path -> contents) so a test can prove a call wrote nothing.
func snapshot(t *testing.T, dir string) map[string]string {
	t.Helper()
	out := map[string]string{}
	_ = filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err == nil && info.Mode().IsRegular() {
			b, _ := os.ReadFile(p)
			out[p] = string(b)
		} else if err == nil && info.Mode()&os.ModeSymlink != 0 {
			tgt, _ := os.Readlink(p)
			out[p] = "symlink:" + tgt
		}
		return nil
	})
	return out
}

func sameTree(t *testing.T, before, after map[string]string) {
	t.Helper()
	if len(before) != len(after) {
		var names []string
		for k := range after {
			names = append(names, k)
		}
		sort.Strings(names)
		t.Fatalf("vyomi_agents_md must never write: file set changed to %v", names)
	}
	for k, v := range before {
		if after[k] != v {
			t.Fatalf("vyomi_agents_md must never write: %s changed", k)
		}
	}
}

// propose calls the tool and fails the test if anything under dir changed.
func propose(t *testing.T, s *mcpServer, dir string, args map[string]any) (map[string]any, bool) {
	t.Helper()
	before := snapshot(t, dir)
	res, isErr := callTool(t, s, "vyomi_agents_md", args)
	sameTree(t, before, snapshot(t, dir))
	return res, isErr
}

func part(t *testing.T, res map[string]any, key string) map[string]any {
	t.Helper()
	m, ok := res[key].(map[string]any)
	if !ok {
		t.Fatalf("result has no %s: %v", key, res)
	}
	return m
}

func TestAgentsMDCreate(t *testing.T) {
	s, _ := testMCPServer(t)
	dir := t.TempDir()
	res, isErr := propose(t, s, dir, map[string]any{"path": dir, "clouds": []string{"azure", "aws", "aws"}})
	if isErr {
		t.Fatal(res["error"])
	}
	am := part(t, res, "agents_md")
	if am["action"] != "created" || am["path"] != filepath.Join(dir, "AGENTS.md") {
		t.Fatalf("agents_md = %v", am)
	}
	body := am["proposed_content"].(string)
	if body != res["section"].(string) {
		t.Error("a new AGENTS.md is exactly the section")
	}
	if !strings.HasPrefix(body, agentsMDStart+"\n") || !strings.HasSuffix(body, agentsMDEnd+"\n") {
		t.Errorf("section must be wrapped in the markers:\n%s", body)
	}
	if !strings.Contains(body, "AWS and Azure code") {
		t.Errorf("clouds should be listed in canonical order, de-duplicated:\n%s", body)
	}
	for _, leak := range []string{"127.0.0.1", ":9000", ":8090", "relay.vyomi.cloud", "AWS_ACCESS_KEY"} {
		if strings.Contains(body, leak) {
			t.Errorf("AGENTS.md is committed and shared: no endpoints or credentials (%q)", leak)
		}
	}
	if n := strings.Count(body, "\n"); n > 20 {
		t.Errorf("section should stay short (%d lines)", n)
	}
	if !strings.Contains(res["next"].(string), "Nothing was written") {
		t.Errorf("next should say nothing was written: %v", res["next"])
	}
}

func TestAgentsMDAppendUpdateUnchanged(t *testing.T) {
	s, _ := testMCPServer(t)
	dir := t.TempDir()
	p := filepath.Join(dir, "AGENTS.md")
	before := "# Agents\n\n- Use pnpm, not npm.\n"
	_ = os.WriteFile(p, []byte(before), 0o644)

	res, isErr := propose(t, s, dir, map[string]any{"path": dir, "clouds": []string{"gcp"}})
	if isErr {
		t.Fatal(res["error"])
	}
	am := part(t, res, "agents_md")
	if am["action"] != "appended" {
		t.Fatalf("action %v, want appended", am["action"])
	}
	appended := am["proposed_content"].(string)
	if appended != before+"\n"+res["section"].(string) {
		t.Errorf("existing text must be kept verbatim with one blank line before the section:\n%s", appended)
	}

	// The user applied it and added text after the section; now the project also uses AWS.
	after := "\n## Testing\n\n- Run `make test`.\n"
	_ = os.WriteFile(p, []byte(appended+after), 0o644)
	oldSection := res["section"].(string)
	res, _ = propose(t, s, dir, map[string]any{"path": dir, "clouds": []string{"aws", "gcp"}, "env_file": ".env.vyomi.local"})
	am = part(t, res, "agents_md")
	if am["action"] != "updated" {
		t.Fatalf("action %v, want updated", am["action"])
	}
	if am["replace_block"] != strings.TrimSuffix(oldSection, "\n") {
		t.Errorf("replace_block should be the old block, start to end marker:\n%v", am["replace_block"])
	}
	upd := am["proposed_content"].(string)
	if !strings.HasPrefix(upd, before+"\n") || !strings.HasSuffix(upd, after) {
		t.Errorf("text outside the markers must not change:\n%s", upd)
	}
	if !strings.Contains(upd, "AWS and GCP code") || !strings.Contains(upd, "`.env.vyomi.local`") || strings.Count(upd, agentsMDStart) != 1 {
		t.Errorf("section not replaced in place:\n%s", upd)
	}

	_ = os.WriteFile(p, []byte(upd), 0o644)
	res, _ = propose(t, s, dir, map[string]any{"path": dir, "clouds": []string{"gcp", "aws"}, "env_file": ".env.vyomi.local"})
	if a := part(t, res, "agents_md")["action"]; a != "unchanged" {
		t.Errorf("same input again: action %v, want unchanged", a)
	}
}

func TestAgentsMDClaudeImport(t *testing.T) {
	s, _ := testMCPServer(t)
	// No CLAUDE.md: Claude Code already reads AGENTS.md, so never propose creating one.
	dir := t.TempDir()
	res, isErr := propose(t, s, dir, map[string]any{"path": dir, "clouds": []string{"aws"}})
	if isErr {
		t.Fatal(res["error"])
	}
	if cm := part(t, res, "claude_md"); cm["action"] != "not_needed" || cm["proposed_content"] != nil {
		t.Errorf("no CLAUDE.md: %v, want not_needed and no proposal", cm)
	}
	// CLAUDE.md without the import hides AGENTS.md from Claude Code: propose the import.
	_ = os.WriteFile(filepath.Join(dir, "CLAUDE.md"), []byte("# Claude notes\n"), 0o644)
	res, _ = propose(t, s, dir, map[string]any{"path": dir, "clouds": []string{"aws"}})
	cm := part(t, res, "claude_md")
	if cm["action"] != "prepended" || cm["proposed_content"] != "@AGENTS.md\n\n# Claude notes\n" || cm["why"] == nil {
		t.Errorf("claude_md = %v", cm)
	}
	_ = os.WriteFile(filepath.Join(dir, "CLAUDE.md"), []byte(cm["proposed_content"].(string)), 0o644)
	res, _ = propose(t, s, dir, map[string]any{"path": dir, "clouds": []string{"aws"}})
	if a := part(t, res, "claude_md")["action"]; a != "unchanged" {
		t.Errorf("import present: %v, want unchanged", a)
	}
	if _, isErr := propose(t, s, dir, map[string]any{"path": dir, "clouds": []string{"aws"}, "claude_md": true}); !isErr {
		t.Error("claude_md is no longer an argument")
	}
}

// Guardrail (threat A): vyomi_agents_md is read-only. It never writes, refuses bad input, and never reads through links.
func TestAgentsMDNeverWrites(t *testing.T) {
	s, _ := testMCPServer(t)
	dir := t.TempDir()
	for _, c := range []map[string]any{
		{"path": "relative/dir", "clouds": []string{"aws"}},
		{"path": filepath.Join(dir, "missing"), "clouds": []string{"aws"}},
		{"path": dir, "clouds": []string{}},
		{"path": dir, "clouds": []string{"oracle"}},
		{"path": dir, "clouds": []string{"aws"}, "env_file": ".env"},
		{"path": dir, "clouds": []string{"aws"}, "env_file": "../.env.vyomi"},
		{"path": dir, "clouds": []string{"aws"}, "dry_run": false},
	} {
		if _, isErr := propose(t, s, dir, c); !isErr {
			t.Errorf("should refuse %v", c)
		}
	}
	for _, bad := range []string{
		"x\n" + agentsMDStart + "\nno end\n",
		"x\n" + agentsMDEnd + "\n" + agentsMDStart + "\n",
		agentsMDStart + "\n" + agentsMDEnd + "\n" + agentsMDStart + "\n" + agentsMDEnd + "\n",
	} {
		d := t.TempDir()
		_ = os.WriteFile(filepath.Join(d, "AGENTS.md"), []byte(bad), 0o644)
		if _, isErr := propose(t, s, d, map[string]any{"path": d, "clouds": []string{"aws"}}); !isErr {
			t.Errorf("should refuse malformed markers %q", bad)
		}
	}
	if runtime.GOOS != "windows" {
		d := t.TempDir()
		target := filepath.Join(t.TempDir(), "elsewhere.md")
		_ = os.WriteFile(target, []byte("outside\n"), 0o644)
		_ = os.Symlink(target, filepath.Join(d, "AGENTS.md"))
		if _, isErr := propose(t, s, d, map[string]any{"path": d, "clouds": []string{"aws"}}); !isErr {
			t.Error("must refuse a symlinked AGENTS.md")
		}
	}
	var tool *mcpTool
	for _, tl := range s.buildTools() {
		if tl.Name == "vyomi_agents_md" {
			tool = tl
		}
	}
	if tool == nil || !tool.ReadOnly || tool.Destructive {
		t.Fatalf("vyomi_agents_md must be registered read-only and non-destructive: %+v", tool)
	}
	for _, want := range []string{"Read-only", "never writes", "ONLY after the user explicitly approved", "is not approval"} {
		if !strings.Contains(tool.Description, want) {
			t.Errorf("description lacks %q", want)
		}
	}
}

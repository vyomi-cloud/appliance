package main

// vyomi_agents_md (read-only): proposes a short, marker-delimited "Local cloud: Vyomi" section into the project's AGENTS.md,
// the cross-agent instructions file (agents.md, stewarded by the Agentic AI Foundation) that Codex, Cursor, Copilot,
// Gemini CLI and most other coding agents read on their own. The section travels with the repo, so every agent that
// opens it (including cloud and PR agents where no plugin can be installed) learns to run against Vyomi and to keep
// away from the real cloud during development.
//
// The section is home-agnostic on purpose: AGENTS.md is committed and shared, and teammates may use Nano, a mesh or
// the offline appliance. Endpoints stay in .env.vyomi (vyomi_write_env), never in AGENTS.md.
//
// The tool never writes. It reads the project's AGENTS.md (and CLAUDE.md) and returns the section, the action
// (created / appended / updated / unchanged), the exact old block to replace and the proposed file. The agent applies it
// with its own file-edit tool, which shows the user a diff and asks first; that keeps the MCP's only write path
// vyomi_write_env (guardrail, MCP-GUARDRAILS-INCIDENT-DESIGN.md threat A). Claude Code reads AGENTS.md only when the
// project has no Claude memory file (CLAUDE.md, .claude/CLAUDE.md or CLAUDE.local.md), so when one exists it also
// proposes an `@AGENTS.md` import into it.

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

const (
	agentsMDFile      = "AGENTS.md"
	agentsMDStart     = "<!-- vyomi:start -->"
	agentsMDEnd       = "<!-- vyomi:end -->"
	agentsMDImport    = "@AGENTS.md"
	agentsMDMaxBytes  = 1 << 20 // refuse to rewrite an AGENTS.md / CLAUDE.md larger than 1 MiB
	agentsMDPluginURL = "https://github.com/vyomi-cloud/claude-plugins"
)

var cloudLabel = map[string]string{"aws": "AWS", "gcp": "GCP", "azure": "Azure"}

// agentsMDSection renders the section, markers included, for the given clouds and env file name.
func agentsMDSection(clouds []string, envFile string) string {
	labels := make([]string, 0, len(clouds))
	for _, c := range clouds {
		labels = append(labels, cloudLabel[c])
	}
	var which string
	switch len(labels) {
	case 1:
		which = labels[0]
	case 2:
		which = labels[0] + " and " + labels[1]
	default:
		which = strings.Join(labels[:len(labels)-1], ", ") + " and " + labels[len(labels)-1]
	}
	var b strings.Builder
	b.WriteString(agentsMDStart + "\n")
	b.WriteString("## Local cloud: Vyomi\n\n")
	fmt.Fprintf(&b, "During development this project's %s code runs against [Vyomi](https://vyomi.cloud), a local cloud simulator. Production still uses the real cloud.\n\n", which)
	fmt.Fprintf(&b, "- Local settings (simulator endpoints, dummy credentials) live in `%s`. Load it only for local runs, e.g. `set -a; . ./%s; set +a`. If it is missing, regenerate it with the `vyomi` MCP server (`vyomi_env`, then `vyomi_write_env` with the developer's OK); never guess endpoints.\n", envFile, envFile)
	b.WriteString("- Do not start the simulator yourself; ask the developer. Nano: run `vyomi-tunnel` and keep https://vyomi.cloud/nano open. Pro/Max mesh or offline appliance: `vyomi up`. Check it with the `vyomi_status` MCP tool.\n")
	fmt.Fprintf(&b, "- Run tests and local scripts with `%s` loaded. Never point local runs at a real cloud account, and do not use MCP servers or CLIs that act on one unless the developer asks.\n", envFile)
	b.WriteString("- Never change production config, deployment manifests or secrets to make local runs work; add local overrides only.\n")
	b.WriteString("- Services Vyomi does not emulate keep using the real cloud (or a stub). Check with `vyomi_scan_repo` before wiring anything new to Vyomi.\n")
	fmt.Fprintf(&b, "- MCP server: `vyomi-tunnel mcp`. Agent plugins for Claude Code, Codex, Cursor and Copilot: %s\n", agentsMDPluginURL)
	b.WriteString(agentsMDEnd + "\n")
	return b.String()
}

// spliceAgentsMD returns the new file contents and the action taken: created, appended, updated or unchanged.
func spliceAgentsMD(existing []byte, exists bool, section string) (string, string, error) {
	if !exists {
		return section, "created", nil
	}
	old := string(existing)
	starts, ends := strings.Count(old, agentsMDStart), strings.Count(old, agentsMDEnd)
	switch {
	case starts == 0 && ends == 0:
		sep := "\n"
		switch {
		case old == "":
			sep = ""
		case strings.HasSuffix(old, "\n\n"):
			sep = ""
		case strings.HasSuffix(old, "\n"):
			sep = "\n"
		default:
			sep = "\n\n"
		}
		return old + sep + section, "appended", nil
	case starts == 1 && ends == 1:
		i, j := strings.Index(old, agentsMDStart), strings.Index(old, agentsMDEnd)
		if j < i {
			return "", "", fmt.Errorf("%s has %s before %s; fix the markers by hand", agentsMDFile, agentsMDEnd, agentsMDStart)
		}
		j += len(agentsMDEnd)
		if j < len(old) && old[j] == '\n' {
			j++
		}
		out := old[:i] + section + old[j:]
		if out == old {
			return out, "unchanged", nil
		}
		return out, "updated", nil
	default:
		return "", "", fmt.Errorf("%s has %d %q and %d %q markers (want exactly one pair, or none); fix them by hand", agentsMDFile, starts, agentsMDStart, ends, agentsMDEnd)
	}
}

// claudeMemoryFile is a project file Claude Code loads instead of AGENTS.md. Imports resolve relative to the importing
// file, so .claude/CLAUDE.md needs `@../AGENTS.md`.
type claudeMemoryFile struct {
	name    string   // relative to the project directory
	imports []string // import lines that pull in the project's AGENTS.md; imports[0] is the one proposed
}

// claudeMemoryFiles: Claude Code (2.1.277+) reads AGENTS.md only when the project has none of these; each one hides it
// unless it imports it. Checked in this order; the first that exists gets the proposal.
var claudeMemoryFiles = []claudeMemoryFile{
	{"CLAUDE.md", []string{agentsMDImport, "@./AGENTS.md"}},
	{filepath.Join(".claude", "CLAUDE.md"), []string{"@../AGENTS.md", "@./../AGENTS.md"}},
	{"CLAUDE.local.md", []string{agentsMDImport, "@./AGENTS.md"}},
}

// importsAgentsMD reports whether a memory file already has one of the import lines on a line of its own.
func importsAgentsMD(content string, imports []string) bool {
	for _, line := range strings.Split(content, "\n") {
		for _, imp := range imports {
			if strings.TrimSpace(line) == imp {
				return true
			}
		}
	}
	return false
}

// symlinkToAgentsMD reports whether dir/name is a symlink whose target is the project's AGENTS.md (the common
// `ln -s AGENTS.md CLAUDE.md`): Claude Code then reads AGENTS.md through it, so no import is needed.
func symlinkToAgentsMD(dir, name string) bool {
	p := filepath.Join(dir, name)
	st, err := os.Lstat(p)
	if err != nil || st.Mode()&os.ModeSymlink == 0 {
		return false
	}
	tgt, err := os.Readlink(p)
	if err != nil {
		return false
	}
	if !filepath.IsAbs(tgt) {
		tgt = filepath.Join(filepath.Dir(p), tgt)
	}
	return filepath.Clean(tgt) == filepath.Join(dir, agentsMDFile)
}

// proposeClaudeMD returns the claude_md part of the result. No memory file -> not_needed (never create one); a memory file
// that imports AGENTS.md (or is a symlink to it) -> unchanged; otherwise -> prepended, against the first file that exists.
func proposeClaudeMD(dir string) (map[string]any, error) {
	var first *claudeMemoryFile
	var firstContent string
	for i := range claudeMemoryFiles {
		f := &claudeMemoryFiles[i]
		if symlinkToAgentsMD(dir, f.name) {
			return map[string]any{"path": filepath.Join(dir, f.name), "action": "unchanged"}, nil
		}
		b, exists, err := readProjectFile(dir, f.name)
		if err != nil {
			return nil, err
		}
		if !exists {
			continue
		}
		if importsAgentsMD(string(b), f.imports) {
			return map[string]any{"path": filepath.Join(dir, f.name), "action": "unchanged"}, nil
		}
		if first == nil {
			first, firstContent = f, string(b)
		}
	}
	if first == nil {
		return map[string]any{"path": filepath.Join(dir, claudeMemoryFiles[0].name), "action": "not_needed"}, nil
	}
	return map[string]any{
		"path":             filepath.Join(dir, first.name),
		"action":           "prepended",
		"proposed_content": first.imports[0] + "\n\n" + firstContent,
		"why":              "This project has " + filepath.ToSlash(first.name) + ", so Claude Code ignores AGENTS.md unless that file imports it.",
	}, nil
}

// readProjectFile reads dir/name for an in-place rewrite. Missing is fine; symlinks, non-regular files and oversized
// files are refused so the tool never writes through a link or truncates something it did not fully read.
func readProjectFile(dir, name string) ([]byte, bool, error) {
	p := filepath.Join(dir, name)
	st, err := os.Lstat(p)
	if os.IsNotExist(err) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if !st.Mode().IsRegular() {
		return nil, false, fmt.Errorf("%s is not a regular file (a symlink?); refusing to write through it", p)
	}
	if st.Size() > agentsMDMaxBytes {
		return nil, false, fmt.Errorf("%s is larger than %d bytes; refusing to rewrite it", p, agentsMDMaxBytes)
	}
	b, err := os.ReadFile(p)
	return b, true, err
}

func (s *mcpServer) toolAgentsMD(raw json.RawMessage) (any, error) {
	var a struct {
		Path    string   `json:"path"`
		Clouds  []string `json:"clouds"`
		EnvFile string   `json:"env_file"`
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
	var clouds []string
	seen := map[string]bool{}
	for _, c := range mcpClouds { // canonical order, de-duplicated
		for _, want := range a.Clouds {
			if want == c && !seen[c] {
				seen[c] = true
				clouds = append(clouds, c)
			}
		}
	}
	for _, c := range a.Clouds {
		if !validCloud(c) {
			return nil, fmt.Errorf("unknown cloud %q", c)
		}
	}
	env := a.EnvFile
	if env == "" {
		env = ".env.vyomi"
	}
	if env != filepath.Base(env) || !strings.HasPrefix(env, ".env.vyomi") {
		return nil, fmt.Errorf("env_file must be a plain file name starting with .env.vyomi (got %q)", a.EnvFile)
	}

	section := agentsMDSection(clouds, env)
	agentsPath := filepath.Join(a.Path, agentsMDFile)
	old, exists, err := readProjectFile(a.Path, agentsMDFile)
	if err != nil {
		return nil, err
	}
	agentsOut, agentsAction, err := spliceAgentsMD(old, exists, section)
	if err != nil {
		return nil, err
	}

	var oldBlock string
	if agentsAction == "updated" || agentsAction == "unchanged" {
		o := string(old)
		i := strings.Index(o, agentsMDStart)
		j := strings.Index(o, agentsMDEnd) + len(agentsMDEnd)
		oldBlock = o[i:j]
	}
	am := map[string]any{"path": agentsPath, "action": agentsAction, "proposed_content": agentsOut}
	if oldBlock != "" {
		am["replace_block"] = oldBlock
	}
	res := map[string]any{"agents_md": am, "section": section, "start_marker": agentsMDStart, "end_marker": agentsMDEnd}
	cm, err := proposeClaudeMD(a.Path)
	if err != nil {
		return nil, err
	}
	res["claude_md"] = cm
	res["next"] = "Nothing was written. Show the user the section and the action. Only after they approve, apply it with your own file-edit tool: " +
		"created -> create the file with proposed_content; appended -> append the section; updated -> replace replace_block (from start_marker to end_marker) with the section; unchanged -> nothing to do. " +
		"If claude_md.action is prepended, also write claude_md.proposed_content to claude_md.path (same approval). Never change text outside the markers. Then suggest committing AGENTS.md so teammates' agents pick it up."
	return res, nil
}

func (s *mcpServer) agentsMDTool() *mcpTool {
	return &mcpTool{
		Name:     "vyomi_agents_md",
		Title:    "Propose the Vyomi section for AGENTS.md",
		ReadOnly: true,
		Description: "Read-only. Proposes a short 'Local cloud: Vyomi' section for the project's AGENTS.md (between <!-- vyomi:start --> and <!-- vyomi:end --> markers) so any coding agent " +
			"that opens the repo runs against Vyomi with .env.vyomi and keeps away from the real cloud. Reads the existing AGENTS.md and returns the section, the action " +
			"(created / appended / updated / unchanged), the block to replace and the proposed file; it never writes. The section names no endpoints (those stay in .env.vyomi). " +
			"If the project has a CLAUDE.md, .claude/CLAUDE.md or CLAUDE.local.md that does not import AGENTS.md, it also proposes that import (Claude Code ignores AGENTS.md when one of those exists). Apply the result with your own file-edit tool ONLY after the user explicitly approved this exact change; " +
			"a general request such as 'set this project up' is not approval.",
		Schema: obj(map[string]any{
			"path":     map[string]any{"type": "string", "description": "Absolute path of the project directory (where AGENTS.md lives or should live)."},
			"clouds":   map[string]any{"type": "array", "items": cloudEnum, "minItems": 1, "description": "Clouds the project uses (from vyomi_scan_repo)."},
			"env_file": map[string]any{"type": "string", "description": "Env file name the section refers to, starting with .env.vyomi (default .env.vyomi)."},
		}, "path", "clouds"),
		handler: s.toolAgentsMD,
	}
}

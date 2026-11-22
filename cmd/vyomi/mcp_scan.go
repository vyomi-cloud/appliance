package main

import (
	"bufio"
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Repo scanner behind vyomi_scan_repo. Rules, aliases and warnings are data in
// mcp_matrix.json (scripts/mcp_wiring.json), so coverage grows without Go changes.

const (
	scanMaxFileBytes = 1 << 20
	scanMaxHits      = 5
)

// Which rule languages apply to which file extensions.
var scanLangExts = map[string][]string{
	"python":    {".py", ".txt", ".toml"},
	"nodejs":    {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json"},
	"java":      {".java", ".kt", ".xml", ".gradle", ".kts"},
	"go":        {".go", ".mod"},
	"terraform": {".tf"},
}

type scanHit struct {
	File string `json:"file"`
	Line int    `json:"line"`
	Lang string `json:"lang,omitempty"`
	// Text is the clipped source line. The local scan fills it; the hosted summary never does, because no source
	// text is sent to the hosted server (design §4, D-I1).
	Text string `json:"text,omitempty"`
}

type scanService struct {
	Service  string    `json:"service"`
	Name     string    `json:"name,omitempty"`
	Status   string    `json:"status"`              // registry status (e.g. released) | v4 (capability registry only) | not_emulated
	Level    string    `json:"level,omitempty"`     // worst feature level in the selected home (nano or offline/mesh)
	Tier     string    `json:"tier,omitempty"`      // "pro" when the service's main feature needs a Pro licence
	Mesh     bool      `json:"mesh,omitempty"`      // the service's main feature needs a Pro/Max mesh
	MeshOnly []string  `json:"mesh_only,omitempty"` // single features that need a mesh
	Uses     int       `json:"uses"`
	Langs    []string  `json:"langs"`
	Examples []scanHit `json:"examples"`
	Warning  string    `json:"warning,omitempty"`
	langSet  map[string]bool
	noneHere bool // every feature is not_simulated in the selected home (e.g. EKS on Nano)
}

type scanReport struct {
	Root         string                    `json:"root,omitempty"` // local scan only: the directory walked
	Home         string                    `json:"home"`
	FilesScanned int                       `json:"files_scanned,omitempty"` // local scan only
	HitsReceived int                       `json:"hits_received,omitempty"` // hosted summary only: hits the agent sent
	Truncated    bool                      `json:"truncated,omitempty"`
	Clouds       map[string][]*scanService `json:"clouds"`
	Unrecognized map[string][]string       `json:"unrecognized,omitempty"`
	AlreadyWired []scanHit                 `json:"already_wired"`
	Summary      []string                  `json:"summary"`
	NextSteps    []string                  `json:"next_steps"`
}

// scanRule is one line rule, as both the local walk and the hosted get_scan_rules see it. The id is stable
// (cloud-lang-n in knowledge order), so a hosted caller can grep with the regex and send back hits that name it.
type scanRule struct {
	ID         string   `json:"id"`
	Cloud      string   `json:"cloud,omitempty"` // empty for the already-wired rule, which is cloud-independent
	Lang       string   `json:"lang"`
	Globs      []string `json:"globs"`
	Regex      string   `json:"regex"`
	TokenGroup int      `json:"token_group"` // capture group holding the service token; 0 = the rule captures nothing
	re         *regexp.Regexp
}

// scanWiredRuleID is the rule that finds endpoint overrides a project already has. It captures no service, and
// its hits are reported as file:line only: the matched text is never sent to the hosted server (D-I1).
const scanWiredRuleID = "already-wired"

// scanRuleGlobs are the file globs for a rule language, from scanLangExts.
func scanRuleGlobs(lang string) []string {
	exts := scanLangExts[lang]
	globs := make([]string, 0, len(exts))
	for _, e := range exts {
		globs = append(globs, "**/*"+e)
	}
	sort.Strings(globs)
	return globs
}

// scanRuleTable compiles the rule table once: the per-language rules in knowledge order, then the already-wired
// rule. The local walk (scanRepo) and the hosted get_scan_rules / summarize_scan_hits all work from this table,
// so a rule id means the same thing everywhere.
func (s *mcpServer) scanRuleTable() ([]scanRule, error) {
	rules := make([]scanRule, 0, len(s.matrix.Scan.Rules)+1)
	n := map[string]int{}
	for _, r := range s.matrix.Scan.Rules {
		re, err := regexp.Compile(r.Pattern)
		if err != nil {
			return nil, fmt.Errorf("scan rule %s/%s: %v", r.Cloud, r.Lang, err)
		}
		key := r.Cloud + "-" + r.Lang
		n[key]++
		rules = append(rules, scanRule{
			ID: fmt.Sprintf("%s-%d", key, n[key]), Cloud: r.Cloud, Lang: r.Lang,
			Globs: scanRuleGlobs(r.Lang), Regex: r.Pattern, TokenGroup: 1, re: re,
		})
	}
	if s.matrix.Scan.AlreadyWired != "" {
		re, err := regexp.Compile(s.matrix.Scan.AlreadyWired)
		if err != nil {
			return nil, fmt.Errorf("already_wired pattern: %v", err)
		}
		all := map[string]bool{}
		var globs []string
		for _, lang := range sortedKeys(scanLangExts) {
			for _, g := range scanRuleGlobs(lang) {
				if !all[g] {
					all[g] = true
					globs = append(globs, g)
				}
			}
		}
		sort.Strings(globs)
		rules = append(rules, scanRule{ID: scanWiredRuleID, Lang: "any", Globs: globs, Regex: s.matrix.Scan.AlreadyWired, TokenGroup: 0, re: re})
	}
	return rules, nil
}

// scanRuleByID indexes a table for the hosted summary.
func scanRuleByID(rules []scanRule) map[string]*scanRule {
	out := make(map[string]*scanRule, len(rules))
	for i := range rules {
		out[rules[i].ID] = &rules[i]
	}
	return out
}

// resolveAlias maps a captured token (e.g. "client-sqs" → "sqs", "pubsub_v1" →
// "pubsub") to a matrix service id. "" means unknown; "_core"/"_ignore" are skipped.
func (s *mcpServer) resolveAlias(cloud, token string) string {
	aliases := s.matrix.Scan.Aliases[cloud]
	token = strings.ToLower(token)
	if v, ok := aliases[token]; ok {
		return v
	}
	if s.matrix.service(cloud, token) != nil {
		return token
	}
	// Package paths: last segment ("mgmt.compute" → "compute",
	// "resourcemanager/compute/armcompute" → "armcompute", "arm-network" → "network").
	if i := strings.LastIndexAny(token, "./-"); i > 0 && i < len(token)-1 {
		if v := s.resolveAlias(cloud, token[i+1:]); v != "" && v != "_ignore" {
			return v
		}
	}
	// Then progressively shorter prefixes: "functions-framework" → "functions".
	for _, sep := range []string{"-", "_", ".", "/"} {
		if i := strings.Index(token, sep); i > 0 {
			if v := s.resolveAlias(cloud, token[:i]); v != "" {
				return v
			}
		}
	}
	return ""
}

// scanWarning is the warning for cloud/svc in a home: the home's own scan_warnings, else the offline ones (which
// mention TLS :9443 and separate emulators, so they are not used on Nano when they need TLS).
func (s *mcpServer) scanWarning(key string, sel homeSel) string {
	if h := s.matrix.Homes[wiringHome(sel.ID)]; h != nil {
		if w, ok := h.ScanWarnings[key]; ok {
			return sel.target.render(w)
		}
	}
	w, ok := s.matrix.Scan.Warnings[key]
	if !ok || (wiringHome(sel.ID) == "nano" && strings.Contains(w, "{tls_")) {
		return ""
	}
	return sel.target.render(w)
}

func (s *mcpServer) scanRepo(root string, maxFiles int, sel homeSel) (*scanReport, error) {
	if root == "" || !filepath.IsAbs(root) {
		return nil, fmt.Errorf("path must be an absolute directory path")
	}
	st, err := os.Stat(root)
	if err != nil || !st.IsDir() {
		return nil, fmt.Errorf("%s is not a directory", root)
	}
	table, err := s.scanRuleTable()
	if err != nil {
		return nil, err
	}
	var rules []scanRule
	var wired *regexp.Regexp
	for _, r := range table {
		if r.ID == scanWiredRuleID {
			wired = r.re
			continue
		}
		rules = append(rules, r)
	}
	skip := map[string]bool{}
	for _, d := range s.matrix.Scan.SkipDirs {
		skip[d] = true
	}
	exts := map[string]bool{}
	for _, e := range s.matrix.Scan.Extensions {
		exts[e] = true
	}

	rep := &scanReport{Root: root, Home: sel.ID, Clouds: map[string][]*scanService{}, Unrecognized: map[string][]string{}}
	levelKey := "offline"
	if wiringHome(sel.ID) == "nano" {
		levelKey = "nano"
	}
	found := map[string]map[string]*scanService{} // cloud → service → entry
	unknown := map[string]map[string]bool{}

	walkErr := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil // unreadable entry: skip, keep scanning
		}
		if d.IsDir() {
			if path != root && skip[d.Name()] {
				return filepath.SkipDir
			}
			return nil
		}
		ext := strings.ToLower(filepath.Ext(d.Name()))
		if ext == "" && strings.HasPrefix(d.Name(), ".env") {
			ext = ".env"
		}
		if !exts[ext] && !strings.HasPrefix(d.Name(), ".env") {
			return nil
		}
		if rep.FilesScanned >= maxFiles {
			rep.Truncated = true
			return filepath.SkipAll
		}
		info, err := d.Info()
		if err != nil || info.Size() > scanMaxFileBytes || !info.Mode().IsRegular() {
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil || bytes.IndexByte(data, 0) >= 0 { // unreadable or binary
			return nil
		}
		rep.FilesScanned++
		rel, _ := filepath.Rel(root, path)
		rel = filepath.ToSlash(rel)

		var langs []string
		for lang, es := range scanLangExts {
			for _, e := range es {
				if e == ext {
					langs = append(langs, lang)
				}
			}
		}
		sc := bufio.NewScanner(bytes.NewReader(data))
		sc.Buffer(make([]byte, 64*1024), scanMaxFileBytes)
		lineNo := 0
		for sc.Scan() {
			lineNo++
			line := sc.Text()
			if wired != nil && len(rep.AlreadyWired) < 10 && wired.MatchString(line) {
				rep.AlreadyWired = append(rep.AlreadyWired, scanHit{File: rel, Line: lineNo, Text: clip(line)})
			}
			for _, r := range rules {
				if !contains(langs, r.Lang) {
					continue
				}
				for _, m := range r.re.FindAllStringSubmatch(line, -1) {
					if len(m) < 2 {
						continue
					}
					svc := s.resolveAlias(r.Cloud, m[1])
					if svc == "_core" || svc == "_ignore" {
						continue
					}
					if svc == "" {
						if unknown[r.Cloud] == nil {
							unknown[r.Cloud] = map[string]bool{}
						}
						unknown[r.Cloud][m[1]] = true
						continue
					}
					if found[r.Cloud] == nil {
						found[r.Cloud] = map[string]*scanService{}
					}
					e := found[r.Cloud][svc]
					if e == nil {
						e = s.newScanService(r.Cloud, svc, levelKey, sel)
						found[r.Cloud][svc] = e
					}
					e.Uses++
					e.langSet[r.Lang] = true
					if len(e.Examples) < scanMaxHits {
						e.Examples = append(e.Examples, scanHit{File: rel, Line: lineNo, Lang: r.Lang, Text: clip(line)})
					}
				}
			}
		}
		return nil
	})
	if walkErr != nil {
		return nil, walkErr
	}

	s.collectScanServices(rep, found, unknown)
	s.summarize(rep)
	return rep, nil
}

// newScanService is one per-service entry of the report: the knowledge for cloud/svc in this home, with the
// home's warnings. Shared by the local walk and the hosted summary, so both grade a service the same way.
func (s *mcpServer) newScanService(cloud, svc, levelKey string, sel homeSel) *scanService {
	e := &scanService{Service: svc, Status: "not_emulated", langSet: map[string]bool{}}
	if ms := s.matrix.service(cloud, svc); ms != nil {
		e.Status, e.Name = ms.Status, ms.Name
		e.Level, e.Tier, e.Mesh, e.MeshOnly = ms.Levels[levelKey], ms.Tier, ms.Mesh, ms.MeshOnly
		if c := ms.LevelCounts[levelKey]; ms.Capabilities > 0 && c["not_simulated"] == ms.Capabilities {
			e.noneHere = true
		}
	}
	e.Warning = s.scanWarning(cloud+"/"+svc, sel)
	if e.Mesh && wiringHome(sel.ID) != "mesh" {
		// spec decision 9: never silently wired to a home that cannot run it
		mw := "needs a Pro/Max mesh: its main feature is mesh-only, so it does not run on Nano or the offline appliance."
		if e.Warning != "" {
			mw += " " + e.Warning
		}
		e.Warning = mw
	}
	return e
}

// collectScanServices fills rep.Clouds (most-used service first) and rep.Unrecognized from the maps both scan
// paths build.
func (s *mcpServer) collectScanServices(rep *scanReport, found map[string]map[string]*scanService, unknown map[string]map[string]bool) {
	for _, cloud := range mcpClouds {
		svcs := found[cloud]
		if len(svcs) == 0 {
			continue
		}
		list := make([]*scanService, 0, len(svcs))
		for _, e := range svcs {
			e.Langs = sortedKeys(e.langSet)
			list = append(list, e)
		}
		sort.Slice(list, func(i, j int) bool {
			if list[i].Uses != list[j].Uses {
				return list[i].Uses > list[j].Uses
			}
			return list[i].Service < list[j].Service
		})
		rep.Clouds[cloud] = list
	}
	for cloud, toks := range unknown {
		rep.Unrecognized[cloud] = sortedKeys(toks)
	}
	if len(rep.Unrecognized) == 0 {
		rep.Unrecognized = nil
	}
}

// scanToolNames are the tool names the report's next_steps point at: the local server names its own tools, the
// hosted one names the hosted tools (and tells the agent it writes the file itself).
type scanToolNames struct {
	env, propose, applyNote string
}

var (
	localScanTools  = scanToolNames{"vyomi_env", "vyomi_write_env", "With the user's OK: vyomi_write_env path=<project> clouds=[...] home="}
	hostedScanTools = scanToolNames{"get_sdk_settings", "propose_env_file", "With the user's OK: propose_env_file clouds=[...] home="}
)

func (s *mcpServer) summarize(rep *scanReport) { s.summarizeWith(rep, localScanTools) }

func (s *mcpServer) summarizeWith(rep *scanReport, names scanToolNames) {
	if len(rep.Clouds) == 0 {
		rep.Summary = []string{"No AWS, GCP or Azure SDK / Terraform usage found."}
		rep.NextSteps = []string{"Nothing to wire. If the project calls clouds through another library, call " + names.env + " to get the endpoint settings anyway."}
		return
	}
	for _, cloud := range mcpClouds {
		list := rep.Clouds[cloud]
		if len(list) == 0 {
			continue
		}
		var ok, gaps, warns []string
		langCount := map[string]int{}
		var meshNeeded []string
		for _, e := range list {
			switch {
			case !emulated(e.Status):
				gaps = append(gaps, e.Service)
			case e.noneHere:
				// in the registry, but not simulated in this home (e.g. EKS on Nano)
				gaps = append(gaps, e.Service+" (not simulated on "+rep.Home+")")
			case e.Mesh && wiringHome(rep.Home) != "mesh":
				meshNeeded = append(meshNeeded, e.Service)
			default:
				lv := e.Service
				if e.Level != "" {
					lv += " (" + e.Level + ")"
				}
				ok = append(ok, lv)
			}
			if e.Warning != "" {
				warns = append(warns, e.Service)
			}
			for _, l := range e.Langs {
				langCount[l] += e.Uses
			}
		}
		line := fmt.Sprintf("%s: %d service(s) used; emulated: %s", strings.ToUpper(cloud), len(list), joinOrNone(ok))
		if len(meshNeeded) > 0 {
			line += "; needs a Pro/Max mesh: " + strings.Join(meshNeeded, ", ")
		}
		if len(gaps) > 0 {
			line += "; NOT emulated: " + strings.Join(gaps, ", ")
		}
		if len(warns) > 0 {
			line += "; needs attention: " + strings.Join(warns, ", ")
		}
		rep.Summary = append(rep.Summary, line)

		best, bestN := "", -1
		for _, l := range sortedKeys(langCount) {
			if langCount[l] > bestN {
				best, bestN = l, langCount[l]
			}
		}
		rep.NextSteps = append(rep.NextSteps, fmt.Sprintf("%s cloud=%s lang=%s home=%s", names.env, cloud, best, wiringHomeArg(rep.Home)))
		if len(gaps) > 0 {
			rep.NextSteps = append(rep.NextSteps, fmt.Sprintf("%s services %s are not emulated: keep them on the real cloud (or stub them) during local runs.", strings.ToUpper(cloud), strings.Join(gaps, ", ")))
		}
	}
	if len(rep.AlreadyWired) > 0 {
		rep.NextSteps = append(rep.NextSteps, "Endpoint overrides already exist (see already_wired): reuse them instead of adding new ones.")
	}
	rep.NextSteps = append(rep.NextSteps, names.applyNote+wiringHomeArg(rep.Home))
	if names.propose == hostedScanTools.propose {
		rep.NextSteps = append(rep.NextSteps, "Nothing is written from here: show the user the file and write it with your own edit tool after they say yes.")
	}
}

// scanHitIn is one hit an agent found by running a rule from get_scan_rules with its own grep: the rule id, where
// it matched, and the captured service token. No source text: a rule's matched line never reaches this server
// (D-I1), and the already-wired rule carries no token at all.
type scanHitIn struct {
	Rule  string `json:"rule"`
	File  string `json:"file"`
	Line  int    `json:"line"`
	Token string `json:"token"`
}

const (
	scanMaxHitsIn   = 2000 // hits accepted in one summarize_scan_hits call (plan §4 rule 5)
	scanMaxTokenLen = 64
)

// scanTokenPattern is the only shape a captured token may have (D-I1): an identifier, not source text.
var scanTokenPattern = regexp.MustCompile(`^[A-Za-z0-9_.\-/]{1,64}$`)

// scanHitFile keeps a caller's file label to a plain repo-relative path, so the report cannot be used to echo
// arbitrary text back to the user.
var scanHitFile = regexp.MustCompile(`^[A-Za-z0-9_.\-/\\ +@]{1,256}$`)

// summarizeHits builds the same report as scanRepo, from hits an agent found locally instead of a file walk.
// Identical knowledge, identical shape: only the examples carry no source text and files_scanned is replaced by
// hits_received.
func (s *mcpServer) summarizeHits(hits []scanHitIn, sel homeSel) (*scanReport, error) {
	if len(hits) > scanMaxHitsIn {
		return nil, fmt.Errorf("too many hits: %d (at most %d per call; run the rules per directory and summarize each batch)", len(hits), scanMaxHitsIn)
	}
	table, err := s.scanRuleTable()
	if err != nil {
		return nil, err
	}
	byID := scanRuleByID(table)
	rep := &scanReport{Home: sel.ID, HitsReceived: len(hits), Clouds: map[string][]*scanService{}, Unrecognized: map[string][]string{}}
	levelKey := "offline"
	if wiringHome(sel.ID) == "nano" {
		levelKey = "nano"
	}
	found := map[string]map[string]*scanService{}
	unknown := map[string]map[string]bool{}

	for i, h := range hits {
		r := byID[strings.TrimSpace(h.Rule)]
		if r == nil {
			return nil, fmt.Errorf("hit %d names an unknown rule %q; use the ids from get_scan_rules", i+1, h.Rule)
		}
		file := strings.TrimSpace(h.File)
		if file == "" || !scanHitFile.MatchString(file) {
			return nil, fmt.Errorf("hit %d: file must be a repo-relative path (got %q)", i+1, h.File)
		}
		file = filepath.ToSlash(file)
		if h.Line < 0 {
			return nil, fmt.Errorf("hit %d: line must be 0 or more (got %d)", i+1, h.Line)
		}
		if r.ID == scanWiredRuleID {
			// Endpoint overrides the project already has: file:line only, never the matched text.
			if len(rep.AlreadyWired) < 10 {
				rep.AlreadyWired = append(rep.AlreadyWired, scanHit{File: file, Line: h.Line})
			}
			continue
		}
		token := strings.TrimSpace(h.Token)
		if token == "" {
			return nil, fmt.Errorf("hit %d (%s): token is required; send capture group %d of the rule's regex (e.g. \"s3\" from boto3.client(\"s3\"))", i+1, r.ID, r.TokenGroup)
		}
		if len(token) > scanMaxTokenLen || !scanTokenPattern.MatchString(token) {
			return nil, fmt.Errorf("hit %d (%s): token %q is not an identifier; send only the captured service token, never the matched line", i+1, r.ID, clip(token))
		}
		svc := s.resolveAlias(r.Cloud, token)
		if svc == "_core" || svc == "_ignore" {
			continue
		}
		if svc == "" {
			if unknown[r.Cloud] == nil {
				unknown[r.Cloud] = map[string]bool{}
			}
			unknown[r.Cloud][strings.ToLower(token)] = true
			continue
		}
		if found[r.Cloud] == nil {
			found[r.Cloud] = map[string]*scanService{}
		}
		e := found[r.Cloud][svc]
		if e == nil {
			e = s.newScanService(r.Cloud, svc, levelKey, sel)
			found[r.Cloud][svc] = e
		}
		e.Uses++
		e.langSet[r.Lang] = true
		if len(e.Examples) < scanMaxHits {
			e.Examples = append(e.Examples, scanHit{File: file, Line: h.Line, Lang: r.Lang})
		}
	}
	s.collectScanServices(rep, found, unknown)
	s.summarizeWith(rep, hostedScanTools)
	return rep, nil
}

func joinOrNone(xs []string) string {
	if len(xs) == 0 {
		return "none"
	}
	return strings.Join(xs, ", ")
}

func clip(s string) string {
	s = strings.TrimSpace(s)
	if len(s) > 160 {
		return s[:157] + "..."
	}
	return s
}

func contains(xs []string, x string) bool {
	for _, v := range xs {
		if v == x {
			return true
		}
	}
	return false
}

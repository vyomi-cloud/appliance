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
	Lang string `json:"lang"`
	Text string `json:"text"`
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
	Root         string                    `json:"root"`
	Home         string                    `json:"home"`
	FilesScanned int                       `json:"files_scanned"`
	Truncated    bool                      `json:"truncated"`
	Clouds       map[string][]*scanService `json:"clouds"`
	Unrecognized map[string][]string       `json:"unrecognized,omitempty"`
	AlreadyWired []scanHit                 `json:"already_wired"`
	Summary      []string                  `json:"summary"`
	NextSteps    []string                  `json:"next_steps"`
}

type compiledRule struct {
	cloud, lang string
	re          *regexp.Regexp
}

func (s *mcpServer) compileScanRules() ([]compiledRule, *regexp.Regexp, error) {
	var rules []compiledRule
	for _, r := range s.matrix.Scan.Rules {
		re, err := regexp.Compile(r.Pattern)
		if err != nil {
			return nil, nil, fmt.Errorf("scan rule %s/%s: %v", r.Cloud, r.Lang, err)
		}
		rules = append(rules, compiledRule{r.Cloud, r.Lang, re})
	}
	var wired *regexp.Regexp
	if s.matrix.Scan.AlreadyWired != "" {
		var err error
		if wired, err = regexp.Compile(s.matrix.Scan.AlreadyWired); err != nil {
			return nil, nil, fmt.Errorf("already_wired pattern: %v", err)
		}
	}
	return rules, wired, nil
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
	rules, wired, err := s.compileScanRules()
	if err != nil {
		return nil, err
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
				if !contains(langs, r.lang) {
					continue
				}
				for _, m := range r.re.FindAllStringSubmatch(line, -1) {
					if len(m) < 2 {
						continue
					}
					svc := s.resolveAlias(r.cloud, m[1])
					if svc == "_core" || svc == "_ignore" {
						continue
					}
					if svc == "" {
						if unknown[r.cloud] == nil {
							unknown[r.cloud] = map[string]bool{}
						}
						unknown[r.cloud][m[1]] = true
						continue
					}
					if found[r.cloud] == nil {
						found[r.cloud] = map[string]*scanService{}
					}
					e := found[r.cloud][svc]
					if e == nil {
						e = &scanService{Service: svc, Status: "not_emulated", langSet: map[string]bool{}}
						if ms := s.matrix.service(r.cloud, svc); ms != nil {
							e.Status, e.Name = ms.Status, ms.Name
							e.Level, e.Tier, e.Mesh, e.MeshOnly = ms.Levels[levelKey], ms.Tier, ms.Mesh, ms.MeshOnly
							if c := ms.LevelCounts[levelKey]; ms.Capabilities > 0 && c["not_simulated"] == ms.Capabilities {
								e.noneHere = true
							}
						}
						e.Warning = s.scanWarning(r.cloud+"/"+svc, sel)
						if e.Mesh && wiringHome(sel.ID) != "mesh" {
							// spec decision 9: never silently wired to a home that cannot run it
							mw := "needs a Pro/Max mesh: its main feature is mesh-only, so it does not run on Nano or the offline appliance."
							if e.Warning != "" {
								mw += " " + e.Warning
							}
							e.Warning = mw
						}
						found[r.cloud][svc] = e
					}
					e.Uses++
					e.langSet[r.lang] = true
					if len(e.Examples) < scanMaxHits {
						e.Examples = append(e.Examples, scanHit{File: rel, Line: lineNo, Lang: r.lang, Text: clip(line)})
					}
				}
			}
		}
		return nil
	})
	if walkErr != nil {
		return nil, walkErr
	}

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
	s.summarize(rep)
	return rep, nil
}

func (s *mcpServer) summarize(rep *scanReport) {
	if len(rep.Clouds) == 0 {
		rep.Summary = []string{"No AWS, GCP or Azure SDK / Terraform usage found."}
		rep.NextSteps = []string{"Nothing to wire. If the project calls clouds through another library, call vyomi_env to get the endpoint settings anyway."}
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
		rep.NextSteps = append(rep.NextSteps, fmt.Sprintf("vyomi_env cloud=%s lang=%s home=%s", cloud, best, wiringHomeArg(rep.Home)))
		if len(gaps) > 0 {
			rep.NextSteps = append(rep.NextSteps, fmt.Sprintf("%s services %s are not emulated: keep them on the real cloud (or stub them) during local runs.", strings.ToUpper(cloud), strings.Join(gaps, ", ")))
		}
	}
	if len(rep.AlreadyWired) > 0 {
		rep.NextSteps = append(rep.NextSteps, "Endpoint overrides already exist (see already_wired): reuse them instead of adding new ones.")
	}
	rep.NextSteps = append(rep.NextSteps, "With the user's OK: vyomi_write_env path=<project> clouds=[...] home="+wiringHomeArg(rep.Home))
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

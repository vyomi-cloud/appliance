package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// AppProfile represents the .vyomi/app.json schema.
type AppProfile struct {
	Version   int                          `json:"version"`
	Name      string                       `json:"name"`
	Resources map[string]any               `json:"resources"`
	Outputs   map[string]map[string]string `json:"outputs"`
}

// AppRecord is a single entry in ~/.vyomi/apps.json.
type AppRecord struct {
	Name     string `json:"name"`
	RepoPath string `json:"repo_path"`
	AddedAt  string `json:"added_at"`
}

// AppRegistry manages known applications in ~/.vyomi/apps.json.
type AppRegistry struct {
	Apps map[string]*AppRecord `json:"apps"`
}

var (
	validAppName = regexp.MustCompile(`^[a-zA-Z_][a-zA-Z0-9_]{0,62}$`)
	exprRegex    = regexp.MustCompile(`\$\{([a-zA-Z0-9_.]+)\}`)
)

func (c *Config) loadRegistry() (*AppRegistry, error) {
	path := filepath.Join(c.VyomiHome, "apps.json")
	reg := &AppRegistry{Apps: make(map[string]*AppRecord)}

	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return reg, nil
		}
		return nil, fmt.Errorf("cannot read apps registry: %w", err)
	}

	if err := json.Unmarshal(data, reg); err != nil {
		return reg, nil
	}
	if reg.Apps == nil {
		reg.Apps = make(map[string]*AppRecord)
	}
	return reg, nil
}

func (c *Config) saveRegistry(reg *AppRegistry) error {
	_ = os.MkdirAll(c.VyomiHome, 0700)
	path := filepath.Join(c.VyomiHome, "apps.json")

	data, err := json.MarshalIndent(reg, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0600)
}

// ValidateProfile validates an AppProfile against the spec schema rules.
func ValidateProfile(profile *AppProfile) error {
	if profile.Version != 1 {
		return fmt.Errorf("unsupported profile version %d: expected 1", profile.Version)
	}
	if !validAppName.MatchString(profile.Name) {
		return fmt.Errorf("invalid app name %q: must match ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$", profile.Name)
	}
	if profile.Resources == nil {
		return errors.New("missing 'resources' object in profile")
	}
	if profile.Outputs == nil {
		return errors.New("missing 'outputs' object in profile")
	}

	// Validate allowed resource categories
	allowedTypes := map[string]bool{
		"postgres": true, "blob": true, "redis": true, "servicebus": true,
	}
	for resType := range profile.Resources {
		if !allowedTypes[resType] {
			return fmt.Errorf("unknown resource type %q in 'resources'", resType)
		}
	}

	// Validate output expressions
	for outFile, varMap := range profile.Outputs {
		cleanOut := filepath.Clean(filepath.FromSlash(outFile))
		if filepath.IsAbs(outFile) || cleanOut == ".." || strings.HasPrefix(cleanOut, ".."+string(filepath.Separator)) {
			return fmt.Errorf("invalid output path %q: must be relative to repo root", outFile)
		}
		for varName, expr := range varMap {
			cleanExpr := strings.ReplaceAll(expr, "$${", "")
			matches := exprRegex.FindAllStringSubmatch(cleanExpr, -1)
			for _, m := range matches {
				ref := m[1]
				parts := strings.Split(ref, ".")
				if parts[0] == "secret" {
					if len(parts) != 2 || !validAppName.MatchString(parts[1]) {
						return fmt.Errorf("malformed secret reference ${%s} in %s:%s", ref, outFile, varName)
					}
				} else {
					if len(parts) != 3 {
						return fmt.Errorf("malformed resource reference ${%s} in %s:%s (expected resource.name.field)", ref, outFile, varName)
					}
					if !allowedTypes[parts[0]] {
						return fmt.Errorf("unknown resource type %q in ${%s} in %s:%s", parts[0], ref, outFile, varName)
					}
				}
			}
		}
	}

	return nil
}

// LoadProfile loads and validates a .vyomi/app.json from a repository directory.
func LoadProfile(repoDir string) (*AppProfile, error) {
	profilePath := filepath.Join(repoDir, ".vyomi", "app.json")
	data, err := os.ReadFile(profilePath)
	if err != nil {
		return nil, fmt.Errorf("cannot read %s: %w", profilePath, err)
	}

	var p AppProfile
	if err := json.Unmarshal(data, &p); err != nil {
		return nil, fmt.Errorf("malformed JSON in %s: %w", profilePath, err)
	}

	if err := ValidateProfile(&p); err != nil {
		return nil, fmt.Errorf("invalid profile in %s: %w", profilePath, err)
	}

	return &p, nil
}

// resolveAppRepo returns the absolute repository path for an app, either
// from --app <name> lookup in the registry or from current working directory.
func (c *Config) resolveAppRepo(appName string) (string, *AppProfile, error) {
	if appName != "" {
		reg, err := c.loadRegistry()
		if err != nil {
			return "", nil, err
		}
		rec, found := reg.Apps[appName]
		if !found {
			return "", nil, fmt.Errorf("app %q not found in registry (run 'vyomi app add <path>')", appName)
		}
		p, err := LoadProfile(rec.RepoPath)
		if err != nil {
			return "", nil, err
		}
		return rec.RepoPath, p, nil
	}

	// Try current directory
	cwd, err := os.Getwd()
	if err != nil {
		return "", nil, err
	}
	p, err := LoadProfile(cwd)
	if err == nil {
		return cwd, p, nil
	}

	return "", nil, errors.New("no app specified; use --app <name> or run from a repo containing .vyomi/app.json")
}

// dispatchApp handles `vyomi app <subcommand> [args]`.
func (c *Config) dispatchApp(args []string) int {
	if len(args) == 0 {
		fmt.Println("Usage: vyomi app add <path> | list | remove <name> | provision [--app <name>] | status [--app <name>]")
		return 2
	}

	sub := args[0]
	rest := args[1:]

	switch sub {
	case "add":
		return c.appAdd(rest)
	case "list":
		return c.appDumpList()
	case "remove", "rm":
		return c.appRemove(rest)
	case "provision":
		return c.appProvision(rest)
	case "status":
		return c.appStatus(rest)
	default:
		fmt.Printf("vyomi app: unknown subcommand %q\n", sub)
		return 2
	}
}

func (c *Config) appAdd(args []string) int {
	if len(args) == 0 {
		fmt.Println("Usage: vyomi app add <path-to-repo>")
		return 2
	}
	pathArg := args[0]
	absPath, err := filepath.Abs(pathArg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app add: invalid path: %v\n", err)
		return 1
	}

	profile, err := LoadProfile(absPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app add: %v\n", err)
		return 1
	}

	reg, err := c.loadRegistry()
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app add: %v\n", err)
		return 1
	}

	reg.Apps[profile.Name] = &AppRecord{
		Name:     profile.Name,
		RepoPath: absPath,
		AddedAt:  time.Now().UTC().Format(time.RFC3339),
	}

	if err := c.saveRegistry(reg); err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app add: failed to save registry: %v\n", err)
		return 1
	}

	fmt.Printf("✓ Registered app %q from %s\n", profile.Name, absPath)
	return 0
}

func (c *Config) appDumpList() int {
	reg, err := c.loadRegistry()
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app list: %v\n", err)
		return 1
	}

	if len(reg.Apps) == 0 {
		fmt.Println("No applications registered. Register one with: vyomi app add <path>")
		return 0
	}

	fmt.Printf("%-18s %-45s %s\n", "NAME", "REPO PATH", "ADDED AT")
	fmt.Printf("%-18s %-45s %s\n", strings.Repeat("-", 18), strings.Repeat("-", 45), strings.Repeat("-", 20))
	for _, app := range reg.Apps {
		fmt.Printf("%-18s %-45s %s\n", app.Name, app.RepoPath, app.AddedAt)
	}
	return 0
}

func (c *Config) appRemove(args []string) int {
	if len(args) == 0 {
		fmt.Println("Usage: vyomi app remove <name>")
		return 2
	}
	appName := args[0]

	reg, err := c.loadRegistry()
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app remove: %v\n", err)
		return 1
	}

	if _, exists := reg.Apps[appName]; !exists {
		fmt.Printf("App %q not found in registry\n", appName)
		return 1
	}

	delete(reg.Apps, appName)
	if err := c.saveRegistry(reg); err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app remove: %v\n", err)
		return 1
	}

	fmt.Printf("✓ Removed app %q from registry (resources left intact)\n", appName)
	return 0
}

func (c *Config) appProvision(args []string) int {
	fs := flag.NewFlagSet("app-provision", flag.ContinueOnError)
	appFlag := fs.String("app", "", "app name from registry")
	if err := fs.Parse(args); err != nil {
		return 2
	}

	_, profile, err := c.resolveAppRepo(*appFlag)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app provision: %v\n", err)
		return 1
	}

	adminKey, err := c.getAdminKey()
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app provision: %v\n", err)
		return 1
	}

	applianceURL := c.applianceURL()
	endpoint := fmt.Sprintf("%s/api/runtime/apps/%s/provision", applianceURL, profile.Name)

	reqBody, _ := json.Marshal(map[string]any{"resources": profile.Resources})
	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(reqBody))
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app provision: %v\n", err)
		return 1
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-CloudLearn-Admin-Key", adminKey)

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app provision: request failed: %v (is vyomi running?)\n", err)
		return 1
	}
	defer resp.Body.Close()

	respBytes, _ := io.ReadAll(resp.Body)
	if resp.StatusCode == 403 {
		fmt.Fprintln(os.Stderr, "vyomi app provision: 403 Forbidden (admin key rejected)")
		return 1
	}
	if resp.StatusCode != 200 {
		fmt.Fprintf(os.Stderr, "vyomi app provision: failed (HTTP %d): %s\n", resp.StatusCode, string(respBytes))
		return 1
	}

	var result struct {
		Ok        bool           `json:"ok"`
		App       string         `json:"app"`
		Resources map[string]any `json:"resources"`
	}
	_ = json.Unmarshal(respBytes, &result)

	if result.Ok {
		fmt.Printf("==> Successfully provisioned resources for %q:\n", profile.Name)
	} else {
		fmt.Printf("==> Provisioning completed with errors for %q:\n", profile.Name)
	}
	for resType, val := range result.Resources {
		typeOk := true
		var lines []string
		if subMap, ok := val.(map[string]any); ok {
			for subName, subDetail := range subMap {
				if detailMap, ok := subDetail.(map[string]any); ok {
					switch detailMap["status"] {
					case "warning":
						lines = append(lines, fmt.Sprintf("      - %s: warning (%v)", subName, detailMap["warning"]))
					case "error":
						typeOk = false
						lines = append(lines, fmt.Sprintf("      - %s: error (%v)", subName, detailMap["error"]))
					default:
						lines = append(lines, fmt.Sprintf("      - %s: %v", subName, detailMap["status"]))
					}
				}
			}
		}
		if typeOk {
			fmt.Printf("  • %-12s: ok\n", resType)
		} else {
			fmt.Printf("  • %-12s: error\n", resType)
		}
		for _, l := range lines {
			fmt.Println(l)
		}
	}
	if !result.Ok {
		return 1
	}
	return 0
}

func (c *Config) appStatus(args []string) int {
	fs := flag.NewFlagSet("app-status", flag.ContinueOnError)
	appFlag := fs.String("app", "", "app name from registry")
	if err := fs.Parse(args); err != nil {
		return 2
	}

	_, profile, err := c.resolveAppRepo(*appFlag)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app status: %v\n", err)
		return 1
	}

	applianceURL := c.applianceURL()
	resp, err := http.Get(applianceURL + "/api/runtime/endpoints")
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi app status: cannot reach appliance at %s: %v\n", applianceURL, err)
		return 1
	}
	defer resp.Body.Close()

	var endpoints map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&endpoints)

	fmt.Printf("App %q status:\n", profile.Name)
	for resType := range profile.Resources {
		ep, exists := endpoints[resType]
		if !exists {
			fmt.Printf("  • %-12s: available via runtime\n", resType)
			continue
		}
		if epMap, ok := ep.(map[string]any); ok {
			if pub, ok := epMap["published"].(map[string]any); ok {
				fmt.Printf("  • %-12s: reachable at %v:%v\n", resType, pub["host"], pub["port"])
				continue
			}
		}
		fmt.Printf("  • %-12s: ready\n", resType)
	}
	return 0
}

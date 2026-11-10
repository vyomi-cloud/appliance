package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// DiffItem describes a planned addition or change in a dotenv file.
type DiffItem struct {
	Key   string
	Old   string
	New   string
	IsAdd bool
}

// dispatchEnv handles `vyomi env [flags]`.
func (c *Config) dispatchEnv(args []string) int {
	fs := flag.NewFlagSet("env", flag.ContinueOnError)
	appFlag := fs.String("app", "", "app name from registry (default: read .vyomi/app.json in cwd)")
	targetFlag := fs.String("target", "host", "target execution environment: host or docker")
	dryRunFlag := fs.Bool("dry-run", false, "print diff without writing files")
	checkFlag := fs.Bool("check", false, "exit 1 if any file would change, 0 if up to date")
	showSecretsFlag := fs.Bool("show-secrets", false, "show unmasked secrets in diff output")
	allowTrackedFlag := fs.Bool("allow-tracked", false, "allow writing secrets into git-tracked .env files")

	if err := fs.Parse(args); err != nil {
		return 2
	}

	target := strings.ToLower(strings.TrimSpace(*targetFlag))
	if target != "host" && target != "docker" {
		fmt.Fprintf(os.Stderr, "vyomi env: invalid --target %q: must be 'host' or 'docker'\n", *targetFlag)
		return 1
	}

	repoDir, profile, err := c.resolveAppRepo(*appFlag)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi env: %v\n", err)
		return 1
	}

	if !have("git") {
		fmt.Fprintln(os.Stderr, "Warning: git is not installed; skipping git-tracked file safety check.")
	}

	// Test 6a: warn if target is docker and host.docker.internal does not resolve on this host
	if target == "docker" {
		if _, err := net.LookupHost("host.docker.internal"); err != nil {
			fmt.Fprintln(os.Stderr, "Warning: host.docker.internal does not resolve on this machine; containerized apps may require extra_hosts: [\"host.docker.internal:host-gateway\"] in compose.")
		}
	}

	adminKey, err := c.getAdminKey()
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi env: %v\n", err)
		return 1
	}

	applianceURL := c.applianceURL()
	endpoint := fmt.Sprintf("%s/api/runtime/apps/%s/resolve", applianceURL, profile.Name)

	reqPayload := map[string]any{
		"outputs": profile.Outputs,
		"target":  target,
	}
	reqBytes, _ := json.Marshal(reqPayload)

	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(reqBytes))
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi env: %v\n", err)
		return 1
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-CloudLearn-Admin-Key", adminKey)

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi env: request failed: %v (is vyomi running?)\n", err)
		return 1
	}
	defer resp.Body.Close()

	respBytes, _ := io.ReadAll(resp.Body)
	if resp.StatusCode == 403 {
		fmt.Fprintln(os.Stderr, "vyomi env: 403 Forbidden (admin key rejected)")
		return 1
	}
	if resp.StatusCode != 200 {
		fmt.Fprintf(os.Stderr, "vyomi env: failed (HTTP %d): %s\n", resp.StatusCode, string(respBytes))
		return 1
	}

	var result struct {
		Ok       bool                         `json:"ok"`
		App      string                       `json:"app"`
		Target   string                       `json:"target"`
		Resolved map[string]map[string]string `json:"resolved"`
		Warnings []string                     `json:"warnings"`
	}
	if err := json.Unmarshal(respBytes, &result); err != nil {
		fmt.Fprintf(os.Stderr, "vyomi env: invalid response JSON: %v\n", err)
		return 1
	}

	for _, w := range result.Warnings {
		fmt.Fprintf(os.Stderr, "Warning: %s\n", w)
	}

	// On Multipass with host target, substitute the VM IP for localhost and 127.0.0.1
	if c.resolveSubstrate() == "multipass" && target == "host" {
		vmIp := c.applianceIp()
		if vmIp != "" {
			for _, kvs := range result.Resolved {
				for k, v := range kvs {
					if strings.Contains(v, "localhost") {
						kvs[k] = strings.ReplaceAll(v, "localhost", vmIp)
					} else if strings.Contains(v, "127.0.0.1") {
						kvs[k] = strings.ReplaceAll(v, "127.0.0.1", vmIp)
					}
				}
			}
		}
	}

	var files []string
	for f := range result.Resolved {
		files = append(files, f)
	}
	sort.Strings(files)

	hasAnyChanges := false

	// Check or Dry-run handling
	if *checkFlag || *dryRunFlag {
		for _, relPath := range files {
			updates := result.Resolved[relPath]
			cleanRel := filepath.FromSlash(relPath)
			targetPath := filepath.Join(repoDir, cleanRel)

			var content []byte
			if data, err := os.ReadFile(targetPath); err == nil {
				content = data
			} else if !errors.Is(err, os.ErrNotExist) {
				fmt.Fprintf(os.Stderr, "vyomi env: cannot read %s: %v\n", targetPath, err)
				return 1
			}

			df := ParseDotenv(content)
			var diffs []DiffItem
			for k, v := range updates {
				if idx, found := df.KeyIndex[k]; found {
					if df.Lines[idx].Value != v {
						diffs = append(diffs, DiffItem{Key: k, Old: df.Lines[idx].Value, New: v, IsAdd: false})
					}
				} else {
					diffs = append(diffs, DiffItem{Key: k, New: v, IsAdd: true})
				}
			}

			if len(diffs) > 0 {
				hasAnyChanges = true
				sort.Slice(diffs, func(i, j int) bool { return diffs[i].Key < diffs[j].Key })
				fmt.Printf("File %s would change:\n", relPath)
				for _, d := range diffs {
					oldVal := d.Old
					newVal := d.New
					if !*showSecretsFlag {
						if !d.IsAdd {
							oldVal = MaskEnvValue(d.Key, oldVal)
						}
						newVal = MaskEnvValue(d.Key, newVal)
					}
					if d.IsAdd {
						fmt.Printf("  + %s = %s\n", d.Key, newVal)
					} else {
						fmt.Printf("  ~ %s = %s -> %s\n", d.Key, oldVal, newVal)
					}
				}
			} else if *dryRunFlag {
				fmt.Printf("File %s: no changes\n", relPath)
			}
		}

		if *checkFlag {
			if hasAnyChanges {
				return 1
			}
			fmt.Println("All environment files are up to date.")
			return 0
		}
		return 0
	}

	// Normal write
	for _, relPath := range files {
		updates := result.Resolved[relPath]
		changed, err := WriteDotenv(repoDir, relPath, profile.Name, updates, *allowTrackedFlag)
		if err != nil {
			fmt.Fprintf(os.Stderr, "vyomi env: %v\n", err)
			return 1
		}
		if len(changed) == 0 {
			fmt.Printf("✓ %s is up to date (no changes)\n", relPath)
		} else {
			fmt.Printf("✓ Updated %s (%d variables changed)\n", relPath, len(changed))
		}
	}

	return 0
}

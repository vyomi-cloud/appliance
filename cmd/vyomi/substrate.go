package main

import (
	"os"
	"path/filepath"
	"strings"
)

// resolveSubstrate mirrors Resolve-Substrate: one launcher, two substrates —
// Docker (Free/Lite/Pro) and Multipass (Max). Resolution order: explicit
// VYOMI_SUBSTRATE → ~/.vyomi/tier → ~/.vyomi/substrate → auto-detect.
func (c *Config) resolveSubstrate() string {
	s := strings.ToLower(strings.TrimSpace(os.Getenv("VYOMI_SUBSTRATE")))

	if s == "" {
		if b, err := os.ReadFile(filepath.Join(c.VyomiHome, "tier")); err == nil {
			switch strings.ToLower(strings.TrimSpace(string(b))) {
			case "max", "enterprise":
				s = "multipass"
			case "free", "lite", "pro", "nano", "micro":
				s = "docker"
			}
		}
	}
	if s == "" {
		if b, err := os.ReadFile(filepath.Join(c.VyomiHome, "substrate")); err == nil {
			s = strings.ToLower(strings.TrimSpace(string(b)))
		}
	}
	if s == "" {
		if have("multipass") && c.applianceExists() {
			s = "multipass"
		} else {
			s = "docker"
		}
	}
	if s == "multipass" {
		return "multipass"
	}
	return "docker"
}

// persistSubstrate records an EXPLICIT --docker/--multipass choice so later
// `vyomi up` (no flag) remembers it.
func (c *Config) persistSubstrate(s string) {
	if s == "" {
		return
	}
	_ = os.MkdirAll(c.VyomiHome, 0o755)
	_ = os.WriteFile(filepath.Join(c.VyomiHome, "substrate"), []byte(s), 0o644)
}

// applianceExists reports whether the Multipass appliance VM record exists.
func (c *Config) applianceExists() bool {
	return runQuiet("multipass", "info", c.ApplianceName)
}

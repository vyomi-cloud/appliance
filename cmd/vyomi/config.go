package main

import (
	"os"
	"path/filepath"
	"strings"
)

// Config mirrors the launcher's resolved settings (the PowerShell param/env block).
// Both VYOMI_* (preferred) and legacy CLOUD_LEARN_* env vars are honored.
type Config struct {
	RootDir        string // dir containing the vyomi sources (compose files live here)
	ProjectName    string
	ComposeFile    string
	RuntimeContext string // "outer" (host launcher) | "inner" (inside the appliance)
	ApplianceName  string
	VyomiHome      string // ~/.vyomi
	ApplianceDir   string
	ApplianceImage string
	Cpus           int
	Memory         string // e.g. "8G"
	Disk           string // e.g. "40G"
	Workspace      string
	ExeDir         string
}

// envAny returns the first non-empty env var from names, else def.
func envAny(def string, names ...string) string {
	for _, n := range names {
		if v := strings.TrimSpace(os.Getenv(n)); v != "" {
			return v
		}
	}
	return def
}

func homeDir() string {
	if h, err := os.UserHomeDir(); err == nil {
		return h
	}
	return envAny("", "USERPROFILE", "HOME")
}

func loadConfig() *Config {
	exe, _ := os.Executable()
	exeDir := filepath.Dir(exe)
	// Installed layout: <INSTALLFOLDER>\bin\vyomi.exe, sources at <INSTALLFOLDER>\.
	rootDefault := filepath.Dir(exeDir)

	c := &Config{ExeDir: exeDir}
	c.VyomiHome = filepath.Join(homeDir(), ".vyomi")
	c.RootDir = envAny(rootDefault, "VYOMI_HOME", "CLOUD_LEARN_HOME")
	if abs, err := filepath.Abs(c.RootDir); err == nil {
		c.RootDir = abs
	}
	c.ProjectName = envAny("cloud-learn", "VYOMI_PROJECT_NAME", "CLOUD_LEARN_PROJECT_NAME")
	c.ComposeFile = envAny(filepath.Join(c.RootDir, "docker-compose.appliance.yml"),
		"VYOMI_COMPOSE_FILE", "CLOUD_LEARN_COMPOSE_FILE")

	rc := strings.ToLower(envAny("outer", "VYOMI_RUNTIME_CONTEXT", "CLOUD_LEARN_RUNTIME_CONTEXT"))
	if rc != "inner" {
		rc = "outer"
	}
	c.RuntimeContext = rc

	c.ApplianceName = envAny("cloudlearn-appliance", "VYOMI_APPLIANCE_NAME", "CLOUD_LEARN_APPLIANCE_NAME")
	c.ApplianceDir = envAny(filepath.Join(c.VyomiHome, "appliance", c.ApplianceName),
		"VYOMI_APPLIANCE_DIR", "CLOUD_LEARN_APPLIANCE_DIR")
	c.ApplianceImage = envAny("24.04", "VYOMI_APPLIANCE_IMAGE", "CLOUD_LEARN_APPLIANCE_IMAGE")
	c.Workspace = envAny("/workspace/cloud-learn", "VYOMI_APPLIANCE_WORKSPACE", "CLOUD_LEARN_APPLIANCE_WORKSPACE")

	sz := recommendedSizing()
	c.Cpus = atoiDefault(envAny("", "VYOMI_APPLIANCE_CPUS", "CLOUD_LEARN_APPLIANCE_CPUS"), sz.Cpus)
	c.Memory = envAny(itoaG(sz.MemGb), "VYOMI_APPLIANCE_MEMORY", "CLOUD_LEARN_APPLIANCE_MEMORY")
	c.Disk = envAny(itoaG(sz.DiskGb), "VYOMI_APPLIANCE_DISK", "CLOUD_LEARN_APPLIANCE_DISK")

	// Keep both env prefixes in sync for child processes (matches the PS1).
	os.Setenv("CLOUDLEARN_DISTRIBUTION_MODE", "appliance")
	os.Setenv("CLOUD_LEARN_RUNTIME_CONTEXT", rc)
	os.Setenv("VYOMI_RUNTIME_CONTEXT", rc)
	// Multipass lands on PATH only in shells opened AFTER its install; add the
	// default dir so `vyomi up` finds it without the user fixing PATH by hand.
	if rc == "outer" {
		addMultipassToPath()
	}
	return c
}

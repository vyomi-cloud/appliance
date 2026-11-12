// Command vyomi is the compiled Vyomi launcher CLI — the single native binary that
// replaces scripts/cloud-learn.ps1 (and the shell launchers). It orchestrates the
// local multi-cloud simulator over two substrates: Docker (Free/Lite/Pro) and a
// Multipass VM (Max). Shipping a compiled binary (not a modifiable on-disk script)
// is what lets the package satisfy winget's no-scripted-applications policy.
package main

import (
	"fmt"
	"os"
	"strings"
)

func progress(msg string) {
	fmt.Fprintln(os.Stderr, msg)
	logAppend(msg)
}

func usage() {
	fmt.Print(`vyomi - local multi-cloud simulator launcher

Usage:
  vyomi up          Boot the simulator (Docker tiers) or the appliance VM (Max)
  vyomi down        Stop the simulator / VM
  vyomi stop        Alias for down
  vyomi force-stop  Force-stop the VM
  vyomi restart     Restart the stack / VM
  vyomi status      Show status
  vyomi logs        Tail service logs (Docker tiers)
  vyomi update      Pull the latest images and recreate (Docker tiers)
  vyomi upgrade     Pull the latest appliance image (Max)
  vyomi app         Manage app profiles (add, list, remove, provision, status)
  vyomi env         Generate or verify .env files from app profile
  vyomi db          Database operations (dump, restore, refresh)
  vyomi redis       Redis operations (flush)
  vyomi mesh status [--json]   Mesh (headless Pro/Max) health, tier, trial, 70% cap usage
  vyomi mesh pair              Print a pairing code to attach the Nano UI at vyomi.cloud
  vyomi doctor      Print diagnostics
  vyomi mcp         MCP server (stdio) for AI agents: claude mcp add vyomi -- vyomi mcp
  vyomi help        This help

Substrate: --docker or --multipass (remembered for next time)

Environment (VYOMI_* preferred; CLOUD_LEARN_* still honored):
  VYOMI_HOME              Root dir containing the vyomi sources
  VYOMI_COMPOSE_FILE      Override the compose file
  VYOMI_SIMULATOR_PORT    Appliance/simulator port (default: 9000)
  VYOMI_SUBSTRATE         docker | multipass
  VYOMI_APPLIANCE_NAME    Multipass VM name (default: cloudlearn-appliance)
  VYOMI_APPLIANCE_CPUS/MEMORY/DISK   VM sizing overrides
  VYOMI_NO_OPEN=1         (no effect: appliance is headless)
`)
}

func (c *Config) doctor() {
	fmt.Println("vyomi root:", c.RootDir)
	fmt.Println("compose file:", c.ComposeFile)
	fmt.Println("runtime context:", c.RuntimeContext)
	if c.RuntimeContext == "inner" {
		fmt.Println("docker:", availStr(have("docker")))
		fmt.Println("engine:", ternary(engineReachable(), "reachable", "unreachable"))
		fmt.Println("mode: appliance inner stack")
		return
	}
	fmt.Println("substrate:", c.resolveSubstrate())
	fmt.Println("multipass:", availStr(have("multipass")))
	state := "absent"
	if c.applianceExists() {
		state = "present"
	}
	fmt.Println("appliance VM:", state)
	fmt.Println("mode: appliance launcher")
}

func availStr(ok bool) string { return ternary(ok, "available", "missing") }
func ternary(b bool, t, f string) string {
	if b {
		return t
	}
	return f
}

func main() {
	c := loadConfig()

	// Installed as `vyomi-mcp` (the macOS/Linux packages ship this binary under
	// that name next to the bash launcher, which execs it for `vyomi mcp`), it is
	// the MCP server and nothing else.
	if isMCPAlias(os.Args[0]) {
		args := os.Args[1:]
		if len(args) > 0 && args[0] == "mcp" {
			args = args[1:]
		}
		os.Exit(c.runMCP(args))
	}

	args := os.Args[1:]
	cmd := "help"
	if len(args) > 0 {
		cmd = args[0]
		args = args[1:]
	}

	// MCP server for AI coding agents (stdio). Substrate-independent: it talks to
	// the simulator over HTTP, so it is routed before inner/outer dispatch.
	if cmd == "mcp" {
		os.Exit(c.runMCP(args))
	}

	// Inner context (inside the appliance): compose straight against the stack.
	if c.RuntimeContext == "inner" {
		os.Exit(c.dispatchInner(cmd, args))
	}

	// Outer: parse a leading (or second-position) --docker/--multipass flag.
	explicit := ""
	if cmd == "--docker" || cmd == "--multipass" {
		explicit = trimDashes(cmd)
		cmd = "help"
		if len(args) > 0 {
			cmd = args[0]
			args = args[1:]
		}
	}
	if len(args) > 0 && (args[0] == "--docker" || args[0] == "--multipass") {
		explicit = trimDashes(args[0])
		args = args[1:]
	}
	if explicit != "" {
		os.Setenv("VYOMI_SUBSTRATE", explicit)
		c.persistSubstrate(explicit)
	}

	os.Exit(c.dispatchOuter(cmd, args))
}

func trimDashes(s string) string {
	for len(s) > 0 && s[0] == '-' {
		s = s[1:]
	}
	return s
}

func fail(err error) int {
	if err != nil {
		fmt.Fprintln(os.Stderr, "vyomi:", err)
		return 1
	}
	return 0
}

// isMCPAlias reports whether the binary was invoked as vyomi-mcp (vyomi-mcp.exe,
// or a platform-suffixed release asset such as vyomi-mcp-darwin-arm64).
func isMCPAlias(argv0 string) bool {
	base := argv0[strings.LastIndexAny(argv0, `/\`)+1:] // both separators, on any OS
	return strings.HasPrefix(strings.ToLower(base), "vyomi-mcp")
}

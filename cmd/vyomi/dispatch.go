package main

import "fmt"

var lifecycle = map[string]bool{
	"up": true, "down": true, "stop": true, "restart": true,
	"status": true, "ps": true, "logs": true, "update": true,
}

// dispatchInner serves the INNER context (running inside the appliance) — compose
// straight against the stack (mirrors the PS1's inner switch).
func (c *Config) dispatchInner(cmd string, args []string) int {
	switch cmd {
	case "up":
		return fail(c.invokeCompose("up", append([]string{"--build", "--force-recreate"}, args...)...))
	case "down":
		return fail(c.invokeCompose("down", args...))
	case "restart":
		return fail(c.invokeCompose("restart", args...))
	case "status", "ps":
		return fail(c.invokeCompose("ps", args...))
	case "doctor":
		c.doctor()
		return 0
	case "help", "-h", "--help":
		usage()
		return 0
	default:
		fmt.Println("vyomi: unknown inner command:", cmd)
		usage()
		return 2
	}
}

// dispatchOuter serves the host launcher. Lifecycle commands route to the Docker
// substrate when resolved to docker; everything else goes to the Multipass path.
func (c *Config) dispatchOuter(cmd string, args []string) int {
	if lifecycle[cmd] && c.resolveSubstrate() == "docker" {
		return fail(c.invokeDockerSubstrate(cmd, args))
	}
	return c.dispatchMultipass(cmd, args)
}

// dispatchMultipass serves the Max-tier VM path. Simple lifecycle commands are
// wired; full `up`/`restart` provisioning + `upgrade` is ported in the next
// increment (they need the VM launch/cloud-init/bridge sequence).
func (c *Config) dispatchMultipass(cmd string, args []string) int {
	switch cmd {
	case "down", "stop":
		return fail(run("multipass", "stop", c.ApplianceName))
	case "force-stop", "kill":
		return fail(run("multipass", "stop", "--force", c.ApplianceName))
	case "status":
		return fail(run("multipass", "info", c.ApplianceName))
	case "doctor":
		c.doctor()
		return 0
	case "help", "-h", "--help":
		usage()
		return 0
	case "up", "restart", "upgrade":
		fmt.Println("vyomi: the Multipass (Max) provisioning path is not yet available in")
		fmt.Println("       this compiled build. Use the Docker tiers (`vyomi --docker up`)")
		fmt.Println("       or the shell launcher for Max. Full VM provisioning ships next.")
		return 3
	default:
		fmt.Println("vyomi: unknown command:", cmd)
		usage()
		return 2
	}
}

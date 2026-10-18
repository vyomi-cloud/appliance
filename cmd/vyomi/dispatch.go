package main

import (
	"fmt"
	"os"
	"strings"
)

var lifecycle = map[string]bool{
	"up": true, "down": true, "stop": true, "restart": true,
	"status": true, "ps": true, "logs": true, "update": true,
}

func handleWithProfile(args []string) []string {
	var filtered []string
	for i := 0; i < len(args); i++ {
		if args[i] == "--with" && i+1 < len(args) {
			setComposeProfile(args[i+1])
			i++
		} else if strings.HasPrefix(args[i], "--with=") {
			setComposeProfile(strings.TrimPrefix(args[i], "--with="))
		} else {
			filtered = append(filtered, args[i])
		}
	}
	return filtered
}

func setComposeProfile(prof string) {
	cur := os.Getenv("COMPOSE_PROFILES")
	if cur != "" {
		os.Setenv("COMPOSE_PROFILES", cur+","+prof)
	} else {
		os.Setenv("COMPOSE_PROFILES", prof)
	}
}

// dispatchInner serves the INNER context (running inside the appliance) — compose
// straight against the stack (mirrors the PS1's inner switch).
func (c *Config) dispatchInner(cmd string, args []string) int {
	if cmd == "up" {
		args = handleWithProfile(args)
	}

	switch cmd {
	case "up":
		return fail(c.invokeCompose("up", append([]string{"--build", "--force-recreate"}, args...)...))
	case "down":
		return fail(c.invokeCompose("down", args...))
	case "restart":
		return fail(c.invokeCompose("restart", args...))
	case "status", "ps":
		return fail(c.invokeCompose("ps", args...))
	case "app":
		return c.dispatchApp(args)
	case "env":
		return c.dispatchEnv(args)
	case "db":
		return c.dispatchDB(args)
	case "redis":
		return c.dispatchRedis(args)
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

// dispatchOuter serves the host launcher.
func (c *Config) dispatchOuter(cmd string, args []string) int {
	if cmd == "up" {
		args = handleWithProfile(args)
	}

	switch cmd {
	case "app":
		return c.dispatchApp(args)
	case "env":
		return c.dispatchEnv(args)
	case "db":
		return c.dispatchDB(args)
	case "redis":
		return c.dispatchRedis(args)
	}

	if lifecycle[cmd] && c.resolveSubstrate() == "docker" {
		return fail(c.invokeDockerSubstrate(cmd, args))
	}
	return c.dispatchMultipass(cmd, args)
}

func (c *Config) dispatchDB(args []string) int {
	if len(args) == 0 {
		fmt.Println("Usage: vyomi db dump | restore <file> | refresh")
		return 2
	}
	sub := args[0]
	switch sub {
	case "dump", "restore", "refresh":
		fmt.Printf("vyomi db %s: database operation\n", sub)
		return 0
	default:
		fmt.Printf("vyomi db: unknown subcommand %q\n", sub)
		return 2
	}
}

func (c *Config) dispatchRedis(args []string) int {
	if len(args) == 0 {
		fmt.Println("Usage: vyomi redis flush")
		return 2
	}
	sub := args[0]
	switch sub {
	case "flush":
		out, err := c.backendExec("redis", []string{"redis-cli", "FLUSHALL"}, nil)
		if err != nil {
			fmt.Fprintf(os.Stderr, "vyomi redis flush: %v\n", err)
			return 1
		}
		fmt.Print(out)
		return 0
	default:
		fmt.Printf("vyomi redis: unknown subcommand %q\n", sub)
		return 2
	}
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
	case "up":
		return fail(c.multipassUp())
	case "restart":
		return fail(c.multipassRestart())
	case "upgrade":
		c.initializeLog()
		return fail(c.invokeUpgrade())
	default:
		fmt.Println("vyomi: unknown command:", cmd)
		usage()
		return 2
	}
}

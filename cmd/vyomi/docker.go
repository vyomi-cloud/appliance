package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// composeBackend picks `docker compose` (v2) or the legacy `docker-compose`.
// Returns (file, prefixArgs). Errors if neither is available.
func composeBackend() (string, []string, error) {
	if have("docker") {
		if runQuiet("docker", "compose", "version") {
			return "docker", []string{"compose"}, nil
		}
	}
	if have("docker-compose") {
		return "docker-compose", nil, nil
	}
	return "", nil, fmt.Errorf("docker compose is not available")
}

func engineReachable() bool { return runQuiet("docker", "info") }

// waitComposeBackendReady polls until `docker compose` + the engine are both up.
func waitComposeBackendReady(timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if runQuiet("docker", "compose", "version") && runQuiet("docker", "info") {
			return nil
		}
		if runQuiet("docker-compose", "version") && runQuiet("docker", "info") {
			return nil
		}
		time.Sleep(2 * time.Second)
	}
	return fmt.Errorf("docker compose is not available yet")
}

// invokeCompose is the INNER (inside-the-appliance) compose path — uses the
// resolved ProjectName + RootDir + ComposeFile (mirrors Invoke-Compose).
func (c *Config) invokeCompose(verb string, extra ...string) error {
	if err := waitComposeBackendReady(180 * time.Second); err != nil {
		return err
	}
	file, prefix, err := composeBackend()
	if err != nil {
		return err
	}
	args := append([]string{}, prefix...)
	args = append(args, "--project-name", c.ProjectName, "--project-directory", c.RootDir,
		"-f", c.ComposeFile, verb)
	args = append(args, extra...)
	return run(file, args...)
}

// resolveDockerComposeFile finds the Free/Lite/Pro compose file
// (docker-compose.cloudlite.yml) — VYOMI_COMPOSE_FILE wins, else known locations.
func (c *Config) resolveDockerComposeFile() (string, error) {
	if cf := strings.TrimSpace(os.Getenv("VYOMI_COMPOSE_FILE")); cf != "" {
		return cf, nil
	}
	for _, cand := range []string{
		filepath.Join(c.RootDir, "docker-compose.cloudlite.yml"),
		filepath.Join(c.ExeDir, "..", "docker-compose.cloudlite.yml"),
	} {
		if _, err := os.Stat(cand); err == nil {
			if abs, err := filepath.Abs(cand); err == nil {
				return abs, nil
			}
			return cand, nil
		}
	}
	return "", fmt.Errorf("docker-compose.cloudlite.yml not found (set VYOMI_COMPOSE_FILE)")
}

// invokeDockerSubstrate serves the Free/Lite/Pro tiers straight on `docker compose`
// (project `vyomi`), mirroring Invoke-DockerSubstrate exactly.
func (c *Config) invokeDockerSubstrate(action string, dcArgs []string) error {
	cf, err := c.resolveDockerComposeFile()
	if err != nil {
		return err
	}
	if !have("docker") {
		return fmt.Errorf("Docker is required for the Free/Lite/Pro tiers. " +
			"Install Docker Desktop: https://docs.docker.com/desktop/")
	}
	base := []string{"compose", "-f", cf, "-p", "vyomi"}
	switch action {
	case "up", "start":
		if err := run("docker", append(append([]string{}, base...), "up", "-d")...); err != nil {
			return err
		}
		progress("==> Vyomi (Docker) starting - open http://localhost:9000 in ~30s")
		return nil
	case "down", "stop":
		return run("docker", append(append([]string{}, base...), "down")...)
	case "restart":
		if err := run("docker", append(append([]string{}, base...), "down")...); err != nil {
			return err
		}
		return run("docker", append(append([]string{}, base...), "up", "-d")...)
	case "status", "ps":
		return run("docker", append(append([]string{}, base...), "ps")...)
	case "logs":
		return run("docker", append(append(append([]string{}, base...), "logs"), dcArgs...)...)
	case "update":
		if err := run("docker", append(append([]string{}, base...), "pull")...); err != nil {
			return err
		}
		return run("docker", append(append([]string{}, base...), "up", "-d")...)
	default:
		return run("docker", append(append(append([]string{}, base...), action), dcArgs...)...)
	}
}

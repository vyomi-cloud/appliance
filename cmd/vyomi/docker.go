package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
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

func engineReachable() bool { return runQuietTimeout(5*time.Second, "docker", "info") }

// ensureDockerEngine makes sure the Docker daemon answers before the Free/Lite/Pro
// substrate runs `docker compose`. On macOS/Windows the engine lives inside the
// Docker Desktop (or OrbStack / Colima) VM, which is often installed but not
// running — so auto-start it once and wait, mirroring multipassReady for Max.
//
// Halfway through the timeout, if the engine is still down, we retry the launch
// once. This covers the case where startDockerHost raced a Docker Desktop
// instance that was still quitting: the `open -a Docker` activated the dying
// process instead of starting a fresh one, so the VM never actually restarts.
func ensureDockerEngine(timeout time.Duration) error {
	if engineReachable() {
		return nil
	}
	progress("==> Docker: engine not reachable, attempting to start it")
	startDockerHost()
	deadline := time.Now().Add(timeout)
	retryAt := time.Now().Add(timeout / 2)
	retried := false
	for time.Now().Before(deadline) {
		if engineReachable() {
			progress("==> Docker: engine ready")
			return nil
		}
		if !retried && time.Now().After(retryAt) {
			retried = true
			progress("==> Docker: engine still not up halfway through the wait, retrying the launch")
			startDockerHost()
		}
		time.Sleep(3 * time.Second)
	}
	return fmt.Errorf("Docker is installed but the engine did not come up within %s. "+
		"Start Docker Desktop (or OrbStack/Colima) manually, wait for it to say "+
		"\"running\", then re-run `vyomi up`. Check with: docker info", timeout)
}

// dockerDesktopCLIAvailable reports whether `docker desktop` (the Docker Desktop
// CLI plugin) is installed. It's the preferred way to start the engine: unlike
// `open -a Docker`, it manages the whole app/VM lifecycle itself instead of just
// sending an Apple Events activation at a possibly half-dead process.
func dockerDesktopCLIAvailable() bool {
	return have("docker") && runQuiet("docker", "desktop", "start", "--help")
}

// dockerDesktopRunning reports whether Docker Desktop considers itself running,
// per its own status command (an IPC call to the Desktop app, independent of
// the `docker info` engine socket we're trying to unwedge). Confirmed on a
// wedged engine: `docker desktop status` still answers "running" instantly
// even while `docker info` hangs — Desktop's notion of "running" means the
// app/VM process exists, not that the engine inside is answering.
func dockerDesktopRunning() bool {
	out, ok := capture("docker", "desktop", "status")
	return ok && strings.Contains(strings.ToLower(out), "running")
}

// waitForDockerDesktopExit blocks (up to timeout) until no Docker Desktop
// process is left running. `open -a Docker` reactivates whatever process macOS
// finds registered for that bundle id — if Docker Desktop is still in the
// middle of quitting (e.g. right after `osascript -e 'quit app "Docker"'`),
// that reactivates the dying instance instead of starting a fresh one, which
// can leave the engine's VM networking wedged indefinitely.
func waitForDockerDesktopExit(timeout time.Duration) {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !runQuiet("pgrep", "-f", "Docker Desktop.app/Contents/MacOS/Docker Desktop") {
			return
		}
		time.Sleep(1 * time.Second)
	}
}

// startDockerHost launches whichever Docker engine provider is installed.
// Best-effort; ensureDockerEngine decides success by polling `docker info`.
func startDockerHost() {
	switch runtime.GOOS {
	case "darwin":
		if dockerDesktopCLIAvailable() {
			// `docker desktop start` no-ops if Desktop already reports itself
			// running — which it will, even mid-wedge (engine unreachable but
			// the app/VM process never actually died, e.g. right after a quit
			// that didn't fully land). `restart` is what actually recovers that.
			if dockerDesktopRunning() {
				progress("==> Docker: Docker Desktop is running but the engine isn't answering, restarting it (docker desktop restart)")
				_ = exec.Command("docker", "desktop", "restart").Run()
			} else {
				progress("==> Docker: starting Docker Desktop (docker desktop start)")
				_ = exec.Command("docker", "desktop", "start").Run()
			}
			return
		}
		waitForDockerDesktopExit(30 * time.Second)
		for _, app := range []string{"Docker", "OrbStack"} {
			if exec.Command("open", "-a", app).Run() == nil {
				progress("==> Docker: launched " + app + ".app, waiting for the engine (first start can take ~1 min)")
				return
			}
		}
		if have("colima") {
			progress("==> Docker: starting Colima")
			_ = exec.Command("colima", "start").Run()
		}
	case "windows":
		exe := filepath.Join(os.Getenv("ProgramFiles"), "Docker", "Docker", "Docker Desktop.exe")
		if _, err := os.Stat(exe); err == nil {
			progress("==> Docker: launching Docker Desktop, waiting for the engine")
			_ = exec.Command(exe).Start()
		}
	default: // linux: native dockerd or Docker Desktop for Linux
		if exec.Command("systemctl", "--user", "start", "docker-desktop").Run() != nil {
			_ = exec.Command("sudo", "-n", "systemctl", "start", "docker").Run()
		}
	}
}

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
	case "up", "start", "restart":
		if err := ensureDockerEngine(150 * time.Second); err != nil {
			return err
		}
	}
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

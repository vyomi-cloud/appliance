package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// resolveContainer discovers the running container name or ID for a service.
// Supports both compose v2 labels and name variants across compose files
// (e.g., vyomi-sql-postgres vs cloudlearn-sql-postgres).
func (c *Config) resolveContainer(serviceName string) (string, error) {
	substrate := c.resolveSubstrate()

	var candidates []string
	switch serviceName {
	case "postgres":
		candidates = []string{"cloudlearn-sql-postgres", "vyomi-sql-postgres", "postgres"}
	case "redis":
		candidates = []string{"vyomi-redis", "redis"}
	case "simulator":
		candidates = []string{"simulator", "cloudsim"}
	default:
		candidates = []string{serviceName}
	}

	// 1. Try label filter for each candidate
	for _, cand := range candidates {
		labelFilter := fmt.Sprintf("label=com.docker.compose.service=%s", cand)
		var out string
		var ok bool
		if substrate == "docker" {
			out, ok = capture("docker", "ps", "--filter", labelFilter, "--format", "{{.ID}}")
		} else {
			out, ok = capture(multipassBin(), "exec", c.ApplianceName, "--", "sudo", "docker", "ps", "--filter", labelFilter, "--format", "{{.ID}}")
		}

		lines := strings.Fields(strings.TrimSpace(out))
		if ok && len(lines) > 0 {
			return lines[0], nil
		}
	}

	// 2. Try by name pattern for each candidate
	for _, cand := range candidates {
		nameFilter := fmt.Sprintf("name=%s", cand)
		var out string
		var ok bool
		if substrate == "docker" {
			out, ok = capture("docker", "ps", "--filter", nameFilter, "--format", "{{.ID}}")
		} else {
			out, ok = capture(multipassBin(), "exec", c.ApplianceName, "--", "sudo", "docker", "ps", "--filter", nameFilter, "--format", "{{.ID}}")
		}

		lines := strings.Fields(strings.TrimSpace(out))
		if ok && len(lines) > 0 {
			return lines[0], nil
		}
	}

	return "", fmt.Errorf("container for service %q not found (is the appliance running?)", serviceName)
}

// backendExec runs a command in the target backend container.
// On Docker: docker exec [-e K=V...] <container> <cmd...>
// On Multipass: multipass exec <vm> -- sudo docker exec [-e K=V...] <container> <cmd...>
// Only passes env vars that are non-empty.
func (c *Config) backendExec(serviceName string, cmdArgs []string, env map[string]string) (string, error) {
	containerID, err := c.resolveContainer(serviceName)
	if err != nil {
		return "", err
	}

	var envFlags []string
	for k, v := range env {
		if strings.TrimSpace(v) != "" {
			envFlags = append(envFlags, "-e", fmt.Sprintf("%s=%s", k, v))
		}
	}

	substrate := c.resolveSubstrate()
	if substrate == "docker" {
		args := append([]string{"exec"}, envFlags...)
		args = append(args, containerID)
		args = append(args, cmdArgs...)
		cmd := exec.Command("docker", args...)
		out, err := cmd.CombinedOutput()
		if err != nil {
			return string(out), fmt.Errorf("docker exec failed: %w (output: %s)", err, string(out))
		}
		return string(out), nil
	}

	// Multipass
	args := []string{"exec", c.ApplianceName, "--", "sudo", "docker", "exec"}
	args = append(args, envFlags...)
	args = append(args, containerID)
	args = append(args, cmdArgs...)
	cmd := exec.Command(multipassBin(), args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return string(out), fmt.Errorf("multipass backend exec failed: %w (output: %s)", err, string(out))
	}
	return string(out), nil
}

// backendCopyIn copies a host file into the container.
// On Multipass, first stages via multipass transfer, then docker cp.
func (c *Config) backendCopyIn(serviceName, srcHostPath, dstContainerPath string) error {
	containerID, err := c.resolveContainer(serviceName)
	if err != nil {
		return err
	}

	substrate := c.resolveSubstrate()
	if substrate == "docker" {
		dst := fmt.Sprintf("%s:%s", containerID, dstContainerPath)
		cmd := exec.Command("docker", "cp", srcHostPath, dst)
		out, err := cmd.CombinedOutput()
		if err != nil {
			return fmt.Errorf("docker cp failed: %w (output: %s)", err, string(out))
		}
		return nil
	}

	// Multipass substrate
	vmTmp := fmt.Sprintf("/tmp/vyomi-transfer-%d.tmp", os.Getpid())
	if err := run(multipassBin(), "transfer", srcHostPath, fmt.Sprintf("%s:%s", c.ApplianceName, vmTmp)); err != nil {
		return fmt.Errorf("multipass transfer failed: %w", err)
	}
	defer func() {
		_ = exec.Command(multipassBin(), "exec", c.ApplianceName, "--", "rm", "-f", vmTmp).Run()
	}()

	cmd := exec.Command(multipassBin(), "exec", c.ApplianceName, "--",
		"sudo", "docker", "cp", vmTmp, fmt.Sprintf("%s:%s", containerID, dstContainerPath))
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("in-vm docker cp failed: %w (output: %s)", err, string(out))
	}
	return nil
}

// backendCopyOut copies a file from inside the container to a host destination.
// On Docker: docker cp <containerID>:<srcContainerPath> <dstHostPath>
// On Multipass: docker cp into VM /tmp, then multipass transfer out to host.
func (c *Config) backendCopyOut(serviceName, srcContainerPath, dstHostPath string) error {
	containerID, err := c.resolveContainer(serviceName)
	if err != nil {
		return err
	}

	substrate := c.resolveSubstrate()
	if substrate == "docker" {
		src := fmt.Sprintf("%s:%s", containerID, srcContainerPath)
		cmd := exec.Command("docker", "cp", src, dstHostPath)
		out, err := cmd.CombinedOutput()
		if err != nil {
			return fmt.Errorf("docker cp out failed: %w (output: %s)", err, string(out))
		}
		return nil
	}

	// Multipass substrate
	vmTmp := fmt.Sprintf("/tmp/vyomi-transfer-out-%d.tmp", os.Getpid())
	cmd := exec.Command(multipassBin(), "exec", c.ApplianceName, "--",
		"sudo", "docker", "cp", fmt.Sprintf("%s:%s", containerID, srcContainerPath), vmTmp)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("in-vm docker cp out failed: %w (output: %s)", err, string(out))
	}
	defer func() {
		_ = exec.Command(multipassBin(), "exec", c.ApplianceName, "--", "rm", "-f", vmTmp).Run()
	}()

	if err := run(multipassBin(), "transfer", fmt.Sprintf("%s:%s", c.ApplianceName, vmTmp), dstHostPath); err != nil {
		return fmt.Errorf("multipass transfer out failed: %w", err)
	}
	return nil
}

// getAdminKey retrieves the admin key from ~/.vyomi/admin_key or extracts it from the running simulator.
func (c *Config) getAdminKey() (string, error) {
	keyFile := filepath.Join(c.VyomiHome, "admin_key")

	// 1. Check cached key
	if data, err := os.ReadFile(keyFile); err == nil {
		key := strings.TrimSpace(string(data))
		if len(key) >= 32 {
			return key, nil
		}
	}

	// 2. Query simulator container
	pyCmd := []string{
		"python3", "-c",
		"from core.admin_auth import get_or_create_admin_key; print(get_or_create_admin_key())",
	}

	// Note: "cloudsim" is a separate Java service with no Python/core
	// package, so it is not a usable fallback here — only "simulator" can
	// ever serve this request.
	out, err := c.backendExec("simulator", pyCmd, nil)
	if err != nil {
		return "", fmt.Errorf("could not retrieve admin key from simulator: %w", err)
	}

	lines := strings.Split(strings.TrimSpace(out), "\n")
	key := ""
	for i := len(lines) - 1; i >= 0; i-- {
		line := strings.TrimSpace(lines[i])
		if len(line) >= 32 && !strings.Contains(line, "=") && !strings.Contains(line, " ") {
			key = line
			break
		}
	}

	if key == "" {
		return "", errors.New("no valid admin key found in simulator output")
	}

	// 3. Cache key at mode 0600
	_ = os.MkdirAll(c.VyomiHome, 0700)
	_ = os.WriteFile(keyFile, []byte(key+"\n"), 0600)

	return key, nil
}

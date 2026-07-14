package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"time"
)

// mpInstance / mpList model `multipass list --format json`.
type mpInstance struct {
	Name  string   `json:"name"`
	State string   `json:"state"`
	Ipv4  []string `json:"ipv4"`
}
type mpList struct {
	List []mpInstance `json:"list"`
}

var (
	reIPv4     = regexp.MustCompile(`^\d+\.\d+\.\d+\.\d+$`)
	rePriv     = regexp.MustCompile(`^(172\.1[7-9]\.|172\.2[0-9]\.|172\.3[0-1]\.|10\.)`)
	reDockerGw = regexp.MustCompile(`^172\.(1[7-9]|2[0-9]|3[01])\.\d+\.1$`)
	reLxdGw    = regexp.MustCompile(`^10\.\d+\.\d+\.1$`)
)

func multipassBin() string { return "multipass" }

// multipassUp is the full Max-tier boot sequence (the PS1 outer `up` case).
func (c *Config) multipassUp() error {
	c.initializeLog()
	if !have("multipass") {
		if !installMultipass() {
			return fmt.Errorf("Multipass is required for the Max tier")
		}
	}
	if err := c.startApplianceVm(); err != nil {
		return err
	}
	progress("==> [4/6] Installing the runtime bridge")
	if err := c.installRuntimeBridge(); err != nil {
		return err
	}
	if err := c.invokeApplianceLauncher(); err != nil {
		return err
	}
	vmIp := c.testApplianceHealth()
	c.startLocalhostBridge(vmIp)
	c.setVBoxNatPortForward(vmIp)
	c.showUrlBanner(vmIp)
	return nil
}

// multipassRestart restarts the VM + stack (the PS1 outer `restart` case).
func (c *Config) multipassRestart() error {
	c.initializeLog()
	if err := run(multipassBin(), "restart", c.ApplianceName); err != nil {
		return err
	}
	_ = run(multipassBin(), "exec", c.ApplianceName, "--", "/bin/bash", "-lc",
		"cloud-init status --wait >/dev/null 2>&1 || true")
	if err := c.installRuntimeBridge(); err != nil {
		return err
	}
	if err := c.invokeApplianceLauncher(); err != nil {
		return err
	}
	vmIp := c.testApplianceHealth()
	c.startLocalhostBridge(vmIp)
	c.setVBoxNatPortForward(vmIp)
	c.showUrlBanner(vmIp)
	return nil
}

// applianceRecord returns the VM record matching ApplianceName (Get-ApplianceRecord).
func (c *Config) applianceRecord() *mpInstance {
	out, ok := capture(multipassBin(), "list", "--format", "json")
	if !ok {
		return nil
	}
	var l mpList
	if json.Unmarshal([]byte(out), &l) != nil {
		return nil
	}
	for i := range l.List {
		if l.List[i].Name == c.ApplianceName {
			return &l.List[i]
		}
	}
	return nil
}

func (c *Config) applianceState() string {
	rec := c.applianceRecord()
	if rec == nil {
		return ""
	}
	return lowerTrim(rec.State)
}

// applianceIp mirrors Get-ApplianceIp: prefer a routable 192.168-style address;
// never return an in-VM bridge gateway (docker0/lxdbr0), so a VirtualBox-NAT VM
// returns "" and the caller falls back to the localhost NAT forward.
func (c *Config) applianceIp() string {
	rec := c.applianceRecord()
	if rec == nil {
		return ""
	}
	return selectIp(rec.Ipv4)
}

// selectIp is Get-ApplianceIp's pure selection logic (extracted for testing).
func selectIp(ips []string) string {
	for _, ip := range ips {
		if reIPv4.MatchString(ip) && !rePriv.MatchString(ip) {
			return ip
		}
	}
	for _, ip := range ips {
		if !reIPv4.MatchString(ip) {
			continue
		}
		if reDockerGw.MatchString(ip) || reLxdGw.MatchString(ip) {
			continue
		}
		return ip
	}
	return ""
}

// installMultipass auto-installs via winget (Install-Multipass).
func installMultipass() bool {
	if have("multipass") {
		return true
	}
	if !have("winget") {
		progress("==> Multipass not found and winget is unavailable. Install Multipass from https://multipass.run/install then re-run `vyomi up`.")
		return false
	}
	progress("==> Multipass not found - installing via winget (a UAC prompt will appear)...")
	if err := run("winget", "install", "--id", "Canonical.Multipass",
		"--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"); err != nil {
		progress("==> winget install failed. Install Multipass manually from https://multipass.run/install")
		return false
	}
	addMultipassToPath()
	if have("multipass") {
		return true
	}
	progress("==> Multipass installed. Open a NEW terminal and run `vyomi up` again so multipass.exe is on PATH.")
	return false
}

// multipassReady polls until the daemon/socket answers, auto-starting the host
// service once (Test-MultipassReady + Start-MultipassHost).
func multipassReady(timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	attempted := false
	for time.Now().Before(deadline) {
		if runQuiet(multipassBin(), "list", "--format", "json") {
			return true
		}
		if !attempted {
			progress("==> Multipass: daemon/socket not reachable, attempting host auto-start")
			startMultipassHost()
			attempted = true
		}
		time.Sleep(3 * time.Second)
	}
	return false
}

// startApplianceVm writes the manifests + cloud-init and launches/starts the VM,
// then waits for cloud-init and syncs the workspace (Start-ApplianceVm).
func (c *Config) startApplianceVm() error {
	if err := c.writeApplianceManifest(); err != nil {
		return err
	}
	if err := c.writeApplianceHostSizing(); err != nil {
		return err
	}
	if err := c.writeApplianceCloudInit(); err != nil {
		return err
	}
	if !multipassReady(12 * time.Second) {
		return fmt.Errorf("Multipass is installed, but the daemon/socket is not reachable. Open or restart Multipass on the host and retry.")
	}
	progress("==> [1/6] Checking appliance VM state")
	rec := c.applianceRecord()
	state := ""
	if rec != nil {
		state = lowerTrim(rec.State)
	}
	ci := filepath.Join(c.ApplianceDir, "cloud-init.yaml")
	if rec == nil {
		progress(fmt.Sprintf("==> [2/6] Launching VM %s: %s RAM / %d CPU / %s disk (cold start 3-5 min; host kept lean to avoid freezes)",
			c.ApplianceName, c.Memory, c.Cpus, c.Disk))
		if err := run(multipassBin(), "launch", c.ApplianceImage, "--name", c.ApplianceName,
			"--cpus", strconv.Itoa(c.Cpus), "--memory", c.Memory, "--disk", c.Disk,
			"--timeout", "900", "--cloud-init", ci); err != nil {
			return err
		}
	} else if state == "running" {
		progress("==> [2/6] Existing VM detected (running)")
	} else if state == "stopped" || state == "suspended" {
		progress(fmt.Sprintf("==> [2/6] Existing VM detected (%s), starting it", state))
		if err := run(multipassBin(), "start", c.ApplianceName); err != nil {
			return err
		}
	} else {
		s := state
		if s == "" {
			s = "unknown"
		}
		progress(fmt.Sprintf("==> [2/6] Existing VM detected (%s), continuing", s))
	}
	progress("==> [3/6] Waiting for cloud-init")
	_ = run(multipassBin(), "exec", c.ApplianceName, "--", "/bin/bash", "-lc",
		"cloud-init status --wait >/dev/null 2>&1 || true")
	if err := c.syncWorkspaceIntoVm(); err != nil {
		return err
	}
	c.syncHostSizingIntoVm()
	return nil
}

var syncItems = []string{
	"Dockerfile", "docker-compose.appliance.yml", "docker-compose.yml", "VERSION", "requirements.txt",
	"server.py", "setup_cython.py", ".env.example", "core", "providers", "routes", "static", "packs",
	"scripts", "packaging", "cloudsim-backbone",
}

// syncWorkspaceIntoVm tars the sources and transfers+extracts them (Sync-WorkspaceIntoVm).
func (c *Config) syncWorkspaceIntoVm() error {
	progress("==> Appliance: syncing workspace into VM (tar + transfer)")
	present := []string{}
	for _, it := range syncItems {
		if fileExists(filepath.Join(c.RootDir, it)) {
			present = append(present, it)
		}
	}
	tarball := filepath.Join(os.TempDir(), "vyomi-src-"+randHex()+".tgz")
	args := []string{"-czf", tarball, "-C", c.RootDir,
		"--exclude=__pycache__", "--exclude=*.pyc", "--exclude=node_modules",
		"--exclude=.git", "--exclude=target", "--exclude=dist"}
	args = append(args, present...)
	if err := run("tar", args...); err != nil {
		return fmt.Errorf("failed to create source tarball (tar): %w", err)
	}
	defer os.Remove(tarball)
	if err := run(multipassBin(), "transfer", tarball, c.ApplianceName+":/tmp/vyomi-src.tgz"); err != nil {
		return err
	}
	return run(multipassBin(), "exec", c.ApplianceName, "--", "/bin/bash", "-lc",
		fmt.Sprintf("sudo mkdir -p '%s' && sudo tar xzf /tmp/vyomi-src.tgz -C '%s' && sudo chown -R ubuntu:ubuntu '%s' && rm -f /tmp/vyomi-src.tgz",
			c.Workspace, c.Workspace, c.Workspace))
}

func (c *Config) syncHostSizingIntoVm() {
	hostFile := filepath.Join(c.ApplianceDir, hostSizingFileName)
	if !fileExists(hostFile) {
		return
	}
	progress("==> Appliance: syncing host sizing into VM-local storage")
	if run(multipassBin(), "transfer", hostFile, c.ApplianceName+":/tmp/"+hostSizingFileName) != nil {
		return
	}
	_ = run(multipassBin(), "exec", c.ApplianceName, "--", "/bin/bash", "-lc",
		fmt.Sprintf("sudo mkdir -p /var/lib/cloudlearn && sudo install -m 644 /tmp/%s /var/lib/cloudlearn/%s && rm -f /tmp/%s",
			hostSizingFileName, hostSizingFileName, hostSizingFileName))
}

const runtimeBridgeUnit = `[Unit]
Description=Vyomi runtime bridge
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 /var/lib/cloudlearn/runtime_bridge.py --host 0.0.0.0 --port 9171
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
`

// installRuntimeBridge transfers core/runtime_bridge.py + installs the systemd unit
// (Install-RuntimeBridge).
func (c *Config) installRuntimeBridge() error {
	src := filepath.Join(c.RootDir, "core", "runtime_bridge.py")
	if !fileExists(src) {
		return fmt.Errorf("runtime bridge source not found at %s", src)
	}
	progress("==> Appliance: installing VM-local runtime bridge (systemd)")
	if err := run(multipassBin(), "transfer", src, c.ApplianceName+":/tmp/runtime_bridge.py"); err != nil {
		return err
	}
	b64 := b64encode(runtimeBridgeUnit)
	remote := "set -e; sudo mkdir -p /var/lib/cloudlearn; sudo install -m 644 /tmp/runtime_bridge.py /var/lib/cloudlearn/runtime_bridge.py; rm -f /tmp/runtime_bridge.py; " +
		"echo " + b64 + " | base64 -d | sudo tee /etc/systemd/system/cloudlearn-runtime-bridge.service >/dev/null; " +
		"sudo systemctl daemon-reload; sudo systemctl enable --now cloudlearn-runtime-bridge.service; " +
		"for i in $(seq 1 30); do curl -fsS http://127.0.0.1:9171/health >/dev/null 2>&1 && exit 0; sleep 1; done; echo 'runtime bridge failed to start' >&2; exit 1"
	return run(multipassBin(), "exec", c.ApplianceName, "--", "/bin/bash", "-lc", remote)
}

// invokeApplianceLauncher starts the CloudLearn stack inside the VM (Invoke-ApplianceLauncher).
func (c *Config) invokeApplianceLauncher() error {
	progress("==> [5/6] Starting the CloudLearn stack inside the appliance")
	remote := fmt.Sprintf("sudo mkdir -p /var/lib/cloudlearn/deployments && cd '%s' && "+
		"CLOUD_LEARN_HOME='%s' CLOUD_LEARN_RUNTIME_CONTEXT=inner CLOUD_LEARN_DISTRIBUTION_MODE=appliance "+
		"CLOUD_LEARN_COMPOSE_FILE='%s/docker-compose.appliance.yml' bash ./scripts/cloud-learn up --detach",
		c.Workspace, c.Workspace, c.Workspace)
	return run(multipassBin(), "exec", c.ApplianceName, "--", "/bin/bash", "-lc", remote)
}

// testApplianceHealth polls :9000/healthz on the VM IP (or 127.0.0.1 via the NAT
// forward), never failing hard on a slow first boot (Test-ApplianceHealth).
func (c *Config) testApplianceHealth() string {
	timeout := atoiDefault(envAny("600", "VYOMI_HEALTH_TIMEOUT", "CLOUD_LEARN_HEALTH_TIMEOUT"), 600)
	vmIp := c.applianceIp()
	probe := vmIp
	if vmIp == "" {
		progress("==> No routable VM IP (VirtualBox NAT) - bridging localhost:9000 to the appliance.")
		c.setVBoxNatPortForward("")
		probe = "127.0.0.1"
	}
	progress(fmt.Sprintf("==> [6/6] Waiting for the simulator at %s:9000 (first boot can take 10-20 min on a slow VM)", probe))
	waited := 0
	for waited < timeout {
		if httpOK(fmt.Sprintf("http://%s:9000/healthz", probe), 3*time.Second) {
			return vmIp
		}
		time.Sleep(5 * time.Second)
		waited += 5
		if waited%30 == 0 {
			progress(fmt.Sprintf("    ... still starting (%ds) - pulling/booting the stack inside the VM", waited))
		}
	}
	progress("")
	progress("==> Simulator not reachable yet - it is still starting inside the VM (slow first boot / image pull).")
	progress(fmt.Sprintf("    Check progress: multipass exec %s -- sudo docker ps", c.ApplianceName))
	progress("    The access URL below will start working once it finishes.")
	return vmIp
}

// invokeUpgrade pulls the latest appliance image and recreates the simulator
// (Invoke-Upgrade).
func (c *Config) invokeUpgrade() error {
	if c.applianceRecord() == nil {
		return fmt.Errorf("appliance VM '%s' does not exist. Run `vyomi up` first.", c.ApplianceName)
	}
	vmIp := c.applianceIp()
	progress("==> Checking for updates...")
	body, ok := httpGet(fmt.Sprintf("http://%s:9000/api/runtime/update-check", vmIp), 5*time.Second)
	if !ok {
		return fmt.Errorf("could not reach the appliance update-check endpoint. Is the appliance running (`vyomi status`)?")
	}
	var uc struct{ Current, Latest string }
	_ = json.Unmarshal([]byte(body), &uc)
	if uc.Latest == "" || uc.Latest == uc.Current {
		progress(fmt.Sprintf("==> Already up to date (v%s).", uc.Current))
		return nil
	}
	progress(fmt.Sprintf("==> Pulling vyomi/appliance:%s inside %s...", uc.Latest, c.ApplianceName))
	if err := run(multipassBin(), "exec", c.ApplianceName, "--", "/bin/bash", "-lc",
		"sudo docker pull vyomi/appliance:"+uc.Latest); err != nil {
		return err
	}
	progress("==> Recreating the simulator container with the new image...")
	if err := run(multipassBin(), "exec", c.ApplianceName, "--", "/bin/bash", "-lc",
		fmt.Sprintf("cd '%s' && CLOUDLEARN_SIMULATOR_IMAGE=vyomi/appliance:%s docker compose -f docker-compose.appliance.yml up -d --force-recreate simulator",
			c.Workspace, uc.Latest)); err != nil {
		return err
	}
	c.testApplianceHealth()
	progress(fmt.Sprintf("==> Vyomi appliance is now on v%s", uc.Latest))
	return nil
}

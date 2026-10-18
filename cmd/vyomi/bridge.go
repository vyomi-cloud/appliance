package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)


// startLocalhostBridge maps 127.0.0.1:<port> → <vmIp>:<port> via netsh portproxy
// (Start-LocalhostBridge). Windows-only; a no-op elsewhere.
func (c *Config) startLocalhostBridge(vmIp string) {
	if vmIp == "" || runtime.GOOS != "windows" || !have("netsh") {
		return
	}
	port := c.simulatorPort()
	p := strconv.Itoa(port)
	_ = exec.Command("netsh", "interface", "portproxy", "delete", "v4tov4",
		"listenaddress=127.0.0.1", "listenport="+p).Run()
	if err := exec.Command("netsh", "interface", "portproxy", "add", "v4tov4",
		"listenaddress=127.0.0.1", "listenport="+p, "connectaddress="+vmIp, "connectport="+p).Run(); err != nil {
		progress(fmt.Sprintf("==> Note: could not bridge localhost:%d (needs an elevated shell). Use http://%s:%d/ instead.", port, vmIp, port))
	}
}

// showUrlBanner prints the READY banner and opens the browser (Show-UrlBanner).
func (c *Config) showUrlBanner(vmIp string) {
	port := c.simulatorPort()
	url := fmt.Sprintf("http://localhost:%d/", port)
	if vmIp != "" {
		url = fmt.Sprintf("http://%s:%d/", vmIp, port)
	}
	if httpOK(fmt.Sprintf("http://127.0.0.1:%d/healthz", port), 2*time.Second) {
		url = fmt.Sprintf("http://localhost:%d/", port)
	}
	progress("")
	progress("  ============================================================")
	progress("   Vyomi appliance is READY")
	progress("   Console : " + url)
	if vmIp != "" {
		progress(fmt.Sprintf("   Direct  : http://%s:%d/   (VM IP, no bridge needed)", vmIp, port))
	}
	progress("  ============================================================")
	progress("")
	if envAny("", "VYOMI_NO_OPEN", "CLOUD_LEARN_NO_OPEN") != "1" {
		openBrowser(url)
	}
}

func openBrowser(url string) {
	switch runtime.GOOS {
	case "windows":
		_ = exec.Command("cmd", "/c", "start", "", url).Start()
	case "darwin":
		_ = exec.Command("open", url).Start()
	default:
		_ = exec.Command("xdg-open", url).Start()
	}
}

var reVBoxVM = regexp.MustCompile(`"([^"]*)"`)

// setVBoxNatPortForward adds a localhost NAT forward on Windows-Home/VirtualBox
// hosts (Set-VBoxNatPortForward). User-context VMs are forwarded automatically; a
// SYSTEM-owned VM (the multipass-service case) prints the proven manual commands.
// No-op on non-Windows or non-VirtualBox hosts.
func (c *Config) setVBoxNatPortForward(vmIp string) {
	port := c.simulatorPort()
	if httpOK(fmt.Sprintf("http://127.0.0.1:%d/healthz", port), 2*time.Second) {
		return // already reachable (Hyper-V / netsh bridge worked)
	}
	if runtime.GOOS != "windows" {
		return
	}
	vbox := findVBoxManage()
	if vbox == "" {
		return // not a VirtualBox host
	}
	// User-context: find a running VM whose name looks like the appliance.
	vmName := ""
	if out, ok := capture(vbox, "list", "runningvms"); ok {
		for _, line := range strings.Split(out, "\n") {
			if m := reVBoxVM.FindStringSubmatch(line); m != nil {
				if matchesAppliance(m[1]) {
					vmName = m[1]
					break
				}
			}
		}
	}
	if vmName != "" {
		rule := fmt.Sprintf("vyomi%d", port)
		_ = exec.Command(vbox, "controlvm", vmName, "natpf1", "delete", rule).Run()
		_ = exec.Command(vbox, "controlvm", vmName, "natpf1",
			fmt.Sprintf("%s,tcp,127.0.0.1,%d,,%d", rule, port, port)).Run()
		time.Sleep(time.Second)
		if httpOK(fmt.Sprintf("http://127.0.0.1:%d/healthz", port), 3*time.Second) {
			progress(fmt.Sprintf("==> VirtualBox NAT port-forward added (localhost:%d -> VM).", port))
			return
		}
	}
	// SYSTEM-owned VM: print the proven manual commands (auto-elevation via a SYSTEM
	// scheduled task is a follow-up; we never shell into a generated script here).
	c.printVBoxManualFallback(vbox)
}

func (c *Config) printVBoxManualFallback(vbox string) {
	port := c.simulatorPort()
	progress("")
	progress("  ------------------------------------------------------------")
	progress("   Windows + VirtualBox NAT: manual fallback for browser access")
	progress("  ------------------------------------------------------------")
	progress("   The appliance is RUNNING, but VirtualBox keeps it behind NAT")
	progress("   and the VM is owned by the SYSTEM account. Add the forward as")
	progress("   SYSTEM. In an ADMINISTRATOR PowerShell, run:")
	progress("")
	progress("     winget install Microsoft.Sysinternals.PsExec   # if not installed")
	progress(fmt.Sprintf(`     $vb = "%s"`, vbox))
	progress("     psexec -s -nobanner -accepteula $vb list runningvms      # note the \"name\"")
	progress(fmt.Sprintf(`     psexec -s -nobanner -accepteula $vb controlvm "<name>" natpf1 "vyomi%d,tcp,127.0.0.1,%d,,%d"`, port, port, port))
	progress("")
	progress(fmt.Sprintf("   Then open http://localhost:%d/", port))
	progress("  ------------------------------------------------------------")
}

func findVBoxManage() string {
	cands := []string{}
	if pf := os.Getenv("ProgramFiles"); pf != "" {
		cands = append(cands, filepath.Join(pf, "Oracle", "VirtualBox", "VBoxManage.exe"))
	}
	if pf := os.Getenv("ProgramFiles(x86)"); pf != "" {
		cands = append(cands, filepath.Join(pf, "Oracle", "VirtualBox", "VBoxManage.exe"))
	}
	for _, c := range cands {
		if fileExists(c) {
			return c
		}
	}
	if p, err := exec.LookPath("VBoxManage.exe"); err == nil {
		return p
	}
	return ""
}

func matchesAppliance(name string) bool {
	n := strings.ToLower(name)
	return strings.Contains(n, "appliance") || strings.Contains(n, "vyomi") || strings.Contains(n, "cloudlearn")
}

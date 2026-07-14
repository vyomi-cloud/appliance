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

// bridgePorts are host ports forwarded to the appliance VM (9443/HTTPS is opt-in).
var bridgePorts = []int{9000}

// startLocalhostBridge maps 127.0.0.1:<port> → <vmIp>:<port> via netsh portproxy
// (Start-LocalhostBridge). Windows-only; a no-op elsewhere.
func (c *Config) startLocalhostBridge(vmIp string) {
	if vmIp == "" || runtime.GOOS != "windows" || !have("netsh") {
		return
	}
	for _, port := range bridgePorts {
		p := strconv.Itoa(port)
		_ = exec.Command("netsh", "interface", "portproxy", "delete", "v4tov4",
			"listenaddress=127.0.0.1", "listenport="+p).Run()
		if err := exec.Command("netsh", "interface", "portproxy", "add", "v4tov4",
			"listenaddress=127.0.0.1", "listenport="+p, "connectaddress="+vmIp, "connectport="+p).Run(); err != nil {
			progress(fmt.Sprintf("==> Note: could not bridge localhost:%d (needs an elevated shell). Use http://%s:%d/ instead.", port, vmIp, port))
		}
	}
}

// showUrlBanner prints the READY banner and opens the browser (Show-UrlBanner).
func (c *Config) showUrlBanner(vmIp string) {
	url := "http://localhost:9000/"
	if vmIp != "" {
		url = fmt.Sprintf("http://%s:9000/", vmIp)
	}
	if httpOK("http://127.0.0.1:9000/healthz", 2*time.Second) {
		url = "http://localhost:9000/"
	}
	progress("")
	progress("  ============================================================")
	progress("   Vyomi appliance is READY")
	progress("   Console : " + url)
	if vmIp != "" {
		progress(fmt.Sprintf("   Direct  : http://%s:9000/   (VM IP, no bridge needed)", vmIp))
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
	if httpOK("http://127.0.0.1:9000/healthz", 2*time.Second) {
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
		for _, p := range bridgePorts {
			rule := fmt.Sprintf("vyomi%d", p)
			_ = exec.Command(vbox, "controlvm", vmName, "natpf1", "delete", rule).Run()
			_ = exec.Command(vbox, "controlvm", vmName, "natpf1",
				fmt.Sprintf("%s,tcp,127.0.0.1,%d,,%d", rule, p, p)).Run()
		}
		time.Sleep(time.Second)
		if httpOK("http://127.0.0.1:9000/healthz", 3*time.Second) {
			progress("==> VirtualBox NAT port-forward added (localhost:9000 -> VM).")
			return
		}
	}
	// SYSTEM-owned VM: print the proven manual commands (auto-elevation via a SYSTEM
	// scheduled task is a follow-up; we never shell into a generated script here).
	c.printVBoxManualFallback(vbox)
}

func (c *Config) printVBoxManualFallback(vbox string) {
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
	progress(`     psexec -s -nobanner -accepteula $vb controlvm "<name>" natpf1 "vyomi9000,tcp,127.0.0.1,9000,,9000"`)
	progress("")
	progress("   Then open http://localhost:9000/")
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

package main

import (
	"encoding/json"
	"fmt"
	"math"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

const hostSizingFileName = "host-sizing-report.json"

func utcNow() string { return time.Now().UTC().Format("2006-01-02T15:04:05.000Z") }

func ensureDir(p string) error { return os.MkdirAll(p, 0o755) }

// writeApplianceManifest → appliance-bootstrap.json (Write-ApplianceManifest).
func (c *Config) writeApplianceManifest() error {
	if err := ensureDir(c.ApplianceDir); err != nil {
		return err
	}
	payload := map[string]any{
		"name": c.ApplianceName, "image": c.ApplianceImage, "cpus": c.Cpus,
		"memory": c.Memory, "disk": c.Disk, "workspace": c.Workspace,
		"host_os": runtime.GOOS, "distribution_mode": "appliance",
		"created_at": utcNow(),
	}
	return writeJSON(filepath.Join(c.ApplianceDir, "appliance-bootstrap.json"), payload)
}

// applianceSshPublicKey generates the ed25519 keypair if missing and returns the
// public key text (Get-ApplianceSshPublicKey).
func (c *Config) applianceSshPublicKey() string {
	priv := filepath.Join(homeDir(), ".ssh", "cloudlearn_multipass_ed25519")
	pub := priv + ".pub"
	if !fileExists(priv) || !fileExists(pub) {
		_ = ensureDir(filepath.Dir(priv))
		_ = run("ssh-keygen", "-t", "ed25519", "-N", "", "-f", priv, "-C", "vyomi")
	}
	if b, err := os.ReadFile(pub); err == nil {
		return strings.TrimSpace(string(b))
	}
	return ""
}

// applianceSizing is the pure host-tier sizing logic from Write-ApplianceHostSizing
// (extracted so it's unit-testable without touching the host).
func applianceSizing(memoryGib, totalGib, freeGib float64, cpuCount int) (cpus, memGb, diskGb int, reserve float64, warnings []string) {
	switch {
	case memoryGib <= 4:
		memGb, diskGb = 2, 24
	case memoryGib <= 8:
		memGb, diskGb = 4, 32
	case memoryGib <= 16:
		memGb, diskGb = 8, 32
	case memoryGib <= 32:
		memGb, diskGb = 12, 48
	case memoryGib <= 64:
		memGb, diskGb = 16, 64
	default:
		memGb = int(math.Min(24, math.Max(16, math.Round(memoryGib*0.25))))
		diskGb = int(math.Min(96, math.Max(64, math.Round(totalGib*0.12))))
	}
	cpus = int(math.Max(1, math.Min(math.Max(float64(cpuCount-1), 1), math.Round(float64(memGb)/2))))
	diskGb = int(math.Min(math.Max(float64(diskGb), 24), math.Max(24, math.Round(freeGib*0.25))))
	switch {
	case memoryGib <= 8:
		reserve = 1.5
	case memoryGib <= 16:
		reserve = 2.0
	case memoryGib <= 32:
		reserve = 2.5
	default:
		reserve = 3.0
	}
	if cpuCount < 4 || memoryGib < 8 {
		warnings = []string{"This host is small for a full appliance. Keep the VM at minimum size and avoid heavy sandboxes."}
	}
	return
}

// writeApplianceHostSizing → host-sizing-report.json (Write-ApplianceHostSizing).
func (c *Config) writeApplianceHostSizing() error {
	if err := ensureDir(c.ApplianceDir); err != nil {
		return err
	}
	cpuCount := runtime.NumCPU()
	memBytes := hostMemBytes()
	memGib := round1(float64(memBytes) / gib)
	totalBytes, freeBytes := diskBytes(c.RootDir)
	totalGib := round1(float64(totalBytes) / gib)
	freeGib := round1(float64(freeBytes) / gib)

	cpus, mem, disk, reserve, warnings := applianceSizing(memGib, totalGib, freeGib, cpuCount)
	available := math.Max(0, float64(mem)-reserve)
	ifaces := interfaceNames()

	payload := map[string]any{
		"source": "launcher", "host_os": runtime.GOOS, "cpu_count": cpuCount,
		"memory_bytes": memBytes, "memory_gib": memGib,
		"disk_total_bytes": totalBytes, "disk_used_bytes": totalBytes - freeBytes, "disk_free_bytes": freeBytes,
		"disk_total_gib": totalGib, "disk_free_gib": freeGib,
		"network_interfaces": ifaces, "network_interface_count": len(ifaces),
		"recommended": map[string]any{
			"appliance": map[string]any{"vcpus": cpus, "memory_gib": mem, "disk_gib": disk},
			"lxd_budget": map[string]any{
				"platform_reserve_gib": reserve,
				"small_instances":      int(math.Floor(available / 0.5)),
				"medium_instances":     int(math.Floor(available / 1.0)),
				"heavy_instances":      int(math.Floor(available / 2.0)),
			},
		},
		"warnings": orEmpty(warnings), "checked_at": utcNow(),
	}
	return writeJSON(filepath.Join(c.ApplianceDir, hostSizingFileName), payload)
}

// writeApplianceCloudInit renders cloud-init.yaml (Write-ApplianceCloudInit).
func (c *Config) writeApplianceCloudInit() error {
	if err := ensureDir(c.ApplianceDir); err != nil {
		return err
	}
	sshKeys := ""
	if pub := c.applianceSshPublicKey(); pub != "" {
		sshKeys = "ssh_authorized_keys:\n  - " + pub + "\n"
	}
	body := renderCloudInit(sshKeys, c.Workspace)
	return os.WriteFile(filepath.Join(c.ApplianceDir, "cloud-init.yaml"), []byte(body), 0o644)
}

// renderCloudInit fills the cloud-init template (extracted for testing).
func renderCloudInit(sshKeysBlock, workspace string) string {
	return fmt.Sprintf(cloudInitTemplate, sshKeysBlock, workspace)
}

// %s (ssh keys block), %s (workspace) — matches the PS1 here-string byte-for-byte.
const cloudInitTemplate = `#cloud-config
package_update: true
package_upgrade: true
%swrite_files:
  - path: /etc/docker/daemon.json
    permissions: '0644'
    content: |
      {"registry-mirrors": ["https://mirror.gcr.io"], "max-concurrent-downloads": 1, "max-download-attempts": 5}
packages:
  - python3
  - python3-pip
  - curl
  - ca-certificates
  - docker.io
  - docker-compose-v2
  - avahi-daemon
  - libnss-mdns
runcmd:
  - [ bash, -lc, "systemctl enable docker && systemctl restart docker" ]
  - [ bash, -lc, "usermod -aG docker ubuntu || true" ]
  - [ bash, -lc, "snap install lxd || true" ]
  - [ bash, -lc, "usermod -aG lxd ubuntu || true" ]
  - [ bash, -lc, "cat >/tmp/cloudlearn-lxd-preseed.yaml <<'EOF'\nconfig: {}\nnetworks:\n- name: lxdbr0\n  type: bridge\n  config:\n    ipv4.address: auto\n    ipv4.nat: \"true\"\n    ipv6.address: auto\n    ipv6.nat: \"true\"\nstorage_pools:\n- name: default\n  driver: dir\nprofiles:\n- name: default\n  description: Default LXD profile\n  config: {}\n  devices:\n    root:\n      type: disk\n      pool: default\n      path: /\n    eth0:\n      type: nic\n      network: lxdbr0\n      name: eth0\nEOF\nlxd init --preseed < /tmp/cloudlearn-lxd-preseed.yaml || true" ]
  - [ bash, -lc, "hostnamectl set-hostname vyomi || true" ]
  - [ bash, -lc, "sed -i 's/^hosts:.*/hosts: files mdns4_minimal [NOTFOUND=return] dns mdns4/' /etc/nsswitch.conf || true" ]
  - [ bash, -lc, "systemctl enable --now avahi-daemon || true" ]
  - [ bash, -lc, "mkdir -p %[2]s" ]
  - [ bash, -lc, "mkdir -p /var/lib/cloudlearn/deployments" ]
`

// ── helpers ────────────────────────────────────────────────────────────────
func writeJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0o644)
}

func fileExists(p string) bool { _, err := os.Stat(p); return err == nil }
func round1(f float64) float64 { return math.Round(f*10) / 10 }

func interfaceNames() []string {
	out := []string{}
	if ifs, err := net.Interfaces(); err == nil {
		for _, i := range ifs {
			if strings.TrimSpace(i.Name) != "" {
				out = append(out, i.Name)
			}
		}
	}
	return out
}

func orEmpty(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

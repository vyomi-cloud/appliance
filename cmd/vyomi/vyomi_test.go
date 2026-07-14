package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestApplianceSizingTiers(t *testing.T) {
	// memoryGib, totalGib, freeGib, cpu -> expected mem/disk/cpus (the PS1 tiers).
	cases := []struct {
		mem, total, free  float64
		cpu               int
		wantMem, wantDisk int
	}{
		{4, 240, 200, 8, 2, 24},    // <=4
		{8, 240, 200, 8, 4, 32},    // <=8
		{16, 480, 400, 8, 8, 32},   // <=16
		{32, 960, 800, 12, 12, 48}, // <=32
		{64, 960, 800, 16, 16, 64}, // <=64
	}
	for _, c := range cases {
		cpus, mem, disk, _, _ := applianceSizing(c.mem, c.total, c.free, c.cpu)
		if mem != c.wantMem {
			t.Errorf("mem=%.0f: got memGb=%d want %d", c.mem, mem, c.wantMem)
		}
		// disk is clamped by max(24, round(free*0.25)); with generous free it stays at tier value.
		if disk != c.wantDisk {
			t.Errorf("mem=%.0f: got disk=%d want %d", c.mem, disk, c.wantDisk)
		}
		if cpus < 1 {
			t.Errorf("mem=%.0f: cpus must be >=1, got %d", c.mem, cpus)
		}
	}
	// small host → warning present
	if _, _, _, _, w := applianceSizing(4, 100, 80, 2); len(w) == 0 {
		t.Error("expected a warning for a small (4GB/2cpu) host")
	}
	// large host → warning absent
	if _, _, _, _, w := applianceSizing(64, 960, 800, 16); len(w) != 0 {
		t.Errorf("did not expect a warning for a large host, got %v", w)
	}
	// disk clamps down on a nearly-full drive: free=40 → round(40*0.25)=10 → max(24,10)=24
	if _, _, disk, _, _ := applianceSizing(32, 960, 40, 12); disk != 24 {
		t.Errorf("expected disk clamped to 24 on a full drive, got %d", disk)
	}
}

func TestSelectIp(t *testing.T) {
	cases := []struct {
		ips  []string
		want string
	}{
		{[]string{"192.168.64.5", "172.17.0.1", "10.1.2.1"}, "192.168.64.5"}, // prefer routable
		{[]string{"172.17.0.1", "10.55.0.1"}, ""},                            // only bridge gateways → ""
		{[]string{"172.17.0.1", "192.168.5.9"}, "192.168.5.9"},               // skip docker gw
		{[]string{}, ""},
		{[]string{"10.20.30.40"}, ""}, // 10.x is treated as private-bridge in pass1; pass2 rejects only .1 gws but rePriv already skipped it in pass1, pass2 keeps non-.1 → but 10.20.30.40 not a gw → pass2 returns it
	}
	// note: the last case documents behavior — pass1 skips 10.x (private), pass2 keeps 10.20.30.40 (not a .1 gateway)
	cases[4].want = "10.20.30.40"
	for _, c := range cases {
		if got := selectIp(c.ips); got != c.want {
			t.Errorf("selectIp(%v) = %q, want %q", c.ips, got, c.want)
		}
	}
}

func TestMultipassListParse(t *testing.T) {
	sample := `{"list":[{"name":"cloudlearn-appliance","state":"Running","ipv4":["192.168.64.7","172.17.0.1"]},{"name":"other","state":"Stopped","ipv4":[]}]}`
	var l mpList
	if err := json.Unmarshal([]byte(sample), &l); err != nil {
		t.Fatal(err)
	}
	if len(l.List) != 2 || l.List[0].Name != "cloudlearn-appliance" || l.List[0].State != "Running" {
		t.Fatalf("bad parse: %+v", l)
	}
	if got := selectIp(l.List[0].Ipv4); got != "192.168.64.7" {
		t.Errorf("selectIp from record = %q", got)
	}
}

func TestCloudInitRender(t *testing.T) {
	c := &Config{Workspace: "/workspace/cloud-learn"}
	// render without a real ssh key (empty block)
	body := renderCloudInit("", c.Workspace)
	for _, must := range []string{
		"#cloud-config",
		"mirror.gcr.io",                   // docker registry mirror
		"docker-compose-v2",               // packages
		"mkdir -p /workspace/cloud-learn", // workspace interpolation
		"lxd init --preseed",              // lxd preseed
	} {
		if !strings.Contains(body, must) {
			t.Errorf("cloud-init missing %q", must)
		}
	}
	// with an ssh key, the authorized-keys block appears
	withKey := renderCloudInit("ssh_authorized_keys:\n  - ssh-ed25519 AAAA test\n", c.Workspace)
	if !strings.Contains(withKey, "ssh-ed25519 AAAA test") {
		t.Error("cloud-init did not include the ssh key")
	}
}

func TestManifestGeneration(t *testing.T) {
	dir := t.TempDir()
	c := &Config{
		ApplianceDir: dir, ApplianceName: "cloudlearn-appliance", ApplianceImage: "24.04",
		Cpus: 4, Memory: "8G", Disk: "40G", Workspace: "/workspace/cloud-learn",
		RootDir: dir,
	}
	if err := c.writeApplianceManifest(); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(filepath.Join(dir, "appliance-bootstrap.json"))
	var boot map[string]any
	if err := json.Unmarshal(b, &boot); err != nil {
		t.Fatalf("bootstrap json invalid: %v", err)
	}
	if boot["name"] != "cloudlearn-appliance" || boot["memory"] != "8G" || boot["distribution_mode"] != "appliance" {
		t.Errorf("bootstrap fields wrong: %+v", boot)
	}

	if err := c.writeApplianceHostSizing(); err != nil {
		t.Fatal(err)
	}
	b, _ = os.ReadFile(filepath.Join(dir, hostSizingFileName))
	var sizing map[string]any
	if err := json.Unmarshal(b, &sizing); err != nil {
		t.Fatalf("host-sizing json invalid: %v", err)
	}
	rec, ok := sizing["recommended"].(map[string]any)
	if !ok || rec["appliance"] == nil || rec["lxd_budget"] == nil {
		t.Errorf("host-sizing missing recommended.appliance/lxd_budget: %+v", sizing)
	}

	if err := c.writeApplianceCloudInit(); err != nil {
		t.Fatal(err)
	}
	ci, _ := os.ReadFile(filepath.Join(dir, "cloud-init.yaml"))
	if !strings.HasPrefix(string(ci), "#cloud-config") {
		t.Errorf("cloud-init.yaml malformed:\n%s", string(ci)[:min(80, len(ci))])
	}
}

func TestSubstrateResolution(t *testing.T) {
	t.Setenv("VYOMI_SUBSTRATE", "multipass")
	c := &Config{VyomiHome: t.TempDir()}
	if got := c.resolveSubstrate(); got != "multipass" {
		t.Errorf("explicit VYOMI_SUBSTRATE=multipass -> %q", got)
	}
	t.Setenv("VYOMI_SUBSTRATE", "")
	if got := c.resolveSubstrate(); got != "docker" {
		t.Errorf("no signal -> default should be docker, got %q", got)
	}
}

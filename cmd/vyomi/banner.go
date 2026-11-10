package main

// Launch view: the dot-matrix VYOMI banner, live steps with real timings and the
// "Ready" line — identical in all three launchers (this one, packaging/docker/vyomi
// and scripts/cloud-learn; tests/launcher/test_launch_view_consistency.py keeps
// them in step). Off when stderr isn't a terminal, in CI, with NO_COLOR or
// VYOMI_NO_BANNER=1; ASCII where the console can't draw the dots.

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"regexp"
	"runtime"
	"strings"
	"time"
)

// LAUNCH-VIEW-MATRIX (keep identical across launchers)
var vyomiMatrix = []string{
	"10001 10001 01110 10001 111",
	"10001 10001 10001 11011 010",
	"10001 01010 10001 10101 010",
	"10001 00100 10001 10101 010",
	"01010 00100 10001 10001 010",
	"01010 00100 10001 10001 010",
	"00100 00100 01110 10001 111",
}

const launchTagline = "local AWS · GCP · Azure — no cloud bill"

type launchView struct {
	tty, utf               bool
	c, d, g, y, r, b, z    string
	on, off, ok, bad, run_ string
	t0                     time.Time
}

func newLaunchView() *launchView {
	v := &launchView{t0: time.Now()}
	fi, err := os.Stderr.Stat()
	v.tty = err == nil && fi.Mode()&os.ModeCharDevice != 0 &&
		os.Getenv("NO_COLOR") == "" && os.Getenv("VYOMI_NO_BANNER") != "1" && os.Getenv("CI") == ""
	if v.tty && !enableVT() {
		v.tty = false // a console that can't render ANSI colours gets plain lines
	}
	loc := strings.ToUpper(os.Getenv("LC_ALL") + os.Getenv("LC_CTYPE") + os.Getenv("LANG"))
	// Windows: the legacy console can't draw the dots; Windows Terminal / VS Code can.
	v.utf = strings.Contains(loc, "UTF-8") || strings.Contains(loc, "UTF8") ||
		(runtime.GOOS == "windows" && (os.Getenv("WT_SESSION") != "" || os.Getenv("TERM_PROGRAM") != "")) ||
		(runtime.GOOS != "windows" && loc == "")
	if v.tty {
		v.c, v.d, v.g, v.y, v.r, v.b, v.z = "\033[36m", "\033[38;5;236m", "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m"
	}
	if v.utf {
		v.on, v.off, v.ok, v.bad, v.run_ = "●", "·", "✓", "✗", "▸"
	} else {
		v.on, v.off, v.ok, v.bad, v.run_ = "#", ".", "ok", "!!", ">"
	}
	return v
}

func (v *launchView) banner(version string) {
	if !v.tty {
		return
	}
	var sb strings.Builder
	sb.WriteString("\n")
	for _, row := range vyomiMatrix {
		sb.WriteString("  ")
		for _, ch := range row {
			switch ch {
			case '1':
				sb.WriteString(v.c + v.on + v.z + " ")
			case '0':
				sb.WriteString(v.d + v.off + v.z + " ")
			default:
				sb.WriteString("  ")
			}
		}
		sb.WriteString("\n")
	}
	fmt.Fprint(os.Stderr, sb.String())
	fmt.Fprintf(os.Stderr, "\n  %s%s%s   %s%s%s\n\n", v.b, launchTagline, v.z, v.d, version, v.z)
}

func (v *launchView) since() string { return fmt.Sprintf("%ds", int(time.Since(v.t0).Seconds())) }

func (v *launchView) stepOK(key, text string) {
	fmt.Fprintf(os.Stderr, "  %s%s%s %-10s %s %s(%s)%s\n", v.g, v.ok, v.z, key, text, v.d, v.since(), v.z)
}

func (v *launchView) stepBad(key, text string) {
	fmt.Fprintf(os.Stderr, "  %s%s%s %-10s %s\n", v.r, v.bad, v.z, key, text)
}

func (v *launchView) stepRun(key, text string) {
	if v.tty {
		fmt.Fprintf(os.Stderr, "\r\033[K  %s%s%s %-10s %s", v.y, v.run_, v.z, key, text)
	}
}

func (v *launchView) stepEnd() {
	if v.tty {
		fmt.Fprint(os.Stderr, "\r\033[K")
	}
}

type readiness struct {
	Ready      int `json:"ready_count"`
	Total      int `json:"total_count"`
	OverallPct int `json:"overall_pct"`
}

func readinessOf(url string) (*readiness, bool) {
	cl := &http.Client{Timeout: 2 * time.Second}
	resp, err := cl.Get(strings.TrimRight(url, "/") + "/api/runtime/readiness")
	if err != nil {
		return nil, false
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, false
	}
	var r readiness
	if json.NewDecoder(resp.Body).Decode(&r) != nil {
		return nil, true
	}
	return &r, true
}

// waitReady: the console first, then the backends coming up (they keep starting in
// the background after we return; the console's readiness strip shows the rest).
func (v *launchView) waitReady(url string) {
	up := false
	for i := 0; i < 120; i++ {
		if _, ok := readinessOf(url); ok {
			up = true
			break
		}
		v.stepRun("console", fmt.Sprintf("starting the simulator… %ds", i))
		time.Sleep(time.Second)
	}
	v.stepEnd()
	if !up {
		v.stepBad("console", "not answering on "+url+" yet — check `vyomi logs`")
		return
	}
	v.stepOK("console", url)
	var r *readiness
	for i := 0; i < 90; i++ {
		r, _ = readinessOf(url)
		if r == nil || r.Total == 0 {
			break
		}
		if r.Ready == r.Total {
			v.stepEnd()
			v.stepOK("backends", fmt.Sprintf("%d/%d ready (S3 · KMS · SQL · NoSQL · queues · Pub/Sub · Blob)", r.Total, r.Total))
			return
		}
		v.stepRun("backends", fmt.Sprintf("%d/%d ready (%d%%) — pulling and starting in the background", r.Ready, r.Total, r.OverallPct))
		if !v.tty {
			break
		}
		time.Sleep(2 * time.Second)
	}
	v.stepEnd()
	if r != nil && r.Total > 0 {
		v.stepOK("backends", fmt.Sprintf("%d/%d ready; the rest keep starting in the background", r.Ready, r.Total))
	}
}

// LAUNCH-VIEW-READY (keep identical across launchers)
func (v *launchView) ready(url string) {
	fmt.Fprintf(os.Stderr, "\n  %sReady.%s Open %s%s%s   ·   SDK/CLI: point --endpoint-url at %s\n", v.b, v.z, v.c, url, v.z, url)
	fmt.Fprintf(os.Stderr, "  %sPro tier: launch an EC2 instance in the console, then ssh ubuntu@<ip>.%s\n\n", v.d, v.z)
}

var reComposeVer = regexp.MustCompile(`vyomi/appliance:([0-9][0-9.]*)`)

// composeVersion reads the release the compose file pins (vyomi/appliance:X.Y.Z).
func composeVersion(cf string) string {
	b, err := os.ReadFile(cf)
	if err != nil {
		return "dev"
	}
	if m := reComposeVer.FindSubmatch(b); m != nil {
		return "v" + string(m[1])
	}
	return "dev"
}

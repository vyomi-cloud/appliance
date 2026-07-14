package main

import (
	"os"
	"strconv"
	"strings"
)

// totalMemGb / freeDiskGb are best-effort, portable (no build tags) fallbacks used
// only by the Multipass VM sizing. The Docker substrate never exercises them. Exact
// Windows detection (GlobalMemoryStatusEx / DriveInfo) is added with the Multipass
// substrate, where sizing is actually applied; here a safe default avoids starving a
// host that we can't measure.
func totalMemGb() float64 {
	// Linux/WSL: /proc/meminfo MemTotal (kB). Other OSes fall through to the default.
	if b, err := os.ReadFile("/proc/meminfo"); err == nil {
		for _, line := range strings.Split(string(b), "\n") {
			if strings.HasPrefix(line, "MemTotal:") {
				f := strings.Fields(line)
				if len(f) >= 2 {
					if kb, err := strconv.ParseFloat(f[1], 64); err == nil {
						return kb / (1024 * 1024)
					}
				}
			}
		}
	}
	return 8.0
}

func freeDiskGb() float64 {
	return 30.0
}

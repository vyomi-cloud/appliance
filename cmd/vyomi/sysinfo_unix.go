//go:build !windows

package main

import (
	"os"
	"strconv"
	"strings"
	"syscall"
)

// hostMemBytes: total physical RAM. Linux/WSL via /proc/meminfo; other unices
// fall back to a safe default (this VM path ships on Windows, where the accurate
// GlobalMemoryStatusEx implementation is used — see sysinfo_windows.go).
func hostMemBytes() int64 {
	if b, err := os.ReadFile("/proc/meminfo"); err == nil {
		for _, line := range strings.Split(string(b), "\n") {
			if strings.HasPrefix(line, "MemTotal:") {
				f := strings.Fields(line)
				if len(f) >= 2 {
					if kb, err := strconv.ParseInt(f[1], 10, 64); err == nil {
						return kb * 1024
					}
				}
			}
		}
	}
	return 8 * 1024 * 1024 * 1024
}

// diskBytes: (total, free) for the filesystem containing path, via statfs.
func diskBytes(path string) (int64, int64) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return 120 * 1024 * 1024 * 1024, 30 * 1024 * 1024 * 1024
	}
	bs := int64(st.Bsize)
	total := int64(st.Blocks) * bs
	free := int64(st.Bavail) * bs
	return total, free
}

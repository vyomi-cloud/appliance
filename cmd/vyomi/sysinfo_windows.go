//go:build windows

package main

import (
	"path/filepath"
	"syscall"
	"unsafe"
)

var (
	kernel32               = syscall.NewLazyDLL("kernel32.dll")
	procGlobalMemoryStatus = kernel32.NewProc("GlobalMemoryStatusEx")
	procGetDiskFreeSpaceEx = kernel32.NewProc("GetDiskFreeSpaceExW")
)

type memoryStatusEx struct {
	Length               uint32
	MemoryLoad           uint32
	TotalPhys            uint64
	AvailPhys            uint64
	TotalPageFile        uint64
	AvailPageFile        uint64
	TotalVirtual         uint64
	AvailVirtual         uint64
	AvailExtendedVirtual uint64
}

// hostMemBytes: total physical RAM via GlobalMemoryStatusEx (matches the PS1's
// Win32_ComputerSystem.TotalPhysicalMemory).
func hostMemBytes() int64 {
	var m memoryStatusEx
	m.Length = uint32(unsafe.Sizeof(m))
	r, _, _ := procGlobalMemoryStatus.Call(uintptr(unsafe.Pointer(&m)))
	if r == 0 {
		return 8 * 1024 * 1024 * 1024
	}
	return int64(m.TotalPhys)
}

// diskBytes: (total, free) for the volume containing path via GetDiskFreeSpaceExW
// (matches the PS1's DriveInfo TotalSize/AvailableFreeSpace).
func diskBytes(path string) (int64, int64) {
	vol := filepath.VolumeName(path)
	if vol == "" {
		vol = "C:"
	}
	dir := vol + `\`
	p, err := syscall.UTF16PtrFromString(dir)
	if err != nil {
		return 120 * 1024 * 1024 * 1024, 30 * 1024 * 1024 * 1024
	}
	var freeAvail, total, totalFree uint64
	r, _, _ := procGetDiskFreeSpaceEx.Call(
		uintptr(unsafe.Pointer(p)),
		uintptr(unsafe.Pointer(&freeAvail)),
		uintptr(unsafe.Pointer(&total)),
		uintptr(unsafe.Pointer(&totalFree)),
	)
	if r == 0 {
		return 120 * 1024 * 1024 * 1024, 30 * 1024 * 1024 * 1024
	}
	return int64(total), int64(freeAvail)
}

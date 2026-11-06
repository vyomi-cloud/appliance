#!/bin/sh
# Builds the Nano in-browser VM guest image (v86, 32-bit x86): an Alpine i386
# kernel (linux-virt) + a whole-rootfs initramfs with dropbear (SSH), busybox
# httpd, sudo, python3 and git (Nano in-browser VMs ship git + Python for every tier; every other language runs on the booster). Run on the host:
#
#   docker run --rm --platform linux/386 -v "$PWD/wasm/vm:/vm" alpine:3.21 sh /vm/build-image.sh
#
# Outputs (committed under wasm/vm/image/): vmlinuz (kernel), rootfs.cpio.gz.
# The rootfs lives in RAM (initramfs), so a VM's state is exactly its v86
# memory snapshot: Stop = save_state, Start = restore_state.
set -eu
WITH_PY="${WITH_PY:-1}"
apk add --no-cache linux-virt cpio kmod >/dev/null
# apk (package manager) + the standard CLI tools. In the browser the supported toolchain is git + Python (below); other languages are the
# booster's job (64-bit Docker, latest versions). Anything else can still be `apk add`-ed over SSH, but it is not supported or tested here.
PKGS="dropbear dropbear-scp busybox-extras sudo apk-tools alpine-keys ca-certificates bash curl nano less coreutils findutils grep sed gawk tar gzip unzip procps-ng openssl git"
[ "$WITH_PY" = 1 ] && PKGS="$PKGS python3 py3-pip"      # pip + apk are the package managers
R=/tmp/rootfs
rm -rf "$R"; mkdir -p "$R"
apk add --no-cache --root "$R" --initdb --keys-dir /etc/apk/keys \
  --repositories-file /etc/apk/repositories alpine-baselayout busybox musl-utils alpine-release $PKGS >/dev/null
# apk inside the guest needs its repository list
mkdir -p "$R/etc/apk"; sed "s,https://,http://," /etc/apk/repositories > "$R/etc/apk/repositories"   # guest TLS cannot go through the in-browser fetch network; the relay /egress fetches over https upstream
KV=$(ls /lib/modules)
# Only the NIC drivers v86 emulates (virtio-net preferred, ne2k-pci fallback) + deps.
for m in drivers/net/virtio_net drivers/net/net_failover net/core/failover \
         drivers/net/ethernet/8390/8390 drivers/net/ethernet/8390/ne2k-pci; do
  mkdir -p "$R/lib/modules/$KV/kernel/$(dirname $m)"
  cp /lib/modules/$KV/kernel/$m.ko.gz "$R/lib/modules/$KV/kernel/$m.ko.gz"
done
cp /lib/modules/$KV/modules.builtin* /lib/modules/$KV/modules.order "$R/lib/modules/$KV/" 2>/dev/null || true
depmod -b "$R" "$KV"
rm -rf "$R/var/cache/apk"/* "$R/usr/share/apk" "$R/lib/apk/db/scripts.tar" 2>/dev/null || true
find "$R/usr/lib" -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$R/usr/lib/python3"*/test "$R/usr/lib/python3"*/idlelib "$R/usr/lib/python3"*/tkinter \
       "$R/usr/lib/python3"*/lib2to3 2>/dev/null || true

cat > "$R/init" <<'EOF'
#!/bin/sh
# PID 1 of the Nano VM: mounts, loopback + NIC, then busybox init (inittab).
mount -t proc proc /proc; mount -t sysfs sys /sys; mount -t devtmpfs dev /dev
mkdir -p /dev/pts /dev/shm /run /tmp; mount -t devpts devpts /dev/pts; mount -t tmpfs tmpfs /run
chmod 1777 /tmp
exec /sbin/init
EOF
chmod +x "$R/init"

cat > "$R/etc/inittab" <<'EOF'
::sysinit:/etc/vyomi/boot.sh
ttyS0::respawn:-/bin/sh
ttyS1::respawn:/etc/vyomi/agent.sh
::ctrlaltdel:/sbin/reboot
::shutdown:/bin/true
EOF
mkdir -p "$R/etc/vyomi" "$R/etc/dropbear"
# Package managers + git work as-is in the browser: the guest has no TLS, so it talks plain HTTP to the tunnel's allow-listed /egress, which upgrades to HTTPS upstream.
printf '[global]\nindex-url = http://pypi.org/simple\ntrusted-host = pypi.org files.pythonhosted.org\nbreak-system-packages = true\n' > "$R/etc/pip.conf"
printf '[url "http://github.com/"]\n\tinsteadOf = https://github.com/\n[url "http://gitlab.com/"]\n\tinsteadOf = https://gitlab.com/\n' > "$R/etc/gitconfig"
cat > "$R/etc/vyomi/boot.sh" <<'EOF'
#!/bin/sh
hostname vyomi-vm
modprobe virtio_net 2>/dev/null || modprobe ne2k-pci 2>/dev/null
ip link set lo up
ip link set eth0 up 2>/dev/null
# v86's in-browser network adapter: VM 192.168.86.100, router/DNS 192.168.86.1.
ip addr add 192.168.86.100/24 dev eth0 2>/dev/null
ip route add default via 192.168.86.1 2>/dev/null
echo "nameserver 192.168.86.1" > /etc/resolv.conf
# -R: host keys generated on first connection (after the per-instance reseed).
/usr/sbin/dropbear -R -p 22
EOF
chmod +x "$R/etc/vyomi/boot.sh"

# Control agent on the 2nd serial port (ttyS1): the page sends
#   <id> <base64 command> [user]
# and reads back "@@VYOMI <id> <rc> <base64 output>". Used by provisioning and
# the /exec API (the console's "run command"), never by SSH.
cat > "$R/etc/vyomi/agent.sh" <<'EOF'
#!/bin/sh
exec </dev/ttyS1 >/dev/ttyS1 2>/dev/null
stty raw -echo 2>/dev/null
echo "@@VYOMI ready 0 -"
while read -r id b64 user; do
  [ -n "$id" ] || continue
  cmd=$(printf %s "$b64" | base64 -d 2>/dev/null)
  if [ -n "$user" ] && [ "$user" != root ]; then
    out=$(cd /tmp; su -s /bin/sh "$user" -c "cd ~ 2>/dev/null; $cmd" 2>&1 </dev/null); rc=$?
  else
    out=$(cd /root; sh -c "$cmd" 2>&1 </dev/null); rc=$?
  fi
  enc=$(printf %s "$out" | base64 -w0); [ -n "$enc" ] || enc=-
  printf '@@VYOMI %s %s %s\n' "$id" "$rc" "$enc"
done
EOF
chmod +x "$R/etc/vyomi/agent.sh"
sed -i 's#^root:[^:]*:#root:*:#' "$R/etc/shadow"
echo "%wheel ALL=(ALL) NOPASSWD: ALL" > "$R/etc/sudoers.d/wheel"
chmod 440 "$R/etc/sudoers.d/wheel"
cat > "$R/etc/motd" <<'EOF'

  Vyomi Nano VM - Alpine Linux (i386) running in your browser tab (v86).
  Files live in RAM: Stop saves them, Terminate discards them.
  Egress is limited to plain-HTTP fetch; see the console's Connect tab.

EOF
mkdir -p /vm/image
cp /boot/vmlinuz-virt /vm/image/vmlinuz
(cd "$R" && find . | cpio -o -H newc 2>/dev/null) | gzip -9 > /vm/image/rootfs.cpio.gz
du -sh "$R"; ls -la /vm/image

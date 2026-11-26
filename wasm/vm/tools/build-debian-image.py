#!/usr/bin/env python3
"""Builds the Nano Debian 12 (bookworm) i386 guest image WITHOUT Docker and WITHOUT root.

  python3 -I build-debian-image.py OUT_DIR [--scratch DIR] [--minimal]

What it does (everything stays in memory / the scratch dir; nothing from the network is ever executed on the host):
  1. pulls the official `i386/debian:bookworm-slim` OCI image from Docker Hub and merges its layer(s)   (oci2initramfs.py)
  2. resolves + downloads the extra .deb files from deb.debian.org (sha256 checked against the signed-by-https Packages index) and unpacks them
     into the same in-memory file tree: git, python3, python3-pip, dropbear-bin, iproute2, kmod, sudo, procps, ca-certificates, nano, less (+ dependencies).
     Maintainer scripts are NOT run (no chroot is possible here); the dpkg database is updated so `dpkg -l` / `apt` see them as installed.
     git's Perl helpers (perl, git-man, liberror-perl) are deliberately left out (~45 MB) and removed from git's Depends in the dpkg database.
  3. adds the Vyomi boot files (/init, /etc/vyomi/boot.sh + agent.sh, pip/git config, sudoers) and the NIC kernel modules of the Alpine guest
     kernel (the Debian guest boots the SAME kernel `vmlinuz` as Alpine: wasm/vm/image/vmlinuz)
  4. writes OUT_DIR/rootfs.cpio.gz (+ OUT_DIR/manifest.json with sizes and sha256)

Kernel: the Alpine guest's wasm/vm/image/vmlinuz is reused as is (images.json points at ../vmlinuz).
"""
import sys, os, io, gzip, json, hashlib, lzma, tarfile, time, stat, urllib.request, argparse, re, importlib.util, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
VM = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("oci2initramfs", os.path.join(HERE, "oci2initramfs.py"))
oci = importlib.util.module_from_spec(spec); spec.loader.exec_module(oci)

MIRROR = "http://deb.debian.org/debian"
SUITE = "bookworm"
ROOTS = ["git", "python3", "python3-pip", "dropbear-bin", "iproute2", "kmod", "sudo", "procps", "ca-certificates", "nano", "less"]
SKIP = {"perl", "git-man", "liberror-perl"}          # git's Perl helpers: left out on purpose (see module docstring)
USRMERGE = ("bin", "sbin", "lib", "lib32", "lib64", "libx32")
EPOCH = 1700000000


def fetch(url):
    last = None
    for _ in range(4):
        try:
            return urllib.request.urlopen(url, timeout=120).read()
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(2)
    raise SystemExit(f"download failed {url}: {last}")


def parse_stanzas(text):
    out = []
    for blk in text.split("\n\n"):
        if not blk.strip():
            continue
        d, key = {}, None
        for line in blk.split("\n"):
            if line[:1] in (" ", "\t") and key:
                d[key] += "\n" + line
            elif ":" in line:
                key, _, v = line.partition(":"); d[key] = v.strip()
        if "Package" in d:
            out.append(d)
    return out


def dep_groups(field):
    groups = []
    for part in (field or "").split(","):
        alts = []
        for a in part.split("|"):
            n = re.sub(r"\(.*?\)|\[.*?\]|<.*?>", "", a).strip().split(":")[0].strip()
            if n:
                alts.append(n)
        if alts:
            groups.append(alts)
    return groups


def ar_members(data):
    assert data[:8] == b"!<arch>\n"
    i, out = 8, {}
    while i < len(data):
        h = data[i:i + 60]; name = h[:16].decode().strip().rstrip("/"); size = int(h[48:58].decode().strip())
        out[name] = data[i + 60:i + 60 + size]; i += 60 + size + (size & 1)
    return out


def open_tar(blob, name):
    if name.endswith(".zst"):
        raise SystemExit("zstd-compressed .deb member not supported by this builder: " + name)
    return tarfile.open(fileobj=io.BytesIO(blob), mode="r:*")


def canon(p, fs):
    p = p.lstrip("./").rstrip("/")
    first = p.split("/", 1)[0]
    if first in USRMERGE and fs.get(first, ("",))[0] == "l":      # /bin -> usr/bin etc. (usrmerge): write through the real directory
        p = "usr/" + p
    return p


def add_tar(fs, tf):
    names = []
    for ti in tf:
        p = canon(ti.name, fs)
        if not p:
            continue
        names.append("/" + ti.name.lstrip("./"))
        if ti.isdir():
            if p not in fs:
                fs[p] = ("d", ti.mode, 0, 0, EPOCH, b"")
        elif ti.issym():
            fs[p] = ("l", 0o777, 0, 0, EPOCH, ti.linkname.encode())
        elif ti.islnk():
            src = fs.get(canon(ti.linkname, fs))
            if src:
                fs[p] = (src[0], ti.mode, 0, 0, EPOCH, src[5])
        elif ti.isreg():
            fs[p] = ("f", ti.mode, 0, 0, EPOCH, tf.extractfile(ti).read())
    return names


def mkdirs(fs):
    for p in list(fs):
        parts = p.split("/")[:-1]
        for k in range(1, len(parts) + 1):
            d = "/".join(parts[:k])
            if d not in fs:
                fs[d] = ("d", 0o755, 0, 0, EPOCH, b"")


INIT = r'''#!/bin/sh
# PID 1 of the Nano Debian VM: mounts, network + sshd (boot.sh), the control agent on ttyS1, then a root shell on ttyS0 (respawned).
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root TERM=vt100 LANG=C.UTF-8
mount -t proc proc /proc; mount -t sysfs sys /sys; mount -t devtmpfs dev /dev
mkdir -p /dev/pts /dev/shm /run /tmp; mount -t devpts devpts /dev/pts; mount -t tmpfs tmpfs /run
chmod 1777 /tmp
/etc/vyomi/boot.sh
setsid /etc/vyomi/agent.sh &
while :; do
  setsid -c /bin/bash -c 'exec /bin/bash -l </dev/ttyS0 >/dev/ttyS0 2>&1'
done
'''
BOOT = r'''#!/bin/sh
hostname vyomi-vm
modprobe virtio_net 2>/dev/null || modprobe ne2k-pci 2>/dev/null
ip link set lo up
ip link set eth0 up 2>/dev/null
# v86's in-browser network adapter: VM 192.168.86.100, router/DNS 192.168.86.1.
ip addr add 192.168.86.100/24 dev eth0 2>/dev/null
ip route add default via 192.168.86.1 2>/dev/null
echo "nameserver 192.168.86.1" > /etc/resolv.conf
mkdir -p /etc/dropbear
# -R: host keys generated on first connection (after the per-instance reseed).
/usr/sbin/dropbear -R -p 22
'''
AGENT = r'''#!/bin/sh
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
'''
MOTD = '''
  Vyomi Nano VM - Debian GNU/Linux 12 (bookworm, i386) running in your browser tab (v86).
  Files live in RAM: Stop saves them, Terminate discards them.
  Egress is limited to plain-HTTP fetch; see the console's Connect tab.

'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("--scratch", default="")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    scratch = a.scratch or os.path.join(a.out, ".scratch"); os.makedirs(scratch, exist_ok=True)
    t0 = time.time()
    fs = oci.merge(oci.pull("i386/debian", "bookworm-slim", "386"))
    base_status = fs["var/lib/dpkg/status"][5].decode()
    installed = {d["Package"]: d for d in parse_stanzas(base_status)}
    provided = {}
    for d in installed.values():
        for g in dep_groups(d.get("Provides", "")):
            for n in g:
                provided[n] = d["Package"]
    idx_gz = os.path.join(scratch, "Packages.xz")
    if not os.path.exists(idx_gz):
        open(idx_gz, "wb").write(fetch(f"{MIRROR}/dists/{SUITE}/main/binary-i386/Packages.xz"))
    avail = {d["Package"]: d for d in parse_stanzas(lzma.open(idx_gz).read().decode())}
    prov_av = {}
    for d in avail.values():
        for g in dep_groups(d.get("Provides", "")):
            for n in g:
                prov_av.setdefault(n, d["Package"])
    want, order = {}, []

    def have(n):
        return n in installed or n in provided or n in want

    def need(n):
        if n in SKIP or have(n):
            return
        real = n if n in avail else prov_av.get(n)
        if real is None:
            print("  (unresolvable, skipped)", n); return
        if have(real):
            return
        want[real] = avail[real]; order.append(real)
        for field in ("Pre-Depends", "Depends"):
            for alts in dep_groups(avail[real].get(field, "")):
                if any(have(x) or x in SKIP for x in alts):
                    continue
                need(alts[0] if alts[0] in avail or alts[0] in prov_av else next((x for x in alts if x in avail or x in prov_av), alts[0]))
    for r in ROOTS:
        need(r)
    print(f"resolved {len(order)} extra packages: {' '.join(order)}")
    dl = 0
    new_status = []
    for n in order:
        d = avail[n]; fn = d["Filename"]
        path = os.path.join(scratch, os.path.basename(fn))
        if not os.path.exists(path):
            open(path, "wb").write(fetch(f"{MIRROR}/{fn}"))
        blob = open(path, "rb").read(); dl += len(blob)
        if hashlib.sha256(blob).hexdigest() != d["SHA256"]:
            raise SystemExit("sha256 mismatch for " + n)
        mem = ar_members(blob)
        dname = next(k for k in mem if k.startswith("data.tar")); cname = next(k for k in mem if k.startswith("control.tar"))
        names = add_tar(fs, open_tar(mem[dname], dname))
        ctl = open_tar(mem[cname], cname)
        for ti in ctl:
            if ti.isreg():
                base = os.path.basename(ti.name)
                if base in ("control", "triggers"):
                    continue
                fs[f"var/lib/dpkg/info/{n}.{base}"] = ("f", ti.mode, 0, 0, EPOCH, ctl.extractfile(ti).read())
        fs[f"var/lib/dpkg/info/{n}.list"] = ("f", 0o644, 0, 0, EPOCH, ("\n".join(names) + "\n").encode())
        keep = ("Package", "Version", "Architecture", "Maintainer", "Installed-Size", "Depends", "Pre-Depends", "Recommends", "Suggests", "Conflicts", "Breaks", "Replaces", "Provides", "Section", "Priority", "Multi-Arch", "Homepage", "Description")
        st = []
        for k in keep:
            if k not in d:
                continue
            v = d[k]
            if n == "git" and k == "Depends":     # the Perl helpers are not installed (see docstring): keep dpkg consistent
                v = ", ".join(x for x in (p.strip() for p in v.split(",")) if x.split(" ")[0] not in SKIP)
            if k == "Package":
                st.append(f"Package: {n}"); st.append("Status: install ok installed")
            else:
                st.append(f"{k}: {v}")
        new_status.append("\n".join(st))
    print(f"downloaded {dl/1e6:.1f} MB of .deb files")
    fs["var/lib/dpkg/status"] = ("f", 0o644, 0, 0, EPOCH, (base_status.rstrip("\n") + "\n\n" + "\n\n".join(new_status) + "\n\n").encode())
    # CA bundle (ca-certificates' postinst would build it)
    certs = sorted(p for p in fs if p.startswith("usr/share/ca-certificates/mozilla/") and p.endswith(".crt"))
    if certs:
        fs["etc/ssl/certs/ca-certificates.crt"] = ("f", 0o644, 0, 0, EPOCH, b"".join(fs[p][5] for p in certs))
    # Vyomi boot files
    def put(path, data, mode=0o644, kind="f"):
        fs[path] = (kind, mode, 0, 0, EPOCH, data if isinstance(data, bytes) else data.encode())
    put("init", INIT, 0o755); put("etc/vyomi/boot.sh", BOOT, 0o755); put("etc/vyomi/agent.sh", AGENT, 0o755)
    put("etc/motd", MOTD); put("etc/hostname", "vyomi-vm\n")
    put("etc/pip.conf", "[global]\nindex-url = http://pypi.org/simple\ntrusted-host = pypi.org files.pythonhosted.org\nbreak-system-packages = true\n")
    put("etc/gitconfig", '[url "http://github.com/"]\n\tinsteadOf = https://github.com/\n[url "http://gitlab.com/"]\n\tinsteadOf = https://gitlab.com/\n')
    put("etc/sudoers.d/wheel", "%wheel ALL=(ALL) NOPASSWD: ALL\n", 0o440)
    put("etc/apt/sources.list", f"deb http://deb.debian.org/debian {SUITE} main\n")
    fs.pop("etc/apt/sources.list.d/debian.sources", None)
    # root: no password, key-only (ssh) / console shell
    sh = fs["etc/shadow"][5].decode().replace("root:*:", "root:*:")
    fs["etc/shadow"] = ("f", 0o640, 0, 0, EPOCH, sh.encode())
    # slim down: docs, man pages, locales, tests, tkinter, pycache (all regenerated / not needed in a RAM disk)
    drop = ("usr/share/man/", "usr/share/info/", "usr/share/locale/", "usr/share/lintian/", "usr/share/bug/", "usr/share/bash-completion/")
    for p in list(fs):
        if p.startswith(drop) or (p.startswith("usr/share/doc/") and fs[p][0] == "f" and not p.endswith("/copyright")) \
           or re.search(r"/__pycache__(/|$)", p) or re.search(r"usr/lib/python3[^/]*/(test|idlelib|tkinter|lib2to3|turtledemo)(/|$)", p):
            del fs[p]
    # kernel NIC modules from the production Alpine guest (same kernel): virtio-net / ne2k-pci + deps, with their depmod files
    for (n, mode, uid, gid, mt, data, rdev) in oci.read_cpio(os.path.join(VM, "image", "rootfs.cpio.gz")):
        if n.startswith("lib/modules"):
            kind = "d" if stat.S_ISDIR(mode) else "l" if stat.S_ISLNK(mode) else "f"
            fs["usr/" + n] = (kind, mode, 0, 0, EPOCH, data)
    mkdirs(fs)
    for d in ("proc", "sys", "dev", "run", "tmp", "root", "home", "mnt", "etc/dropbear"):
        fs.setdefault(d, ("d", 0o755, 0, 0, EPOCH, b""))
    fs["tmp"] = ("d", 0o1777, 0, 0, EPOCH, b"")
    # cpio
    buf = io.BytesIO(); ino = 1
    for p in sorted(fs, key=lambda x: (x.count("/"), x)):
        kind, mode, uid, gid, mt, payload = fs[p]; ino += 1
        typ = {"d": stat.S_IFDIR, "f": stat.S_IFREG, "l": stat.S_IFLNK}[kind]
        oci.cpio_entry(buf, ino, p, (mode & 0o7777) | typ, uid, gid, mt, payload)
    oci.cpio_entry(buf, 0, "TRAILER!!!", 0, 0, 0, 0)
    raw = buf.getvalue(); gz = gzip.compress(raw, 9)
    open(os.path.join(a.out, "rootfs.cpio.gz"), "wb").write(gz)
    man = {"image": "debian12-i386", "files": len(fs), "rootfs_raw_bytes": len(raw), "rootfs_gz_bytes": len(gz),
           "rootfs_sha256": hashlib.sha256(gz).hexdigest(), "kernel": "shared with Alpine: ../vmlinuz",
           "extra_packages": order, "debs_downloaded_bytes": dl, "build_seconds": round(time.time() - t0)}
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print(json.dumps(man, indent=1)[:600])


main()

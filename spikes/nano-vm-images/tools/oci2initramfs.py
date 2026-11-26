#!/usr/bin/env python3
"""oci2initramfs.py - turn an OCI/Docker image (any arch) into a gzip'd newc cpio initramfs WITHOUT Docker and
WITHOUT root. Layers are streamed from the registry (anonymous pull), merged in memory (whiteouts honoured) and written
straight to a cpio stream, so nothing from the image is ever extracted to disk (no path-traversal / no setuid on host).

  oci2initramfs.py REPO TAG PLATFORM OUT.cpio.gz [--init init.sh] [--keep-cpio-prefix lib/modules --from-cpio old.cpio.gz]
  e.g.  oci2initramfs.py i386/debian bookworm-slim 386 debian.cpio.gz --init init-debian.sh \
            --from-cpio ../../wasm/vm/image/rootfs.cpio.gz --keep-cpio-prefix lib/modules

SPIKE tool (no production use)."""
import sys, io, json, gzip, tarfile, urllib.request, argparse, stat, time

def http(url, token=None, accept=None):
    h = {}
    if token: h["Authorization"] = "Bearer " + token
    if accept: h["Accept"] = accept
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=120)

def pull(repo, tag, platform):
    if "/" not in repo: repo = "library/" + repo
    tok = json.load(http(f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"))["token"]
    acc = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
    m = json.load(http(f"https://registry-1.docker.io/v2/{repo}/manifests/{tag}", tok, acc))
    if "manifests" in m:
        arch, _, variant = platform.partition("/")
        pick = [x for x in m["manifests"] if x["platform"]["architecture"] == arch and x["platform"]["os"] == "linux"
                and (not variant or x["platform"].get("variant") == variant)]
        if not pick: raise SystemExit("no such platform; have: " + ", ".join(x["platform"]["architecture"] for x in m["manifests"]))
        m = json.load(http(f"https://registry-1.docker.io/v2/{repo}/manifests/{pick[0]['digest']}", tok, acc))
    layers = []
    for l in m["layers"]:
        t0 = time.time(); data = http(f"https://registry-1.docker.io/v2/{repo}/blobs/{l['digest']}", tok).read()
        sys.stderr.write(f"layer {l['digest'][:19]} {len(data)/1e6:.1f} MB in {time.time()-t0:.1f}s\n")
        layers.append(data)
    return layers

def merge(layers):
    fs = {}  # path -> (kind, mode, uid, gid, mtime, payload)
    for data in layers:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            for ti in tf:
                p = ti.name.lstrip("./").rstrip("/")
                if not p: continue
                base = p.rsplit("/", 1)[-1]
                if base.startswith(".wh."):
                    dead = p[:-len(base)] + base[4:]
                    if base == ".wh..wh..opq":
                        pre = p[:-len(base)]
                        for k in [k for k in fs if k.startswith(pre) and k != pre.rstrip("/")]: del fs[k]
                    else:
                        for k in [k for k in fs if k == dead or k.startswith(dead + "/")]: del fs[k]
                    continue
                if ti.isdir(): fs[p] = ("d", ti.mode, ti.uid, ti.gid, ti.mtime, b"")
                elif ti.issym(): fs[p] = ("l", 0o777, ti.uid, ti.gid, ti.mtime, ti.linkname.encode())
                elif ti.islnk():
                    src = fs.get(ti.linkname.lstrip("./"))
                    if src: fs[p] = (src[0], ti.mode, ti.uid, ti.gid, ti.mtime, src[5])
                elif ti.isreg(): fs[p] = ("f", ti.mode, ti.uid, ti.gid, ti.mtime, tf.extractfile(ti).read())
                elif ti.ischr() or ti.isblk(): fs[p] = ("c" if ti.ischr() else "b", ti.mode, ti.uid, ti.gid, ti.mtime, (ti.devmajor, ti.devminor))
    return fs

def cpio_entry(out, ino, name, mode, uid, gid, mtime, data=b"", rdev=(0, 0)):
    nb = name.encode() + b"\0"
    hdr = "070701" + "".join("%08x" % v for v in (ino, mode, uid, gid, 1, int(mtime) & 0xffffffff, len(data), 0, 0, rdev[0], rdev[1], len(nb), 0))
    out.write(hdr.encode() + nb); out.write(b"\0" * (-(len(hdr) + len(nb)) % 4))
    out.write(data); out.write(b"\0" * (-len(data) % 4))

def read_cpio(path):
    raw = gzip.open(path).read(); i = 0; res = []
    while True:
        h = raw[i:i + 110]; assert h[:6] == b"070701"
        f = [int(h[6 + 8 * k:14 + 8 * k], 16) for k in range(13)]
        nl, fl = f[11], f[6]; name = raw[i + 110:i + 110 + nl - 1].decode(); i = (i + 110 + nl + 3) & ~3
        data = raw[i:i + fl]; i = (i + fl + 3) & ~3
        if name == "TRAILER!!!": return res
        res.append((name, f[1], f[2], f[3], f[5], data, (f[9], f[10])))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("repo"); ap.add_argument("tag"); ap.add_argument("platform"); ap.add_argument("out")
    ap.add_argument("--init"); ap.add_argument("--from-cpio"); ap.add_argument("--keep-cpio-prefix", action="append", default=[])
    ap.add_argument("--add", action="append", default=[], help="path_in_image=local_file[:mode]")
    a = ap.parse_args()
    fs = merge(pull(a.repo, a.tag, a.platform))
    buf = io.BytesIO(); ino = 1
    def put(name, kind, mode, uid, gid, mt, payload):
        nonlocal ino; ino += 1
        typ = {"d": stat.S_IFDIR, "f": stat.S_IFREG, "l": stat.S_IFLNK, "c": stat.S_IFCHR, "b": stat.S_IFBLK}[kind]
        mode = (mode & 0o7777) | typ
        if kind in "cb": cpio_entry(buf, ino, name, mode, uid, gid, mt, b"", payload)
        else: cpio_entry(buf, ino, name, mode, uid, gid, mt, payload)
    extra = {}
    if a.init: extra["init"] = (open(a.init, "rb").read(), 0o755)
    for s in a.add:
        dst, _, rest = s.partition("="); src, _, m = rest.partition(":"); extra[dst] = (open(src, "rb").read(), int(m, 8) if m else 0o644)
    for k, (d, m) in extra.items(): fs[k] = ("f", m, 0, 0, time.time(), d)
    if a.from_cpio:
        for (n, mode, uid, gid, mt, data, rdev) in read_cpio(a.from_cpio):
            if any(n == p or n.startswith(p + "/") for p in a.keep_cpio_prefix):
                kind = "d" if stat.S_ISDIR(mode) else "l" if stat.S_ISLNK(mode) else "f"
                fs[n] = (kind, mode, uid, gid, mt, data)
    for p in sorted(fs, key=lambda x: (x.count("/"), x)):  # parents first
        kind, mode, uid, gid, mt, payload = fs[p]; put(p, kind, mode, uid, gid, mt, payload)
    cpio_entry(buf, 0, "TRAILER!!!", 0, 0, 0, 0)
    t0 = time.time(); gz = gzip.compress(buf.getvalue(), 6)
    open(a.out, "wb").write(gz)
    sys.stderr.write(f"files={len(fs)} raw={len(buf.getvalue())/1e6:.1f} MB gz={len(gz)/1e6:.1f} MB ({time.time()-t0:.0f}s gzip)\n")
main()

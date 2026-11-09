"""Kubernetes version tables for the managed-cluster flavours (AKS / EKS / GKE) mapped onto real, pinned k3s images.

OFFLINE-ONLY helper for core/k3s_runtime.py. A requested version (``1.29``, ``1.29.7``, ``1.31.2-gke.100``, ``latest`` ...) is resolved to the
NEAREST minor the cloud supports, and that minor to the k3s release we pin for it (one pinned patch release per minor). The
runtime reports the version it ACTUALLY runs (``actualVersion``), never the requested one.
"""
from __future__ import annotations
import re

# k3s image tag per Kubernetes minor (rancher/k3s:<tag>); every tag below is a published k3s release.
K3S_BY_MINOR = {
    "1.28": "v1.28.15-k3s1",
    "1.29": "v1.29.10-k3s1",
    "1.30": "v1.30.5-k3s1",
    "1.31": "v1.31.1-k3s1",
    "1.32": "v1.32.0-k3s1",
}
# minors each managed service offers (its GA window for the pinned era).
SUPPORTED = {
    "azure": ["1.29", "1.30", "1.31", "1.32"],        # AKS
    "aws": ["1.28", "1.29", "1.30", "1.31", "1.32"],   # EKS
    "gcp": ["1.28", "1.29", "1.30", "1.31", "1.32"],   # GKE
}
DEFAULT_MINOR = "1.30"


def _minor_key(m):
    a, b = m.split(".")
    return int(a), int(b)


def parse_minor(version):
    """'1.29.7' / 'v1.29' / '1.31.2-gke.100' / '1.30.5+k3s1' -> '1.29'; None for latest/empty/unparseable."""
    m = re.match(r"^v?(\d+)\.(\d+)", str(version or "").strip())
    return "%s.%s" % (m.group(1), m.group(2)) if m else None


def supported_minors(cloud):
    return list(SUPPORTED.get((cloud or "").lower(), SUPPORTED["azure"]))


def resolve(cloud, requested=None):
    """-> {"minor", "k3sTag", "version", "exact"}: the nearest supported minor (ties go to the NEWER one) and its pinned k3s tag."""
    sup = supported_minors(cloud)
    want = parse_minor(requested)
    if want is None:
        minor = DEFAULT_MINOR if DEFAULT_MINOR in sup else sup[-1]
    else:
        w = _minor_key(want)
        minor = min(sup, key=lambda s: (abs(_minor_key(s)[0] - w[0]) * 1000 + abs(_minor_key(s)[1] - w[1]), -_minor_key(s)[1]))
    tag = K3S_BY_MINOR[minor]
    return {"minor": minor, "k3sTag": tag, "version": tag_to_version(tag), "exact": want == minor}


def tag_to_version(tag):
    """'v1.30.5-k3s1' / 'v1.30.5+k3s1' -> '1.30.5'"""
    m = re.match(r"^v?(\d+\.\d+\.\d+)", str(tag or ""))
    return m.group(1) if m else str(tag or "")


def tag_minor(tag):
    return parse_minor(tag)


def available_versions(cloud):
    return [{"minor": m, "version": tag_to_version(K3S_BY_MINOR[m]), "k3sTag": K3S_BY_MINOR[m]} for m in supported_minors(cloud)]

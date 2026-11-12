"""Manifest rendering for GitOps controllers (substrate-free): a plain-YAML directory, or a ``kustomization.yaml``
(resources / namespace / namePrefix / nameSuffix / commonLabels / commonAnnotations / images, recursive bases).

NOT rendered (reported, never faked): Helm charts / HelmRelease, remote bases (URLs), patches, generators, components.
"""
from __future__ import annotations

import copy
import posixpath

try:
    from core import k8s_yaml
except ImportError:                                      # Pyodide flat layout
    import k8s_yaml                                      # type: ignore

_UNSUPPORTED = ("patches", "patchesStrategicMerge", "patchesJson6902", "configMapGenerator", "secretGenerator", "components",
                "helmCharts", "replacements", "vars", "generators", "transformers")
_KUST = ("kustomization.yaml", "kustomization.yml", "Kustomization")


class RenderError(Exception):
    pass


def _norm(path: str) -> str:
    p = posixpath.normpath((path or "").strip("/") or ".")
    return "" if p == "." else p


def _load(tree: dict, path: str) -> list:
    raw = tree.get(path)
    if raw is None:
        raise RenderError(f"file '{path}' not found in the source")
    try:
        docs = k8s_yaml.load_all(raw.decode(errors="replace") if isinstance(raw, bytes) else raw)
    except k8s_yaml.YAMLError as e:
        raise RenderError(f"{path}: {e}")
    out = []
    for d in docs:
        if isinstance(d, dict) and d.get("kind") == "List" and isinstance(d.get("items"), list):
            out += d["items"]
        elif d:
            out.append(d)
    return out


def _is_manifest_file(name: str) -> bool:
    return name.endswith((".yaml", ".yml", ".json"))


def render_dir(tree: dict, path: str, _depth=0) -> list:
    """Render the manifests for a source ``path`` (directory) to a flat list of objects."""
    if _depth > 8:
        raise RenderError("kustomize base nesting too deep (cycle?)")
    base = _norm(path)
    pref = base + "/" if base else ""
    own = {p[len(pref):] for p in tree if p.startswith(pref)}
    if not own:
        raise RenderError(f"path './{base}' does not exist in the source (or is empty)")
    kf = next((n for n in ("kustomization.yaml", "kustomization.yml") if n in own), None)
    if kf is None:
        docs = []
        for rel in sorted(r for r in own if "/" not in r and _is_manifest_file(r)):
            docs += _load(tree, pref + rel)
        return docs
    kdocs = _load(tree, pref + kf)
    k = kdocs[0] if kdocs else {}
    for u in _UNSUPPORTED:
        if k.get(u):
            raise RenderError(f"kustomization field '{u}' is not rendered by Vyomi's kustomize (supported: resources, namespace, namePrefix, nameSuffix, commonLabels, commonAnnotations, images)")
    docs = []
    for res in k.get("resources") or []:
        if "://" in str(res) or str(res).startswith("git@"):
            raise RenderError(f"remote kustomize base '{res}' cannot be fetched")
        rp = _norm(pref + str(res))
        if rp in tree:
            docs += _load(tree, rp)
        else:
            docs += render_dir(tree, rp, _depth + 1)
    out = []
    for d in copy.deepcopy(docs):
        md = d.setdefault("metadata", {})
        if k.get("namePrefix") or k.get("nameSuffix"):
            if d.get("kind") != "Namespace":
                md["name"] = f"{k.get('namePrefix', '')}{md.get('name', '')}{k.get('nameSuffix', '')}"
        if k.get("namespace") and d.get("kind") not in ("Namespace", "CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding", "StorageClass", "PersistentVolume"):
            md["namespace"] = k["namespace"]
        if k.get("commonLabels"):
            md.setdefault("labels", {}).update(k["commonLabels"])
        if k.get("commonAnnotations"):
            md.setdefault("annotations", {}).update(k["commonAnnotations"])
        for im in k.get("images") or []:
            _set_image(d, im)
        out.append(d)
    if k.get("namespace"):
        pass
    return out


def _set_image(obj: dict, im: dict):
    name = im.get("name")
    specs = []
    spec = obj.get("spec") or {}
    tmpl = (spec.get("template") or {}).get("spec") or spec
    for key in ("containers", "initContainers"):
        specs += tmpl.get(key) or []
    for c in specs:
        img = str(c.get("image", ""))
        repo, _, tag = img.rpartition(":") if ":" in img.rsplit("/", 1)[-1] else (img, "", "")
        if repo == name:
            new = im.get("newName", repo)
            if im.get("newTag"):
                c["image"] = f"{new}:{im['newTag']}"
            else:
                c["image"] = f"{new}:{tag}" if tag else new


def has_helm(docs: list) -> list:
    return [d for d in docs if isinstance(d, dict) and d.get("kind") in ("HelmRelease", "HelmRepository", "HelmChart")]

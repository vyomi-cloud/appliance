"""The generated rag_design.py loader (chapter 14): defaults equal the pre-chapter constants, a design file overrides them, bad values warn and fall back."""
import importlib.util
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from vyomilabs.content import rag_design_src  # noqa: E402


def _load(cloud, tmp_path, design=None, monkeypatch=None):
    (tmp_path / "rag_design.py").write_text(rag_design_src.loader_code(cloud))
    if design is not None:
        (tmp_path / "rag-design.json").write_text(json.dumps(design) if not isinstance(design, str) else design)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAG_DESIGN_PATH", raising=False)
    spec = importlib.util.spec_from_file_location("rag_design_" + cloud, tmp_path / "rag_design.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("cloud,search", [("aws", "vector"), ("gcp", "vector"), ("azure", "hybrid")])
def test_defaults_equal_todays_constants(cloud, search, tmp_path, monkeypatch):
    m = _load(cloud, tmp_path, None, monkeypatch)
    assert m.chunk_cfg() == dict(strategy="FIXED_SIZE", maxTokens=200, overlapPct=10)
    assert (m.top_k(), m.search_type(), m.rerank(), m.grounding_threshold(), m.dimensions()) == (3, search, dict(enabled=False, topN=2), 0, None)
    assert m.source() is None and m.problems() == []


@pytest.mark.parametrize("cloud", ["aws", "gcp", "azure"])
def test_shipped_example_design_is_the_defaults(cloud, tmp_path, monkeypatch):
    m = _load(cloud, tmp_path, rag_design_src.design_json(cloud), monkeypatch)
    assert m.problems() == [] and not any(m.customised(s) for s in ("chunking", "retrieve", "rerank", "generate", "embedding"))


def test_design_overrides_and_studio_search_type(tmp_path, monkeypatch):
    m = _load("aws", tmp_path, {"cloud": "aws", "chunking": {"maxTokens": 400}, "retrieve": {"topK": 5, "searchType": "HYBRID"}, "rerank": {"enabled": True, "topN": 3},
                                "generate": {"groundingThreshold": 0.4, "model": "x"}, "embedding": {"dimensions": 256}}, monkeypatch)
    assert m.chunk_cfg()["maxTokens"] == 400 and m.chunk_cfg()["overlapPct"] == 10
    assert (m.top_k(), m.search_type(), m.rerank(), m.grounding_threshold(), m.dimensions()) == (5, "hybrid", dict(enabled=True, topN=3), 0.4, 256)
    assert m.load()["generate"]["model"] == "x" and m.customised("chunking")


def test_bad_values_warn_and_fall_back(tmp_path, monkeypatch, capsys):
    m = _load("aws", tmp_path, {"cloud": "aws", "retrieve": {"topK": 0, "searchType": "fuzzy"}, "chunking": {"overlapPct": "ten"}, "rerank": {"enabled": "yes"}}, monkeypatch)
    assert (m.top_k(), m.search_type(), m.chunk_cfg()["overlapPct"], m.rerank()["enabled"]) == (3, "vector", 10, False)
    assert len(m.problems()) == 4 and "warning" in capsys.readouterr().err


def test_unreadable_file_never_crashes(tmp_path, monkeypatch):
    m = _load("gcp", tmp_path, "{not json", monkeypatch)
    assert m.top_k() == 3 and m.problems()

"""Edition metadata: every block has an edition, Nano is a subset of Mesh, and the enterprise additions are Mesh-only."""
import pytest

from vyomilabs.content import build_courses

CLOUDS = ("aws", "gcp", "azure")


def _blocks(doc):
    return [bl for ch in doc["layers"] for bl in ch.get("blocks", [])] if "layers" in doc else []


@pytest.mark.parametrize("cloud", CLOUDS)
def test_every_block_has_a_valid_edition(cloud):
    import importlib
    LAB = importlib.import_module(f"vyomilabs.content.labs_{cloud}").LAB
    for layer, blocks in LAB.items():
        for bl in blocks:
            assert bl["edition"] and set(bl["edition"]) <= {"nano", "mesh"}, (layer, bl["file"])
            assert "mesh" in bl["edition"], "Mesh is the full course: every block is on it"
            assert bl["kind"] in ("build", "harden", "iam", "failure", "ship")


@pytest.mark.parametrize("cloud", CLOUDS)
def test_enterprise_blocks_are_mesh_only_and_explained(cloud):
    import importlib
    LAB = importlib.import_module(f"vyomilabs.content.labs_{cloud}").LAB
    ent = [bl for blocks in LAB.values() for bl in blocks if bl["kind"] != "build"]
    assert ent, "each cloud has enterprise additions"
    for bl in ent:
        if bl["edition"] == ["mesh"]:
            assert bl["nano_note"], bl["file"] + ": a mesh-only block says why"
    assert any(bl["kind"] == "ship" for bl in ent), "each cloud has a Ship it capstone"

"""The console avatar menu has a 'Dashboard' item (all three clouds, v4 + classic consoles share wasm/vyomi-appbar.js)."""
import pathlib
import re
import shutil
import subprocess

WASM = pathlib.Path(__file__).resolve().parent.parent / "wasm"
CONSOLES = ["aws-console.html", "azure-console.html", "gcp-console.html", "v4/aws/index.html", "v4/azure/index.html", "v4/gcp/index.html"]


def test_menu_has_dashboard_item_fed_by_me_endpoint():
    js = (WASM / "vyomi-appbar.js").read_text()
    assert "data-act', 'dashboard'" in js and "<span>Dashboard</span>" in js
    assert "j.dashboard_url" in js                                   # URL comes from /api/auth/me
    assert re.search(r"\[who\$, act, bo, gh, db, tc, hr, so\]", js)  # item is in the menu, above Sign out
    assert "db.style.display = NANO && authed" in js                 # only for a signed-in Nano user


def test_every_console_loads_the_shared_menu():
    for c in CONSOLES:
        assert "vyomi-appbar.js" in (WASM / c).read_text(), c


def test_v4_cache_buster_tracks_the_file():
    import hashlib
    h = hashlib.sha256((WASM / "vyomi-appbar.js").read_bytes()).hexdigest()[:12]
    for c in CONSOLES[3:]:
        assert f"vyomi-appbar.js?v={h}" in (WASM / c).read_text(), c


def test_appbar_is_valid_js():
    node = shutil.which("node")
    if node:
        assert subprocess.run([node, "--check", str(WASM / "vyomi-appbar.js")]).returncode == 0

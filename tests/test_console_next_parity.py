"""Console-next commonality guarantee — CI parity test + no-substrate-branch lint.

Enforces §15 of docs/CONSOLE-UX-REDESIGN.md ("UI commonality guarantee — HARD
CONSTRAINT") for the console-next engine:

  1. Cross-substrate / cross-lens parity (§15.3): for every substrate
     (local | codespaces | nano) and every cloud lens (aws | gcp | azure), the
     capability manifest declares the SAME service/widget set, with ONLY the
     documented mode differences (connect.mode per substrate; the two Nano
     compute-shaped degradations). A missing widget on any substrate/lens is a
     build failure.

  2. No-substrate-branch lint (§15.2 / §15.3): grep the console-next JS and FAIL
     if any component branches on a substrate or cloud NAME
     (`if (substrate === …)`, `=== 'nano'`, `cloud === …`, `=== 'aws'`, …). All
     variation must live in the capability manifest (server-side), never in UI
     component logic.

Runs under the repo's unittest-style runner (pytest or `python -m unittest`).
Importing ``routes.console_next`` requires FastAPI (present in the repo venv); if
FastAPI is unavailable the parity test skips, but the pure-text lint always runs.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONSOLE_JS_DIR = _REPO_ROOT / "static" / "console-next"

# The complete widget set the one engine ships (§4/§14.3). This is the invariant:
# it must be present, identically, on every substrate and every lens.
_EXPECTED_WIDGETS = frozenset({
    "object-browser",
    "sql-console",
    "compute-terminal",
    "serverless-invoke",
    "nosql-item-viewer",
    "kv-secret-viewer",
    "kms-crypto-view",
    "queue-topic-viewer",
    "generic-control-plane",
})

# Documented per-substrate connect.mode (§14.8): nano reaches its SW-served API via
# the relay; local/codespaces use the endpoint mode.
_EXPECTED_CONNECT_MODE = {
    "local": "endpoint",
    "codespaces": "endpoint",
    "nano": "relay",
}

# The ONLY documented widget-mode differences (§14.9): Nano has no real compute in a
# browser tab, so exactly these two widgets degrade. Everything else keeps whatever
# mode the lens gave it — identical across substrates.
_NANO_DEGRADATIONS = {
    "compute-terminal": "degraded",
    "serverless-invoke": "partial",
}


def _load_capabilities():
    """Import the manifest builder. Skip cleanly if FastAPI isn't installed."""
    try:
        from routes.console_next import _capabilities, CLOUD_LENSES  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - env without fastapi
        raise unittest.SkipTest(f"routes.console_next unavailable: {exc}")
    return _capabilities, list(CLOUD_LENSES)


class ConsoleNextParityTest(unittest.TestCase):
    """§15.3 — the same component tree renders on every substrate & lens."""

    _SUBSTRATES = ("local", "codespaces", "nano")

    def setUp(self) -> None:
        # Deterministic env: clear the knobs that can shift connect.mode / ssh so the
        # test asserts the substrate-DRIVEN defaults, not a developer's local env.
        self._saved_env = {
            k: os.environ.pop(k, None)
            for k in ("VYOMI_CONNECT_MODE", "VYOMI_CONSOLE_SUBSTRATE", "VYOMI_SUBSTRATE")
        }

    def tearDown(self) -> None:
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_same_widget_set_every_substrate_and_lens(self) -> None:
        _capabilities, lenses = _load_capabilities()
        self.assertTrue(lenses, "no cloud lenses declared")
        for substrate in self._SUBSTRATES:
            for lens in lenses:
                m = _capabilities(lens, substrate)
                with self.subTest(substrate=substrate, lens=lens):
                    # Same widget KEYS everywhere — no missing widgets (§15.1 #4).
                    self.assertEqual(
                        set(m["widgets"].keys()), set(_EXPECTED_WIDGETS),
                        f"widget set differs for {substrate}/{lens}",
                    )
                    # Every service in the rail maps to a known widget (rail == engine).
                    svc_widgets = {s.get("widget") for s in m["services"]}
                    self.assertTrue(
                        svc_widgets.issubset(_EXPECTED_WIDGETS),
                        f"service rail references an unknown widget on {substrate}/{lens}: "
                        f"{svc_widgets - set(_EXPECTED_WIDGETS)}",
                    )
                    # The manifest self-reports the substrate/lens it was built for.
                    self.assertEqual(m["substrate"], substrate)
                    self.assertEqual(m["lens"], lens)
                    self.assertEqual(set(m["cloud_lenses"]), set(lenses))

    def test_connect_mode_per_substrate(self) -> None:
        _capabilities, lenses = _load_capabilities()
        for substrate in self._SUBSTRATES:
            for lens in lenses:
                m = _capabilities(lens, substrate)
                with self.subTest(substrate=substrate, lens=lens):
                    self.assertEqual(
                        m["connect"]["mode"], _EXPECTED_CONNECT_MODE[substrate],
                        f"connect.mode wrong for {substrate}",
                    )
                    # relay is on iff nano; ssh is never on without the explicit local
                    # ssh env (cleared in setUp), so it must be False here.
                    self.assertEqual(m["features"]["relay"], substrate == "nano")
                    self.assertFalse(m["features"]["ssh"])

    def test_only_documented_mode_differences(self) -> None:
        """local and codespaces are widget-mode-identical; nano differs ONLY by the
        two documented compute degradations — nothing else drifts (§15.3)."""
        _capabilities, lenses = _load_capabilities()
        for lens in lenses:
            local = _capabilities(lens, "local")["widgets"]
            codespaces = _capabilities(lens, "codespaces")["widgets"]
            nano = _capabilities(lens, "nano")["widgets"]
            with self.subTest(lens=lens):
                # local ≡ codespaces for every widget (no substrate difference at all).
                self.assertEqual(
                    local, codespaces,
                    f"local vs codespaces widget modes diverge for {lens}",
                )
                # nano differs from local ONLY on the documented degraded widgets.
                differing = {k for k in _EXPECTED_WIDGETS if nano[k] != local[k]}
                self.assertEqual(
                    differing, set(_NANO_DEGRADATIONS),
                    f"nano diverges from local on undocumented widgets for {lens}: "
                    f"{differing ^ set(_NANO_DEGRADATIONS)}",
                )
                for widget, expected_mode in _NANO_DEGRADATIONS.items():
                    self.assertEqual(nano[widget], expected_mode)
                    # A degraded/partial widget MUST carry its capability-driven note
                    # so the SAME widget can render the CTA without a substrate check.
                    self.assertTrue(
                        _capabilities(lens, "nano")["degrade_notes"].get(widget),
                        f"nano {widget} degraded without a degrade_note ({lens})",
                    )


class NoSubstrateBranchLintTest(unittest.TestCase):
    """§15.2/§15.3 — UI components must never branch on a substrate/cloud NAME.

    The capability manifest is the single place variation lives. This lint greps the
    console-next JS (excluding vendored libs) and fails on any equality branch against
    a substrate name (local/codespaces/nano) or a cloud name (aws/gcp/azure), or on
    `substrate ===` / `cloud ===`. It deliberately does NOT flag branching on
    capability VALUES like `connect.mode === 'relay'` — that is reading the manifest,
    which is exactly the sanctioned pattern.
    """

    # Match forbidden branching on substrate/cloud NAMES or the substrate/cloud vars.
    _PATTERNS = (
        # === 'nano' | === "local" | === `codespaces`  (substrate names)
        re.compile(r"===\s*['\"`](?:nano|local|codespaces)['\"`]"),
        # === 'aws' | === "gcp" | === 'azure'  (cloud names)
        re.compile(r"===\s*['\"`](?:aws|gcp|azure)['\"`]"),
        # if (substrate === …) / cloud === … / substrate == …
        re.compile(r"\b(?:substrate|cloud)\s*===?"),
    )

    def _js_files(self):
        return [
            p for p in _CONSOLE_JS_DIR.rglob("*.js")
            if "vendor" not in p.parts
        ]

    def test_console_js_present(self) -> None:
        files = self._js_files()
        self.assertTrue(files, f"no console-next JS found under {_CONSOLE_JS_DIR}")

    def test_no_substrate_or_cloud_branching(self) -> None:
        violations = []
        for path in self._js_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                for pat in self._PATTERNS:
                    if pat.search(line):
                        violations.append(
                            f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}"
                        )
        self.assertEqual(
            violations, [],
            "substrate/cloud-name branching in console-next UI code is forbidden "
            "(§15.2) — route the variation through the capability manifest instead:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

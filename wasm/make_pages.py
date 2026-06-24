"""Wrap the REAL Pro/Max front-end (splash/launch dashboard + the three SPA
consoles) for the Nano in-browser substrate. We DON'T fork these pages — we
take the shipped HTML verbatim and add one <script> + rewrite the inter-page
links so the exact same UI runs against the in-browser backend.

Pro/Max flow            ->  Nano (static, in-browser)
  /clouds (clouds.html) ->  /  (index.html)        launch dashboard / splash
  /console/aws          ->  /aws-console.html       SPA console
  /console/gcp          ->  /gcp-console.html
  /console/azure        ->  /azure-console.html

Run:  python3 wasm/make_pages.py   (after build_fixtures.py)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, "static")

# Pro/Max console URLs -> the static files we serve them as.
LINKS = {
    "/console/aws": "/aws-console.html",
    "/console/gcp": "/gcp-console.html",
    "/console/azure": "/azure-console.html",
    '"/ui"': '"/"',          # "back to spaces/dashboard" -> the dashboard at root
    '"/clouds"': '"/"',
}

BOOT = '  <script type="module" src="/nano-boot.js"></script>\n</head>'  # consoles: Pyodide + SW
# Dashboard: SW only + hide the appliance host-health panel (CPU/RAM/Disk are
# the host VM's stats — there is no VM in a browser tab, so it's N/A for Nano).
SW = ('  <style>#stats-card{display:none!important}</style>\n'
      '  <script src="/nano-sw.js" defer></script>\n</head>')

# The conformance docs (API/SDK/Utility) live on the public portal.
DOCS_BASE = "https://vyomi.cloud"


def _docs_widget(cloud=None):
    """A floating 'Conformance' pill linking the three distinct docs (API · SDK
    · Utility) + the Conformance Pack. On a console it deep-links that cloud; on
    the dashboard it links the pack. Docs live on the portal (vyomi.cloud)."""
    if cloud:
        head = f"{cloud.upper()} conformance"
        links = (
            f'<a href="{DOCS_BASE}/docs/{cloud}" target="_blank" rel="noopener">API doc <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/{cloud}/sdk" target="_blank" rel="noopener">SDK doc <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/{cloud}/cli" target="_blank" rel="noopener">Utility doc <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/conformance-pack" target="_blank" rel="noopener">Conformance Pack <span>↗</span></a>'
        )
    else:
        head = "Conformance"
        links = (
            f'<a href="{DOCS_BASE}/docs/conformance-pack" target="_blank" rel="noopener">Conformance Pack <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/aws" target="_blank" rel="noopener">AWS · API / SDK / Utility <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/gcp" target="_blank" rel="noopener">GCP · API / SDK / Utility <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/azure" target="_blank" rel="noopener">Azure · API / SDK / Utility <span>↗</span></a>'
        )
    return f"""
<style>
 #nano-docs{{position:fixed;right:16px;bottom:52px;z-index:99998;font:13px system-ui,-apple-system,sans-serif}}
 #nano-docs .pill{{background:#0d1030;color:#e4e4e7;border:1px solid #2a2f55;border-radius:999px;padding:8px 14px;cursor:pointer;box-shadow:0 6px 18px rgba(0,0,0,.35);user-select:none}}
 #nano-docs .pop{{position:absolute;right:0;bottom:42px;background:#0d1030;border:1px solid #2a2f55;border-radius:12px;padding:6px;min-width:218px;display:none;box-shadow:0 12px 34px rgba(0,0,0,.45)}}
 #nano-docs.open .pop{{display:block}}
 #nano-docs .pop .h{{font-size:11px;color:#8b8ba7;padding:6px 10px;text-transform:uppercase;letter-spacing:1px}}
 #nano-docs .pop a{{display:flex;justify-content:space-between;gap:14px;padding:8px 10px;border-radius:8px;color:#cdd8e6;text-decoration:none}}
 #nano-docs .pop a:hover{{background:#171b3d;color:#fff}}
 #nano-docs .pop a span{{color:#7cc4ff}}
</style>
<div id="nano-docs">
 <div class="pop"><div class="h">{head}</div>{links}</div>
 <div class="pill" onclick="this.parentNode.classList.toggle('open')">📘 Conformance</div>
</div>"""


def _process(src_name, dst_name, inject, cloud=None):
    src = os.path.join(STATIC, src_name)
    with open(src) as f:
        html = f.read()
    if "</head>" not in html:
        raise SystemExit(f"no </head> in {src_name}")
    for a, b in LINKS.items():
        html = html.replace(a, b)
    # Nano has no appliance to boot — drop the "getting ready" readiness strip.
    html = html.replace('<script src="/assets/readiness-strip.js" defer></script>', "")
    # "Back to launch" pointed at the appliance's legacy all-in-one console (/),
    # which isn't part of Nano — Workspaces IS the home. Remove the dead button.
    html = html.replace('<a class="tb-btn tb-btn-secondary" href="/">← Back to launch</a>', "")
    if "/nano-boot.js" not in html and "/nano-sw.js" not in html:
        html = html.replace("</head>", inject, 1)
    # Floating Conformance-docs widget (API/SDK/Utility links to the portal).
    if "</body>" in html and "nano-docs" not in html:
        html = html.replace("</body>", _docs_widget(cloud) + "</body>", 1)
    dst = os.path.join(HERE, dst_name)
    with open(dst, "w") as f:
        f.write(html)
    print(f"{dst_name:24} <- {src_name:22} ({len(html)} bytes)")


def main():
    # Launch dashboard / splash -> entry (/).
    _process("clouds.html", "index.html", SW)
    # The three SPA consoles, verbatim + Pyodide boot loader + per-cloud docs.
    _process("aws-console.html", "aws-console.html", BOOT, cloud="aws")
    _process("gcp-console.html", "gcp-console.html", BOOT, cloud="gcp")
    _process("azure-console.html", "azure-console.html", BOOT, cloud="azure")


if __name__ == "__main__":
    main()

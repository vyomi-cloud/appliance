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


def _process(src_name, dst_name, inject):
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
    dst = os.path.join(HERE, dst_name)
    with open(dst, "w") as f:
        f.write(html)
    print(f"{dst_name:24} <- {src_name:22} ({len(html)} bytes)")


def main():
    # Launch dashboard / splash -> entry (/).
    _process("clouds.html", "index.html", SW)
    # The three SPA consoles, verbatim + Pyodide boot loader.
    _process("aws-console.html", "aws-console.html", BOOT)
    _process("gcp-console.html", "gcp-console.html", BOOT)
    _process("azure-console.html", "azure-console.html", BOOT)


if __name__ == "__main__":
    main()

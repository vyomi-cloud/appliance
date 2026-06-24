"""Wrap the REAL console (static/aws-console.html) for the Nano in-browser
substrate by injecting the Pyodide+service-worker boot loader. We DON'T fork
the console — we take the shipped HTML verbatim and add one <script> so the
exact same UI runs against the in-browser backend.

Run:  python3 wasm/make_console.py   (after build_fixtures.py)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SRC = os.path.join(ROOT, "static", "aws-console.html")
DST = os.path.join(HERE, "aws-console.html")

INJECT = '  <script type="module" src="/wasm/nano-boot.js"></script>\n</head>'


def main():
    with open(SRC) as f:
        html = f.read()
    if "</head>" not in html:
        raise SystemExit("no </head> in source console — cannot inject loader")
    if "/wasm/nano-boot.js" in html:
        out = html  # already injected
    else:
        out = html.replace("</head>", INJECT, 1)
    with open(DST, "w") as f:
        f.write(out)
    print(f"wrote {os.path.relpath(DST, ROOT)} ({len(out)} bytes) — boot loader injected")


if __name__ == "__main__":
    main()

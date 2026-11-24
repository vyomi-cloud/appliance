"""vyomilabs command line: serve the app, list layers, run a layer check."""
import argparse
import os
import sys

from . import checks, layers, progress, server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vyomilabs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the local web app")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--endpoint", default=None, help="simulator URL (default $VYOMILABS_ENDPOINT or http://localhost:9000)")
    sub.add_parser("list", help="list the layers in build order with your progress")
    c = sub.add_parser("check", help="check one layer against the simulator")
    c.add_argument("layer", type=int)
    c.add_argument("--endpoint", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run(server.create_app(a.endpoint), host=a.host, port=a.port, log_level="warning")
        return 0
    if a.cmd == "list":
        prog = progress.load()
        for lid in layers.order():
            L = layers.get(lid)
            print(f"{L['order']:>2}. layer {lid:>2}  {prog.get(str(lid), {}).get('status', 'TODO'):7}  {L['title']}")
        return 0
    if a.cmd == "check":
        ep = a.endpoint or os.environ.get("VYOMILABS_ENDPOINT") or server.DEFAULT_ENDPOINT
        if not layers.get(a.layer):
            print("no such layer"); return 2
        res = checks.run(a.layer, ep)
        for st in res["steps"]:
            print(f"  [{st['status']:7}] {st['name']}" + (f"  - {st['detail']}" if st["detail"] else ""))
        if res["implemented"]:
            progress.record(a.layer, res["status"], res["steps"])
        print(f"layer {a.layer}: {res['status']}")
        return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

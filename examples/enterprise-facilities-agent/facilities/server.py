"""Start the Vyomi simulator in-process (same wire front door the appliance uses). Only used when no --endpoint is given."""
import os, socket, sys, tempfile, threading, time


def start_in_process():
    here = os.path.abspath(__file__)
    root = os.environ.get("VYOMI_REPO") or here        # VYOMI_REPO: use another checkout's simulator code
    for _ in range(8 if not os.environ.get("VYOMI_REPO") else 1):
        root = root if os.environ.get('VYOMI_REPO') else os.path.dirname(root)
        if os.path.exists(os.path.join(root, "core", "wire_ingress.py")):
            break
    else:
        raise SystemExit("run from inside the simulator repo, or pass --endpoint http://host:port")
    work = tempfile.mkdtemp(prefix="facilities-e2e-")
    os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(work, "state.sqlite3"))   # clean state every run
    sys.path.insert(0, root)
    os.chdir(work)                                                                         # keep generated dirs out of the repo
    import asyncio, anyio, uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    app, router = FastAPI(), wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        # each request runs on a worker thread: a Lambda that calls back into the simulator (boto3 inside the function) must not block the event loop
        body = await request.body()
        return await anyio.to_thread.run_sync(lambda: asyncio.run(wire_ingress.serve(router, request, body=body)))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"

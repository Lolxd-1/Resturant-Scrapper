"""Menu Studio launcher: starts the local server, opens the browser, detects a running instance."""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

import requests
import uvicorn

from studio.config import home_dir
from studio.server import VC_RUNTIME_URL, create_app, onnxruntime_error

log = logging.getLogger("app")


def _free_port(host: str, start_port: int) -> int:
    port = start_port
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                port += 1
    raise RuntimeError("No free port found")


def _health_ok(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        resp = requests.get(f"http://{host}:{port}/api/health", timeout=timeout)
        return resp.status_code == 200 and resp.json().get("app") == "menustudio"
    except Exception:
        return False


def _self_test() -> int:
    if onnxruntime_error():
        print("SELF-TEST FAILED: the visual and logo checks need the Microsoft Visual C++ runtime. "
              f"Install it from {VC_RUNTIME_URL} and run Menu Studio again.")
        return 1
    port = _free_port("127.0.0.1", 8765)
    config = uvicorn.Config(create_app(start_worker=False), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.1)
        ok = False
        try:
            r1 = requests.get(f"http://127.0.0.1:{port}/api/health", timeout=5)
            r2 = requests.get(f"http://127.0.0.1:{port}/", timeout=5)
            ok = r1.status_code == 200 and r2.status_code == 200
        except Exception:
            ok = False
        if ok:
            print("SELF-TEST OK")
            return 0
        print("SELF-TEST FAILED")
        return 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.py", description="Menu Studio")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    if args.self_test:
        return _self_test()

    server_file = home_dir() / "server.json"
    if server_file.exists():
        try:
            info = json.loads(server_file.read_text(encoding="utf-8"))
            existing_port = int(info.get("port", 0))
        except (OSError, ValueError):
            existing_port = 0
        if existing_port and _health_ok(args.host, existing_port):
            url = f"http://{args.host}:{existing_port}/"
            if not args.no_browser:
                webbrowser.open(url)
            print(f"Menu Studio is already running at {url}")
            return 0

    port = _free_port(args.host, args.port)
    server_file.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    url = f"http://{args.host}:{port}/"

    def _open_when_ready() -> None:
        for _ in range(100):
            if _health_ok(args.host, port, timeout=0.5):
                if not args.no_browser:
                    webbrowser.open(url)
                return
            time.sleep(0.1)

    threading.Thread(target=_open_when_ready, daemon=True).start()
    print(f"Menu Studio is running at {url} — keep this window open. Close it to stop.")
    uvicorn.run(create_app(), host=args.host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())

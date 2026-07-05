"""Dev/prod server entrypoint.

On Windows, psycopg async cannot run on uvicorn's default ProactorEventLoop, so
we force the selector loop policy and let `asyncio.run` (via loop="none") create
a compatible loop. On Linux this is a no-op.
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn


def _listening_pids(port: int) -> list[int]:
    """Return PIDs listening on *port* (platform-specific)."""
    if sys.platform == "win32":
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
        )
        pids: list[int] = []
        for line in result.stdout.splitlines():
            if f":{port}" not in line or "LISTENING" not in line:
                continue
            pid = int(line.split()[-1])
            if pid and pid not in pids:
                pids.append(pid)
        return pids

    result = subprocess.run(
        ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [int(pid) for pid in result.stdout.split() if pid.strip().isdigit()]


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _ensure_port_free(host: str, port: int) -> None:
    if _port_available(host, port):
        return

    pids = _listening_pids(port)
    lines = [
        f"Port {port} is already in use on {host}.",
        "Stop the existing backend before starting another instance.",
    ]
    if pids:
        stop_cmd = (
            f"Stop-Process -Id {pids[0]} -Force"
            if sys.platform == "win32"
            else f"kill {pids[0]}"
        )
        lines.append(f"Listening process PID(s): {', '.join(map(str, pids))}")
        lines.append(f"Example: {stop_cmd}")
    else:
        lines.append(
            f"Or use a different port: $env:PORT=8001; python run.py"
            if sys.platform == "win32"
            else "Or use a different port: PORT=8001 python run.py"
        )
    raise SystemExit("\n".join(lines))


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    _ensure_port_free(host, port)
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        loop="none",  # use the selector loop created by asyncio.run
    )

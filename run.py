"""
run.py — Production / development entry-point for the TCI backend.

Why this file exists
--------------------
On Windows, Python 3.8+ defaults to ProactorEventLoop.  psycopg3 (the async
PostgreSQL driver) is incompatible with ProactorEventLoop and raises:

    psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' …

Python 3.14 deprecated ``set_event_loop_policy`` (slated for removal in 3.16).
The modern, forward-compatible fix is to pass ``loop_factory`` directly to
uvicorn via its ``Server`` API.  That is what this file does.

Alembic uses its own equivalent fix in alembic/env.py (SelectorEventLoop
created directly, without touching the global policy).

Usage
-----
    # From backend/ directory — the recommended way:
    python run.py
    python run.py --host 127.0.0.1 --port 8000 --reload

    # Direct uvicorn invocation also works because the loop_factory approach
    # in uvicorn Config takes precedence over the process-level policy.
"""
from __future__ import annotations

import argparse
import asyncio
import selectors
import sys

import uvicorn

from app.core.config import get_settings

settings = get_settings()


def _get_loop_factory():
    """
    Return a SelectorEventLoop factory on Windows to ensure compatibility
    with psycopg3 async.  On other platforms return None (uvicorn default).
    Uses the loop_factory approach which is supported from Python 3.10+ and
    does NOT rely on the deprecated set_event_loop_policy API.
    """
    if sys.platform == "win32":
        return lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TCI backend server.")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument(
        "--reload",
        action="store_true",
        default=settings.debug,
        help="Enable auto-reload (dev only)",
    )
    args = parser.parse_args()

    loop_factory = _get_loop_factory()

    config = uvicorn.Config(
        app="app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    if loop_factory is not None and not args.reload:
        # loop_factory is only usable in non-reload mode
        # (reload mode spawns sub-processes that manage their own loops)
        loop = loop_factory()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.serve())
        finally:
            loop.close()
    else:
        # Reload mode or non-Windows: let uvicorn manage the event loop
        server.run()


if __name__ == "__main__":
    main()

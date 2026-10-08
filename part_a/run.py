"""
Entry point for running the server on Windows.

Why this file exists: `uvicorn app.main:app --reload` creates its asyncio
event loop BEFORE it imports your app module, so setting the event loop
policy inside app/main.py happens too late -- the loop already exists by
then. This script sets the policy as the very first thing Python does,
then starts uvicorn in-process, guaranteeing the right loop is used from
the start.

Usage (from the part_a/ folder, venv active):
    python run.py

This replaces running `uvicorn app.main:app --reload --port 8000` directly
on Windows. On macOS/Linux you can keep using the plain uvicorn command if
you prefer -- this script works there too, it's just unnecessary.
"""

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
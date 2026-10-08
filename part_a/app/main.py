import sys
import traceback

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from starlette.requests import Request

from .database import get_cached_place, init_db, save_place
from .models import PlaceDetails
from .scraper import fetch_place_data

# On Windows, asyncio's default SelectorEventLoop cannot spawn subprocesses,
# which Playwright needs to launch Chromium. Without this, browser.launch()
# fails with a bare `NotImplementedError` (empty message). This must be set
# before uvicorn creates its event loop, so it lives at module import time.
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(
    title="Landmark Data API",
    description="Retrieves structured place details and reviews for a landmark from Google Maps.",
    version="1.0.0",
)


@app.exception_handler(Exception)
async def log_unhandled_exceptions(request: Request, exc: Exception):
    # Without this, an exception raised anywhere outside our own try/except
    # blocks (e.g. during response_model validation) just shows the client
    # a bare "Internal Server Error" with no detail in the terminal either.
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Unhandled error: {exc!r} ({type(exc).__name__})"},
    )


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/place", response_model=PlaceDetails)
async def get_place(
    name: str = Query(..., description="Landmark or place name, e.g. 'Eiffel Tower'"),
    use_cache: bool = Query(True, description="Return a previously stored result if available"),
):
    if use_cache:
        cached = get_cached_place(name)
        if cached:
            return cached

    try:
        place = await fetch_place_data(name)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail=f"Failed to retrieve data from Google Maps: {exc!r} ({type(exc).__name__})",
        )

    try:
        save_place(place)
    except Exception as exc:
        # Don't let a caching failure hide a perfectly good scrape result --
        # log it, but still return the place data to the caller.
        traceback.print_exc()
        print(f"[warning] failed to cache place '{name}': {exc!r}")

    return place


@app.get("/health")
def health():
    return {"status": "ok"}
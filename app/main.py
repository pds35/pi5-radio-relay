"""
Pi 5 Internet Radio - station list relay service.

Serves the station list (JSON) that the Pico 2 W syncs periodically and
caches locally. Does NOT touch audio -- the Pico streams audio directly
from each station's URL. This service only manages metadata: names,
stream URLs, and (optionally) whether each URL is currently reachable.

Run locally:
    uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload

Endpoints:
    GET  /stations              -> full station list (what the Pico fetches)
    GET  /stations/{station_id} -> single station
    POST /stations/{station_id} -> update a station (stream_url, name, notes)
    GET  /stations/health       -> re-check every stream URL, update status
    GET  /health                -> service liveness check
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Overridable via env var so tests (and any future second deployment) can
# point at a throwaway file instead of the real station list.
DATA_PATH = Path(
    os.environ.get(
        "STATIONS_DATA_PATH",
        Path(__file__).resolve().parent.parent / "data" / "stations.json",
    )
)

app = FastAPI(title="Pico Radio Station Relay", version="0.1.0")


class StationUpdate(BaseModel):
    name: Optional[str] = None
    stream_url: Optional[str] = None
    format: Optional[str] = None
    hls_only: Optional[bool] = None
    notes: Optional[str] = None


def load_data() -> dict:
    with DATA_PATH.open("r") as f:
        return json.load(f)


def save_data(data: dict) -> None:
    tmp_path = DATA_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(data, f, indent=2)
    tmp_path.replace(DATA_PATH)  # atomic-ish swap so the Pico never reads a half-written file


def find_station(data: dict, station_id: str) -> dict:
    for station in data["stations"]:
        if station["id"] == station_id:
            return station
    raise HTTPException(status_code=404, detail=f"Unknown station id: {station_id}")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stations")
def get_stations():
    """What the Pico actually fetches and caches locally."""
    return load_data()


# NOTE: this must be registered before the /stations/{station_id} routes
# below. FastAPI/Starlette matches routes in registration order, and
# {station_id} would otherwise greedily match the literal path "health",
# treating it as a station lookup and returning a 404 -- a real bug caught
# by the test suite, see DEVLOG.md entry 1.
@app.get("/stations/health")
def check_all_streams():
    """
    Hit every station's stream_url with a short GET (streamed, aborted after
    first bytes) to confirm it's alive. Updates status/verified/last_checked
    in place and persists the result, so /stations reflects the latest check
    without re-running it on every Pico sync.
    """
    data = load_data()
    results = []

    with httpx.Client(follow_redirects=True, timeout=6.0) as client:
        for station in data["stations"]:
            url = station.get("stream_url")
            if not url:
                station["status"] = "unresolved"
                station["verified"] = False
                results.append({"id": station["id"], "status": "unresolved"})
                continue

            try:
                with client.stream("GET", url) as resp:
                    if resp.status_code < 400:
                        # Pull a small chunk to confirm it's actually audio, not just
                        # a 200 on an empty/redirect page.
                        got_bytes = False
                        for chunk in resp.iter_bytes():
                            if chunk:
                                got_bytes = True
                            break
                        station["status"] = "alive" if got_bytes else "empty_response"
                        station["verified"] = got_bytes
                    else:
                        station["status"] = f"http_{resp.status_code}"
                        station["verified"] = False
            except httpx.RequestError as exc:
                station["status"] = f"error: {exc.__class__.__name__}"
                station["verified"] = False

            station["last_checked"] = int(time.time())
            results.append({"id": station["id"], "status": station["status"]})

    save_data(data)
    return {"checked": len(results), "results": results}


@app.get("/stations/{station_id}")
def get_station(station_id: str):
    data = load_data()
    return find_station(data, station_id)


@app.post("/stations/{station_id}")
def update_station(station_id: str, update: StationUpdate):
    data = load_data()
    station = find_station(data, station_id)

    for field, value in update.model_dump(exclude_unset=True).items():
        station[field] = value

    # Any manual edit resets verification -- health check will re-confirm it.
    station["verified"] = False
    station["status"] = "candidate" if station.get("stream_url") else "unresolved"

    save_data(data)
    return station

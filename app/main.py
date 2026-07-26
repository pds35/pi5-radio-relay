"""
Pi 5 Internet Radio - station list relay service.

Serves the station list (JSON) that the Pico 2 W syncs periodically and
caches locally. Does NOT touch audio -- the Pico streams audio directly
from each station's URL. This service only manages metadata: names,
stream URLs, and (optionally) whether each URL is currently reachable.

Run locally:
    uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload

Endpoints:
    GET  /                       -> HTML status dashboard (human-facing)
    GET  /player                 -> HTML station picker + audio playback
    GET  /stations              -> full station list (what the Pico fetches)
    GET  /stations/{station_id} -> single station
    GET  /stations/{station_id}/nowplaying -> current track info (ICY metadata)
    POST /stations/{station_id} -> update a station (stream_url, name, notes)
    GET  /stations/health       -> re-check every stream URL, update status
    GET  /health                -> service liveness check
"""

import json
import os
import time
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl

from app.dashboard import render_dashboard
from app.nowplaying import fetch_now_playing
from app.player import render_player

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
    stream_url: Optional[HttpUrl] = None
    format: Optional[Literal["mp3", "aac", "hls", "dash"]] = None
    hls_only: Optional[bool] = None
    notes: Optional[str] = None


def load_data() -> dict:
    with DATA_PATH.open("r") as f:
        return json.load(f)


def save_data(data: dict) -> None:
    tmp_path = DATA_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(data, f, indent=2)
    tmp_path.replace(DATA_PATH)


def find_station(data: dict, station_id: str) -> dict:
    for station in data["stations"]:
        if station["id"] == station_id:
            return station
    raise HTTPException(status_code=404, detail=f"Unknown station id: {station_id}")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Human-facing status page. Not what the Pico talks to -- see /stations."""
    return render_dashboard(load_data())


@app.get("/player", response_class=HTMLResponse)
def player():
    """Station picker + audio playback + now-playing info."""
    return render_player(load_data())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stations")
def get_stations():
    """What the Pico actually fetches and caches locally."""
    return load_data()


@app.get("/stations/health")
def check_all_streams():
    """
    Hit every station's stream_url with a short GET (streamed, aborted after
    first bytes) to confirm it's alive.
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


@app.get("/stations/{station_id}/nowplaying")
def station_now_playing(station_id: str):
    data = load_data()
    station = find_station(data, station_id)
    url = station.get("stream_url")
    if not url:
        return {"supported": False, "title": None}
    return fetch_now_playing(url)


@app.post("/stations/{station_id}")
def update_station(station_id: str, update: StationUpdate):
    data = load_data()
    station = find_station(data, station_id)

    for field, value in update.model_dump(exclude_unset=True, mode="json").items():
        station[field] = value

    station["verified"] = False
    station["status"] = "candidate" if station.get("stream_url") else "unresolved"

    save_data(data)
    return station

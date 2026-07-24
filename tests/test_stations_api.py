"""
Tests for the station relay API.

Everything network-related (httpx calls out to actual radio streams) is
mocked with respx. This exists because the dev sandbox this project was
built in can't reach real streaming CDNs -- see DEVLOG.md entry 0. The goal
here is to prove the *logic* is correct (status transitions, persistence,
error handling) so the only thing left to verify on the real Pi 5 is
whether each candidate URL is actually a live stream.
"""

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Point the app at a throwaway copy of the station data for each test."""
    data_file = tmp_path / "stations.json"
    data_file.write_text(json.dumps({
        "stations": [
            {
                "id": "alive_station",
                "name": "Alive Station",
                "stream_url": "http://example.test/alive.mp3",
                "format": "mp3",
                "hls_only": False,
                "verified": False,
                "last_checked": None,
                "status": "candidate",
                "notes": "",
            },
            {
                "id": "dead_station",
                "name": "Dead Station",
                "stream_url": "http://example.test/dead.mp3",
                "format": "mp3",
                "hls_only": False,
                "verified": False,
                "last_checked": None,
                "status": "candidate",
                "notes": "",
            },
            {
                "id": "no_url_station",
                "name": "No URL Station",
                "stream_url": None,
                "format": None,
                "hls_only": False,
                "verified": False,
                "last_checked": None,
                "status": "unresolved",
                "notes": "",
            },
        ]
    }))
    monkeypatch.setattr(main, "DATA_PATH", data_file)
    return TestClient(main.app)


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_get_stations_returns_all(client):
    resp = client.get("/stations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["stations"]) == 3


def test_get_single_station(client):
    resp = client.get("/stations/alive_station")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Alive Station"


def test_get_unknown_station_404s(client):
    resp = client.get("/stations/does_not_exist")
    assert resp.status_code == 404


def test_post_update_resets_verification(client):
    """
    Editing a station's URL should reset verified/status -- an old health
    check result shouldn't silently keep applying to a URL that changed.
    """
    resp = client.post(
        "/stations/no_url_station",
        json={"stream_url": "http://example.test/newly-added.mp3"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stream_url"] == "http://example.test/newly-added.mp3"
    assert body["verified"] is False
    assert body["status"] == "candidate"  # has a URL now, so no longer "unresolved"


def test_stream_health_check_marks_alive_dead_and_unresolved(client):
    with respx.mock(assert_all_called=True) as mock:
        mock.get("http://example.test/alive.mp3").mock(
            return_value=httpx.Response(200, content=b"\xff\xfb\x90\x00" * 100)  # fake mp3 frame bytes
        )
        mock.get("http://example.test/dead.mp3").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        resp = client.get("/stations/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["checked"] == 3

    results = {r["id"]: r["status"] for r in body["results"]}
    assert results["alive_station"] == "alive"
    assert results["dead_station"].startswith("error:")
    assert results["no_url_station"] == "unresolved"

    # Confirm persistence: a fresh GET reflects the check we just ran.
    refreshed = client.get("/stations/alive_station").json()
    assert refreshed["verified"] is True
    assert refreshed["last_checked"] is not None

# Dev Log — Pi 5 Radio Station Relay

Running record of what we build, why, and what we learned. Newest entry on top.

---

## Entry 1 — Mocked test suite (respx)

**Goal:** verify `/stations/health` logic without real internet access, per the gap flagged in Entry 0.

**What we did:**
- Made `DATA_PATH` overridable via `STATIONS_DATA_PATH` env var / direct monkeypatch, so tests run against a throwaway JSON file instead of the real station list
- Added `tests/test_stations_api.py` using `respx` to mock `httpx` calls: one route returns a fake 200 with MP3-like bytes, one raises `ConnectError`, one station has no URL at all
- 6 tests covering: basic endpoints, 404 handling, POST-resets-verification behaviour, and the three health-check outcomes (alive / error / unresolved)

**Outcome — caught a real bug on the first run:**
`GET /stations/health` was returning 404. Cause: FastAPI/Starlette matches routes in registration order, and `/stations/{station_id}` was registered *before* `/stations/health` — so `{station_id}` greedily matched the literal string `"health"`, ran it through `find_station()`, found no station called "health", and 404'd. The health-check endpoint had never actually been reachable, even in the earlier manual `curl` test (which we thought had just timed out due to sandbox network restrictions — it had actually 404'd well before it got anywhere near the network).

**Fix:** moved the `/stations/health` route definition above the `/stations/{station_id}` routes. Route order matters in FastAPI; more specific/literal paths need to come before parameterized ones that could shadow them.

**Lesson:** the "can't test against the real network from this sandbox" limitation from Entry 0 masked a completely unrelated bug that had nothing to do with the network — the request never got that far. Mocking the dependency didn't just work around the limitation, it surfaced a bug that manual `curl` testing had misdiagnosed. Worth remembering for the Pico-side work too: when something "times out" or fails, check the simplest explanation (wrong route, wrong URL, typo) before assuming it's the exotic one (network/hardware).

---

## Entry 0 — Baseline (initial build)

**What exists:**
- FastAPI service (`app/main.py`) serving `/stations`, `/stations/{id}`, `POST /stations/{id}`, `/stations/health`
- Station data as flat JSON on disk (`data/stations.json`), 11 stations pre-loaded with real (but unverified) stream URLs
- Dockerfile + docker-compose snippet to slot into the existing Pi 5 stack

**Verified:**
- Service boots, `/health` and `/stations` respond correctly (tested in sandbox)

**Not yet verified — known gap:**
- `/stations/health` (the live stream check) has never actually been run against a real stream. This sandbox's network is locked to package registries only, so `httpx` can't reach `media-ice.musicradio.com` or similar. First real test of this endpoint has to happen on the Pi 5 itself.
- No automated tests exist. Everything so far has been "run it and eyeball the output."

**Lesson:** building blind against a real dependency (the internet radio streams) that the dev sandbox can't reach is a recurring risk for this whole project — not just this one endpoint. Worth building a habit of writing tests that *mock* the network call, so logic can be verified here even when the real endpoint can't be reached.

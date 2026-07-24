# Dev Log — Pi 5 Radio Station Relay

Running record of what we build, why, and what we learned. Newest entry on top.

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

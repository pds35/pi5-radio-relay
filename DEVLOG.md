# Dev Log — Pi 5 Radio Station Relay

Running record of what we build, why, and what we learned. Newest entry on top.

---

## Entry 5 — Sync process failure: data/stations.json committed empty

**What happened:** while syncing Entry 3's results to the Pi, the file-copy instructions used a placeholder path (`/path/to/pi5-radio-relay.zip`) that got pasted literally instead of being swapped for the real path. `unzip -p <nonexistent-file> ... > target` fails to find anything, but the `>` redirect still runs and truncates `target` to empty -- silently. `git status` then correctly reports the file as "modified" (empty is different from the old content), which looks like success. It got committed and pushed to GitHub empty, and stayed that way through Entry 4's file sync too, until the dashboard's `GET /` route tried to `json.load()` an empty file and threw a clear 500.

**Why it took this long to notice:** every check in between (`git status`, `git log`, "everything up to date") was reporting truthfully on git's state, which was self-consistent -- an empty file committed cleanly is still a clean commit. Nothing in the git-level checks would ever catch a *wrong but validly-committed* file. The first thing that actually exercised the file's contents (not just its presence) was the dashboard trying to parse it as JSON.

**Fix:** re-ran the extraction with the real path, verified with `python3 -c "import json; ..."` that it actually parsed and had 11 stations -- not just that the file existed or had a nonzero size -- then committed properly.

**Lesson:** "the file changed" and "the file changed correctly" are different claims, and git only ever confirms the first one. From here on, any file sync step should include a content-level check (parse the JSON, run the tests, load the module) before committing, not just a presence/git-status check. This applies as much to the human-in-the-loop copy-paste process as it would to an automated deploy script -- arguably more, since typos in a manually-run command are exactly the kind of thing that produces a plausible-looking but wrong result.

---

## Entry 4 — HTML status dashboard

**Goal:** up to now the only way to see station status was raw JSON from `/stations`. Add a human-readable page.

**What we did:**
- `app/dashboard.py` -- a small, dependency-free HTML renderer (no template engine, just an f-string). Colour-coded status dots (green/amber/grey/red), a summary line, and a "Run health check" button that calls `/stations/health` via `fetch()` and reloads the page.
- `GET /` in `main.py` serves it.
- Explicitly escaped every user-editable field (`name`, `notes`, `stream_url`) with `html.escape()` -- station data comes in through `POST /stations/{id}`, which is API-writable, so it's untrusted input even though today it's only ever "untrusted" in the sense of *me* typo-ing something, not an actual attacker on a home LAN. Better to build the habit now than assume the trust boundary never moves.
- 2 new tests: dashboard renders all stations, and a station name containing `<script>` gets escaped rather than executed.

**Outcome:** all 14 tests passed first run. Spot-checked the rendered output against the real 11-station data file directly (not just the test fixtures) before committing -- looked correct, all 3 confirmed-alive/2 confirmed-dead stations from Entry 3 displaying with the right colours and notes.

**Lesson:** this is the first entry where "add a test" and "manually eyeball it" were both worth doing, for different reasons -- the automated test proves the escaping logic doesn't regress later, but only looking at the actual rendered page against real data caught things a passing test wouldn't (e.g. does the layout read sensibly with genuinely long note text, do the colours make sense against the real status strings like `"dead: http_500"` rather than the clean fixture value `"alive"`). Neither replaces the other.

---

## Entry 3 — First real-world verification (on the actual Pi 5)

**Goal:** finally answer the question every entry so far has flagged as unverifiable from the dev sandbox -- do any of the candidate stream URLs actually work?

**Detour first:** Docker build on the Pi stalled -- turned out to be a genuinely slow connection (~85-110 KB/s measured via `curl` speed test against speedtest.tele2.net), not a Docker or Dockerfile problem. Base image layers alone would've taken 10+ minutes to pull. Worked around it by running the service directly with a Python venv instead of waiting on the container build -- got a real answer in minutes rather than deferring everything to a slow pull. Docker packaging still stands as the eventual deployment method; this was just about getting an answer *now*.

**Result — `GET /stations/health` run against the real internet, 2026-07-24:**

| Station | Result |
|---|---|
| Classic FM | ✅ alive |
| Capital FM | ✅ alive |
| Smooth Radio | ✅ alive |
| BBC World Service | ❌ HTTP 410 Gone -- the legacy MP3 endpoint has been formally retired, not just rotted |
| Absolute Radio 80s | ❌ HTTP 500 -- stale mount, needs a fresh URL |
| BBC Radio 1 / 2 / 6 Music | unresolved (expected -- no URL was ever set, HLS-only, tracked separately) |
| Jazz FM / Heart UK / Absolute Radio Country | unresolved (expected -- no candidate URL was ever found in research) |

**Outcome:** 3 of 11 stations are confirmed, real, working direct MP3 streams on the first try -- Classic FM, Capital FM, Smooth Radio. That's enough to prove the whole architecture end-to-end (Pi 5 relay -> health check -> a stream a VS1053 could actually decode). 2 more candidates were disproven rather than confirmed, which is just as useful: BBC World Service's "legacy" escape hatch from Entry 0's notes is now confirmed dead, not just unverified, so it drops out of the HLS-workaround conversation entirely rather than lingering as a maybe.

**Lesson:** this is the first entry in the whole project with zero simulated/mocked/assumed data in it -- every other entry, including the "candidate" URLs, was built on secondhand research (forum posts, GitHub gists, old blog entries) of uncertain freshness. The gap between "found in a 2022 forum post" and "actually alive today" turned out to be real: one of the two dead candidates (Absolute 80s) was exactly that kind of aged source. Worth treating every research-sourced URL as a guess until this endpoint says otherwise, not a fact.

**Remaining unresolved:** Jazz FM, Heart UK, Absolute Radio Country still need a fresh URL each -- next research pass should use the browser-devtools method (Network tab on the station's own listen-live page) rather than searching aggregator sites, since that's what actually worked for the three confirmed-alive stations' origins.

---

## Entry 2 — Input validation on POST /stations/{id}

**Goal:** stop garbage from ever reaching `data/stations.json` via the API — a typo'd URL, wrong scheme, or made-up format string used to save silently and only surface later when the Pico tried (and failed) to stream it.

**What we did:**
- `stream_url` is now `Optional[HttpUrl]` (pydantic) instead of a plain string. Rejects anything that isn't a well-formed `http://` or `https://` URL -- wrong scheme (`ftp://`), missing scheme (bare hostname), or plain nonsense all get a 422 before the handler even runs.
- `format` is now `Optional[Literal["mp3", "aac", "hls", "dash"]]` instead of a free string -- typos or made-up formats (`"flac"`) get rejected too.
- Handler serializes with `model_dump(mode="json")` so the validated `HttpUrl` object gets stored back as a plain string, not a pydantic object.
- 6 new tests: reject bad scheme, reject garbage, reject schemeless URL, reject unknown format, accept a valid URL+format, and confirm you can still explicitly clear a `stream_url` back to `null`.

**Outcome:** all 12 tests passed on the first run -- no surprise bugs this time, unlike Entry 1. Worth noting as a contrast: Entry 1's bug was in *our* routing logic; this change leans entirely on pydantic's already-battle-tested URL parser, so there was much less surface area for us to get wrong.

**Scope note:** this only validates data coming in through the API (`POST /stations/{id}`). The 11 stations pre-loaded directly into `data/stations.json` at baseline were never validated this way and still aren't -- if one of those URLs turns out to be malformed, this layer won't catch it. `/stations/health` (the live check) is still the real source of truth for whether a URL actually works, not just whether it's shaped like one.

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

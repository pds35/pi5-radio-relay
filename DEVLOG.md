# Dev Log — Pi 5 Radio Station Relay

## Entry 14 — Pico display polling hardened; GUI start/stop working

**Date:** 2026-07-28

### Thonny/mpremote port lock
- Diagnosed a recurring Thonny "Device is busy or does not respond" error: caused
  by a long-running script left as `main.py`, which blocks Thonny's Ctrl+C from
  landing between loop iterations.
- `mpremote connect /dev/ttyACM0` reliably breaks in where Thonny's interrupt
  can't — useful fallback going forward.
- Lesson reinforced: never leave a long-running loop as `main.py` while actively
  developing; keep it under a different filename until ready to run unattended.
- Also confirmed: Thonny holds an exclusive lock on the serial port while
  connected — `mpremote` can't attach until Thonny disconnects (or its backend
  process is killed).

### GTK start/stop GUI (Pi 5)
- Built a small GTK3 C++ app (Code::Blocks) with Start Radio / Stop Radio
  buttons, wrapping `~/start-radio.sh` and `~/stop-radio.sh` via `system()`.
- Required manually adding `pkg-config --cflags/--libs gtk+-3.0` output to
  Code::Blocks' compiler/linker settings — not automatic.
- Found `start-radio.sh` was missing `sudo` on all three `systemctl` calls
  (inconsistent with `stop-radio.sh`, which had it) — fixed.
- Set up passwordless sudo via `/etc/sudoers.d/radio-control`, scoped to the
  exact six start/stop systemctl commands needed — avoids GUI hangs waiting on
  a password prompt with no terminal to answer it.
- Confirmed full stop/start loop working end-to-end against all three services.

### now_playing.py (Pico 2 W, ST7735 display)
- Confirmed `now_playing.py` (polls Pi 5 `/stations/{id}/nowplaying` every 10s)
  works correctly when actively run via Thonny/mpremote, but need to formalize
  running it as `main.py` for unattended operation.
- **Bug 1 — ECONNRESET on repeated polls:** first poll after boot succeeded,
  every poll after that failed with ECONNRESET, even though `curl` against the
  same endpoint from the Pi 5 succeeded every time. Root cause: CYW43 WiFi
  driver doesn't always release a closed socket immediately. Fixed with a
  200ms delay after `s.close()` plus a retry-once wrapper
  (`fetch_nowplaying_with_retry`) so a single transient reset doesn't flip the
  display to "Poll failed".
- **Bug 2 — stale "Poll failed" after recovery:** if the same track was still
  playing before and after a stop/start cycle, the `title != last_title` check
  suppressed the redraw, leaving "Poll failed" stuck on screen even though
  polling had recovered. Fixed by tracking a `was_failing` flag that forces a
  redraw on the first successful poll after any failure, regardless of whether
  the title changed.
- Both fixes validated against a real stop/start cycle via the GTK GUI.

### Open for next session
- **GUI has no user feedback.** Clicking Start/Stop gives no visual confirmation
  it registered, and `system()` calls are fire-and-forget with no exit-code
  check — the GUI doesn't actually know if the script succeeded. Needs a status
  label (e.g. "Starting…" / "Radio running" / "Radio off") for immediate
  feedback, decoupled from the ~10s it takes the Pico display to catch up.
- Consider a less binary "Poll failed" state on the Pico display (e.g.
  "Reconnecting…") since a normal stop/start cycle currently looks identical
  to a genuine outage from the display alone.
- `now_playing.py` still needs to be promoted to `main.py` (or equivalent) for
  unattended boot — currently only tested via Thonny/mpremote sessions.

## Entry 13 — Pico display polls /nowplaying, fixes a socket leak

**Goal:** get the Pico's bench-test square display (ST7735, framebuf-based driver) showing live
"now playing" info, reusing the Pi 5's existing `/stations/{id}/nowplaying` endpoint (Entry 11)
rather than duplicating ICY metadata parsing on the Pico itself.

**What we built:**
- `pico/now_playing.py` -- connects WiFi, then polls `GET /stations/classic_fm/nowplaying`
  over plain HTTP every 10s, parses the JSON response, and redraws the display only when the
  title actually changes.
- Deliberately thin on the Pico side: no ICY parsing, no persistent stream connection -- just a
  small HTTP client hitting the endpoint that already works, consistent with keeping heavy lifting
  on the Pi 5 and the Pico's job simple.

**Bug found and fixed:** first version connected fine on the very first poll, then timed out
(`ETIMEDOUT`) on every single poll after that. Ruled out the server first -- `curl` against
`/nowplaying` from the Pi 5 itself was consistently fast (100-250ms) even hammered repeatedly,
so the problem wasn't Classic FM being slow or the BBC relay stealing resources. Root cause was
on the Pico side: `fetch_nowplaying()` only wrapped the `recv()` loop in `try/finally`, not the
`connect()` call -- so a slow or failed connect could leak the socket with no cleanup. MicroPython's
lwIP socket pool on the Pico is small, and repeated open/close cycles every 10s (plus `Connection:
close` leaving sockets briefly in TIME_WAIT) exhausted it fast enough to explain "works once, fails
forever after."

**Fix:** moved `connect()` inside the `try/finally` so every code path guarantees `s.close()`,
and added an explicit `gc.collect()` right after, to help release the freed socket promptly rather
than lingering. Bumped the timeout from 5s to 8s as a secondary safety margin.

**Verified:** ran for several minutes straight with zero timeouts, correctly picking up two real
track changes live (Clarke/Purcell -> Kamen) on both the console and the physical display.

**Lesson:** "worked once, then failed every time after" is a strong signal for a resource leak
(sockets, file handles, memory) rather than a network or server issue -- confirmed here by timing
the server independently first before looking at the client. Worth remembering for the eventual
VS1053 audio-streaming code too, since that will hold a socket open far longer per station and any
leak there would be more painful to debug than this quick metadata poll.

**Not yet done:** station is still hardcoded to `classic_fm` -- no station-switching wired up yet
(that's still blocked on the rotary encoders arriving). No visual distinction on-screen yet between
"poll failed" and "station has no metadata support" (both currently just show a generic error line).

Running record of what we build, why, and what we learned. Newest entry on top.



## Entry 12 — Remote access via Tailscale + web service hardened to systemd
**Goal:** check the player page from away from home, safely, without exposing anything to the public internet.

**What we did:**
- Installed Tailscale on the Pi 5 (`curl -fsSL https://tailscale.com/install.sh | sh`, `sudo tailscale up`), joined the same tailnet as an iPhone already running the Tailscale app. No ports opened to the public internet -- private mesh network only, reachable only from devices explicitly logged into the same account.
- Pi's Tailscale address: `100.118.84.110`. Player page reachable at `http://100.118.84.110:8090/player` from anywhere the phone has any internet connection, not just home WiFi.

**Hit the same "foreground process dies with the terminal" issue as the BBC relay (Entry 8):** uvicorn had only been started manually with `nohup` in a terminal session, which had since ended -- `/health` returned nothing over Tailscale until we noticed and restarted it. Fixed properly this time by wrapping it in a systemd service (`pi5-radio-web.service`, `Restart=always`, `enabled` for boot survival) rather than repeating the same fragile pattern.

**Verified:** confirmed working from the phone over Tailscale, both immediately after the systemd handover and via a plain curl health check.

**Not yet done:** the Icecast BBC relay mount (port 8000) isn't yet exposed over Tailscale the same way -- only the web player (port 8090) is tested so far. Worth checking whether the Pico's own eventual station-list sync should also go through Tailscale, or stay LAN-only (Tailscale adds a dependency the Pico doesn't currently need, since it's always at home).

## Entry 11 — Web player with station picker and live "now playing" info
**Goal:** let a human pick from the 10 confirmed stations and play them in-browser, with live track info, building on the ICY metadata parsing proven in Entry 9's PoC script.

**What we built:**
- `app/nowplaying.py` -- single-shot ICY metadata fetcher. Opens a fresh connection per request (not persistent/background), requests `Icy-MetaData: 1`, reads past exactly `icy-metaint` bytes of audio, extracts the `StreamTitle` from the metadata block via regex, and closes. Reuses the buffer-accounting fix from the earlier PoC script (leftover bytes tracked correctly across reads, so audio data never gets misread as metadata text).
- `app/player.py` -- server-rendered picker page at `/player`. Station buttons built from `stations.json` (only `status: alive` ones shown), a native `<audio>` element for playback (browser connects directly to the station URL -- the Pi doesn't proxy audio, consistent with the whole direct-streaming architecture), and a JS poller hitting `/stations/{id}/nowplaying` every 10s.
- New route in `main.py`: `GET /stations/{station_id}/nowplaying`, returns `{"supported": bool, "title": str|None}`.

**Hit a real deployment snag:** pasting the updated `main.py` via a large heredoc over SSH got silently truncated mid-paste (bash sat waiting for the terminator that never arrived) -- not a code bug, a terminal/paste-buffer limit with very large blocks. Worked around it by moving the file via the browser download + `mv` from `~/Downloads` instead of a giant paste. Worth remembering for future large-file edits: heredoc is reliable for short/medium content (proven repeatedly today), but full-file rewrites of 150+ lines are better done as a downloaded file moved into place, or split into smaller heredoc chunks.

**Verified:** `/stations/health` re-confirms all 10 stations alive independently of the player. `/stations/classic_fm/nowplaying` returned a real, current track title. Manually tested in-browser at `/player` -- all 10 stations play correctly, switching between them works, now-playing text updates on schedule.

**Not yet done:** no visual distinction yet for stations without ICY support vs. ones that are just between metadata updates. No handling yet for what happens if a station's `stream_url` changes while it's mid-playback (the picker always uses whatever's in `stations.json` at page-load time). Player isn't linked from the main dashboard yet.


## Entry 10 — Reached 10 confirmed stations via CDN-family mount guessing
**Goal:** get to 10 working stations without touching the BBC/HLS relay (shelved pending the watchdog fix) or chasing Jazz FM further (confirmed dead-end in Entry 9).

**Method:** the `media-ice.musicradio.com` CDN family (Global-owned: Classic FM, Heart, Capital, Smooth) has been 100% reliable so far, and Global runs many more stations on the same infrastructure. Guessed mount names following the established naming convention (`<Name>MP3`) and tested in batches with a quick curl status-code loop before verifying real ones with actual audio bytes.

**Results — 6 new stations found, 4 added:**
- Smooth Country, LBC, Radio X, Smooth Chill -- all confirmed alive with real audio bytes, added to stations.json.
- GoldMP3 timed out (000) and GoldRadioMP3/CapitalXTRAMP3 404'd -- Gold and Capital Xtra need different mount names, not yet found.
- LBCLondonMP3 also returned 200 alongside LBCUKMP3 -- likely a duplicate/regional variant; only LBCUKMP3 added for now, worth checking later if they're actually different feeds.

**Station count: 10 of 15 confirmed working** (original 11 + 4 newly discovered). Genre spread now includes classical, talk (LBC), rock (Radio X), on top of the existing pop/hits/chill/country stations.

**Not yet done:** Gold, Capital Xtra, and other Global/Bauer stations likely also exist on the same CDN family with a different naming pattern -- worth another guessing pass if more stations are wanted later. BBC (3 stations) and Jazz FM remain the only unresolved originals.

## Entry 9 — Rescued 2 dead stations via radiofeeds.co.uk's bauerflash.pls redirector
**Goal:** find real URLs for the stations still marked dead/unresolved after Entry 7 (Jazz FM, Absolute Radio Country, Absolute Radio 80s).

**Method:** same redirector-resolution technique used for BBC's `lsn.lv` in Entry 8 — `radiofeeds.co.uk` links to `http://www.radiofeeds.net/playlists/bauerflash.pls?station=<name>-mp3`, which needs a browser-like User-Agent (`curl -A "VLC/3.0.18 LibVLC/3.0.18"`) and resolves to a `.pls` playlist containing the real, current stream URL.

**Results:**
- **Absolute Radio 80s**: old mount dead, new mount (`edge-bauerabsolute-05-gos2.sharp-stream.com/absolute80s.mp3`) confirmed alive, verified with real audio bytes.
- **Absolute Radio Country**: old `.aac` mount dead (ConnectError), new `.mp3` mount on the same edge-bauerabsolute-05-gos2 server confirmed alive, verified with real audio bytes.
- **Jazz FM**: tried the same pattern (`jazzfm-mp3`) — resolved to a plausible-looking URL, but got `404` on two separate fresh session keys. This rules out token expiry as the cause; the mount genuinely doesn't exist. Stays unresolved — Jazz FM really has moved fully behind the Rayo app player, confirming the Entry 6 finding rather than overturning it.

**New URLs both include a query-string session key/player-id** (`aw_0_1st.skey`, `aw_0_1st.playerid`) unlike the plain `media-ice.musicradio.com` mounts (Classic FM/Heart/Capital/Smooth), which have no such parameters. Worth treating these two as slightly less durable and re-verifying periodically in case the key format changes or requires per-session freshness.

**Station count: 6 of 11 confirmed working** (up from 4), all direct-stream, no Pi relay needed. Remaining: 3 BBC stations (need the HLS relay from Entry 8, currently shelved pending a watchdog fix) + Jazz FM (no viable mount found) + BBC World Service (confirmed dead, separate issue).

## Entry 8 — HLS blocker resolved: ffmpeg + Icecast relay PoC (BBC Radio 2)

**Goal:** Entry 7 left 3 stations (BBC Radio 1/2/6 Music) marked "HLS-only-blocked" — the Pico can't decode HLS directly. Proved whether a Pi-side relay can unblock them by converting HLS to plain HTTP before it ever reaches the Pico.

**What we did:**
- Installed ffmpeg + icecast2 on the Pi 5, bound Icecast to the LAN IP only.
- Found BBC Radio 2's real HLS manifest via the `lsn.lv` redirector (needs a browser-like `User-Agent`; a bare `curl -I` gets 401/404 and looks like a dead URL until you add the header — same "check the boring explanation first" lesson as Entry 1).
- ffmpeg relays the manifest into Icecast as plain MP3: `-user_agent ... -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -i "<manifest>" -avoid_negative_ts make_zero -fflags +genpts -acodec libmp3lame -ab 96k -f mp3 icecast://source:***@<lan-ip>:8000/radio2`
- Wrapped as a systemd service (`Restart=always`) so it survives without a live terminal.

**Outcome — first version crash-looped every 60-90s:**
Icecast's default `source-timeout` was too tight for an occasional stall caused by a DTS/timestamp discontinuity in the HLS stream (`Application provided invalid, non monotonically increasing dts`). Fixed with `-avoid_negative_ts make_zero -fflags +genpts` on ffmpeg plus `source-timeout: 30` in icecast.xml. Also self-inflicted a ~60-restart-in-a-minute spiral mid-fix: a pasted edit split `-avoid_negative_ts` into two args, pointing `-i` at a nonexistent file called `-avoid`.

**Current state:** stable since the fix — one isolated `Broken pipe` restart after ~90 minutes clean, auto-recovered by systemd in 5s, none since. 5-minute soak-test logging in progress, `NRestarts=0` since that one event.

**Significance for the station count:** this doesn't just prove a PoC — it's a candidate fix for the 3 HLS-blocked stations from Entry 7. If BBC Radio 1 and 6 Music work the same way (same CDN family, same manifest pattern, just different `station=` param), the project could go from 4/11 to potentially 7/11 working stations, once each is relayed the same way. BBC World Service is separately confirmed dead (Entry 7) so stays excluded regardless.

**Not yet done:**
- Only Radio 2 relayed so far — Radio 1 and 6 Music not yet tried against this same pipeline (should just be a `station=` swap in the manifest URL).
- Icecast itself has no equivalent resilience wrapper beyond the OS package default — only the ffmpeg relay is wrapped in `Restart=always` so far.
- Full 24h soak test still running as of this entry.
- Not yet decided how this relay fits architecturally alongside the existing FastAPI station-list service (Entry 0) — likely as a sibling component (`relay/`) rather than inside it, but not yet wired together or reflected in `docker-compose.snippet.yml`.
---

## Entry 7 — Verified the Entry 6 candidates: 1 alive, 1 dead

**Result on the Pi 5, 2026-07-24:**
- Heart UK: ✅ confirmed **alive**. 4th station now working (Classic FM, Capital FM, Smooth Radio, Heart UK).
- Absolute Radio Country: ❌ confirmed **dead** -- and notably, `ConnectError`, not an HTTP error code. `absolute_80s` and `bbc_world_service` at least got a real response from a real server (500, 410) -- this one didn't connect at all, meaning the hostname itself is likely dead or was already stale in the 2023 source that provided it.

**Score so far across all research methods used in this project:** Wikipedia infobox + mount-listing verification is now 4-for-4 (Classic FM, Capital FM, Smooth Radio, Heart UK all came from the same `media-ice.musicradio.com` family and all are alive). Aged blog/forum posts are more of a mixed bag -- worked for `absolute_80s`'s original discovery but that one later also died, and now this one died too. Pattern holding up: same-CDN-family candidates are much better bets than one-off mentions in old posts, regardless of how specific the post was.

**Remaining unresolved:** Jazz FM (no candidate ever found) and Absolute Radio Country (candidate found but dead) -- 2 of 11 stations still need real URLs. 3 stations are HLS-only-blocked (BBC Radio 1/2/6 Music) and BBC World Service is confirmed dead. That leaves this project at **4 working stations out of 11**, with a clear path (find same-CDN-family URLs) for the remaining 2 that don't have a structural blocker.

---

## Entry 6 — Research session: 2 of 3 remaining stations found candidates

**Goal:** resolve Jazz FM, Heart UK, Absolute Radio Country -- the 3 stations that have sat "unresolved" since the project began.

**Dead ends checked and ruled out:** internetradiouk.com and radio.net (both large consumer-facing directories) stream through their own embedded/proxied players rather than exposing raw URLs -- confirmed by fetching Jazz FM's actual page on internetradiouk.com, which just links out to hellorayo.co.uk (the same Bauer app-based player already known to be a dead end). Neither directory is a source of usable stream URLs for a VS1053, regardless of how comprehensive their station list is.

**What worked:** Wikipedia's own infobox for Heart UK links a "Webcast: MP3 Stream" -- not rendered as a clickable URL in the fetched content, but it prompted a targeted search that found the mount point confirmed directly against `media-ice.musicradio.com`'s own server listing. For Absolute Radio Country, a 2023 German radio blog post happened to name the station's Bauer sharp-stream.com mount specifically (unlike Jazz FM, where similar searches only surfaced sibling stations' URLs, never Jazz FM's own).

**Result:**
- Heart UK: `http://media-ice.musicradio.com/HeartUKMP3` -- same host as 3 already-confirmed-alive stations, good sign, not yet run through `/stations/health`
- Absolute Radio Country: `http://edge-bauerall-01-gos2.sharp-stream.com/absolutecountry.aac` -- AAC not MP3, worth noting the VS1053 needs a plugin loaded to decode AAC (MP3/WMA/MIDI are native); not yet run through `/stations/health`
- Jazz FM: still unresolved. Found the Bauer CDN's URL *pattern* from sibling stations but nothing naming Jazz FM specifically -- declined to guess a URL from the pattern and present it as a real candidate, since a wrong guess presented confidently is worse than an honest gap

**Lesson:** the useful signal wasn't "search harder," it was recognizing which *kind* of source was worth pursuing. Listener-facing directories (however comprehensive) are the wrong shape of resource for this task regardless of which one you try, because they're built to embed a player, not disclose a URL. Wikipedia infoboxes and old blog posts/forum threads that happen to paste a real playlist are the right shape, because someone was doing exactly what we're doing (building a personal player) and left the evidence behind. Worth remembering for Jazz FM specifically -- it needs a similarly-shaped source, not a bigger directory.

**Next step:** run `/stations/health` on the Pi against these 2 new candidates to get real verification, same as Entry 3.

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

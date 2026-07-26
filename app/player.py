"""
Server-rendered player page at GET /player.

A simple station picker: click a station, it starts playing via the
browser's native <audio> element (the browser connects directly to the
station's stream_url -- the Pi does not proxy audio), and a small JS
poller hits /stations/{id}/nowplaying every 10s to show the current
track title, when the station supports ICY metadata.

Same "no template engine, no JS framework" philosophy as dashboard.py --
this is a personal utility, not a product.
"""

import html
import json


def render_player(data: dict) -> str:
    stations = [s for s in data.get("stations", []) if s.get("status") == "alive"]

    stations_json = json.dumps(
        [{"id": s["id"], "name": s["name"], "url": s["stream_url"]} for s in stations]
    )

    buttons = "\n".join(
        f'<button class="station-btn" data-id="{html.escape(s["id"])}" onclick="playStation(\'{html.escape(s["id"])}\')">{html.escape(s["name"])}</button>'
        for s in stations
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pi 5 Radio Player</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #14171a;
    color: #e8e6df;
    margin: 0;
    padding: 24px clamp(16px, 4vw, 48px) 60px;
    max-width: 640px;
  }}
  h1 {{ font-size: 1.3rem; margin-bottom: 4px; }}
  .summary {{ color: #8b9198; margin-bottom: 24px; font-size: 0.9rem; }}
  .stations {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 10px;
    margin-bottom: 28px;
  }}
  .station-btn {{
    background: #21262b; color: #e8e6df; border: 1px solid #2c3238;
    padding: 14px 10px; border-radius: 8px; cursor: pointer; font-size: 0.9rem;
    text-align: center;
  }}
  .station-btn:hover {{ background: #2c3238; }}
  .station-btn.active {{ border-color: #4c8bf5; background: #1c2b42; }}
  .now-playing {{
    background: #1b1f23; border: 1px solid #2c3238; border-radius: 10px;
    padding: 18px 20px; min-height: 70px;
  }}
  .now-playing .station-name {{ font-size: 1.05rem; font-weight: 600; margin-bottom: 6px; }}
  .now-playing .track {{ color: #cfcac0; font-size: 0.95rem; }}
  .now-playing .track.muted {{ color: #5c6268; font-style: italic; }}
  audio {{ width: 100%; margin-top: 16px; }}
  .placeholder {{ color: #5c6268; font-size: 0.9rem; }}
</style>
</head>
<body>
  <h1>Pi 5 Radio Player</h1>
  <div class="summary">{len(stations)} stations available</div>

  <div class="stations">
    {buttons}
  </div>

  <div class="now-playing" id="now-playing">
    <div class="placeholder">Pick a station to start listening.</div>
  </div>

  <audio id="player" controls></audio>

  <script>
    const stations = {stations_json};
    let currentStationId = null;
    let pollTimer = null;

    function playStation(id) {{
      const station = stations.find(s => s.id === id);
      if (!station) return;

      currentStationId = id;

      document.querySelectorAll('.station-btn').forEach(btn => {{
        btn.classList.toggle('active', btn.dataset.id === id);
      }});

      const audio = document.getElementById('player');
      audio.src = station.url;
      audio.play().catch(err => console.warn('Playback failed:', err));

      document.getElementById('now-playing').innerHTML = `
        <div class="station-name">${{station.name}}</div>
        <div class="track muted">Loading track info...</div>
      `;

      if (pollTimer) clearInterval(pollTimer);
      pollNowPlaying();
      pollTimer = setInterval(pollNowPlaying, 10000);
    }}

    async function pollNowPlaying() {{
      if (!currentStationId) return;
      const id = currentStationId;
      try {{
        const resp = await fetch(`/stations/${{id}}/nowplaying`);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();

        if (id !== currentStationId) return;

        const station = stations.find(s => s.id === id);
        const trackEl = document.querySelector('.now-playing .track');
        if (!trackEl) return;

        if (data.supported === false) {{
          trackEl.textContent = '(this station doesn\\'t provide track info)';
          trackEl.classList.add('muted');
        }} else if (data.title) {{
          trackEl.textContent = data.title;
          trackEl.classList.remove('muted');
        }} else {{
          trackEl.textContent = '(track info unavailable right now)';
          trackEl.classList.add('muted');
        }}
      }} catch (err) {{
        console.warn('Now-playing poll failed:', err);
      }}
    }}
  </script>
</body>
</html>"""

"""
Server-rendered HTML for the human-facing status dashboard at GET /.

Kept deliberately simple: no template engine, no JS framework, no build
step. It's an admin utility for one person on a home network, not a
product -- inline HTML string building is the right amount of tooling
for that, and it means zero extra dependencies.
"""

import html

STATUS_COLORS = {
    "alive": "#2e7d32",       # green
    "candidate": "#b8860b",   # amber -- has a URL, not yet checked
    "unresolved": "#757575",  # grey -- no URL at all
}


def _status_color(status: str) -> str:
    if status in STATUS_COLORS:
        return STATUS_COLORS[status]
    if status.startswith("dead") or status.startswith("http_") or status.startswith("error"):
        return "#c62828"  # red
    return "#757575"


def render_dashboard(data: dict) -> str:
    stations = data.get("stations", [])
    rows = []
    for s in stations:
        name = html.escape(s.get("name", s.get("id", "?")))
        status = s.get("status", "unknown")
        color = _status_color(status)
        url = s.get("stream_url")
        url_html = (
            f'<code>{html.escape(url)}</code>' if url else '<span class="muted">none</span>'
        )
        verified = "yes" if s.get("verified") else "no"
        last_checked = s.get("last_checked")
        last_checked_html = html.escape(str(last_checked)) if last_checked else "never"
        notes = html.escape(s.get("notes", "") or "")

        rows.append(f"""
        <tr>
          <td>{name}</td>
          <td><span class="dot" style="background:{color}"></span>{html.escape(status)}</td>
          <td>{url_html}</td>
          <td>{verified}</td>
          <td class="muted">{last_checked_html}</td>
          <td class="notes">{notes}</td>
        </tr>""")

    alive_count = sum(1 for s in stations if s.get("status") == "alive")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pico Radio Station Relay</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #14171a;
    color: #e8e6df;
    margin: 0;
    padding: 24px clamp(16px, 4vw, 48px) 60px;
  }}
  h1 {{ font-size: 1.3rem; margin-bottom: 4px; }}
  .summary {{ color: #8b9198; margin-bottom: 20px; font-size: 0.9rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ text-align: left; padding: 8px 10px; color: #8b9198; border-bottom: 1px solid #2c3238; font-weight: 600; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #21262b; vertical-align: top; }}
  code {{ font-size: 0.78rem; color: #cfcac0; word-break: break-all; }}
  .muted {{ color: #5c6268; }}
  .notes {{ color: #8b9198; max-width: 320px; font-size: 0.78rem; }}
  .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
  button {{
    background: #21262b; color: #e8e6df; border: 1px solid #2c3238;
    padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 0.85rem;
  }}
  button:hover {{ background: #2c3238; }}
  button:disabled {{ opacity: 0.5; cursor: default; }}
  #status-msg {{ margin-left: 12px; color: #8b9198; font-size: 0.85rem; }}
</style>
</head>
<body>
  <h1>Pico Radio Station Relay</h1>
  <div class="summary">{alive_count} of {len(stations)} stations confirmed alive &middot; served from data/stations.json</div>
  <button id="recheck-btn" onclick="runHealthCheck()">Run health check</button>
  <span id="status-msg"></span>

  <table>
    <thead>
      <tr>
        <th>Station</th>
        <th>Status</th>
        <th>Stream URL</th>
        <th>Verified</th>
        <th>Last checked</th>
        <th>Notes</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>

  <script>
    async function runHealthCheck() {{
      const btn = document.getElementById('recheck-btn');
      const msg = document.getElementById('status-msg');
      btn.disabled = true;
      msg.textContent = 'Checking all streams (can take up to ~1 min)...';
      try {{
        const resp = await fetch('/stations/health');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        msg.textContent = 'Done -- refreshing...';
        window.location.reload();
      }} catch (err) {{
        msg.textContent = 'Health check failed: ' + err.message;
        btn.disabled = false;
      }}
    }}
  </script>
</body>
</html>"""

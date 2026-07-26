"""
Lightweight, single-shot ICY metadata fetcher.

Opens a fresh connection to a station's stream_url, requests ICY metadata,
reads just far enough to capture one "Now Playing" title, then closes the
connection. Deliberately not a persistent/background connection -- this is
a personal dashboard with light polling (one browser tab, one station at a
time), so the cost of a short-lived connection per poll is negligible and
it keeps the logic simple and stateless.

Reuses the buffer-accounting approach proven in icy_metadata_test_v2.py
(DEVLOG-adjacent script) -- the earlier version of this logic had a bug
where leftover audio bytes weren't tracked correctly between reads and
audio data got misread as metadata text. recv_exact() here fixes that by
always returning the untaken remainder, so nothing is ever double-counted.
"""

import re
import socket
from urllib.parse import urlparse

TIMEOUT_SECONDS = 6.0
MAX_AUDIO_SKIP_BYTES = 200_000  # safety cap in case icy-metaint is huge/missing


def recv_exact(sock: socket.socket, buf: bytes, n: int) -> tuple[bytes, bytes]:
    while len(buf) < n:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("Server closed connection")
        buf += chunk
    return buf[:n], buf[n:]


def fetch_now_playing(stream_url: str) -> dict:
    """
    Returns one of:
      {"supported": True, "title": "Artist - Track"}
      {"supported": True, "title": None}          # ICY ok, but block was empty (no change)
      {"supported": False, "title": None}         # server doesn't send icy-metaint
      {"supported": None, "title": None, "error": "..."}  # couldn't connect/timed out
    """
    parsed = urlparse(stream_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    if parsed.scheme == "https":
        # Deliberately not supporting HTTPS metadata scraping here -- all
        # current direct-stream stations in stations.json are plain HTTP.
        return {"supported": None, "title": None, "error": "https not supported"}

    try:
        with socket.create_connection((host, port), timeout=TIMEOUT_SECONDS) as s:
            request = (
                "GET {} HTTP/1.0\r\n"
                "Host: {}\r\n"
                "User-Agent: Pi5RadioNowPlaying\r\n"
                "Icy-MetaData: 1\r\n"
                "\r\n"
            ).format(path, host)
            s.sendall(request.encode())

            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = s.recv(1024)
                if not chunk:
                    break
                buf += chunk

            header_data, _, buf = buf.partition(b"\r\n\r\n")
            headers_text = header_data.decode(errors="replace")

            icy_metaint = None
            for line in headers_text.split("\r\n"):
                if line.lower().startswith("icy-metaint"):
                    icy_metaint = int(line.split(":", 1)[1].strip())

            if icy_metaint is None or icy_metaint > MAX_AUDIO_SKIP_BYTES:
                return {"supported": False, "title": None}

            # Skip exactly icy_metaint bytes of audio
            _, buf = recv_exact(s, buf, icy_metaint)

            # Read the 1-byte metadata length indicator
            length_byte_data, buf = recv_exact(s, buf, 1)
            meta_len = length_byte_data[0] * 16

            if meta_len == 0:
                return {"supported": True, "title": None}

            meta_block, buf = recv_exact(s, buf, meta_len)
            meta_text = meta_block.decode(errors="replace").rstrip("\x00")

            match = re.search(r"StreamTitle='([^']*)'", meta_text)
            title = match.group(1).strip() if match else None
            return {"supported": True, "title": title or None}

    except (OSError, ConnectionError, socket.timeout) as exc:
        return {"supported": None, "title": None, "error": str(exc)}

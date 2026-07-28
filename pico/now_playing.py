"""
Live Now Playing display — Pico 2 W (MicroPython)
Polls the Pi 5's existing /stations/{id}/nowplaying endpoint (Entry 11)
instead of parsing ICY metadata directly — reuses the server-side parsing
that's already proven working, rather than duplicating it on the Pico.

Wiring (SPI0):
  GND -> GND      SCL -> GP18 (SCK)     RES -> GP21
  VCC -> 3V3      SDA -> GP19 (MOSI)    DC  -> GP20
  CS  -> GP17     BL  -> GP22

Hardening notes (added after repeated ECONNRESET on rapid poll cycles):
  - CYW43 WiFi driver doesn't always fully release a socket immediately
    after close(); a short delay after close() gives it time to settle.
  - fetch_nowplaying() is retried once on OSError before the loop reports
    a failure, since a single transient reset shouldn't flip the display.
"""

import network
import socket
import time
import json
import gc
import framebuf
from machine import Pin, SPI

# ---- WiFi / Pi 5 web service config ----
SSID = "TP-Mesh35_Guest"
PASSWORD = ""
PI5_HOST = "192.168.68.118"
PI5_PORT = 8090
STATION_ID = "classic_fm"          # one of the 10 confirmed stations
STATION_LABEL = "CLASSIC FM"       # display label, since the endpoint only returns title
POLL_SECONDS = 10
SOCKET_RELEASE_DELAY_MS = 200      # let CYW43 driver release the socket after close()
RETRY_DELAY_MS = 300               # pause before the single retry attempt

# ---- display pins ----
SCK_PIN, MOSI_PIN = 18, 19
CS_PIN, DC_PIN, RST_PIN, BL_PIN = 17, 20, 21, 22

SWRESET, SLPOUT, COLMOD, MADCTL = 0x01, 0x11, 0x3A, 0x36
DISPON, CASET, RASET, RAMWR = 0x29, 0x2A, 0x2B, 0x2C
INVON, INVOFF = 0x21, 0x20


class ST7735(framebuf.FrameBuffer):
    def __init__(self, width=128, height=128, x_offset=2, y_offset=3, invert=True):
        self.width = width
        self.height = height
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.buf = bytearray(width * height * 2)
        super().__init__(self.buf, width, height, framebuf.RGB565)

        self.spi = SPI(0, baudrate=20_000_000, polarity=0, phase=0,
                        sck=Pin(SCK_PIN), mosi=Pin(MOSI_PIN))
        self.cs = Pin(CS_PIN, Pin.OUT, value=1)
        self.dc = Pin(DC_PIN, Pin.OUT, value=0)
        self.rst = Pin(RST_PIN, Pin.OUT, value=1)
        self.bl = Pin(BL_PIN, Pin.OUT, value=1)

        self._reset()
        self._init_display(invert)

    def _reset(self):
        self.rst.value(1); time.sleep_ms(10)
        self.rst.value(0); time.sleep_ms(10)
        self.rst.value(1); time.sleep_ms(120)

    def _cmd(self, c, data=None):
        self.cs.value(0)
        self.dc.value(0)
        self.spi.write(bytes([c]))
        if data is not None:
            self.dc.value(1)
            self.spi.write(data)
        self.cs.value(1)

    def _init_display(self, invert):
        self._cmd(SWRESET); time.sleep_ms(150)
        self._cmd(SLPOUT); time.sleep_ms(500)
        self._cmd(COLMOD, b'\x05'); time.sleep_ms(10)
        self._cmd(MADCTL, b'\x00')
        self._cmd(INVON if invert else INVOFF); time.sleep_ms(10)
        self._cmd(DISPON); time.sleep_ms(100)

    def show(self):
        x0, y0 = self.x_offset, self.y_offset
        x1, y1 = x0 + self.width - 1, y0 + self.height - 1
        self._cmd(CASET, bytes([0, x0, 0, x1]))
        self._cmd(RASET, bytes([0, y0, 0, y1]))
        self._cmd(RAMWR)
        self.cs.value(0)
        self.dc.value(1)
        mv = memoryview(self.buf)
        chunk = bytearray(1024)
        for i in range(0, len(mv), 1024):
            piece = mv[i:i + 1024]
            n = len(piece)
            for j in range(0, n, 2):
                chunk[j] = piece[j + 1]
                chunk[j + 1] = piece[j]
            self.spi.write(chunk[:n])
        self.cs.value(1)


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


BLACK = rgb565(0, 0, 0)
WHITE = rgb565(255, 255, 255)
GREY = rgb565(150, 150, 160)
RED = rgb565(220, 60, 60)


def draw_now_playing(tft, station, title, artist, status_text=""):
    tft.fill(BLACK)
    tft.text(station[:16], max(0, (128 - len(station[:16]) * 8) // 2), 4, WHITE)
    tft.hline(8, 16, 112, GREY)
    tft.text("NOW PLAYING", 28, 26, GREY)
    tft.text(title[:16], max(0, (128 - len(title[:16]) * 8) // 2), 48, WHITE)
    tft.text(artist[:16], max(0, (128 - len(artist[:16]) * 8) // 2), 62, GREY)
    if status_text:
        tft.text(status_text[:16], 4, 116, RED)
    tft.show()


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)
    print("Connecting to WiFi...")
    timeout = 15
    while not wlan.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1
    if not wlan.isconnected():
        raise OSError("WiFi connection failed")
    print("Connected:", wlan.ifconfig())
    return wlan


def fetch_nowplaying():
    """GET /stations/{id}/nowplaying from the Pi 5, return parsed JSON dict."""
    path = "/stations/{}/nowplaying".format(STATION_ID)
    addr_info = socket.getaddrinfo(PI5_HOST, PI5_PORT)[0][-1]

    s = socket.socket()
    try:
        s.settimeout(8)
        s.connect(addr_info)
        request = (
            "GET {} HTTP/1.0\r\n"
            "Host: {}\r\n"
            "User-Agent: PicoRadioDisplay\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).format(path, PI5_HOST)
        s.send(request.encode())

        response = b""
        while True:
            chunk = s.recv(512)
            if not chunk:
                break
            response += chunk
    finally:
        # guaranteed to run even if connect()/send()/recv() throws,
        # so a slow/failed attempt never leaks the socket
        s.close()
        gc.collect()
        # CYW43 driver doesn't always release the socket immediately on
        # close() — a short pause here avoids ECONNRESET on the *next*
        # connection attempt when polling on a tight interval.
        time.sleep_ms(SOCKET_RELEASE_DELAY_MS)

    header_part, _, body = response.partition(b"\r\n\r\n")
    if not body:
        raise ValueError("Empty response body")
    return json.loads(body)


def fetch_nowplaying_with_retry():
    """Try once, and on a transient OSError (e.g. ECONNRESET) try once
    more after a short pause before letting the caller treat it as a
    real failure. A single dropped connection shouldn't flip the display."""
    try:
        return fetch_nowplaying()
    except OSError as e:
        print("Poll error (retrying once):", e)
        time.sleep_ms(RETRY_DELAY_MS)
        return fetch_nowplaying()


def parse_title(title):
    if not title:
        return "", ""
    if " - " in title:
        artist, track = title.split(" - ", 1)
        return artist.strip(), track.strip()
    return "", title.strip()


def main():
    tft = ST7735()
    draw_now_playing(tft, STATION_LABEL, "Starting...", "")

    try:
        connect_wifi()
    except OSError as e:
        draw_now_playing(tft, STATION_LABEL, "WiFi failed", "", str(e))
        return

    last_title = None
    was_failing = False  # tracks whether the previous poll failed, so a
                          # recovered poll always redraws even if the
                          # track title is unchanged from before the outage

    while True:
        try:
            data = fetch_nowplaying_with_retry()
            if data.get("supported") and data.get("title"):
                title = data["title"]
                if title != last_title or was_failing:
                    last_title = title
                    artist, track = parse_title(title)
                    print("Now playing:", title)
                    draw_now_playing(tft, STATION_LABEL, track or title, artist)
            else:
                draw_now_playing(tft, STATION_LABEL, "(no metadata)", "")
            was_failing = False
        except Exception as e:
            print("Poll failed:", e)
            draw_now_playing(tft, STATION_LABEL, "Poll failed", "", str(e)[:16])
            was_failing = True

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
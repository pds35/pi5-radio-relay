import json

PATH = "data/stations.json"

with open(PATH, "r") as f:
    data = json.load(f)

new_stations = [
    {
        "id": "smooth_country",
        "name": "Smooth Country",
        "stream_url": "http://media-ice.musicradio.com/SmoothCountryMP3",
        "format": "mp3",
        "hls_only": False,
        "verified": True,
        "last_checked": "2026-07-26 (Pi 5, real network)",
        "status": "alive",
        "notes": "Found by guessing mount names on the media-ice.musicradio.com CDN family (same host as Classic FM/Heart/Capital/Smooth, 4-for-4 reliable so far). Confirmed alive with real audio bytes."
    },
    {
        "id": "lbc",
        "name": "LBC",
        "stream_url": "http://media-ice.musicradio.com/LBCUKMP3",
        "format": "mp3",
        "hls_only": False,
        "verified": True,
        "last_checked": "2026-07-26 (Pi 5, real network)",
        "status": "alive",
        "notes": "Talk/news station, same CDN family as the other Global-owned stations. Confirmed alive with real audio bytes. Note: LBCLondonMP3 also returned 200 -- may be a duplicate/regional variant of the same feed, not yet checked which is preferred."
    },
    {
        "id": "radio_x",
        "name": "Radio X",
        "stream_url": "http://media-ice.musicradio.com/RadioXUKMP3",
        "format": "mp3",
        "hls_only": False,
        "verified": True,
        "last_checked": "2026-07-26 (Pi 5, real network)",
        "status": "alive",
        "notes": "Rock format, same CDN family as the other Global-owned stations. Confirmed alive with real audio bytes."
    },
    {
        "id": "smooth_chill",
        "name": "Smooth Chill",
        "stream_url": "http://media-ice.musicradio.com/SmoothChillMP3",
        "format": "mp3",
        "hls_only": False,
        "verified": True,
        "last_checked": "2026-07-26 (Pi 5, real network)",
        "status": "alive",
        "notes": "Same CDN family as the other Global-owned stations. Confirmed alive with real audio bytes."
    }
]

existing_ids = {s["id"] for s in data["stations"]}
added = []
for station in new_stations:
    if station["id"] not in existing_ids:
        data["stations"].append(station)
        added.append(station["id"])

with open(PATH, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Added:", added)
print("Total stations now:", len(data["stations"]))

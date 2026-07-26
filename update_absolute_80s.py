import json

PATH = "data/stations.json"

with open(PATH, "r") as f:
    data = json.load(f)

updated = False
for station in data["stations"]:
    if station["id"] == "absolute_80s":
        station["stream_url"] = (
            "http://edge-bauerabsolute-05-gos2.sharp-stream.com/absolute80s.mp3"
            "?aw_0_1st.skey=1785055397&aw_0_1st.playerid=BMUK_RPi"
        )
        station["format"] = "mp3"
        station["hls_only"] = False
        station["verified"] = True
        station["last_checked"] = "2026-07-26 (Pi 5, real network)"
        station["status"] = "alive"
        station["notes"] = (
            "Previous mount (icy-e-bab-04-cr.sharp-stream.com) confirmed dead "
            "2026-07-24. New working mount found via radiofeeds.co.uk's "
            "bauerflash.pls redirector, resolved with curl -A "
            "\"VLC/3.0.18 LibVLC/3.0.18\". URL includes a query-string "
            "session key/player-id (aw_0_1st.skey, aw_0_1st.playerid) -- "
            "worth re-checking periodically in case this expires or "
            "rotates, unlike the plain media-ice.musicradio.com mounts "
            "which have no such parameters."
        )
        updated = True
        break

if not updated:
    print("ERROR: absolute_80s entry not found -- no changes made.")
else:
    with open(PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("Updated absolute_80s entry successfully.")

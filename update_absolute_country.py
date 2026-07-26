import json

PATH = "data/stations.json"

with open(PATH, "r") as f:
    data = json.load(f)

updated = False
for station in data["stations"]:
    if station["id"] == "absolute_country":
        station["stream_url"] = (
            "http://edge-bauerabsolute-05-gos2.sharp-stream.com/absolutecountry.mp3"
            "?aw_0_1st.skey=1785055940&aw_0_1st.playerid=BMUK_RPi"
        )
        station["format"] = "mp3"
        station["hls_only"] = False
        station["verified"] = True
        station["last_checked"] = "2026-07-26 (Pi 5, real network)"
        station["status"] = "alive"
        station["notes"] = (
            "Previous mount (edge-bauerall-01-gos2.sharp-stream.com/absolutecountry.aac) "
            "confirmed dead 2026-07-24 (ConnectError). New working mp3 mount found via "
            "radiofeeds.co.uk's bauerflash.pls redirector, same method as absolute_80s. "
            "URL includes a query-string session key/player-id -- worth re-checking "
            "periodically in case it expires or rotates. Jazz FM tried via the same "
            "redirector pattern (station=jazzfm-mp3) but returned 404 on two separate "
            "fresh keys -- confirms Jazz FM has no live direct mount right now, not a "
            "token-expiry issue; stays unresolved, only the Rayo app player is available."
        )
        updated = True
        break

if not updated:
    print("ERROR: absolute_country entry not found -- no changes made.")
else:
    with open(PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("Updated absolute_country entry successfully.")

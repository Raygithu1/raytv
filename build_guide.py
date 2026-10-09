#!/usr/bin/env python3
"""Build data.json for the Ray TV guide from a free XMLTV EPG feed.

Reads the channel mapping from channels.json, downloads the configured XMLTV
gzip feed, keeps only programmes for the mapped channels within a rolling
window, and writes a compact data.json consumed by the static web page.
"""

import datetime as dt
import gzip
import json
import re
import sys
import urllib.request
from xml.etree import ElementTree as ET

CHANNELS_FILE = "channels.json"
OUTPUT_FILE = "data.json"
PAST_HOURS = 12
FUTURE_HOURS = 48

TIME_RE = re.compile(r"^(\d{14})\s*([+-]\d{4})?$")


def parse_xmltv_time(value):
    if not value:
        return None
    m = TIME_RE.match(value.strip())
    if not m:
        return None
    when = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    offset = m.group(2)
    if offset:
        sign = 1 if offset[0] == "+" else -1
        minutes = sign * (int(offset[1:3]) * 60 + int(offset[3:5]))
        when -= dt.timedelta(minutes=minutes)
    return when.replace(tzinfo=dt.timezone.utc)


def child_text(elem, tag):
    node = elem.find(tag)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def main():
    with open(CHANNELS_FILE, encoding="utf-8") as fh:
        config = json.load(fh)

    channels = config["channels"]
    feed_url = config["source"]
    tz_name = config.get("timezone", "America/Los_Angeles")

    # Map every accepted xmltv id to its owning channel, preserving priority.
    id_owner = {}
    for ch in channels:
        for xid in ch["xmltv_ids"]:
            id_owner[xid] = ch

    now = dt.datetime.now(dt.timezone.utc)
    window_lo = now - dt.timedelta(hours=PAST_HOURS)
    window_hi = now + dt.timedelta(hours=FUTURE_HOURS)

    # channel number -> xmltv_id -> list of programmes
    collected = {ch["number"]: {} for ch in channels}

    print(f"Downloading {feed_url} ...", flush=True)
    request = urllib.request.Request(
        feed_url, headers={"User-Agent": "raytv-guide-builder/1.0"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        with gzip.open(response, "rb") as stream:
            for _event, elem in ET.iterparse(stream, events=("end",)):
                if elem.tag == "channel":
                    elem.clear()
                    continue
                if elem.tag != "programme":
                    continue

                xmltv_id = elem.get("channel")
                if xmltv_id in id_owner:
                    start = parse_xmltv_time(elem.get("start"))
                    stop = parse_xmltv_time(elem.get("stop"))
                    if start and stop and stop > window_lo and start < window_hi:
                        owner = id_owner[xmltv_id]["number"]
                        collected[owner].setdefault(xmltv_id, []).append(
                            {
                                "start_ts": int(start.timestamp()),
                                "stop_ts": int(stop.timestamp()),
                                "title": child_text(elem, "title"),
                                "subtitle": child_text(elem, "sub-title"),
                                "desc": child_text(elem, "desc"),
                                "category": child_text(elem, "category"),
                            }
                        )
                elem.clear()

    programmes = []
    out_channels = []
    for ch in channels:
        number = ch["number"]
        chosen = []
        chosen_id = None
        for xid in ch["xmltv_ids"]:
            entries = collected[number].get(xid)
            if entries:
                chosen = entries
                chosen_id = xid
                break
        out_channels.append(
            {
                "number": number,
                "name": ch["name"],
                "color": ch.get("color", "#333"),
                "xmltv_id": chosen_id,
            }
        )
        for entry in chosen:
            entry["channel"] = number
            programmes.append(entry)

    programmes.sort(key=lambda p: (p["channel"], p["start_ts"]))

    output = {
        "generated": now.isoformat().replace("+00:00", "Z"),
        "timezone": tz_name,
        "source": feed_url,
        "window_start": int(window_lo.timestamp()),
        "window_end": int(window_hi.timestamp()),
        "channels": out_channels,
        "programmes": programmes,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, separators=(",", ":"))

    summary = ", ".join(
        f"{c['number']} {c['name']}: {sum(1 for p in programmes if p['channel'] == c['number'])}"
        for c in out_channels
    )
    print(f"Wrote {OUTPUT_FILE} ({len(programmes)} programmes) -> {summary}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"build_guide failed: {exc}", file=sys.stderr)
        raise
